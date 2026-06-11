# mt5-mac-bridge

Use the **MetaTrader 5 Python API from macOS and Linux.**

The official [`MetaTrader5`](https://pypi.org/project/MetaTrader5/) package is
**Windows-only** — a compiled binary that talks to a local MT5 terminal over
Windows IPC, with no Mac/Linux build and no network API. `mt5-mac-bridge` gives
you the *same* API everywhere by brokering three interchangeable backends behind
one object:

| backend  | what it is | install | use for |
|----------|------------|---------|---------|
| `bridge` | rpyc client → a real MT5 terminal under Wine (Docker, or the macOS MT5.app's own Rosetta Wine) | `pip install 'mt5-mac-bridge[bridge]'` | dev / forward-test on Mac & Linux |
| `mock`   | pure-Python stub — no broker, no network | `pip install 'mt5-mac-bridge[mock]'` | offline logic + unit tests |
| `native` | the official `MetaTrader5` package (Windows only) | `pip install 'mt5-mac-bridge[native]'` | **live capital** |

All three speak the identical MT5 API (constants + 32 functions), so your code
is written once.

## Install

```bash
pip install 'mt5-mac-bridge[bridge,mock]'      # Mac/Linux dev
# or with uv:
uv add 'mt5-mac-bridge[bridge,mock]'
```

## Quick start

```python
import mt5_mac_bridge as mt5b

h = mt5b.init()                 # backend from MT5_BACKEND env, else auto-detect
print(h.mt5.account_info())
rates = h.mt5.copy_rates_from_pos("EURUSD", h.mt5.TIMEFRAME_M5, 0, 100)
mt5b.shutdown(h)
```

`init()` also registers the chosen backend as `sys.modules["MetaTrader5"]`, so
**any existing code that does `import MetaTrader5 as mt5` works unchanged** — pass
`register=False` to opt out.

### Backend selection

Precedence: explicit arg → `MT5_BACKEND` env → `auto` (bridge if its port is open,
else mock).

```python
mt5b.init(backend="mock")                       # force the offline mock
mt5b.init(backend="bridge", port=18813)         # native macOS app bridge
```

Configure via env (credentials never belong in code):

```dotenv
MT5_BACKEND=auto          # auto | bridge | mock | native
MT5_BRIDGE_HOST=localhost
MT5_BRIDGE_PORT=18812     # Docker bridge; native macOS app bridge defaults to 18813
MT5_LOGIN=
MT5_PASSWORD=
MT5_SERVER=
MT5_PATH=                 # override the in-Wine terminal64.exe path if non-standard
```

## Standing up a bridge

### Option A — Docker (reproducible)

Uses the maintained [`gmag11/metatrader5_vnc`](https://github.com/gmag11/MetaTrader5-Docker)
image (MT5 under Wine + an rpyc server + a web VNC). On Apple Silicon, run Docker
Desktop with **QEMU** emulation (Settings → General → uncheck "Use Rosetta…") —
Rosetta crashes Wine.

```bash
scripts/mt5_bridge.sh up        # docker compose up -d (first run pulls ~1.6 GB)
# then log into a broker once via http://localhost:3000 (File > Open an Account)
scripts/mt5_bridge.sh test      # should report backend "bridge" + real bars
```

If the image's in-container Python provisioning is broken (it can be), repair it:
`docker/provision-wine-python.sh` (embeddable Python + `MetaTrader5` + `rpyc`),
and `docker/mt5-rpyc-service.sh` runs the rpyc server under s6 supervision.

### Option B — Native macOS app (no Docker, Rosetta-speed)

The MetaTrader 5.app **is** a Wine bottle. Inject a Windows Python + the package
into its own prefix and run the rpyc server with the app's own Wine — native
Python then reaches the terminal you already use.

```bash
scripts/mt5_native_bridge.sh provision    # one-time: Python + MetaTrader5 + rpyc
# open MetaTrader 5.app and log into an account
scripts/mt5_native_bridge.sh serve        # rpyc server on :18813
MT5_BACKEND=bridge MT5_BRIDGE_PORT=18813 python tests/test_smoke.py
```

## Gotchas (hard-won)

- **`-10005 IPC timeout`** on a fresh terminal until you log into a broker once
  via the GUI — selecting the company alone isn't enough.
- **`10027 AutoTrading disabled by client`** until the **Algo Trading** toolbar
  button is green; there's no API override.
- **Filling mode**: some brokers reject IOC (`10030`) and want FOK. Read the
  symbol's `filling_mode` bitmask (1=FOK, 2=IOC) and pick accordingly.
- **`order_check`** in the upstream `siliconmetatrader5` client returns `None`
  due to an `*args`-serialization bug; this package patches it automatically to
  the working direct-dict form when the bridge backend is created.
- **Apple Silicon Docker** must use **QEMU, not Rosetta** (Rosetta crashes Wine).

## The mock is not a faithful clone

The `mock` backend (`MMetaTrader5`) is randomised stub data for offline logic
testing only. Known divergences are enumerated in `mt5_mac_bridge.MOCK_GAPS`
(e.g. `order_check`/`copy_rates_range` missing, different `TIMEFRAME_*` integer
values, structurally different position objects). The shim papers over the worst
(`initialize`/`login`/`last_error`/`version`), but never mistake "passes against
the mock" for "works against a broker".

## Production note

For **real-money trading**, run on **native Windows** (`MT5_BACKEND=native`, zero
code change) — a VPS or VM, not a laptop bridge. The Wine+rpyc bridge is great for
development and paper/forward-testing but adds emulation latency and depends on
community-maintained, unsupported layers; not suited to live execution.

## License

MIT
