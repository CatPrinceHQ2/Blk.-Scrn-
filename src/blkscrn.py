#!/usr/bin/env python3
# Blk.[Scrn] - a black screen. click it for options.
# Python 3.6+, GTK 3 (PyGObject) + cairo. No other dependencies.

import json
import math
import os
import sys
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402
import cairo  # noqa: E402

APP_NAME = "Blk.[Scrn]"
VERSION = "1.0.0"
FG = (0.0, 1.0, 0.0)          # terminal green, the only ink
IDLE_POLL_MS = 50              # how often we check whether animation must start
SAVE_DELAY_MS = 400            # settings are written this long after the last change
COLS = 46                      # menu text columns
TRACK = COLS - 2               # slider track width in characters
LUT_N = 360
STRIP_OVERSAMPLE = 4           # strip pixels per screen pixel for diagonal gradients

MODES = [("static", "Static Black"), ("hue", "Hue Shift"), ("gradient", "Gradient")]
SPACES = [("srgb", "sRGB"), ("oklab", "OKLAB"), ("linear", "Linear RGB")]

# key, header, min, max, mouse step, format (used when the value is a whole number)
SLIDERS = {
    "wavelength": ("WAVELENGTH / GRADIENT WIDTH", 0.25, 8.0, 0.25, "%.2f cycles"),
    "angle": ("ANGLE", 0, 355, 5, "%d deg"),
    "speed": ("SPEED", 0, 180, 1, "%d deg/s"),
    "saturation": ("SATURATION", 0, 100, 1, "%d%%"),
    "lightness": ("LIGHTNESS", 0, 100, 1, "%d%%"),
    # Board Mode
    "board_hue": ("INK HUE", 0, 360, 1, "%d deg"),
    "board_size": ("BRUSH SIZE", 1, 80, 1, "%d px"),
}
# format used once arrow keys have produced a fractional value
FINE_FMT = {
    "wavelength": "%.2f cycles",
    "angle": "%.1f deg",
    "speed": "%.1f deg/s",
    "saturation": "%.1f%%",
    "lightness": "%.1f%%",
    "board_hue": "%.1f deg",
    "board_size": "%.1f px",
}
FINE_STEP = 0.1                # arrow key increment
FINER_STEP = 0.01              # Ctrl + arrow key increment

DEFAULTS = {
    "mode": "static",
    "space": "srgb",
    "wavelength": 1.5,
    "angle": 0,
    "speed": 30,
    "saturation": 100,
    "lightness": 90,
    "board_hue": 0,            # ink colour (HSV); default ink is white
    "board_sat": 0,
    "board_val": 100,
    "board_size": 6,
}

# quick ink colours for Board Mode: (hue, saturation %, value %)
SWATCHES = [(0, 0, 100), (0, 0, 0), (0, 100, 100), (30, 100, 100), (60, 100, 100),
            (120, 100, 100), (180, 100, 100), (240, 100, 100), (300, 100, 100)]
SWATCH_W = 4                   # swatch width in menu columns (+1 gap)

MONO_PREFS = ["JetBrains Mono", "Fira Code", "Fira Mono", "DejaVu Sans Mono",
              "Liberation Mono", "Noto Sans Mono", "Ubuntu Mono", "Courier New",
              "Courier", "Monospace"]


# --------------------------------------------------------------------------
# color math
# --------------------------------------------------------------------------

def _enc(c):
    c = 0.0 if c < 0 else (1.0 if c > 1 else c)
    return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


def _hsv(h, s, v):
    h = (h % 360.0) / 60.0
    i = int(h)
    f = h - i
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    return [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][i % 6]


def _oklch_lin(L, C, h):
    a = C * math.cos(math.radians(h))
    b = C * math.sin(math.radians(h))
    l_ = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
            -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
            -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_)


def _in_gamut(rgb):
    return all(-0.0005 <= c <= 1.0005 for c in rgb)


def color_at(space, hue, sat, light):
    """hue in degrees, sat/light in 0..1 -> sRGB tuple 0..1"""
    if space == "srgb":
        return _hsv(hue, sat, light)
    if space == "linear":
        r, g, b = _hsv(hue, sat, light)       # values are linear light
        return (_enc(r), _enc(g), _enc(b))
    # oklab: perceptual lightness, chroma reduced until it fits the gamut
    L = light * 0.85                      # 100% on the slider = L 0.85, still colourful
    C = sat * 0.33
    if L <= 0.0:
        return (0.0, 0.0, 0.0)
    rgb = _oklch_lin(L, C, hue)
    if not _in_gamut(rgb):
        lo, hi = 0.0, C
        for _ in range(11):
            mid = (lo + hi) / 2
            if _in_gamut(_oklch_lin(L, mid, hue)):
                lo = mid
            else:
                hi = mid
        rgb = _oklch_lin(L, lo, hue)
    return (_enc(rgb[0]), _enc(rgb[1]), _enc(rgb[2]))


