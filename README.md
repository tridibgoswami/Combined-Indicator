# SVMKR UT HMA ORB Chop-No-ADX Engine

Run live mode:

```bash
python main.py
```

Run broker-backed backtest:

```bash
python main.py --from 2026-06-15 --to 2026-06-22 --export results.csv
```

The backtest now logs into AngelOne, checks the local candle cache, downloads missing historical candles, updates `data/cache/`, and then runs the same indicator/trade/risk engine used by live mode.

Offline CSV backtest is still available only when explicitly requested:

```bash
python main.py --source csv --csv data/sample.csv --from 2026-06-01 --to 2026-06-01 --export results.csv
```

## Important behavior

- Broker is the default source of truth for live and backtest.
- CSV is only cache/offline research, not the default.
- If the requested date range is not available, the engine raises a clear error instead of returning misleading zero trades.
- Warmup candles are fetched before the requested backtest start date so indicator state is stable.
- MAE exits remain trade/risk-layer exits and do not alter BUY/SELL indicator signal generation.

## New config section

```yaml
data:
  use_cache: true
  cache_dir: data/cache
  max_days_per_fetch: 30
  fetch_sleep_seconds: 0.35

backtest:
  source: broker
  use_csv: false
  export: backtest_results.csv
  warmup_days: 10
  warmup_calendar_multiplier: 3
  force_refresh: false
```

## CLI

```bash
python main.py --from 2026-06-15 --to 2026-06-22
python main.py --from "2026-06-15 09:15" --to "2026-06-22 15:30" --export outputs/june_results.csv
python main.py --from 2026-06-15 --to 2026-06-22 --force-refresh
```


## MAE backtest usage

Backtest uses the same trade/risk engine as live. To enable the fixed-points MAE cap for one run:

```bash
python main.py --from 2026-06-15 --to 2026-06-22 --mae-points 400 --export results.csv
```

Or set it in `config/config.yaml`:

```yaml
risk_management:
  mode: FIXED_POINTS
  enable_mae_exit: true
  mae_points: 400
```

The backtest console now prints `Risk Control` so you can immediately verify whether MAE is enabled. If it says disabled, losses will continue until the next opposite BUY/SELL signal.

## Configurable Entry Time Block Filter

The engine now supports optional intraday time windows where **new entries are blocked**.
This is useful for testing/avoiding weak time periods such as `10:30-11:00`.

Configure in `config/config.yaml`:

```yaml
entry_filters:
  enable_time_block_filter: true
  blocked_entry_windows:
    - "10:30-11:00"
    - "13:15-13:45"
```

Rules:

- Blocks **new BUY/SELL entries only**.
- Does **not** block exits.
- Does **not** block MAE exits.
- If an opposite signal appears inside a blocked window while a position is open, the engine exits the current position but does not reverse into the new position.
- End time is exclusive: `10:30-11:00` blocks 10:30 through 10:59 and allows 11:00.

Backtest normally to compare results:

```bash
python main.py --from 2026-01-01 --to 2026-06-22 --export results.csv
```

## Production execution instrument selection

This version separates the signal instrument from the execution instrument.

- `instrument:` is used for signal candles. Default is BANKNIFTY index token `99926009`.
- `execution:` is used for order placement. The engine downloads AngelOne's scrip master at startup and auto-selects the nearest active BANKNIFTY futures contract when `execution.instrument_selector.enabled: true`.

Startup now performs:

1. AngelOne login.
2. Historical warmup reconstruction.
3. AngelOne NFO scrip-master download/cache.
4. Nearest futures contract selection.
5. Optional paper/live execution sync.

Example expected log:

```text
AngelOne login successful.
Downloading AngelOne instrument list...
Instrument list loaded: <N> contracts
[BANKNIFTY] Futures: BANKNIFTY<EXPIRY>FUT | Expiry: <date> | Lot: 30 | Token: <token>
Execution instrument ready: BANKNIFTY<EXPIRY>FUT | Token: <token> | Lot: 30
Execution mode: PAPER | Qty: 30 | Startup trade: False
```

