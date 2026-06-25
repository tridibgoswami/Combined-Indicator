from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import pandas as pd
import pytz

from trading_engine.data.loaders import normalize_ohlc

INTERVAL_MINUTES = {
    "ONE_MINUTE": 1,
    "THREE_MINUTE": 3,
    "FIVE_MINUTE": 5,
    "TEN_MINUTE": 10,
    "FIFTEEN_MINUTE": 15,
    "THIRTY_MINUTE": 30,
    "ONE_HOUR": 60,
    "ONE_DAY": 1440,
}


@dataclass
class AngelOneSettings:
    api_key: str
    client_id: str
    mpin: str
    totp_secret: str
    exchange: str
    tradingsymbol: str
    symboltoken: str
    interval: str
    producttype: str = "INTRADAY"
    variety: str = "NORMAL"
    ordertype: str = "MARKET"
    duration: str = "DAY"


class AngelOneBroker:
    def __init__(self, cfg: Dict[str, Any]):
        broker = cfg.get("broker", {}).get("angelone", {})
        instr = cfg.get("instrument", {})
        self.cfg = cfg
        self.tz = pytz.timezone(cfg.get("engine", {}).get("timezone", "Asia/Kolkata"))
        self.settings = AngelOneSettings(
            api_key=broker.get("api_key", ""),
            client_id=broker.get("client_id", ""),
            mpin=broker.get("mpin", ""),
            totp_secret=broker.get("totp_secret", ""),
            exchange=instr.get("exchange", "NSE"),
            tradingsymbol=instr.get("tradingsymbol", instr.get("symbol", "NIFTY")),
            symboltoken=str(instr.get("symboltoken", "")),
            interval=instr.get("interval", "FIVE_MINUTE"),
            producttype=cfg.get("trading", {}).get("producttype", "INTRADAY"),
            variety=cfg.get("trading", {}).get("variety", "NORMAL"),
            ordertype=cfg.get("trading", {}).get("ordertype", "MARKET"),
            duration=cfg.get("trading", {}).get("duration", "DAY"),
        )
        self.obj = None
        self.execution_instrument = (cfg.get("execution", {}) or {}).get("resolved_instrument", {}) or {}

    def set_execution_instrument(self, instrument: Dict[str, Any]) -> None:
        self.execution_instrument = instrument or {}


    def connect(self):
        missing = [k for k, v in self.settings.__dict__.items() if k in {"api_key", "client_id", "mpin", "totp_secret", "symboltoken"} and not v]
        if missing:
            raise ValueError(f"Live mode needs AngelOne credentials/settings. Missing: {missing}. Create .env from .env.example and verify config/config.yaml instrument token/tradingsymbol.")
        try:
            from SmartApi import SmartConnect
            import pyotp
        except Exception as exc:
            raise RuntimeError("SmartAPI dependencies missing. Run: pip install -r requirements.txt") from exc
        self.obj = SmartConnect(api_key=self.settings.api_key)
        totp = pyotp.TOTP(self.settings.totp_secret).now()
        session = self.obj.generateSession(self.settings.client_id, self.settings.mpin, totp)
        if not session or not session.get("status"):
            raise RuntimeError(f"AngelOne login failed: {session}")
        return self.obj

    def get_candles(self, start_dt: datetime, end_dt: datetime) -> pd.DataFrame:
        if self.obj is None:
            self.connect()
        params = {
            "exchange": self.settings.exchange,
            "symboltoken": str(self.settings.symboltoken),
            "interval": self.settings.interval,
            "fromdate": start_dt.strftime("%Y-%m-%d %H:%M"),
            "todate": end_dt.strftime("%Y-%m-%d %H:%M"),
        }
        res = self.obj.getCandleData(params)
        if not res or not res.get("status"):
            raise RuntimeError(f"AngelOne candle fetch failed: {res}")
        rows = res.get("data") or []
        df = pd.DataFrame(rows, columns=["datetime", "open", "high", "low", "close", "volume"])
        return normalize_ohlc(df, self.cfg.get("engine", {}).get("timezone", "Asia/Kolkata"))

    def place_order(self, side: str, quantity: int, instrument: Optional[Dict[str, Any]] = None) -> Any:
        if self.obj is None:
            self.connect()
        txn = "BUY" if side.upper() == "BUY" else "SELL"
        exe = instrument or self.execution_instrument or {}
        tradingsymbol = exe.get("tradingsymbol") or self.settings.tradingsymbol
        symboltoken = str(exe.get("symboltoken") or self.settings.symboltoken)
        exchange = exe.get("exchange") or self.settings.exchange
        orderparams = {
            "variety": self.settings.variety,
            "tradingsymbol": tradingsymbol,
            "symboltoken": symboltoken,
            "transactiontype": txn,
            "exchange": exchange,
            "ordertype": self.settings.ordertype,
            "producttype": self.settings.producttype,
            "duration": self.settings.duration,
            "quantity": str(quantity),
        }
        return self.obj.placeOrder(orderparams)

    def ltp(self, execution: bool = False) -> float:
        if self.obj is None:
            self.connect()
        exe = self.execution_instrument if execution else {}
        exchange = exe.get("exchange") or self.settings.exchange
        tradingsymbol = exe.get("tradingsymbol") or self.settings.tradingsymbol
        symboltoken = str(exe.get("symboltoken") or self.settings.symboltoken)
        res = self.obj.ltpData(exchange, tradingsymbol, symboltoken)
        if not res or not res.get("status"):
            raise RuntimeError(f"AngelOne LTP fetch failed: {res}")
        return float((res.get("data") or {}).get("ltp"))

    def ltp_for(self, instrument: Dict[str, Any]) -> float:
        if self.obj is None:
            self.connect()
        exchange = instrument.get("exchange") or self.settings.exchange
        tradingsymbol = instrument.get("tradingsymbol") or self.settings.tradingsymbol
        symboltoken = str(instrument.get("symboltoken") or self.settings.symboltoken)
        res = self.obj.ltpData(exchange, tradingsymbol, symboltoken)
        if not res or not res.get("status"):
            raise RuntimeError(f"AngelOne LTP fetch failed for {tradingsymbol}: {res}")
        return float((res.get("data") or {}).get("ltp"))

    def get_net_position_qty(self) -> int:
        if self.obj is None:
            self.connect()
        exe = self.execution_instrument or {}
        wanted_symbol = str(exe.get("tradingsymbol") or self.settings.tradingsymbol).upper()
        wanted_token = str(exe.get("symboltoken") or self.settings.symboltoken)
        res = self.obj.position()
        if not res or not res.get("status"):
            raise RuntimeError(f"AngelOne position fetch failed: {res}")
        net_qty = 0
        for row in res.get("data") or []:
            symbol = str(row.get("tradingsymbol") or row.get("symbolname") or "").upper()
            token = str(row.get("symboltoken") or row.get("token") or "")
            if symbol == wanted_symbol or (wanted_token and token == wanted_token):
                for key in ["netqty", "netQty", "net_quantity", "netqty"]:
                    if key in row:
                        try:
                            net_qty += int(float(row.get(key) or 0))
                            break
                        except Exception:
                            pass
        return net_qty

    @property
    def interval_minutes(self) -> int:
        return INTERVAL_MINUTES.get(self.settings.interval, 5)
