from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Enum, Float, ForeignKey, Integer, String, Text, JSON
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Role(str, enum.Enum):
    ADMIN = "ADMIN"
    VIEWER = "VIEWER"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(Enum(Role), default=Role.VIEWER, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class EngineStatus(Base):
    __tablename__ = "engine_status"

    id = Column(Integer, primary_key=True)
    engine_id = Column(String(64), index=True, nullable=False)
    state = Column(String(32), nullable=False)  # STOPPED, STARTING, RUNNING, STOPPING, ERROR
    mode = Column(String(16), nullable=False)  # PAPER, LIVE
    instrument_mode = Column(String(32), nullable=True)
    pid = Column(Integer, nullable=True)
    detail = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Signal(Base):
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True)
    signal_id = Column(String(64), unique=True, index=True, nullable=False)
    engine_id = Column(String(64), index=True)
    instrument = Column(String(64))
    signal_type = Column(String(16))  # BUY/SELL/MAE_EXIT
    price = Column(Float)
    candle_time = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True)
    engine_id = Column(String(64), index=True)
    instrument = Column(String(64))
    entry_time = Column(DateTime)
    entry_signal = Column(String(16))
    entry_price = Column(Float)
    exit_time = Column(DateTime, nullable=True)
    exit_signal = Column(String(16), nullable=True)
    exit_price = Column(Float, nullable=True)
    position = Column(String(16))
    points = Column(Float, nullable=True)
    pnl_value = Column(Float, nullable=True)
    status = Column(String(16))  # OPEN/CLOSED
    created_at = Column(DateTime, default=datetime.utcnow)


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    idempotency_key = Column(String(128), unique=True, index=True, nullable=False)
    engine_id = Column(String(64), index=True)
    mode = Column(String(16))  # PAPER/LIVE
    instrument_mode = Column(String(32))
    action = Column(String(16))
    side = Column(String(8))
    quantity = Column(Integer)
    tradingsymbol = Column(String(64))
    symboltoken = Column(String(32))
    exchange = Column(String(16))
    from_position = Column(Integer)
    to_position = Column(Integer)
    reason = Column(String(128))
    broker_response = Column(JSON, nullable=True)
    status = Column(String(16), default="SUBMITTED")  # SUBMITTED/FILLED/PARTIAL/FAILED/BLOCKED
    created_at = Column(DateTime, default=datetime.utcnow)


class Position(Base):
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True)
    engine_id = Column(String(64), index=True)
    tradingsymbol = Column(String(64))
    instrument_mode = Column(String(32))
    net_position = Column(Integer, default=0)
    quantity = Column(Integer, default=0)
    entry_price = Column(Float, nullable=True)
    open_points = Column(Float, nullable=True)
    open_pnl = Column(Float, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PnlSnapshot(Base):
    __tablename__ = "pnl_snapshots"

    id = Column(Integer, primary_key=True)
    engine_id = Column(String(64), index=True)
    net_points = Column(Float, default=0)
    realized_pnl = Column(Float, default=0)
    unrealized_pnl = Column(Float, default=0)
    captured_at = Column(DateTime, default=datetime.utcnow)


class BrokerSession(Base):
    __tablename__ = "broker_sessions"

    id = Column(Integer, primary_key=True)
    broker = Column(String(32), default="angelone")
    status = Column(String(16))  # CONNECTED/DISCONNECTED/ERROR
    detail = Column(Text, nullable=True)
    connected_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RiskEvent(Base):
    __tablename__ = "risk_events"

    id = Column(Integer, primary_key=True)
    engine_id = Column(String(64), index=True)
    event_type = Column(String(32))  # MAE_EXIT/EMERGENCY_STOP/EXIT_ALL/RECONCILE_PAUSE
    detail = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ConfigAuditLog(Base):
    __tablename__ = "config_audit_log"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    path = Column(String(255))  # dotted config key path that changed
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")


class SystemLog(Base):
    __tablename__ = "system_logs"

    id = Column(Integer, primary_key=True)
    engine_id = Column(String(64), nullable=True, index=True)
    strategy_name = Column(String(64), nullable=True)
    instrument = Column(String(64), nullable=True)
    mode = Column(String(16), nullable=True)
    signal_id = Column(String(64), nullable=True)
    order_id = Column(String(64), nullable=True)
    severity = Column(String(16), default="INFO")
    message = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