class Lut(object):
    """Precomputed hue -> colour table for the current colour settings."""

    def __init__(self):
        self.key = None
        self.table = []

    def get(self, space, sat, light):
        key = (space, sat, light)
        if key != self.key:
            self.table = [color_at(space, i * 360.0 / LUT_N, sat, light)
                          for i in range(LUT_N)]
            self.key = key
        return self

    def at(self, hue):
        x = (hue % 360.0) * LUT_N / 360.0
        i = int(x)
        f = x - i
        a = self.table[i % LUT_N]
        b = self.table[(i + 1) % LUT_N]
        return (a[0] + (b[0] - a[0]) * f,
                a[1] + (b[1] - a[1]) * f,
                a[2] + (b[2] - a[2]) * f)


# --------------------------------------------------------------------------
# settings
# --------------------------------------------------------------------------

def config_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "blkscrn", "config.json")


def load_settings():
    s = dict(DEFAULTS)
    try:
        with open(config_path()) as fh:
            data = json.load(fh)
        for k in DEFAULTS:
            if k not in data:
                continue
            num = (int, float)
            if isinstance(data[k], num) == isinstance(DEFAULTS[k], num) and \
                    not isinstance(data[k], bool):
                s[k] = data[k]
        if s["mode"] not in [m[0] for m in MODES]:
            s["mode"] = DEFAULTS["mode"]
        if s["space"] not in [m[0] for m in SPACES]:
            s["space"] = DEFAULTS["space"]
    except Exception:
        pass
    return s


def fmt_value(key, v):
    fmt = SLIDERS[key][4]
    if key == "wavelength":
        return fmt % v
    if abs(v - round(v)) < 1e-9:
        return fmt % int(round(v))
    # fractional value from arrow keys: one decimal, two if Ctrl-steps made it needed
    tenth = abs(v * 10 - round(v * 10)) < 1e-6
    return FINE_FMT[key].replace(".1f", ".1f" if tenth else ".2f") % v


def save_settings(s):
    try:
        p = config_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            json.dump(s, fh, indent=1)
    except Exception:
        pass


# --------------------------------------------------------------------------
# the screen
# --------------------------------------------------------------------------

