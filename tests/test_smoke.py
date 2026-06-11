#!/usr/bin/env python
"""Manual end-to-end smoke test against a live bridge (not run in CI).

Resolves a backend (MT5_BACKEND env, else auto: bridge if its port is open,
else the offline mock), connects, prints account/terminal info, fetches a few
bars, and shuts down cleanly.

    MT5_BACKEND=bridge MT5_BRIDGE_PORT=18812 python tests/test_smoke.py   # Docker
    MT5_BACKEND=bridge MT5_BRIDGE_PORT=18813 python tests/test_smoke.py   # native app
    MT5_BACKEND=mock                          python tests/test_smoke.py   # offline

Exit code 0 = the selected backend connected and returned data.
"""

from __future__ import annotations

import logging
import sys

import mt5_mac_bridge as mt5b

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

PROBE_SYMBOL = "EURUSD"


def main() -> int:
    print("=" * 64)
    print("mt5-mac-bridge smoke test")
    print("=" * 64)
    try:
        handle = mt5b.init()
    except Exception as exc:  # noqa: BLE001
        print(f"\n[FAIL] could not initialise any MT5 backend: {exc}")
        return 1

    mt5 = handle.mt5
    print(f"\nbackend : {handle.backend}")
    try:
        print(f"version : {mt5.version()}")
        acct = mt5.account_info()
        if acct is not None:
            print(
                f"account : login={getattr(acct, 'login', '?')} "
                f"balance={getattr(acct, 'balance', '?')} "
                f"currency={getattr(acct, 'currency', '?')} "
                f"server={getattr(acct, 'server', '?')}"
            )
        mt5.symbol_select(PROBE_SYMBOL, True)
        rates = mt5.copy_rates_from_pos(PROBE_SYMBOL, mt5.TIMEFRAME_M5, 0, 5)
        n = len(rates) if rates is not None and hasattr(rates, "__len__") else 0
        print(f"rates   : {PROBE_SYMBOL} M5 -> {n} bars")
        if n:
            print(f"          last bar: {rates[-1]}")
    except Exception as exc:  # noqa: BLE001
        print(f"\n[FAIL] backend call errored: {exc}")
        mt5b.shutdown(handle)
        return 1

    mt5b.shutdown(handle)
    print("\n[OK] smoke test passed; connection closed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
