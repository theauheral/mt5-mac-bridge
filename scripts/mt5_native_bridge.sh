#!/usr/bin/env bash
# mt5_native_bridge.sh — EXPERIMENT: run the MT5 rpyc bridge natively on macOS,
# inside the MetaTrader 5.app's own (Rosetta) Wine prefix. No Docker, no QEMU.
#
# Why this can work where you'd expect it not to: the MetaTrader5 Python package
# talks to the terminal over local IPC *within the same Wine prefix*. The Mac
# MT5.app IS a Wine bottle, so if we drop a Windows Python + the MetaTrader5
# package into that exact prefix and run an rpyc server with the app's own wine,
# native macOS Python can reach the terminal you already run — at Rosetta speed.
#
# Subcommands:
#   provision   install embeddable Python + MetaTrader5 + rpyc into the app prefix
#   serve       launch the rpyc SlaveService (foreground) on $MT5_NATIVE_PORT
#   verify      from the app-wine Python, import MetaTrader5 (no terminal needed)
#
# Requires: MetaTrader 5.app installed; for live data the app must be RUNNING and
# logged into an account (reuse your demo creds).  Port defaults to 18813 so it
# never collides with the Docker bridge on 18812.
set -euo pipefail

APP="/Applications/MetaTrader 5.app"
WINE="$APP/Contents/SharedSupport/wine/bin/wine"
export WINEPREFIX="$HOME/Library/Application Support/net.metaquotes.wine.metatrader5"
export WINEDEBUG="${WINEDEBUG:--all}"
export WINEDLLOVERRIDES="mscoree=d;mshtml=d"
PORT="${MT5_NATIVE_PORT:-18813}"
PYDIR_WIN='C:\Python311'
PYEXE="$WINEPREFIX/drive_c/Python311/python.exe"
PYVER="3.11.9"

[ -x "$WINE" ] || { echo "MetaTrader 5.app wine not found at $WINE"; exit 1; }

provision() {
  cd "$WINEPREFIX/drive_c" || { echo "app prefix missing — launch MT5.app once first"; exit 1; }
  if [ ! -f "$PYEXE" ]; then
    echo "[1/3] embeddable Python $PYVER -> $PYDIR_WIN (no installer to crash)"
    curl -fsSL -o /tmp/py-embed.zip "https://www.python.org/ftp/python/$PYVER/python-$PYVER-embed-amd64.zip"
    "$APP/Contents/SharedSupport/wine/bin/wine" --version >/dev/null 2>&1 || true
    /usr/bin/python3 -m zipfile -e /tmp/py-embed.zip "$WINEPREFIX/drive_c/Python311/"
    printf 'python311.zip\n.\nimport site\n' > "$WINEPREFIX/drive_c/Python311/python311._pth"
  else
    echo "[1/3] Python already present at $PYEXE"
  fi
  echo "[2/3] bootstrap pip (under app wine, slow first time)"
  curl -fsSL -o "$WINEPREFIX/drive_c/get-pip.py" https://bootstrap.pypa.io/get-pip.py
  "$WINE" "$PYDIR_WIN\\python.exe" 'C:\get-pip.py' --no-warn-script-location 2>/dev/null || true
  echo "[3/3] install MetaTrader5 + rpyc + numpy<2"
  "$WINE" "$PYDIR_WIN\\python.exe" -m pip install --no-cache-dir --no-warn-script-location \
    "MetaTrader5" "rpyc==6.0.2" "numpy<2" 2>/dev/null
  verify
}

verify() {
  echo "verify: importing MetaTrader5 under app wine…"
  "$WINE" "$PYDIR_WIN\\python.exe" -c \
    "import MetaTrader5 as mt5, rpyc, numpy; print('NATIVE wine OK | MetaTrader5', mt5.__version__, '| rpyc', rpyc.__version__, '| numpy', numpy.__version__)" 2>/dev/null
}

serve() {
  echo "Starting rpyc SlaveService on 0.0.0.0:$PORT via app wine (Ctrl+C to stop)."
  echo "Make sure MetaTrader 5.app is running and logged in for live data."
  exec "$WINE" "$PYDIR_WIN\\python.exe" -c \
    "from rpyc.utils.server import ThreadedServer; from rpyc.core import SlaveService; ThreadedServer(SlaveService, hostname='0.0.0.0', port=$PORT, reuse_addr=True, protocol_config={'allow_all_attrs':True,'allow_public_attrs':True}).start()"
}

case "${1:-}" in
  provision) provision ;;
  serve)     serve ;;
  verify)    verify ;;
  *) echo "usage: $0 {provision|serve|verify}"; exit 1 ;;
esac
