#!/usr/bin/env bash
# Container entrypoint: virtual display -> VNC -> MT5 terminal -> rpyc bridge.
# Paired with Dockerfile.mt5 (a starting template — see its header).
set -e

PORT="${MT5_RPYC_PORT:-18812}"

# 1) Virtual framebuffer so the (GUI-only) MT5 terminal has a display.
Xvfb :100 -ac -screen 0 1366x768x24 >/tmp/xvfb.log 2>&1 &

# 2) VNC + noVNC web UI on :6081 — used once to log in to the broker account.
x11vnc -display :100 -forever -nopw -rfbport 5900 >/tmp/x11vnc.log 2>&1 &
websockify --web=/usr/share/novnc 6081 localhost:5900 >/tmp/novnc.log 2>&1 &

# 3) Launch the MT5 terminal under Wine (no-op if not yet installed).
WINPY="$(find /root/.wine -iname 'python.exe' 2>/dev/null | head -1)"
TERMINAL="$(find /root/.wine -iname 'terminal64.exe' 2>/dev/null | head -1)"
[ -n "${TERMINAL}" ] && wine "${TERMINAL}" >/tmp/mt5.log 2>&1 &

# 4) Start the rpyc bridge against the Windows Python that holds MetaTrader5.
if [ -n "${WINPY}" ]; then
  echo "Starting siliconmetatrader5 rpyc server on :${PORT} (win python: ${WINPY})"
  exec python3 -m siliconmetatrader5 "${WINPY}" --host 0.0.0.0 -p "${PORT}"
else
  echo "Windows Python not found under Wine. Open the VNC UI (http://localhost:6081/vnc.html)"
  echo "to install Windows Python + MetaTrader5, then restart this container."
  # Keep the container alive so you can finish setup via VNC.
  tail -f /dev/null
fi
