# Blk.[Scrn]
<p align="center">
  <img src="icons/blkscrn-512.png" alt="Blk.[Scrn]" width="384">
</p>

Black screen. Open for a black screen. Click for colors. You can use it as a whiteboard as well. Real simple, hope you like it.
<p align="center">
  <img src="BlkReadmeImage.png" alt="Blk.[Scrn] screenshot" width="800">
</p>

## Install

Download the file for your distro from the [Releases page](https://github.com/CatPrinceHQ2/Blk.-Scrn-/releases), then run the matching commands from the folder you downloaded it to. IMPORTANT: THESE ARE NOT GENERALIZED. YOU NEED TO PUT IN THE FOLDER PATH.

Then launch it from your app menu (**Blk.[Scrn]**) or run `blkscrn` in a terminal.

### Debian / Ubuntu / Mint / Pop!_OS (`.deb`)

```bash
sudo apt install ./blkscrn_1.0.0_all.deb
```

Remove: `sudo apt remove blkscrn`

### Fedora / RHEL / Rocky / Alma (`.rpm`)

```bash
sudo dnf install ./blkscrn-1.0.0-1.noarch.rpm
```

Remove: `sudo dnf remove blkscrn`

### Arch / Manjaro / EndeavourOS (`.pkg.tar.zst`)

```bash
sudo pacman -U blkscrn-1.0.0-1-any.pkg.tar.zst
```

Remove: `sudo pacman -R blkscrn`

### Any other distro (`.tar.gz`)

Install the dependencies first (Python 3, PyGObject, pycairo, GTK 3):

```bash
# Debian / Ubuntu
sudo apt install python3 python3-gi python3-gi-cairo gir1.2-gtk-3.0

# Fedora
sudo dnf install python3 python3-gobject python3-cairo gtk3

# Arch
sudo pacman -S python python-gobject python-cairo gtk3
```

Then build and install:

```bash
tar -xzf blkscrn-1.0.0.tar.gz
cd blkscrn-1.0.0
sudo make install
```

To install under `/usr/local` instead of `/usr`, use `sudo make install PREFIX=/usr/local`.

Remove (from the same folder, with the same `PREFIX` you installed with): `sudo make uninstall`

### Check it worked

```bash
blkscrn --version
```
