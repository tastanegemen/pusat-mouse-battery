#!/usr/bin/env bash
# Kullanım: sudo bash install.sh
set -euo pipefail
DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
if [[ $EUID -ne 0 ]]; then
    echo 'Kurulum için sudo bash install.sh çalıştırın.' >&2
    exit 1
fi
TARGET_USER="${SUDO_USER:-}"
if [[ -z "$TARGET_USER" || "$TARGET_USER" == root ]]; then
    echo 'Masaüstü kullanıcınızdan sudo bash install.sh çalıştırın.' >&2
    exit 1
fi
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
TARGET_GROUP="$(id -gn "$TARGET_USER")"
if [[ -z "$TARGET_HOME" || ! -d "$TARGET_HOME" ]]; then
    echo 'Kullanıcı ev dizini bulunamadı.' >&2
    exit 1
fi
if ! command -v apt-get >/dev/null || ! command -v udevadm >/dev/null; then
    echo 'Bu kurulum betiği apt-get ve udev gerektirir. Diğer dağıtımlar için README.md dosyasına bakın.' >&2
    exit 1
fi
apt-get install -y --no-install-recommends python3-gi gir1.2-gtk-3.0 \
    gir1.2-gdkpixbuf-2.0 gir1.2-ayatanaappindicator3-0.1 librsvg2-common libnotify-bin
install -m 0644 "$DIR/70-mouse-battery.rules" /etc/udev/rules.d/70-mouse-battery.rules
# Remove the rule installed by earlier versions of this application.
rm -f /etc/udev/rules.d/99-mouse-battery.rules
udevadm control --reload-rules
udevadm trigger --subsystem-match=hidraw
udevadm settle
AUTOSTART="$TARGET_HOME/.config/autostart"
# Create as the desktop user to avoid root-owned configuration directories.
sudo -u "$TARGET_USER" mkdir -p "$AUTOSTART"
# Escape reserved characters for the desktop Exec field, including spaces.
ESCAPED_DIR="${DIR//\\/\\\\}"
ESCAPED_DIR="${ESCAPED_DIR//\"/\\\"}"
ESCAPED_DIR="${ESCAPED_DIR//\$/\\\$}"
ESCAPED_DIR="${ESCAPED_DIR//\`/\\\`}"
ESCAPED_DIR="${ESCAPED_DIR//%/%%}"
TEMP_DESKTOP="$(mktemp)"
trap 'rm -f "$TEMP_DESKTOP"' EXIT
cat > "$TEMP_DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Exec=/usr/bin/python3 "$ESCAPED_DIR/mouse_tray.py"
Hidden=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
Name=Mouse Battery Indicator
Comment=Monster Pusat mouse pil göstergesi
EOF
install -m 0644 -o "$TARGET_USER" -g "$TARGET_GROUP" "$TEMP_DESKTOP" "$AUTOSTART/mouse-battery-indicator.desktop"
echo 'Kurulum tamamlandı. Pil okuma testi:'
sudo -u "$TARGET_USER" /usr/bin/python3 "$DIR/mouse_battery.py" || {
    echo 'Alıcıyı yeniden takın ve mouse açıkken testi tekrar deneyin.'
}
echo "Başlatma: /usr/bin/python3 \"$DIR/mouse_tray.py\""
echo 'GNOME üst barında görünmesi için AppIndicator uzantısı etkin olmalıdır.'
