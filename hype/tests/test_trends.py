from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

from hype import trends


class _ClientStub:
    def __init__(self, frame: pd.DataFrame):
        self._frame = frame
        self.last_payload = None

    def build_payload(self, kw_list, cat, timeframe, geo, gprop):
        self.last_payload = {
            "kw_list": kw_list,
            "cat": cat,
            "timeframe": timeframe,
            "geo": geo,
            "gprop": gprop,
        }

    def interest_over_time(self) -> pd.DataFrame:
        return self._frame


def _daily_frame(term: str, days: int) -> pd.DataFrame:
    start = datetime(2026, 3, 1, tzinfo=UTC)
    idx = [start + timedelta(days=i) for i in range(days)]
    values = list(range(days))
    return pd.DataFrame({term: values, "isPartial": [False] * days}, index=idx)


def _hourly_frame(term: str, hours: int) -> pd.DataFrame:
    start = datetime(2026, 3, 1, tzinfo=UTC)
    idx = [start + timedelta(hours=i) for i in range(hours)]
    values = [float(i % 24) for i in range(hours)]
    return pd.DataFrame({term: values, "isPartial": [False] * hours}, index=idx)


def test_fetch_30d_daily_points(monkeypatch):
    term = "bape"
    frame = _daily_frame(term, 30)
    stub = _ClientStub(frame)
    monkeypatch.setattr(trends, "_build_client", lambda: stub)

    result = trends.fetch(term, "30d")

    assert result.range == "30d"
    assert len(result.points) == 30
    assert result.points[0].intensity == 0
    assert result.points[-1].intensity == 29


def test_fetch_7d_hourly_resamples_to_7_daily(monkeypatch):
    term = "stussy"
    frame = _hourly_frame(term, 7 * 24)
    stub = _ClientStub(frame)
    monkeypatch.setattr(trends, "_build_client", lambda: stub)

    result = trends.fetch(term, "7d")

    assert result.range == "7d"
    assert len(result.points) == 7
    assert all(p.intensity == 12 for p in result.points)


def test_fetch_90d_daily_points(monkeypatch):
    term = "cdg"
    frame = _daily_frame(term, 90)
    stub = _ClientStub(frame)
    monkeypatch.setattr(trends, "_build_client", lambda: stub)

    result = trends.fetch(term, "90d")

    assert result.range == "90d"
    assert len(result.points) == 90


def test_fetch_empty_frame_returns_empty_points(monkeypatch):
    term = "jordan"
    frame = pd.DataFrame()
    stub = _ClientStub(frame)
    monkeypatch.setattr(trends, "_build_client", lambda: stub)

    result = trends.fetch(term, "30d")

    assert result.range == "30d"
    assert result.points == []


def test_fetch_missing_term_column_returns_empty_points(monkeypatch):
    term = "jordan"
    frame = pd.DataFrame({"other": [1, 2, 3]})
    stub = _ClientStub(frame)
    monkeypatch.setattr(trends, "_build_client", lambda: stub)

    result = trends.fetch(term, "30d")

    assert result.range == "30d"
    assert result.points == []
