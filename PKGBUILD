# Maintainer: CatPrinceHQ <catprincehq@gmail.com>
pkgname=blkscrn
pkgver=1.0.0
pkgrel=1
pkgdesc='Open for a black screen. Click for colors. Draw if you'd like. Luv Lofi.'
arch=('any')
url='https://github.com/CatPrinceHQ2/Blk.-Scrn-'
license=('MIT')
depends=('python' 'python-gobject' 'python-cairo' 'gtk3')
optdepends=('ttf-jetbrains-mono: preferred menu font'
            'ttf-dejavu: fallback monospace menu font')
source=("$pkgname-$pkgver.tar.gz")
sha256sums=('ce6d81054c6ca7ee580ffe8b643b7826ea161a687ce8d556267a2114989b90b5')

package() {
  cd "$srcdir/$pkgname-$pkgver"
  make DESTDIR="$pkgdir" PREFIX=/usr LICENSEDIR=/usr/share/licenses/$pkgname install
}
