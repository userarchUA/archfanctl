# Maintainer: you
pkgname=archfanctl
pkgver=1.0.0
pkgrel=1
pkgdesc="GPU and case fan curve control (hwmon + NVIDIA NVML), Qt GUI + systemd daemon"
arch=('any')
license=('MIT')
depends=('python' 'python-pyqt6' 'polkit' 'systemd')
optdepends=('python-nvidia-ml-py: NVIDIA GPU fan control')
backup=('etc/archfanctl/config.json')
install=archfanctl.install
source=(core.py archfanctld archfanctl-apply archfanctl-gui archfanctl.service
        org.archfanctl.apply.policy archfanctl.desktop config.json)
sha256sums=('SKIP' 'SKIP' 'SKIP' 'SKIP' 'SKIP' 'SKIP' 'SKIP' 'SKIP')

package() {
  install -Dm644 core.py "$pkgdir/usr/lib/archfanctl/core.py"
  install -Dm755 archfanctld "$pkgdir/usr/bin/archfanctld"
  install -Dm755 archfanctl-apply "$pkgdir/usr/bin/archfanctl-apply"
  install -Dm755 archfanctl-gui "$pkgdir/usr/bin/archfanctl-gui"
  install -Dm644 archfanctl.service "$pkgdir/usr/lib/systemd/system/archfanctl.service"
  install -Dm644 org.archfanctl.apply.policy "$pkgdir/usr/share/polkit-1/actions/org.archfanctl.apply.policy"
  install -Dm644 archfanctl.desktop "$pkgdir/usr/share/applications/archfanctl.desktop"
  install -Dm644 config.json "$pkgdir/etc/archfanctl/config.json"
}
