Name:           blkscrn
Version:        1.0.0
Release:        1%{?dist}
Summary:        Open for a black screen. Click for colors.
License:        MIT
URL:            https://github.com/CatPrinceHQ2/Blk.-Scrn-
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch
Requires:       python3
Requires:       python3-gobject
Requires:       python3-cairo
Requires:       gtk3
Recommends:     jetbrains-mono-fonts
Packager:       CatPrinceHQ <catprincehq@gmail.com>

%description
Open for a black screen. Click for colors.
Draw if you'd like. Luv Lofi.

%prep
%autosetup

%build

%install
make DESTDIR=%{buildroot} PREFIX=%{_prefix} LICENSEDIR=%{_licensedir}/%{name} install

%files
%license %{_licensedir}/%{name}/LICENSE
%{_bindir}/blkscrn
%{_datadir}/applications/blkscrn.desktop
%{_datadir}/pixmaps/blkscrn.png
%{_datadir}/icons/hicolor/*/apps/blkscrn.png

%changelog
* Sun Oct 11 2026 CatPrinceHQ <catprincehq@gmail.com> - 1.0.0-1
- Initial release: black screen, hue shift, gradients, Board Mode drawing
