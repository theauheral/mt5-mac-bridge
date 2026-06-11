"""CI-runnable tests against the MMetaTrader5 mock backend — no broker, no network.

These exercise the package's public API and the mock compatibility shim. The
bridge/native backends need a live terminal and are covered by tests/test_smoke.py
(manual). Run: `pytest` (the `mock` extra / dev group provides MMetaTrader5).
"""

from __future__ import annotations

import sys

import pytest

import mt5_mac_bridge as mt5b

pytest.importorskip("MMetaTrader5", reason="install the 'mock' extra to run mock tests")


def test_resolve_backend_explicit():
    assert mt5b.resolve_backend("mock") == mt5b.MOCK
    assert mt5b.resolve_backend("bridge") == mt5b.BRIDGE
    assert mt5b.resolve_backend("native") == mt5b.NATIVE


def test_resolve_backend_rejects_garbage():
    with pytest.raises(ValueError):
        mt5b.resolve_backend("nope")


def test_resolve_backend_env(monkeypatch):
    monkeypatch.setenv("MT5_BACKEND", "mock")
    assert mt5b.resolve_backend() == mt5b.MOCK


def test_is_bridge_up_closed_port():
    # Nothing should be listening on this port during tests.
    assert mt5b.is_bridge_up(port=1, timeout=0.2) is False


def test_init_mock_connects_and_registers():
    h = mt5b.init(backend="mock")
    try:
        assert h.backend == mt5b.MOCK
        assert h.registered is True
        # Registered as the global MetaTrader5 alias for drop-in code.
        assert sys.modules.get("MetaTrader5") is h.mt5
        acct = h.mt5.account_info()
        assert acct.balance > 0
        # Shim fills the gaps the mock omits.
        assert h.mt5.version()[0] == 500
        assert h.mt5.last_error() == (0, "MMetaTrader5 mock: no error tracking")
        # Constant fallback for a name the mock lacks.
        assert h.mt5.POSITION_TYPE_BUY == 0
        rates = h.mt5.copy_rates_from_pos("EURUSD", h.mt5.TIMEFRAME_M5, 0, 5)
        assert len(rates) > 0
    finally:
        mt5b.shutdown(h)
    # shutdown unregisters the alias.
    assert sys.modules.get("MetaTrader5") is not h.mt5


def test_init_no_register_leaves_sys_modules_clean():
    sys.modules.pop("MetaTrader5", None)
    h = mt5b.init(backend="mock", register=False)
    try:
        assert h.registered is False
        assert "MetaTrader5" not in sys.modules
    finally:
        mt5b.shutdown(h)
