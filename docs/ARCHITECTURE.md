# Architecture

## Overview

The platform has two independently-deployable halves that communicate only
through the filesystem and lightweight control flags — there is no hard
runtime dependency between them, so the original engine keeps working with
plain `python main.py` even if the backend/dashboard/DB are never started.

```
trading_engine/   <- unchanged signal/backtest/execution logic, now packaged
backend_api/      <- FastAPI control plane: auth, DB, Redis, REST API
mobile_dashboard/ <- Next.js PWA that talks to backend_api over HTTP
deployment/       <- docker-compose, nginx, systemd, CI/CD glue
```

## trading_engine/

- `signal_engine/` — indicator math (`indicator.py`) and trade/MAE/time-block
  logic (`trades.py`). Untouched besides import path changes.
- `execution_engine/` — `ExecutionManager`: futures/option order alignment,
  paper/live gate, idempotency, emergency-stop and exit-all flags.
- `broker_adapters/` — `AngelOneBroker` (SmartAPI login, candles, orders).
- `instrument_selector/` — scrip master download + futures/option contract
  resolution (delta-proxy strike selection, spread hedge selection).
- `data/`, `backtest/`, `notifications/`, `risk_engine/` — supporting/empty
  packages kept for the target layout; MAE/risk logic still lives inside
  `signal_engine/trades.py` by design (rule: don't move signal logic).
- `runner.py` / `config.py` — state machine (backtest/replay/live) and YAML +
  env config loader, same behavior as before the restructure.

`main.py` at the repo root is unchanged in spirit: `python main.py` still
runs backtest/replay/live exactly as configured in `config/config.yaml`.

## backend_api/

FastAPI app (`app/main.py`) exposing:
- `auth/` — JWT login, bcrypt password hashing, admin-only dependency.
- `database/` — SQLAlchemy models (Postgres in prod, SQLite for local/dev/CI)
  for users, engine_status, signals, trades, orders, positions,
  pnl_snapshots, broker_sessions, risk_events, config_audit_log, system_logs.
- `services/`
  - `engine_controller.py` — starts/stops the trading engine as a subprocess
    (`python main.py`) and tracks its PID; this is intentionally a process
    boundary, not an in-process call, so a backend crash can't take the
    engine down with it.
  - `redis_state.py` — engine state cache, emergency-stop flag, rate-limit
    locks (used by multi-instance deployments; single-instance deployments
    can rely on the in-process limiter in `main.py`).
  - `outputs_service.py` — reads the engine's own CSV/JSON outputs
    (`outputs/orders.csv`, `outputs/live_latest_*`) rather than requiring the
    engine to write directly to Postgres. Keeps `trading_engine` free of any
    backend/DB dependency.
  - `config_service.py` — reads/patches `config/config.yaml` by dotted path,
    writes every change to `config_audit_log`.
- `routes/` — one module per resource area (auth, engine, trading, backtest,
  config, health), matching the required endpoint list.

## Execution safety model

The execution engine never talks to Redis or Postgres directly. Instead it
watches two filesystem flags under `data/cache/`:

- `EMERGENCY_STOP` — when present, `align_to_strategy()` blocks all new
  orders and logs a `BLOCKED` row to `orders.csv`. Written by
  `POST /risk/disable-live-trading`, or automatically on startup if the
  broker's reconciled position conflicts with the strategy's reconstructed
  position.
- `EXIT_ALL_REQUESTED` — when present, the engine flattens any open
  position/legs on its next loop tick and deletes the flag. Written by
  `POST /risk/exit-all`.

This means the safety gates work even if Redis/Postgres/the backend are
down — the engine only needs to read two files it already has filesystem
access to.

Idempotency: each candle-close signal carries a key of
`f"{candle_datetime}:{instrument_mode}:{strategy_position}"`; the execution
manager skips re-firing an order for a key it has already processed, which
covers reprocessing the same closed candle after a restart.

## mobile_dashboard/

Next.js + `next-pwa` app with pages for Login, Dashboard, Signals, Orders,
Positions, Backtest, Risk Control and Settings, all calling `backend_api`
over `NEXT_PUBLIC_API_URL`. Installable on a phone home screen via the PWA
manifest/service worker.
