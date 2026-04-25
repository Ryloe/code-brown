"""Google Trends fetcher for hype signal."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

import pandas as pd
from pytrends.request import TrendReq

from shared.models import TrendPoint, TrendSeries

RANGE_TO_TIMEFRAME: dict[str, str] = {
    "7d": "now 7-d",
    "30d": "today 1-m",
    "90d": "today 3-m",
}


def _build_client() -> TrendReq:
    return TrendReq(hl="en-US", tz=0)


def _to_daily_points(frame: pd.DataFrame, term: str, range: str) -> list[TrendPoint]:
    """Convert a pytrends interest_over_time DataFrame to daily TrendPoints."""
    if frame.empty or term not in frame.columns:
        return []

    series = frame[term]

    if range == "7d":
        series = series.copy()
        series.index = pd.to_datetime(series.index, utc=True)
        daily = series.resample("1D").mean().dropna()
    else:
        daily = series.copy()
        daily.index = pd.to_datetime(daily.index, utc=True)

    points: list[TrendPoint] = []
    for ts, val in daily.items():
        if pd.isna(val):
            continue
        midnight = datetime(ts.year, ts.month, ts.day, tzinfo=UTC)
        points.append(
            TrendPoint(
                day_unix=int(midnight.timestamp()),
                intensity=int(round(float(val))),
            )
        )
    return points


def fetch(term: str, range: Literal["7d", "30d", "90d"]) -> TrendSeries:
    """Blocking fetch. Returns a TrendSeries with daily buckets, oldest -> newest."""
    timeframe = RANGE_TO_TIMEFRAME[range]
    client = _build_client()
    client.build_payload([term], cat=0, timeframe=timeframe, geo="", gprop="")
    frame = client.interest_over_time()
    points = _to_daily_points(frame, term=term, range=range)
    return TrendSeries(range=range, points=points)

