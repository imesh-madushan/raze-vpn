#!/usr/bin/env bash
set -euo pipefail
umask 077
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
[[ $EUID -ne 0 ]] || { echo 'Run bash setup.sh as your normal desktop user; it will request authorization.'; exit 1; }
log_dir="${XDG_STATE_HOME:-$HOME/.local/state}/raze-vpn/logs"
mkdir -p "$log_dir"
setup_log="$(mktemp "$log_dir/setup-$(date +%Y%m%d-%H%M%S)-XXXXXX.log")"
ln -sfn "$(basename "$setup_log")" "$log_dir/latest-setup.log"
exec > >(tee -a "$setup_log") 2>&1
printf 'Setup log: %s\n' "$setup_log"
missing=()
for tool in python3 sudo pkexec curl ip pgrep getent systemctl systemd-run runuser setpriv nft sing-box; do
    command -v "$tool" >/dev/null || missing+=("$tool")
done
if ((${#missing[@]})); then
    echo "Installing missing prerequisites: ${missing[*]}"
    if command -v pacman >/dev/null; then
        sudo pacman -Syu --needed bash python sudo polkit curl iproute2 procps-ng glibc coreutils util-linux nftables sing-box
    else
        echo 'Automatic dependency installation currently supports CachyOS/Arch with Noctalia in the configured repositories.'
        echo 'See README.md for other Linux installations.'
        exit 1
    fi
fi
if ! python3 -c 'import gi; gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1"); from gi.repository import Gtk, Adw' >/dev/null 2>&1; then
    if command -v pacman >/dev/null; then
        sudo pacman -Syu --needed python-gobject gtk4 libadwaita
    else
        echo 'GTK 4, libadwaita (1.5+) and Python GObject are required for the desktop-independent GUI.'
        exit 1
    fi
fi
sing-box version
python3 "$project_dir/installer/install-user.py"
pkexec /usr/bin/python3 -I "$project_dir/installer/install-system.py"
if command -v noctalia >/dev/null; then
    noctalia msg config-reload || true
    noctalia msg plugins enable raze/vpn || true
fi
if command -v dms >/dev/null && dms ipc call plugins list >/dev/null 2>&1; then
    dms restart
    dms ipc call plugins enable razeVpn
fi
python3 "$project_dir/installer/install-user.py" --record
printf '\nInstalled. Click VPN in the top bar, or run ~/.local/bin/vpn gui.\n'
printf 'Existing profiles are preserved. No VPN was automatically started.\n'
