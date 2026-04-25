from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hype.score import compute
from shared.models import TrendPoint


def _points(values: list[int]) -> list[TrendPoint]:
    base = datetime(2026, 3, 1, tzinfo=UTC)
    return [
        TrendPoint(day_unix=int((base + timedelta(days=i)).timestamp()), intensity=v)
        for i, v in enumerate(values)
    ]


def test_empty_points_is_insufficient():
    score_value, confidence = compute([])
    assert score_value is None
    assert confidence == "insufficient"


def test_all_zero_is_insufficient():
    score_value, confidence = compute(_points([0] * 30))
    assert score_value is None
    assert confidence == "insufficient"


def test_two_non_zero_days_is_insufficient():
    values = [0] * 28 + [20, 20]
    score_value, confidence = compute(_points(values))
    assert score_value is None
    assert confidence == "insufficient"


def test_exactly_three_non_zero_days_is_low():
    values = [0] * 27 + [20, 20, 20]
    score_value, confidence = compute(_points(values))
    assert confidence == "low"
    assert score_value is not None


def test_twelve_non_zero_days_is_medium():
    values = [0] * 18 + [20] * 12
    score_value, confidence = compute(_points(values))
    assert confidence == "medium"
    assert score_value is not None


def test_twenty_five_non_zero_days_is_high():
    values = [0] * 5 + [30] * 25
    score_value, confidence = compute(_points(values))
    assert confidence == "high"
    assert score_value is not None


def test_recent_shift_produces_positive_score():
    values = [0] * 15 + [20] * 15
    score_value, confidence = compute(_points(values))
    assert confidence == "medium"
    assert score_value is not None
    assert score_value > 0


def test_hot_spike_positive_score():
    values = [10] * 23 + [80] * 7
    score_value, confidence = compute(_points(values))
    assert confidence == "high"
    assert score_value is not None
    assert score_value > 0


def test_decline_negative_score():
    values = [80 - int(i * (75 / 29)) for i in range(30)]
    score_value, confidence = compute(_points(values))
    assert confidence == "high"
    assert score_value is not None
    assert score_value < 0


def test_all_equal_no_std_crash_and_near_zero():
    values = [50] * 30
    score_value, confidence = compute(_points(values))
    assert confidence == "high"
    assert score_value is not None
    assert abs(score_value) < 0.2


def test_short_series_high_coverage_returns_zero_low():
    values = [50] * 5
    score_value, confidence = compute(_points(values))
    assert confidence == "low"
    assert score_value == 0.0


def test_score_clips_high():
    values = [1] * 22 + [2] + [100] * 7
    score_value, confidence = compute(_points(values))
    assert confidence == "high"
    assert score_value == 5.0


def test_score_clips_low():
    values = [100] * 22 + [99] + [1] * 7
    score_value, confidence = compute(_points(values))
    assert confidence == "high"
    assert score_value == -3.0

