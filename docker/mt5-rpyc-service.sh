#!/usr/bin/env bash
# s6 custom service (mounted at /custom-services.d/mt5-rpyc): rpyc classic
# server under Wine Python, exposing the MetaTrader5 API on :8001.
#
# Replaces the gmag11 image's built-in [7/7] mt5linux launcher, which is broken
# two ways on this setup: (a) the unpinned mt5linux from PyPI no longer accepts
# the -w flag start.sh passes, and (b) the Wine Python *installer* crashes under
# emulation, so we provision the embeddable Python zip at C:\Python39 instead
# (see README_MT5_SETUP.md "first-boot provisioning").
#
# s6 supervises this: if the server dies it is restarted automatically.
PY="/config/.wine/drive_c/Python39/python.exe"

# Wait out first-boot provisioning (MT5 install + embeddable python drop-in).
until [ -f "$PY" ]; do
  echo "[mt5-rpyc] waiting for Wine python at $PY ..."
  sleep 15
done

echo "[mt5-rpyc] starting rpyc SlaveService on 0.0.0.0:8001 (wine, qemu — slow start)"
exec s6-setuidgid abc env WINEPREFIX=/config/.wine HOME=/config DISPLAY=:1 \
  wine 'C:\Python39\python.exe' -c "from rpyc.utils.server import ThreadedServer; from rpyc.core import SlaveService; ThreadedServer(SlaveService, hostname='0.0.0.0', port=8001, reuse_addr=True).start()"
