#!/usr/bin/env bash
# provision-wine-python.sh — provision the Wine-side Python inside the MT5
# bridge container. Run from the HOST after first boot (or after wiping the
# mt5_config volume):
#
#   docker/provision-wine-python.sh            # default container name
#   MT5_CONTAINER=other-name docker/provision-wine-python.sh
#
# Why this exists: the gmag11 image's own start.sh provisioning is broken on
# this setup — the python-3.9.13.exe *installer* crashes under emulation
# (Rosetta AND QEMU), so steps [5/7]-[7/7] silently no-op. We bypass the
# installer entirely with the embeddable Python zip (plain files, nothing to
# execute at install time), then bootstrap pip and install the MT5 + rpyc
# stack. Idempotent: safe to re-run.
#
# Pins, and why:
#   MetaTrader5==5.0.5735  newest with a cp39 wheel; older 5.0.36 (the image
#                          pin) cannot IPC with 2026 terminal builds (-10005)
#   rpyc==6.0.2            must match the rpyc on the macOS client side
#   numpy<2                MetaTrader5 wheels are built against numpy 1.x ABI
set -euo pipefail

C="${MT5_CONTAINER:-momq-mt5-bridge}"
PYVER="3.9.13"
EMBED_URL="https://www.python.org/ftp/python/${PYVER}/python-${PYVER}-embed-amd64.zip"
GETPIP_URL="https://bootstrap.pypa.io/pip/3.9/get-pip.py"   # 3.9-compatible pip

exec_c() { docker exec -u abc -e WINEPREFIX=/config/.wine "$C" sh -c "$1"; }

docker ps --format '{{.Names}}' | grep -q "^${C}$" || {
  echo "Container ${C} is not running (start it: scripts/mt5_bridge.sh up)"; exit 1; }

if exec_c '[ -f /config/.wine/drive_c/Python39/python.exe ]'; then
  echo "[1/3] Embeddable Python already present — skipping unzip."
else
  echo "[1/3] Installing embeddable Python ${PYVER} into the Wine prefix…"
  exec_c "cd /config \
    && curl -fsSL -o py-embed.zip '${EMBED_URL}' \
    && python3 -m zipfile -e py-embed.zip .wine/drive_c/Python39/ \
    && printf 'python39.zip\n.\nimport site\n' > .wine/drive_c/Python39/python39._pth \
    && rm py-embed.zip"
fi

if exec_c 'wine "C:\Python39\python.exe" -m pip --version >/dev/null 2>&1'; then
  echo "[2/3] pip already bootstrapped — skipping."
else
  echo "[2/3] Bootstrapping pip (slow under emulation)…"
  exec_c "cd /config \
    && curl -fsSL -o get-pip.py '${GETPIP_URL}' \
    && wine 'C:\Python39\python.exe' get-pip.py --no-warn-script-location \
    && rm get-pip.py"
fi

echo "[3/3] Installing MetaTrader5 + rpyc + numpy (slow under emulation)…"
exec_c "wine 'C:\Python39\python.exe' -m pip install --no-cache-dir --no-warn-script-location \
  'MetaTrader5==5.0.5735' 'rpyc==6.0.2' 'numpy<2'"

echo "Verifying imports…"
exec_c "wine 'C:\Python39\python.exe' -c \"import rpyc, MetaTrader5, numpy; print('wine-side OK: rpyc', rpyc.__version__, '| MetaTrader5', MetaTrader5.__version__, '| numpy', numpy.__version__)\" 2>/dev/null"

echo "Done. Restart the container so the s6 service picks everything up:"
echo "  docker restart ${C}"
