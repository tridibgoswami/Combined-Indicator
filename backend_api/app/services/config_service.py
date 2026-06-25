from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.orm import Session

from backend_api.app.database.models import ConfigAuditLog

ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = ROOT / "config" / "config.yaml"


def read_config() -> dict[str, Any]:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}


def _get_by_path(cfg: dict, dotted: str) -> Any:
    node = cfg
    for part in dotted.split("."):
        node = (node or {}).get(part)
    return node


def _set_by_path(cfg: dict, dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    node = cfg
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value


def patch_config(dotted_path: str, value: Any, db: Session, user_id: int | None) -> dict[str, Any]:
    cfg = read_config()
    old_value = _get_by_path(cfg, dotted_path)
    _set_by_path(cfg, dotted_path, value)
    CONFIG_PATH.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")

    log = ConfigAuditLog(
        user_id=user_id,
        path=dotted_path,
        old_value=str(old_value),
        new_value=str(value),
    )
    db.add(log)
    db.commit()
    return cfg
