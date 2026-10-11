PREFIX     ?= /usr
DESTDIR    ?=
LICENSEDIR ?= $(PREFIX)/share/doc/blkscrn
SIZES       = 16 24 32 48 64 128 256 512

install:
	install -Dm755 src/blkscrn.py $(DESTDIR)$(PREFIX)/bin/blkscrn
	install -Dm644 data/blkscrn.desktop $(DESTDIR)$(PREFIX)/share/applications/blkscrn.desktop
	for s in $(SIZES); do \
	  install -Dm644 icons/blkscrn-$$s.png $(DESTDIR)$(PREFIX)/share/icons/hicolor/$${s}x$${s}/apps/blkscrn.png; \
	done
	install -Dm644 icons/blkscrn-64.png $(DESTDIR)$(PREFIX)/share/pixmaps/blkscrn.png
	install -Dm644 LICENSE $(DESTDIR)$(LICENSEDIR)/LICENSE

uninstall:
	rm -f $(DESTDIR)$(PREFIX)/bin/blkscrn $(DESTDIR)$(PREFIX)/share/applications/blkscrn.desktop \
	      $(DESTDIR)$(PREFIX)/share/pixmaps/blkscrn.png
	for s in $(SIZES); do rm -f $(DESTDIR)$(PREFIX)/share/icons/hicolor/$${s}x$${s}/apps/blkscrn.png; done
	rm -rf $(DESTDIR)$(LICENSEDIR)

.PHONY: install uninstall
