# Live Trading Checklist

Do not flip any of these until every item above it is verified.

## 1. Paper mode validation
- [ ] `execution.mode: PAPER` and `execution.allow_live_orders: false` in
      `config/config.yaml` (this is the default — verify it hasn't drifted).
- [ ] Run the engine in paper mode for at least one full live session and
      confirm `outputs/orders.csv` shows the expected BUY/SELL/exit sequence
      matching the signals.
- [ ] Backtest the same window and confirm signal counts/timestamps match
      the paper-mode run (sanity check that nothing diverged).

## 2. Instrument selection
- [ ] Confirm `execution.instrument_mode` matches intent (FUTURES /
      OPTION_BUYING / OPTION_SELLING).
- [ ] Confirm the scrip master downloaded successfully
      (`data/cache/angelone_scrip_master.json` exists and is recent).
- [ ] For options: confirm expiry_mode resolves to the contract you expect
      (BankNifty monthly vs Nifty weekly Tuesday) — check the printed
      "Instrument selected" log line at startup/first signal.

## 3. Risk controls
- [ ] `risk_management.enable_mae_exit` is set and `mae_points` matches your
      risk appetite.
- [ ] `entry_filters.blocked_entry_windows` covers the time blocks you want
      excluded.
- [ ] Confirm `POST /risk/disable-live-trading` actually blocks an order in a
      paper-mode dry run (write `data/cache/EMERGENCY_STOP` manually and
      confirm the next signal logs a `BLOCKED` row instead of an order).
- [ ] Confirm `POST /risk/exit-all` flattens an open paper position.

## 4. Broker reconciliation
- [ ] With a manually-opened broker position, start the engine and confirm
      it writes `EMERGENCY_STOP` and pauses instead of stacking an order on
      top of the unexpected position (see
      `ExecutionManager.startup_sync` in
      `trading_engine/execution_engine/execution.py`).
- [ ] Flatten manually, restart, confirm it proceeds normally.

## 5. Going live
- [ ] Set `execution.mode: LIVE` (or `POST /engine/live-mode {"confirm": true}`).
- [ ] Set `execution.allow_live_orders: true` only after the above are all
      green — this is the final gate that actually lets an order reach the
      broker.
- [ ] Start with `execution.lots: 1` / minimum quantity for the first live
      session regardless of backtested size.
- [ ] Watch the dashboard's Risk Control screen for the first session; keep
      the emergency-stop button reachable.
- [ ] Confirm `system_logs`/`risk_events` (or `outputs/orders.csv` if DB
      logging isn't wired up yet) are being written for every order.

## 6. Rollback plan
- [ ] Know how to immediately stop new orders: `POST /risk/disable-live-trading`
      or `touch data/cache/EMERGENCY_STOP` directly on the host/container.
- [ ] Know how to flatten everything: `POST /risk/exit-all` or
      `touch data/cache/EXIT_ALL_REQUESTED`.
- [ ] Know how to stop the engine process entirely: `POST /engine/stop` or
      `systemctl stop trading-engine` / `docker compose stop trading-engine`.