class Screen(Gtk.DrawingArea):
    def __init__(self, window):
        Gtk.DrawingArea.__init__(self)
        self.win = window
        self.s = load_settings()
        self.lut = Lut()
        # Animation phase in degrees. It is *integrated* (phase += dt * speed)
        # rather than computed as time * speed: with the latter, any change of
        # speed re-scales the whole elapsed time and the colours jump
        # (flashing while dragging the speed slider).
        self.phase = 0.0
        self.phase_t = time.monotonic()
        self.strip = None          # 1-pixel-high gradient strip for diagonal gradients
        self.ripples = []          # (x, y, start_time)
        self.menu_open = False
        self.menu_pos = (0, 0)
        self.menu_t = 0.0
        self.menu_pending = None   # (time_to_open, x, y)
        self.regions = []          # (x, y, w, h, kind, data)
        self.drag = None
        self.sel = "speed"          # slider that arrow keys adjust
        self.tick_id = None         # frame-clock callback while animating
        self.save_id = None         # pending debounced settings write
        self.last_motion = time.monotonic()
        self.cursor_hidden = False
        self.board = False          # Board Mode (free drawing) active?
        self.board_surf = None      # persistent ink layer (ARGB32), kept while mode is off
        self.stroke = []            # points of the stroke being drawn
        self.font = self._pick_font()
        self.debug = os.environ.get("BLKSCRN_DEBUG")

        self.set_can_focus(True)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                        Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.SCROLL_MASK |
                        Gdk.EventMask.KEY_PRESS_MASK)
        self.connect("draw", self.on_draw)
        self.connect("button-press-event", self.on_press)
        self.connect("button-release-event", self.on_release)
        self.connect("motion-notify-event", self.on_motion)
        self.connect("scroll-event", self.on_scroll)
        self.connect("realize", self.on_realize)
        # Animation is driven by the display's frame clock (one callback per
        # monitor refresh, 60/120/144/240 Hz...) instead of a fixed timer.
        # While nothing moves we only poll cheaply so an idle black screen
        # costs next to nothing.
        GLib.timeout_add(IDLE_POLL_MS, self.poll)

    # -- helpers ----------------------------------------------------------
    def _pick_font(self):
        try:
            fams = self.get_pango_context().list_families()
            names = {f.get_name().lower(): f.get_name() for f in fams}
            for p in MONO_PREFS:
                if p.lower() in names:
                    return names[p.lower()]
            for f in fams:
                if f.is_monospace():
                    return f.get_name()
        except Exception:
            pass
        return "monospace"

    def on_realize(self, w):
        # deliver every pointer event (no per-frame coalescing) so strokes
        # follow the mouse smoothly instead of looking polygonal
        try:
            self.get_window().set_event_compression(False)
        except Exception:
            pass

    def now(self):
        return time.monotonic()

    def animating(self):
        return self.s["mode"] != "static" and self.s["speed"] > 0

    def update(self):
        """Advance timers/state. Returns True while frames must keep coming."""
        t = self.now()
        dt = t - self.phase_t
        self.phase_t = t
        if 0.0 < dt < 0.25:        # a longer gap (suspend, stall) must not make a leap
            self.phase = (self.phase + dt * self.s["speed"]) % 360.0
        if self.menu_pending and t >= self.menu_pending[0]:
            _, x, y = self.menu_pending
            self.menu_pending = None
            self.menu_pos = (x, y)
            self.menu_open = True
            self.menu_t = t
        self.ripples = [r for r in self.ripples if t - r[2] < 1.4]
        # hide the pointer when idle so the black stays black
        if not self.menu_open and not self.board and not self.cursor_hidden \
                and t - self.last_motion > 2.0:
            self.set_cursor(True)
        return bool(self.animating() or self.ripples or self.menu_pending
                    or (self.menu_open and t - self.menu_t < 0.3))

    def poll(self):
        # idle: check whether something started; if so, hand over to the frame clock
        if self.update() and self.tick_id is None:
            self.tick_id = self.add_tick_callback(self.on_frame)
        return True

    def on_frame(self, widget, clock):
        # runs once per display refresh, right before GTK paints the frame
        if self.update() or self.drag:
            self.queue_draw()
            return True
        self.tick_id = None
        self.queue_draw()          # final frame
        return False

    def set_cursor(self, hide):
        gw = self.get_window()
        if not gw:
            return
        if hide:
            gw.set_cursor(Gdk.Cursor.new_for_display(gw.get_display(), Gdk.CursorType.BLANK_CURSOR))
        elif self.board:
            gw.set_cursor(Gdk.Cursor.new_for_display(gw.get_display(), Gdk.CursorType.CROSSHAIR))
        else:
            gw.set_cursor(None)
        self.cursor_hidden = hide

    # -- board mode -------------------------------------------------------
    def ink(self):
        s = self.s
        return _hsv(s["board_hue"], s["board_sat"] / 100.0, s["board_val"] / 100.0)

    def set_board(self, on):
        if on == self.board:
            return
        self.board = on
        self.stroke = []
        self.drag = None
        self.set_cursor(False)     # crosshair in board mode, normal pointer otherwise
        self.queue_draw()

    def board_layer(self):
        """The ink surface, (re)sized to the widget; old ink is kept on resize."""
        a = self.get_allocation()
        W, H = max(1, a.width), max(1, a.height)
        old = self.board_surf
        if old is None or old.get_width() != W or old.get_height() != H:
            self.board_surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
            if old is not None:
                cr = cairo.Context(self.board_surf)
                cr.set_source_surface(old, 0, 0)
                cr.paint()
        return self.board_surf

    def clear_board(self):
        if self.board_surf is not None:
            cr = cairo.Context(self.board_surf)
            cr.set_operator(cairo.OPERATOR_CLEAR)
            cr.paint()
        self.stroke = []
        self.queue_draw()

    def stroke_start(self, x, y):
        cr = cairo.Context(self.board_layer())
        cr.set_source_rgb(*self.ink())
        cr.arc(x, y, self.s["board_size"] / 2.0, 0, 2 * math.pi)
        cr.fill()
        self.stroke = [(x, y)]
        self.queue_draw()

    def stroke_to(self, x, y):
        """Extend the stroke. Segments run between midpoints of the raw points
        with the raw point as quadratic control, which rounds off corners so
        the line follows the mouse smoothly instead of as a polyline."""
        pts = self.stroke
        if not pts:
            return
        if abs(x - pts[-1][0]) < 0.01 and abs(y - pts[-1][1]) < 0.01:
            return
        pts.append((x, y))
        cr = cairo.Context(self.board_layer())
        cr.set_source_rgb(*self.ink())
        cr.set_line_width(self.s["board_size"])
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        if len(pts) == 2:
            # first segment: straight to the midpoint
            cr.move_to(*pts[0])
            cr.line_to((pts[0][0] + x) / 2.0, (pts[0][1] + y) / 2.0)
        else:
            p0, p1 = pts[-3], pts[-2]
            a = ((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0)
            b = ((p1[0] + x) / 2.0, (p1[1] + y) / 2.0)
            # quadratic a -> b with control p1, as the equivalent cubic
            cr.move_to(*a)
            cr.curve_to(a[0] + 2.0 / 3 * (p1[0] - a[0]), a[1] + 2.0 / 3 * (p1[1] - a[1]),
                        b[0] + 2.0 / 3 * (p1[0] - b[0]), b[1] + 2.0 / 3 * (p1[1] - b[1]),
                        b[0], b[1])
        cr.stroke()
        if len(pts) > 64:
            del pts[:-3]
        self.queue_draw()

    def stroke_end(self):
        pts = self.stroke
        if len(pts) >= 2:
            # finish the last half-segment so the line reaches the release point
            cr = cairo.Context(self.board_layer())
            cr.set_source_rgb(*self.ink())
            cr.set_line_width(self.s["board_size"])
            cr.set_line_cap(cairo.LINE_CAP_ROUND)
            p0, p1 = pts[-2], pts[-1]
            cr.move_to((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0)
            cr.line_to(*p1)
            cr.stroke()
            self.queue_draw()
        self.stroke = []

    def change(self, key, value):
        if key == "board_hue" and (self.s["board_sat"] < 1 or self.s["board_val"] < 1):
            # moving the hue slider after picking white/black gives a real colour again
            self.s["board_sat"] = 100
            self.s["board_val"] = 100
        self.s[key] = value
        self.schedule_save()
        self.queue_draw()

    def schedule_save(self):
        # never hit the disk from inside a drag / key-repeat; write once things settle
        if self.save_id is not None:
            GLib.source_remove(self.save_id)
        self.save_id = GLib.timeout_add(SAVE_DELAY_MS, self.flush_save)

    def flush_save(self):
        self.save_id = None
        save_settings(self.s)
        return False

    def visible_sliders(self):
        keys = []
        if self.s["mode"] == "gradient":
            keys += ["wavelength", "angle"]
        keys += ["speed", "saturation", "lightness"]
        if self.board:
            keys += ["board_hue", "board_size"]
        return keys

    def nudge(self, key, delta):
        """Move a slider by an exact delta (arrow keys), clamped and de-noised."""
        _, lo, hi, _step, _f = SLIDERS[key]
        v = round(min(hi, max(lo, float(self.s[key]) + delta)), 3)
        if abs(v - round(v)) < 1e-9 and not isinstance(SLIDERS[key][3], float):
            v = int(round(v))
        if v != self.s[key]:
            self.change(key, v)

    def slider_key(self, name, shift, ctrl):
        """Keyboard control for the menu sliders. Returns True if handled."""
        keys = self.visible_sliders()
        if self.sel not in keys:
            self.sel = "speed"
        i = keys.index(self.sel)
        if name in ("Up", "Down", "Tab", "ISO_Left_Tab"):
            back = name in ("Up", "ISO_Left_Tab")
            self.sel = keys[(i + (-1 if back else 1)) % len(keys)]
            self.queue_draw()
            return True
        _, lo, hi, step, _f = SLIDERS[self.sel]
        if name in ("Left", "Right"):
            amt = FINER_STEP if ctrl else (1.0 if shift else FINE_STEP)
            self.nudge(self.sel, amt if name == "Right" else -amt)
            return True
        if name in ("Page_Up", "Page_Down"):
            self.nudge(self.sel, step if name == "Page_Up" else -step)
            return True
        if name == "Home":
            self.change(self.sel, lo)
            return True
        if name == "End":
            self.change(self.sel, hi)
            return True
        return False

    # -- events -----------------------------------------------------------
    def on_motion(self, w, ev):
        self.last_motion = self.now()
        if self.cursor_hidden:
            self.set_cursor(False)
        if self.drag:
            self.slide(self.drag, ev.x)
        elif self.stroke and ev.state & Gdk.ModifierType.BUTTON1_MASK:
            self.stroke_to(ev.x, ev.y)
        return True

    def on_press(self, w, ev):
        # Board Mode: left button draws, right button opens the menu
        # (a plain click can't open it there, it would start a stroke).
        if ev.button != 1 and not (self.board and ev.button == 3):
            return True
        self.last_motion = self.now()
        if self.menu_open:
            hit = self.hit(ev.x, ev.y) if ev.button == 1 else None
            if hit is not None:
                self.activate(hit, ev.x)
                return True
            self.menu_open = False        # click outside the menu closes it
            if self.board:
                self.queue_draw()
                return True               # ...without leaving a mark
        elif self.board and ev.button == 1:
            self.stroke_start(ev.x, ev.y)
            return True
        elif self.menu_pending is None:
            self.menu_pending = (self.now() + 0.14, ev.x, ev.y)
        self.ripples.append((ev.x, ev.y, self.now()))
        self.queue_draw()
        return True

    def on_release(self, w, ev):
        if ev.button == 1:
            self.stroke_end()
        self.drag = None
        return True

    def on_scroll(self, w, ev):
        if self.menu_open:
            hit = self.hit(ev.x, ev.y)
            if hit and hit[4] == "slider":
                key = hit[5]
                self.sel = key
                _, lo, hi, step, _f = SLIDERS[key]
                d = -1 if ev.direction == Gdk.ScrollDirection.UP else 1
                if ev.direction == Gdk.ScrollDirection.SMOOTH:
                    d = -1 if ev.delta_y < 0 else 1
                    if ev.delta_y == 0:
                        return True
                v = round(min(hi, max(lo, self.s[key] - d * step)), 3)
                if isinstance(step, int):
                    v = int(round(v))
                self.change(key, v)
        return True

    def hit(self, x, y):
        for r in reversed(self.regions):
            if r[0] <= x < r[0] + r[2] and r[1] <= y < r[1] + r[3]:
                return r
        return None

    def activate(self, r, x):
        kind, data = r[4], r[5]
        if kind == "mode":
            self.change("mode", data)
        elif kind == "space":
            self.change("space", data)
        elif kind == "board":
            self.set_board(not self.board)
            self.schedule_save()
        elif kind == "swatch":
            self.s["board_hue"], self.s["board_sat"], self.s["board_val"] = data
            self.schedule_save()
            self.queue_draw()
        elif kind == "clear":
            self.clear_board()
        elif kind == "slider":
            self.drag = r
            self.sel = r[5]
            self.slide(r, x)
        elif kind == "close":
            self.menu_open = False
            self.queue_draw()
        elif kind == "quit":
            self.win.quit()

    def slide(self, r, x):
        key = r[5]
        _, lo, hi, step, _f = SLIDERS[key]
        cw = r[2] / float(TRACK)
        frac = (x - r[0] - cw / 2.0) / float(r[2] - cw)
        frac = 0.0 if frac < 0 else (1.0 if frac > 1 else frac)
        v = lo + frac * (hi - lo)
        v = round(v / step) * step
        v = min(hi, max(lo, v))
        if isinstance(step, int):
            v = int(v)
        if v != self.s[key]:
            self.change(key, v)

    # -- drawing ----------------------------------------------------------
    def on_draw(self, w, cr):
        alloc = self.get_allocation()
        W, H = alloc.width, alloc.height
        self.paint_background(cr, W, H)      # keeps rolling in Board Mode too
        if self.board and self.board_surf is not None:
            cr.set_source_surface(self.board_layer(), 0, 0)
            cr.paint()
        self.paint_ripples(cr, W, H)
        self.regions = []
        if self.menu_open:
            self.paint_menu(cr, W, H)
        return False

    def paint_background(self, cr, W, H):
        s = self.s
        mode = s["mode"]
        if mode == "static":
            cr.set_source_rgb(0, 0, 0)
            cr.paint()
            return
        off = self.phase           # integrated by update(), see advance_phase()
        lut = self.lut.get(s["space"], s["saturation"] / 100.0, s["lightness"] / 100.0)
        if mode == "hue":
            cr.set_source_rgb(*lut.at(off))
            cr.paint()
            return
        cycles = float(s["wavelength"])
        th = math.radians(s["angle"])
        dx, dy = math.cos(th), math.sin(th)
        length = abs(W * dx) + abs(H * dy)
        cx, cy = W / 2.0, H / 2.0
        sx, sy = cx - dx * length / 2, cy - dy * length / 2
        n = int(min(480, max(48, cycles * 48)))
        diagonal = min(abs(dx), abs(dy)) > 1e-6
        if not diagonal:
            # 0/90/180/270 deg: cairo renders a plain linear gradient in ~1 ms
            grad = cairo.LinearGradient(sx, sy, sx + dx * length, sy + dy * length)
        else:
            # A diagonal cairo gradient is evaluated per pixel on one CPU thread
            # (~110 ms at 4K -> ~9 fps while CPU/GPU look idle). Render the
            # gradient once along a 1-pixel-high strip instead (axis aligned,
            # trivial) and let cairo rotate it onto the screen with a cheap
            # nearest-neighbour fetch; the strip is padded so it covers the
            # whole screen. Colours match the real gradient to within 1 level.
            # The strip has STRIP_OVERSAMPLE pixels per screen pixel so the
            # nearest-neighbour fetch stays within a couple of colour levels
            # even for many fast cycles on a small window.
            ss = max(1, min(STRIP_OVERSAMPLE, 30000 // (int(length) + 66)))   # cairo max width ~32k
            sw = ((int(length) + 66) * ss) & ~63          # reuse the surface while it fits
            if self.strip is None or self.strip.get_width() < sw:
                self.strip = cairo.ImageSurface(cairo.FORMAT_ARGB32, sw, 1)
            grad = cairo.LinearGradient(0, 0, length * ss, 0)
        for i in range(n + 1):
            f = i / float(n)
            grad.add_color_stop_rgb(f, *lut.at(f * cycles * 360.0 - off))
        if not diagonal:
            cr.set_source(grad)
            cr.paint()
            return
        sc = cairo.Context(self.strip)
        sc.set_operator(cairo.OPERATOR_SOURCE)
        sc.set_source(grad)
        sc.paint()
        self.strip.flush()
        pat = cairo.SurfacePattern(self.strip)
        pat.set_extend(cairo.EXTEND_PAD)
        pat.set_filter(cairo.FILTER_NEAREST)
        # screen (x, y) -> strip x = distance along the gradient direction
        pat.set_matrix(cairo.Matrix(ss * dx, -dy, ss * dy, dx, -ss * (sx * dx + sy * dy), 0.0))
        cr.set_source(pat)
        cr.paint()

    def paint_ripples(self, cr, W, H):
        if not self.ripples:
            return
        t = self.now()
        scale = max(1.0, H / 1080.0)
        reach = math.hypot(W, H) * 0.75
        try:
            cr.set_operator(cairo.OPERATOR_DIFFERENCE)
        except Exception:
            pass
        for (x, y, t0) in self.ripples:
            for k in range(3):
                age = t - t0 - k * 0.12
                if age < 0 or age > 1.1:
                    continue
                p = age / 1.1
                e = 1 - (1 - p) ** 3               # ease out
                cr.set_source_rgba(1, 1, 1, (1 - p))
                cr.set_line_width(max(1.0, 2.0 * scale))
                cr.arc(x, y, 4 + e * reach, 0, 2 * math.pi)
                cr.stroke()
        cr.set_operator(cairo.OPERATOR_OVER)

    # -- menu -------------------------------------------------------------
    def menu_rows(self, gradient, board):
        rows = []
        rows.append(("title",))
        rows.append(("rule",))
        rows.append(("head", "MODE", None))
        for key, label in MODES:
            rows.append(("opt", key, label))
        rows.append(("gap",))
        if gradient:
            rows.append(("slider", "wavelength"))
            rows.append(("slider", "angle"))
            rows.append(("gap",))
        rows.append(("head", "COLOR SPACE", None))
        rows.append(("spaces",))
        rows.append(("gap",))
        rows.append(("slider", "speed"))
        rows.append(("slider", "saturation"))
        rows.append(("slider", "lightness"))
        rows.append(("gap",))
        rows.append(("head", "BOARD", None))
        rows.append(("board",))
        if board:
            rows.append(("swatches",))
            rows.append(("slider", "board_hue"))
            rows.append(("slider", "board_size"))
            rows.append(("brush",))
        rows.append(("gap",))
        rows.append(("rule",))
        rows.append(("hint",))
        if board:
            rows.append(("hint2",))
        rows.append(("footer",))
        return rows

    def paint_menu(self, cr, W, H):
        cr.select_font_face(self.font, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)

        def row_h(r, lh):
            if r[0] == "slider":
                return 2 * lh
            if r[0] in ("rule", "gap"):
                return lh * 0.6
            return lh

        def metrics(scale):
            fs = 16.0 * scale
            lh = fs * 1.5
            cr.set_font_size(fs)
            cw = cr.text_extents("M").x_advance
            fo = cr.font_extents()
            base = (lh - (fo[0] + fo[1])) / 2 + fo[0]    # baseline offset inside a row
            return fs, lh, cw, base

        def tall_for(scale):
            # height of the tallest layout (gradient + board) so the panel never jumps
            fs, lh, cw, base = metrics(scale)
            return sum(row_h(r, lh) for r in self.menu_rows(True, True)) + cw

        scale = min(2.5, max(1.0, H / 1080.0))
        tall = tall_for(scale)
        if tall > H - 16:                                 # small screens: shrink to fit
            scale = max(0.5, scale * (H - 16) / tall)
        fs, lh, cw, base = metrics(scale)
        pad = cw
        pw = COLS * cw + 2 * pad

        # layout (list of row builders) so we know the height before drawing
        s = self.s
        rows = self.menu_rows(s["mode"] == "gradient", self.board)
        full = sum(row_h(r, lh) for r in rows) + pad

        # panel position: where the user clicked, kept on screen
        tall = tall_for(scale)
        mx = min(max(self.menu_pos[0], 8), max(8, W - pw - 8))
        my = min(max(self.menu_pos[1], 8), max(8, H - tall - 8))
        x0 = mx
        y0 = my

        # unfold animation (answers the click)
        age = self.now() - self.menu_t
        prog = 1.0 if age >= 0.18 else max(0.05, age / 0.18)
        cr.save()
        cr.rectangle(x0 - 1, y0 - 1, pw + 2, (full + 2) * prog)
        cr.clip()

        # panel body: pure black, 1px border, nothing else
        cr.set_antialias(cairo.ANTIALIAS_NONE)
        cr.set_source_rgb(0, 0, 0)
        cr.rectangle(x0, y0, pw, full)
        cr.fill()
        cr.set_source_rgb(*FG)
        cr.set_line_width(1)
        cr.rectangle(round(x0) + 0.5, round(y0) + 0.5, pw - 1, full - 1)
        cr.stroke()
        cr.set_antialias(cairo.ANTIALIAS_DEFAULT)

        tx = x0 + pad
        y = y0 + pad / 2.0

        def text(col, yy, str_, inv=False, dim=False):
            if inv:
                cr.set_antialias(cairo.ANTIALIAS_NONE)
                cr.set_source_rgb(*FG)
                cr.rectangle(round(tx + col * cw), round(yy), round(len(str_) * cw), round(lh))
                cr.fill()
                cr.set_antialias(cairo.ANTIALIAS_DEFAULT)
                cr.set_source_rgb(0, 0, 0)
            elif dim:
                cr.set_source_rgba(FG[0], FG[1], FG[2], 0.45)
            else:
                cr.set_source_rgb(*FG)
            cr.move_to(tx + col * cw, yy + base)
            cr.show_text(str_)

        def hline(yy):
            cr.set_antialias(cairo.ANTIALIAS_NONE)
            cr.set_source_rgb(*FG)
            cr.set_line_width(1)
            cr.move_to(x0, round(yy) + 0.5)
            cr.line_to(x0 + pw, round(yy) + 0.5)
            cr.stroke()
            cr.set_antialias(cairo.ANTIALIAS_DEFAULT)

        def region(col, yy, ncols, h, kind, data):
            self.regions.append((tx + col * cw, yy, ncols * cw, h, kind, data))

        static = s["mode"] == "static"
        for r in rows:
            h = row_h(r, lh)
            kind = r[0]
            if kind == "title":
                text(0, y, "BLK.[SCRN]")
                text(11, y, "v" + VERSION, dim=True)
                text(COLS - 3, y, "[X]")
                region(COLS - 3, y, 3, lh, "close", None)
            elif kind == "rule":
                hline(y + h / 2)
            elif kind == "head":
                text(0, y, "> " + r[1])
            elif kind == "opt":
                sel = s["mode"] == r[1]
                label = ("[*] " if sel else "[ ] ") + r[2]
                text(0, y, label.ljust(COLS), inv=sel)
                region(0, y, COLS, lh, "mode", r[1])
            elif kind == "spaces":
                col = 0
                for key, label in SPACES:
                    sel = s["space"] == key
                    item = ("[*] " if sel else "[ ] ") + label
                    text(col, y, item, inv=sel, dim=static and not sel)
                    region(col, y, len(item), lh, "space", key)
                    col += len(item) + 2
            elif kind == "slider":
                key = r[1]
                head, lo, hi, step, fmt = SLIDERS[key]
                if key == "saturation" and s["space"] == "oklab":
                    head = "CHROMA"
                if key == "lightness":
                    head = "LIGHTNESS" if s["space"] == "oklab" else "VALUE"
                dim = static and key in ("speed", "saturation", "lightness")
                if key == self.sel:
                    text(0, y, ("> " + head).ljust(COLS), inv=True, dim=dim)
                else:
                    text(0, y, "> " + head, dim=dim)
                val = fmt_value(key, s[key])
                if key == self.sel:
                    text(COLS - len(val), y, val, inv=True, dim=dim)
                else:
                    text(COLS - len(val), y, val, dim=dim)
                frac = (s[key] - lo) / float(hi - lo)
                k = int(round(frac * (TRACK - 1)))
                track = "[" + "-" * k + "0" + "-" * (TRACK - 1 - k) + "]"
                text(0, y + lh, track, dim=dim)
                region(1, y + lh, TRACK, lh, "slider", key)
            elif kind == "board":
                label = ("[*] " if self.board else "[ ] ") + "Board Mode (draw on screen)"
                text(0, y, label.ljust(COLS), inv=self.board)
                region(0, y, COLS, lh, "board", None)
            elif kind == "swatches":
                col = 0
                for sw in SWATCHES:
                    on = round(s["board_sat"]) == sw[1] and round(s["board_val"]) == sw[2] and \
                        (sw[1] == 0 or sw[2] == 0 or round(s["board_hue"]) % 360 == sw[0])
                    rgb = _hsv(sw[0], sw[1] / 100.0, sw[2] / 100.0)
                    sx = tx + col * cw
                    sy, sh, sw_w = y + lh * 0.12, lh * 0.76, SWATCH_W * cw
                    cr.set_antialias(cairo.ANTIALIAS_NONE)
                    cr.set_source_rgb(*rgb)
                    cr.rectangle(round(sx), round(sy), round(sw_w), round(sh))
                    cr.fill()
                    cr.set_source_rgb(*FG)
                    cr.set_line_width(1)
                    cr.rectangle(round(sx) + 0.5, round(sy) + 0.5, round(sw_w) - 1, round(sh) - 1)
                    cr.stroke()
                    if on:                                  # selected: second, inset frame
                        cr.set_source_rgb(0, 0, 0) if sum(rgb) > 1.5 else cr.set_source_rgb(*FG)
                        cr.rectangle(round(sx) + 3.5, round(sy) + 3.5, round(sw_w) - 7, round(sh) - 7)
                        cr.stroke()
                    cr.set_antialias(cairo.ANTIALIAS_DEFAULT)
                    region(col, y, SWATCH_W, lh, "swatch", sw)
                    col += SWATCH_W + 1
            elif kind == "brush":
                text(0, y, "[ CLEAR ]  C")
                region(0, y, 9, lh, "clear", None)
                # live preview of the current ink + thickness
                rad = min(float(s["board_size"]) / 2.0, lh * 0.45)
                cr.set_source_rgb(*self.ink())
                cr.arc(tx + (COLS - 3) * cw, y + lh / 2.0, rad, 0, 2 * math.pi)
                cr.fill()
                cr.set_source_rgb(*FG)
                cr.set_line_width(1)
                cr.arc(tx + (COLS - 3) * cw, y + lh / 2.0, rad + 2, 0, 2 * math.pi)
                cr.stroke()
            elif kind == "hint":
                text(0, y, "UP/DN pick  L/R 0.1  SHIFT 1  CTRL 0.01", dim=True)
            elif kind == "hint2":
                text(0, y, "DRAG draw  R-CLICK menu  B board  C clear", dim=True)
            elif kind == "footer":
                text(0, y, "[ QUIT ]")
                hint = "ESC close"
                text(COLS - len(hint), y, hint, dim=True)
                region(0, y, 8, lh, "quit", None)
            y += h
        cr.restore()

        if self.debug:
            try:
                with open(self.debug, "w") as fh:
                    json.dump({"panel": [x0, y0, pw, full], "regions": [
                        [r[0], r[1], r[2], r[3], r[4], r[5]] for r in self.regions]}, fh)
            except Exception:
                pass


# --------------------------------------------------------------------------
# window
# --------------------------------------------------------------------------

class Win(Gtk.Window):
    def __init__(self):
        Gtk.Window.__init__(self, title=APP_NAME)
        self.set_icon_name("blkscrn")
        self.set_decorated(False)
        self.set_app_paintable(True)
        self.screen_w = Screen(self)
        self.add(self.screen_w)
        self.connect("destroy", Gtk.main_quit)
        self.connect("key-press-event", self.on_key)
        self.fullscreen()
        self.show_all()
        self.screen_w.grab_focus()

    def quit(self):
        save_settings(self.screen_w.s)   # flush anything still pending
        Gtk.main_quit()

    def on_key(self, w, ev):
        name = Gdk.keyval_name(ev.keyval) or ""
        ctrl = ev.state & Gdk.ModifierType.CONTROL_MASK
        sc = self.screen_w
        if name == "Escape":
            if sc.menu_open:
                sc.menu_open = False
                sc.queue_draw()
        elif name.lower() == "q" and ctrl:
            self.quit()
        elif sc.menu_open and name in ("Left", "Right", "Up", "Down", "Tab", "ISO_Left_Tab",
                                       "Page_Up", "Page_Down", "Home", "End"):
            sc.slider_key(name, ev.state & Gdk.ModifierType.SHIFT_MASK,
                          ctrl)
        elif name.lower() == "b" and not ctrl:
            sc.set_board(not sc.board)
        elif name.lower() == "c" and not ctrl and sc.board:
            sc.clear_board()
        elif name in ("space", "Return") and not sc.menu_open:
            a = self.get_allocation()
            sc.menu_pending = (sc.now(), a.width / 2.0 - 230, a.height / 2.0 - 300)
            sc.ripples.append((a.width / 2.0, a.height / 2.0, sc.now()))
        return True


def main():
    if "--version" in sys.argv:
        print("blkscrn " + VERSION)
        return 0
    if "--help" in sys.argv or "-h" in sys.argv:
        print("usage: blkscrn\n\n"
              "  click       open options (ripple + menu)\n"
              "  Esc         close menu\n"
              "  Ctrl+Q      quit\n"
              "  Space/Enter open menu from keyboard\n"
              "  B           toggle Board Mode (draw with the mouse)\n"
              "  C           clear the board (Board Mode)\n"
              "  right-click open menu while in Board Mode\n"
              "  Up/Down     choose slider (menu open)\n"
              "  Left/Right  adjust slider by 0.1 (Shift 1, Ctrl 0.01)\n\n"
              "settings: " + config_path())
        return 0
    GLib.set_prgname("blkscrn")
    GLib.set_application_name(APP_NAME)
    Win()
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
