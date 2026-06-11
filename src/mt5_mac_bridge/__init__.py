"""mt5-mac-bridge — use the MetaTrader 5 Python API from macOS (and Linux).

The official ``MetaTrader5`` pip package is **Windows-only** — it ships a binary
that talks to a locally running MT5 terminal over IPC, and there is no native
macOS/Linux build. This package brokers three interchangeable backends behind a
single, API-faithful object so the same code runs everywhere:

============  ===========================================================
 backend       what it is / when to use
============  ===========================================================
 ``bridge``    ``siliconmetatrader5`` client → a real MT5 terminal running
               headless under Wine (Docker container, or the macOS MT5.app's
               own Rosetta Wine prefix), reached over an rpyc socket. The
               working path on Apple Silicon.
 ``mock``      ``MMetaTrader5`` — a pure-Python stub. No broker, no network.
               For writing/unit-testing trading *logic* offline. NOT a
               faithful clone (see ``MOCK_GAPS``) — flagged loudly.
 ``native``    the real ``MetaTrader5`` package. Only importable on Windows
               (or Windows-Python under Wine). Recommended for live capital.
============  ===========================================================

Usage::

    import mt5_mac_bridge as mt5b

    h = mt5b.init()                  # backend from MT5_BACKEND env, else auto
    print(h.mt5.account_info())
    rates = h.mt5.copy_rates_from_pos("EURUSD", h.mt5.TIMEFRAME_M5, 0, 100)
    mt5b.shutdown(h)

By default ``init`` also registers the resolved backend as
``sys.modules["MetaTrader5"]``, so any third-party code that does
``import MetaTrader5 as mt5`` transparently drives whichever backend you
selected — no edits to that code required.

NEVER hard-code broker credentials. They are read from the environment
(``MT5_LOGIN`` / ``MT5_PASSWORD`` / ``MT5_SERVER`` / ``MT5_PATH``).

See the README for standing up the Docker or native bridge.
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
import socket
import sys
from dataclasses import dataclass
from typing import Any, Optional

__version__ = "0.1.0"

__all__ = [
    "init",
    "shutdown",
    "MT5Handle",
    "resolve_backend",
    "is_bridge_up",
    "BRIDGE",
    "MOCK",
    "NATIVE",
    "AUTO",
    "MOCK_GAPS",
    "DEFAULT_BRIDGE_HOST",
    "DEFAULT_BRIDGE_PORT",
    "DEFAULT_TERMINAL_PATH",
]

logger = logging.getLogger(__name__)

# Backends, in the order ``auto`` tries them.
BRIDGE = "bridge"
MOCK = "mock"
NATIVE = "native"
AUTO = "auto"

DEFAULT_BRIDGE_HOST = "localhost"
# rpyc classic default port. The siliconmetatrader5 container listens here;
# override with MT5_BRIDGE_PORT if you remap it (e.g. 18813 for the native bridge).
DEFAULT_BRIDGE_PORT = 18812

# Standard MT5 install path inside the Wine prefix (Docker image AND macOS app).
# initialize() needs this over the bridge or it can't find the terminal (-10003).
DEFAULT_TERMINAL_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"

# Known divergences of the MMetaTrader5 mock from the real API. Surfaced so
# nobody mistakes "passes against the mock" for "works against a broker".
MOCK_GAPS = (
    "initialize() requires 6 positional args (path, login, password, server, "
    "timeout, portable) — the real API works arg-less; the shim fills defaults.",
    "login() takes NO args — the real API takes (login, password=, server=).",
    "TIMEFRAME_* integer VALUES differ from the real terminal and the bridge — "
    "only ever pass mt5.TIMEFRAME_* symbolically, never a hard-coded int.",
    "missing entirely: last_error, version, copy_rates_range, order_check, "
    "positions_total, symbols_get, symbols_total, history_orders_get "
    "(the shim stubs last_error/version so error paths don't crash).",
    "copy_rates_from() is a no-arg stub; only copy_rates_from_pos() returns data.",
    "all data is randomised/stubbed — no broker, no fills, no real prices.",
)


@dataclass
class MT5Handle:
    """A live MT5 connection plus the backend that produced it.

    ``mt5`` exposes the MetaTrader5 API surface (constants + functions). For the
    ``bridge`` backend it is a connected client *instance*; for ``mock``/``native``
    it is a module (or module-like shim). Either way, ``handle.mt5.account_info()``,
    ``handle.mt5.TIMEFRAME_M5`` etc. work uniformly.
    """

    mt5: Any
    backend: str
    registered: bool = False

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"MT5Handle(backend={self.backend!r}, registered={self.registered})"


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    val = os.getenv(name)
    return val if val not in (None, "") else default


def is_bridge_up(
    host: str = DEFAULT_BRIDGE_HOST,
    port: int = DEFAULT_BRIDGE_PORT,
    timeout: float = 1.0,
) -> bool:
    """True if something is accepting TCP connections at host:port.

    A cheap pre-flight so ``auto`` can fall back to the mock without paying an
    rpyc connection timeout when the bridge isn't running.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def resolve_backend(prefer: Optional[str] = None) -> str:
    """Decide which backend to use.

    Precedence: explicit ``prefer`` arg > ``MT5_BACKEND`` env > ``auto``.
    ``auto`` picks ``bridge`` if the bridge port is open, else ``mock``.
    """
    choice = (prefer or _env("MT5_BACKEND") or AUTO).lower()
    if choice not in (BRIDGE, MOCK, NATIVE, AUTO):
        raise ValueError(
            f"Unknown MT5 backend {choice!r}; expected one of "
            f"{BRIDGE}, {MOCK}, {NATIVE}, {AUTO}."
        )
    if choice != AUTO:
        return choice

    host = _env("MT5_BRIDGE_HOST", DEFAULT_BRIDGE_HOST) or DEFAULT_BRIDGE_HOST
    port = int(_env("MT5_BRIDGE_PORT", str(DEFAULT_BRIDGE_PORT)) or DEFAULT_BRIDGE_PORT)
    if is_bridge_up(host, port):
        logger.info("auto: siliconmetatrader5 bridge reachable at %s:%s", host, port)
        return BRIDGE
    logger.warning(
        "auto: no MT5 bridge at %s:%s — falling back to the MMetaTrader5 MOCK. "
        "This is offline stub data, NOT a broker connection.",
        host,
        port,
    )
    return MOCK


