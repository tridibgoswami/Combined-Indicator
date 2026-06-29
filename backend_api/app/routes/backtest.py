from __future__ import annotations

import subprocess
import sys
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from backend_api.app.auth.security import get_current_user
from backend_api.app.database.models import User
from backend_api.app.schemas.schemas import BacktestRunRequest, BacktestRunResponse

router = APIRouter(prefix="/backtest", tags=["backtest"])

ROOT = Path(__file__).resolve().parents[3]
RESULTS_DIR = ROOT / "outputs" / "backtests"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/run", response_model=BacktestRunResponse)
def run_backtest(payload: BacktestRunRequest, user: User = Depends(get_current_user)):
    backtest_id = str(uuid.uuid4())
    export_path = RESULTS_DIR / f"{backtest_id}.csv"
    args = [
        sys.executable, str(ROOT / "main.py"),
        "--from", payload.start, "--to", payload.end,
        "--export", str(export_path),
        "--source", payload.source,
    ]
    if payload.csv_path:
        args += ["--csv", payload.csv_path]
    if payload.mae_points is not None:
        args += ["--mae-points", str(payload.mae_points)]
    log_path = RESULTS_DIR / f"{backtest_id}.log"
    with log_path.open("w") as log_file:
        subprocess.run(args, cwd=str(ROOT), stdout=log_file, stderr=subprocess.STDOUT)
    return BacktestRunResponse(backtest_id=backtest_id, status="completed" if export_path.exists() else "failed")


@router.get("/results/{backtest_id}")
def get_results(backtest_id: str, user: User = Depends(get_current_user)):
    export_path = RESULTS_DIR / f"{backtest_id}.csv"
    if not export_path.exists():
        raise HTTPException(status_code=404, detail="Backtest result not found")
    import csv
    with export_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return {"backtest_id": backtest_id, "rows": rows}
