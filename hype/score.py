"""Pure hype scoring logic (Trends-native)."""

from __future__ import annotations

import statistics
from typing import Literal

from shared.models import TrendPoint

_HIGH_NONZERO = 20
_MEDIUM_NONZERO = 10
_LOW_NONZERO = 3

_W_Z = 0.6
_W_SLOPE = 0.4
_SLOPE_SCALE = 10.0
_SCORE_MIN = -3.0
_SCORE_MAX = 5.0

_RECENT_DAYS = 7

Confidence = Literal["high", "medium", "low", "insufficient"]


def _confidence(non_zero_days: int) -> Confidence:
    if non_zero_days >= _HIGH_NONZERO:
        return "high"
    if non_zero_days >= _MEDIUM_NONZERO:
        return "medium"
    if non_zero_days >= _LOW_NONZERO:
        return "low"
    return "insufficient"


def _linear_slope(values: list[float]) -> float:
    """Slope of best-fit line through (i, values[i]) for i in 0..len-1."""
    n = len(values)
    if n < 2:
        return 0.0
    mean_x = (n - 1) / 2.0
    mean_y = sum(values) / n
    num = sum((i - mean_x) * (values[i] - mean_y) for i in range(n))
    den = sum((i - mean_x) ** 2 for i in range(n))
    if den == 0:
        return 0.0
    return num / den


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def compute(points: list[TrendPoint]) -> tuple[float | None, Confidence]:
    """Compute (score, confidence) from a 30-day TrendPoint list."""
    intensities = [float(p.intensity) for p in points]
    non_zero = sum(1 for v in intensities if v > 0)
    confidence = _confidence(non_zero)
    if confidence == "insufficient":
        return None, confidence

    if len(intensities) <= _RECENT_DAYS:
        return 0.0, confidence

    recent = intensities[-_RECENT_DAYS:]
    baseline = intensities[:-_RECENT_DAYS]

    baseline_mean = statistics.mean(baseline) if baseline else 0.0
    baseline_std = statistics.pstdev(baseline) if baseline else 0.0
    recent_mean = statistics.mean(recent)

    if baseline_std > 0:
        z = (recent_mean - baseline_mean) / baseline_std
    else:
        z = 0.0

    slope = _linear_slope(intensities)
    series_mean = statistics.mean(intensities)
    norm_slope = slope / max(1.0, series_mean)

    raw = (_W_Z * z) + (_W_SLOPE * norm_slope * _SLOPE_SCALE)
    return _clip(raw, _SCORE_MIN, _SCORE_MAX), confidence

