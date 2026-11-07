from datetime import datetime, timedelta

import pandas as pd
import pytz

from trading_engine.broker_adapters import angelone
from trading_engine.broker_adapters.angelone import AngelOneBroker

IST = pytz.timezone("Asia/Kolkata")


class FakeSmartApi:
    """Returns one-minute candles for 09:15-15:29 and rejects ranges over 30 days."""

    def __init__(self):
        self.requests = []

    def getCandleData(self, params):
        start = datetime.strptime(params["fromdate"], "%Y-%m-%d %H:%M")
        end = datetime.strptime(params["todate"], "%Y-%m-%d %H:%M")
        self.requests.append((start, end))
        if (end - start).days > 30:
            return {"status": False, "message": "range too large"}
        rows = []
        day = start.replace(hour=0, minute=0)
        while day <= end:
            t = day.replace(hour=9, minute=15)
            close = day.replace(hour=15, minute=29)
            while t <= close:
                if start <= t <= end:
                    rows.append([t.strftime("%Y-%m-%dT%H:%M:%S+05:30"), 100, 101, 99, 100, 10])
                t += timedelta(minutes=1)
            day += timedelta(days=1)
        return {"status": True, "data": rows}


def _broker(monkeypatch):
    monkeypatch.setattr(angelone, "CHUNK_SLEEP_SECONDS", 0)
    cfg = {
        "engine": {"timezone": "Asia/Kolkata"},
        "instrument": {"exchange": "NSE", "symboltoken": "99926009", "interval": "ONE_MINUTE"},
    }
    b = AngelOneBroker(cfg)
    b.obj = FakeSmartApi()
    return b


def test_one_minute_range_is_split_within_limit(monkeypatch):
    b = _broker(monkeypatch)
    end = IST.localize(datetime(2026, 10, 28, 15, 30))
    start = end - timedelta(days=45)
    df = b.get_candles(start, end)
    assert len(b.obj.requests) == 2
    assert all((e - s).days <= 30 for s, e in b.obj.requests)
    assert df["datetime"].is_monotonic_increasing
    assert not df["datetime"].duplicated().any()


def test_incremental_fetch_only_downloads_new_candles(monkeypatch):
    b = _broker(monkeypatch)
    end = IST.localize(datetime(2026, 10, 28, 10, 0))
    start = end - timedelta(days=30)
    first = b.get_candles(start, end, incremental=True)
    calls_after_first = len(b.obj.requests)

    later = end + timedelta(minutes=5)
    second = b.get_candles(start + timedelta(minutes=5), later, incremental=True)
    new_requests = b.obj.requests[calls_after_first:]
    assert len(new_requests) == 1
    s, e = new_requests[0]
    assert (e - s) <= timedelta(minutes=10)
    assert second["datetime"].max() == pd.Timestamp(later)
    assert len(second) >= len(first)
