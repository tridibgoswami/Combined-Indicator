from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Optional

from backend_api.app.services import redis_state

ROOT = Path(__file__).resolve().parents[3]
PID_FILE = ROOT / "data" / "cache" / "engine.pid"
PAUSE_FLAG = ROOT / "data" / "cache" / "ENGINE_PAUSED"
ENGINE_ID = "trading-engine-1"

_process: Optional[subprocess.Popen] = None


def _read_pid() -> Optional[int]:
    if not PID_FILE.exists():
        return None
    try:
        return int(PID_FILE.read_text().strip())
    except Exception:
        return None


def _is_running(pid: Optional[int]) -> bool:
    if pid is None:
        return False
    try:
        subprocess.run(["kill", "-0", str(pid)], check=True, capture_output=True)
        return True
    except Exception:
        return False


def status() -> dict:
    pid = _read_pid()
    running = _is_running(pid)
    heartbeat = redis_state.get_heartbeat()
    # In a Docker Compose deployment the engine runs as its own container
    # process rather than being spawned by backend_api, so the PID file is
    # never created. A recent Redis heartbeat (TTL-bound, written by the
    # engine itself) is then the only valid liveness signal.
    if heartbeat is not None:
        running = True
    paused = PAUSE_FLAG.exists()
    state_data = redis_state.get_engine_state() or {}
    return {
        "engine_id": ENGINE_ID,
        "state": "PAUSED" if (running and paused) else ("RUNNING" if running else "STOPPED"),
        "mode": (heartbeat or {}).get("mode") or state_data.get("mode", "PAPER"),
        "instrument_mode": (heartbeat or {}).get("instrument_mode") or state_data.get("instrument_mode"),
        "pid": pid if pid and _is_running(pid) else None,
        "detail": (heartbeat or {}).get("detail") or state_data.get("detail"),
    }


def start(config_path: str = "config/config.yaml") -> dict:
    # Container deployment: the engine process is already alive in its own
    # container, so "start" just clears the pause flag it polls.
    if PAUSE_FLAG.exists():
        PAUSE_FLAG.unlink()
    # Local/non-Docker fallback: also spawn main.py directly if no PID is tracked.
    pid = _read_pid()
    if not _is_running(pid) and redis_state.get_heartbeat() is None:
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.Popen(
            [sys.executable, str(ROOT / "main.py"), "--config", config_path],
            cwd=str(ROOT),
            stdout=open(ROOT / "logs" / "engine_stdout.log", "a"),
            stderr=subprocess.STDOUT,
        )
        PID_FILE.write_text(str(proc.pid))
    redis_state.set_engine_state({"mode": "PAPER", "detail": "started"})
    return status()


def stop() -> dict:
    # Container deployment: pause flag tells the running engine process to
    # idle without exiting (so the container's restart policy doesn't fight us).
    PAUSE_FLAG.parent.mkdir(parents=True, exist_ok=True)
    PAUSE_FLAG.write_text("paused via backend_api /engine/stop")
    # Local/non-Docker fallback: kill the tracked subprocess if one exists.
    pid = _read_pid()
    if pid and _is_running(pid):
        subprocess.run(["kill", str(pid)], capture_output=True)
    if PID_FILE.exists():
        PID_FILE.unlink()
    redis_state.set_engine_state({"mode": "PAPER", "detail": "stopped"})
    return status()


def restart(config_path: str = "config/config.yaml") -> dict:
    stop()
    return start(config_path)


def exit_all() -> None:
    flag = ROOT / "data" / "cache" / "EXIT_ALL_REQUESTED"
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("requested via backend_api")


def disable_live_trading() -> None:
    redis_state.set_emergency_stop(True)
    flag = ROOT / "data" / "cache" / "EMERGENCY_STOP"
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("disabled via backend_api /risk/disable-live-trading")


def enable_live_trading() -> None:
    redis_state.set_emergency_stop(False)
    flag = ROOT / "data" / "cache" / "EMERGENCY_STOP"
    if flag.exists():
        flag.unlink()