# ---------------------------------------------------------------------------
# Mock compatibility shim
# ---------------------------------------------------------------------------


class _MockShim:
    """Module-like wrapper that makes ``MMetaTrader5`` a closer drop-in.

    Delegates every attribute to the mock module but patches the handful of
    incompatibilities that would otherwise crash code written against the real
    API: an arg-less ``initialize``/``login`` and stubbed ``last_error``/
    ``version``. Everything else passes through.
    """

    # Constants the real API defines that the mock omits, with their genuine
    # integer values. Used only as a fallback when the mock lacks them, so code
    # that reads e.g. POSITION_TYPE_BUY doesn't crash.
    _CONST_FALLBACK = {
        "POSITION_TYPE_BUY": 0,
        "POSITION_TYPE_SELL": 1,
        "ORDER_TYPE_BUY": 0,
        "ORDER_TYPE_SELL": 1,
        "TRADE_ACTION_DEAL": 1,
        "ORDER_FILLING_FOK": 0,
        "ORDER_FILLING_IOC": 1,
        "ORDER_FILLING_RETURN": 2,
        "ORDER_TIME_GTC": 0,
    }

    def __init__(self, mock_mod: Any) -> None:
        self._m = mock_mod

    def initialize(self, *args: Any, **kwargs: Any) -> bool:
        # Real API: initialize() or initialize(path=..., login=..., ...).
        # Mock API: 6 required positionals. Fill defaults from kwargs/env.
        return bool(
            self._m.initialize(
                path=kwargs.get("path", _env("MT5_PATH", "") or ""),
                login=int(kwargs.get("login", _env("MT5_LOGIN", "0") or 0)),
                password=kwargs.get("password", _env("MT5_PASSWORD", "") or ""),
                server=kwargs.get("server", _env("MT5_SERVER", "") or ""),
                timeout=int(kwargs.get("timeout", 0)),
                portable=bool(kwargs.get("portable", False)),
            )
        )

    def login(self, *args: Any, **kwargs: Any) -> bool:
        # Mock's login() takes no args; the real one takes credentials.
        try:
            self._m.login()
        except TypeError:
            pass
        return True

    def last_error(self) -> tuple[int, str]:
        return (0, "MMetaTrader5 mock: no error tracking")

    def version(self) -> tuple[int, int, str]:
        return (500, 0, "MMetaTrader5-mock")

    def __getattr__(self, name: str) -> Any:
        # Mock module first; then real-valued constant fallbacks for the few
        # constants it omits; otherwise it genuinely doesn't exist.
        try:
            return getattr(self._m, name)
        except AttributeError:
            if name in self._CONST_FALLBACK:
                return self._CONST_FALLBACK[name]
            raise