### Safe execution defaults

Order execution is disabled by default:

```yaml
execution:
  enabled: false
  mode: PAPER
  allow_live_orders: false
```

Paper execution:

```yaml
execution:
  enabled: true
  mode: PAPER
```

Live execution requires all of the following:

```yaml
execution:
  enabled: true
  mode: LIVE
  allow_live_orders: true
```

or equivalent `.env` values:

```env
EXECUTION_ENABLED=true
EXECUTION_MODE=LIVE
ALLOW_LIVE_ORDERS=true
```

The engine will not automatically place a trade just because a reconstructed historical signal is open unless this is explicitly enabled:

```yaml
execution:
  trade_reconstructed_position_on_startup: true
```

The default is `false` to avoid entering stale positions after a restart. Future signal changes after startup can still trigger paper/live orders when execution is enabled.


## Execution modes

The engine supports three execution instrument modes. Signal generation is unchanged.

### 1) Futures

```yaml
execution:
  enabled: true
  mode: PAPER
  allow_live_orders: false
  instrument_mode: FUTURES
```

BUY = long the auto-selected index future. SELL = short the auto-selected index future.

### 2) Option buying

```yaml
execution:
  enabled: true
  mode: PAPER
  allow_live_orders: false
  instrument_mode: OPTION_BUYING

option_execution:
  expiry_mode: NEAREST
  strike_selection:
    mode: DELTA
    target_delta: 0.60
    fallback: ATM
```

BUY signal closes any existing PE and buys CE. SELL signal closes any existing CE and buys PE.

Delta selection currently uses a deterministic ATM/ITM delta proxy from the AngelOne NFO scrip master and live underlying LTP. If a broker Greek feed is added later, it can replace the proxy without changing the execution interface.

### 3) Option selling

```yaml
execution:
  enabled: true
  mode: PAPER
  allow_live_orders: false
  instrument_mode: OPTION_SELLING

option_execution:
  option_selling:
    short_delta: 0.30
    hedge_strikes: 5
```

BUY signal opens a Bull Put Spread: SELL PE + BUY lower PE hedge.
SELL signal opens a Bear Call Spread: SELL CE + BUY higher CE hedge.

Live orders require both:

```yaml
execution:
  mode: LIVE
  allow_live_orders: true
```

Keep `mode: PAPER` until signals, strikes, orders, and broker positions are verified.

## Running as a platform

The engine above still runs standalone with `python main.py` exactly as
before — nothing about signal generation, backtesting, or CLI usage has
changed. On top of it, this repo also ships an optional production
platform: a FastAPI backend, a Postgres/Redis-backed control plane, and a
mobile-friendly PWA dashboard for monitoring and controlling the engine
remotely.

### Engine-only (unchanged)

```bash
python main.py --from 2026-06-15 --to 2026-06-22
```

### Full platform (Docker Compose)

```bash
cp .env.example .env   # fill in AngelOne credentials and secrets, never commit this file
docker compose -f deployment/docker-compose.yml up -d
```

This starts Postgres, Redis, the trading engine, the FastAPI backend
(`backend_api/`), the Next.js PWA dashboard (`mobile_dashboard/`), and an
nginx reverse proxy. See `docs/ARCHITECTURE.md` for the component
breakdown, `docs/DEPLOYMENT.md` for VPS/systemd setup, and
`docs/LIVE_TRADING_CHECKLIST.md` before flipping `execution.mode: LIVE`.

The trading engine process never depends on Postgres/Redis/the API — it
reads `config/config.yaml` and writes to `outputs/`/`data/cache/` exactly
as it does standalone. The backend only reads those outputs and writes
file-based control flags (`EMERGENCY_STOP`, `EXIT_ALL_REQUESTED`) that the
engine checks before placing orders. If the backend or dashboard goes
down, the engine keeps trading uninterrupted; see
`docs/FAILURE_SCENARIOS.md`.
