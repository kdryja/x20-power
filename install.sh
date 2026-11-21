#!/bin/bash
# Install X20 Power into Decky Loader. Run from the repo folder: sudo ./install.sh
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run with sudo."; exit 1; }
SRC=$(cd "$(dirname "$0")" && pwd)
USER_HOME=$(getent passwd "${SUDO_USER:?run with sudo from your user account}" | cut -d: -f6)
DST="$USER_HOME/homebrew/plugins/x20-power"
[ -d "$USER_HOME/homebrew/plugins" ] || { echo "Decky Loader not found in $USER_HOME/homebrew"; exit 1; }
install -d -o root -g root -m 755 "$DST" "$DST/dist"
install -o root -g root -m 644 "$SRC/plugin.json" "$SRC/package.json" "$SRC/main.py" "$DST/"
install -o root -g root -m 644 "$SRC/dist/index.js" "$DST/dist/"
systemctl restart plugin_loader
echo "Installed to $DST and restarted Decky."