# ---------------------------------------------------------------------------
# Backend constructors
# ---------------------------------------------------------------------------


def _make_bridge(
    host: str,
    port: int,
    login: Optional[str],
    password: Optional[str],
    server: Optional[str],
    path: Optional[str] = None,
) -> Any:
    try:
        from siliconmetatrader5 import MetaTrader5 as BridgeMT5  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - install guard
        raise RuntimeError(
            "siliconmetatrader5 is not installed. Install the bridge extra: "
            "`pip install 'mt5-mac-bridge[bridge]'` (or `pip install siliconmetatrader5`)."
        ) from exc

    mt5 = BridgeMT5(host=host, port=port, keepalive=True)
    init_kwargs: dict[str, Any] = {}
    # The terminal runs inside the remote Wine session; initialize() must be told
    # where terminal64.exe is or it returns -10003 ("MetaTrader 5 x64 not found").
    # Both the Docker image and the macOS app install to this standard path.
    init_kwargs["path"] = path or DEFAULT_TERMINAL_PATH
    if login and password and server:
        init_kwargs.update(login=int(login), password=password, server=server)
    if not mt5.initialize(**init_kwargs):
        err = mt5.last_error()
        try:
            mt5.close()
        except Exception:  # pragma: no cover - best-effort cleanup
            pass
        raise RuntimeError(
            f"Bridge connected to {host}:{port} but MT5 initialize() failed: {err}. "
            "Common causes: the MT5 terminal is still booting (slow under "
            "emulation — retry in a minute), or no broker account is logged in "
            "(a fresh terminal returns -10005 'IPC timeout' until you log in once)."
        )
    # initialize() does not always authenticate; log in explicitly when creds given.
    if login and password and server:
        if not mt5.login(int(login), password=password, server=server):
            err = mt5.last_error()
            mt5.close()
            raise RuntimeError(f"Bridge MT5 login() failed: {err}")
    _patch_bridge_order_check(mt5)
    return mt5


def _patch_bridge_order_check(mt5: Any) -> None:
    """Work around a serialization bug in siliconmetatrader5's ``order_check``.

    The upstream client serializes the call as ``mt5.order_check(*(<req>,), **{})``
    — that ``*args``-unpacking form makes the MT5 terminal reject the request with
    ``(-2, 'Unnamed arguments not allowed')``, so ``order_check`` always returns
    ``None`` over the bridge. ``order_send`` serializes the request *directly*
    (``mt5.order_send(<req>)``) and works fine, so we rebind ``order_check`` to the
    same working form, going through the client's public ``eval()`` — the exact
    rpyc channel ``order_send`` uses, and the server already has ``mt5`` imported
    into its namespace on connect.
    """
    if not hasattr(mt5, "eval"):  # pragma: no cover - non-bridge object
        return

    def _order_check(request: dict[str, Any]) -> Any:
        # Datetimes aren't expected in an order_check request, but normalize to
        # epoch seconds for parity with the client's other eval-based calls.
        clean = {
            k: (int(v.timestamp()) if isinstance(v, _dt.datetime) else v)
            for k, v in dict(request).items()
        }
        return mt5.eval(f"mt5.order_check({clean!r})")

    try:
        mt5.order_check = _order_check  # type: ignore[attr-defined]
        logger.debug("patched bridge order_check (direct-dict eval form)")
    except (AttributeError, TypeError):  # pragma: no cover - defensive
        logger.warning("could not patch bridge order_check; using upstream impl")


def _make_mock() -> Any:
    try:
        import MMetaTrader5 as mock  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - install guard
        raise RuntimeError(
            "MMetaTrader5 is not installed. Install the mock extra: "
            "`pip install 'mt5-mac-bridge[mock]'` (or `pip install MMetaTrader5`)."
        ) from exc

    logger.warning(
        "Using the MMetaTrader5 MOCK backend — offline stub data only, NOT a "
        "broker. Known gaps vs the real API:\n  - %s",
        "\n  - ".join(MOCK_GAPS),
    )
    shim = _MockShim(mock)
    shim.initialize()
    return shim


def _make_native(
    login: Optional[str],
    password: Optional[str],
    server: Optional[str],
    path: Optional[str],
) -> Any:
    try:
        import MetaTrader5 as mt5  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "The official MetaTrader5 package is Windows-only and is not "
            "importable here. On macOS/Linux use backend='bridge' or 'mock'. "
            "For live trading, run on native Windows."
        ) from exc

    init_kwargs: dict[str, Any] = {}
    if path:
        init_kwargs["path"] = path
    if login and password and server:
        init_kwargs.update(login=int(login), password=password, server=server)
    if not mt5.initialize(**init_kwargs):
        raise RuntimeError(f"Native MT5 initialize() failed: {mt5.last_error()}")
    if login and password and server:
        if not mt5.login(int(login), password=password, server=server):
            err = mt5.last_error()
            mt5.shutdown()
            raise RuntimeError(f"Native MT5 login() failed: {err}")
    return mt5


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def init(
    backend: Optional[str] = None,
    *,
    host: Optional[str] = None,
    port: Optional[int] = None,
    login: Optional[str] = None,
    password: Optional[str] = None,
    server: Optional[str] = None,
    path: Optional[str] = None,
    register: bool = True,
) -> MT5Handle:
    """Resolve a backend, connect, and return a ready :class:`MT5Handle`.

    Credentials default to the ``MT5_*`` environment variables. When
    ``register`` is True (default) the resolved backend is installed as
    ``sys.modules["MetaTrader5"]`` so ``import MetaTrader5`` anywhere in the
    process uses it.
    """
    resolved = resolve_backend(backend)
    host = host or _env("MT5_BRIDGE_HOST", DEFAULT_BRIDGE_HOST)
    port = port or int(_env("MT5_BRIDGE_PORT", str(DEFAULT_BRIDGE_PORT)) or DEFAULT_BRIDGE_PORT)
    login = login or _env("MT5_LOGIN")
    password = password or _env("MT5_PASSWORD")
    server = server or _env("MT5_SERVER")
    path = path or _env("MT5_PATH")

    if resolved == BRIDGE:
        mt5 = _make_bridge(host or DEFAULT_BRIDGE_HOST, port, login, password, server, path)
    elif resolved == MOCK:
        mt5 = _make_mock()
    elif resolved == NATIVE:
        mt5 = _make_native(login, password, server, path)
    else:  # pragma: no cover - resolve_backend already validated
        raise ValueError(resolved)

    registered = False
    if register:
        sys.modules["MetaTrader5"] = mt5  # type: ignore[assignment]
        registered = True
        logger.debug("Registered %r backend as sys.modules['MetaTrader5']", resolved)

    logger.info("MT5 backend ready: %s", resolved)
    return MT5Handle(mt5=mt5, backend=resolved, registered=registered)


def shutdown(handle: MT5Handle) -> None:
    """Cleanly tear down a handle and unregister the global MetaTrader5 alias.

    For the bridge, ``close()`` drops *this* client's connection without
    stopping the remote terminal (use ``handle.mt5.shutdown()`` directly if you
    really want to stop the remote MT5).
    """
    mt5 = handle.mt5
    try:
        if handle.backend == BRIDGE and hasattr(mt5, "close"):
            mt5.close()
        elif hasattr(mt5, "shutdown"):
            mt5.shutdown()
    except Exception as exc:  # pragma: no cover - best-effort cleanup
        logger.warning("MT5 shutdown raised (ignored): %s", exc)
    finally:
        if handle.registered and sys.modules.get("MetaTrader5") is mt5:
            del sys.modules["MetaTrader5"]
            handle.registered = False
