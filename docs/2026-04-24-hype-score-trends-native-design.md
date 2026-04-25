# Hype Score — Trends-Native Redesign

**Status:** approved, pending implementation
**Owner:** Oliver
**Last updated:** 2026-04-24
**Supersedes (in part):** `docs/2026-04-24-hype-score-design.md` (Reddit-based design)
**Related:** SPEC.md (parent project — Grailed Arbitrage)

---

## 1. Summary

Rewrite the `hype/` package to be **Google Trends-native** instead of Reddit-shaped. The current code (`hype/trends.py`, `hype/score.py`) fetches Google Trends data, then synthesizes fake `Post` objects with fabricated `created_utc` timestamps so the original Reddit-style velocity/acceleration scorer keeps running. That hack ends. The new scorer consumes real Trends timeseries directly.

This spec covers the `hype/` package and `shared/models.py` only. **No FastAPI router. No frontend code. No orchestrator changes.** The CLI in `hype/cli.py` is the only entry point. A frontend will be designed later in its own spec.

Core bet (unchanged): **a term's recent search-interest momentum is a leading indicator for collectible/streetwear demand.** We compute a single headline score per term, expose 7-day / 30-day / 90-day series for chart context, and surface Google's own related/rising queries as evidence.

---

## 2. Scope

**In scope:**
- Rewrite `hype/trends.py`, `hype/score.py`, `hype/cli.py`.
- New `hype/related.py`.
- Replace hype-related types in `shared/models.py`.
- Unit tests for all of the above.
- Delete `hype/aliases.py` and its tests (no longer used).

**Out of scope (deferred to future specs):**
- FastAPI endpoint / router.
- Frontend chart, range tabs, related-query chips.
- Lazy-load semantics (sequential fetch in CLI is fine).
- Caching layer.
- Geographic breakdown (`interest_by_region`).
- Multi-term comparison / category overlays.
- LLM narration.
- Sentiment.

---

## 3. Architecture

```
hype/                               (top-level package, sibling of backend/)
  ├── __init__.py
  ├── trends.py    — pytrends wrapper. fetch(term, range) → TrendSeries.
  ├── related.py   — pytrends related_queries wrapper. fetch(term) → list[RelatedQuery].
  ├── score.py     — pure function. compute(points_30d) → (score, confidence).
  ├── cli.py       — wires it all together. Sequential fetches, prints summary or JSON.
  └── tests/
       ├── __init__.py
       ├── test_score.py
       ├── test_trends.py
       ├── test_related.py
       └── test_cli_smoke.py
```

CLI flow (no async, no API):

```
hype <term>
  1. series_30d  = trends.fetch(term, "30d")
  2. score, conf = score.compute(series_30d.points)
  3. series_7d   = trends.fetch(term, "7d")
  4. series_90d  = trends.fetch(term, "90d")
  5. related     = related.fetch(term)
  6. assemble HypeResult, print
```

Sequential, blocking. pytrends is rate-limited; the CLI is for inspection, not throughput.

---

## 4. Data models — `shared/models.py`

**Delete** the following existing classes (they were Reddit-shaped and are no longer used):
`Post`, `TopPost`, `SubEvidence`, `HypeEvidence` (old shape), `DailyBucket`, `SubSeries`, `HypeTimeseries`, `HypeResult` (old shape).

Leave `EVDistribution`, `SellerBadges`, `Seller`, `LivePrice`, `SoldPrice`, `LiveListing`, `SoldListing`, `GrailedResultRow`, `ScrapeMetadata`, `GrailedScrapeResult` untouched.

**Add** the following:

```python
from typing import Literal
from pydantic import BaseModel, Field


class TrendPoint(BaseModel):
    day_unix: int      # UTC midnight of the bucket day, seconds since epoch
    intensity: int     # Google Trends 0-100 index, integer


class TrendSeries(BaseModel):
    range: Literal["7d", "30d", "90d"]
    points: list[TrendPoint] = Field(default_factory=list)
    # Length is 7, 30, or 90 when populated; oldest → newest.
    # Empty list when Trends returned no data.


class RelatedQuery(BaseModel):
    query: str
    value: int                              # See note below
    kind: Literal["rising", "top"]
    is_breakout: bool                       # True if Trends flagged "Breakout"
    # Notes:
    #   kind="top":     value = interest score (0-100)
    #   kind="rising":  value = growth percent; 0 when is_breakout=True
    #   is_breakout=True only ever appears with kind="rising"


class HypeEvidence(BaseModel):
    related: list[RelatedQuery] = Field(default_factory=list)


class HypeResult(BaseModel):
    term: str
    score: float | None                     # None when confidence == "insufficient"
    confidence: Literal["high", "medium", "low", "insufficient"]
    series_30d: TrendSeries                 # always present, drives the score
    series_7d: TrendSeries | None = None
    series_90d: TrendSeries | None = None
    evidence: HypeEvidence
    fetched_at_unix: int
```

Naming note: there is now a `HypeEvidence` with a different shape than the old one. This is a hard break — anything that imported the old `HypeEvidence`, `Post`, etc. must be updated or deleted.

---

## 5. `hype/trends.py`

Pure pytrends wrapper. **No scoring logic.**

```python
"""Google Trends fetcher for hype signal."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

import pandas as pd
from pytrends.request import TrendReq

from shared.models import TrendPoint, TrendSeries

RANGE_TO_TIMEFRAME: dict[str, str] = {
    "7d":  "now 7-d",       # pytrends returns hourly buckets; we resample to daily
    "30d": "today 1-m",     # daily buckets
    "90d": "today 3-m",     # daily buckets
}


def _build_client() -> TrendReq:
    return TrendReq(hl="en-US", tz=0)


def _to_daily_points(frame: pd.DataFrame, term: str, range: str) -> list[TrendPoint]:
    """Convert a pytrends interest_over_time DataFrame to daily TrendPoints."""
    if frame.empty or term not in frame.columns:
        return []

    # Drop the 'isPartial' column if present — it's a bool flag, not data.
    series = frame[term]

    if range == "7d":
        # pytrends returns ~168 hourly rows for 'now 7-d'.
        # Resample by UTC date, take the mean of the 24 hourly intensities.
        # Mean (not sum) keeps the 0-100 scale conceptually consistent
        # with the daily-bucket ranges.
        series = series.copy()
        series.index = pd.to_datetime(series.index, utc=True)
        daily = series.resample("1D").mean().dropna()
    else:
        # 30d / 90d already daily.
        daily = series.copy()
        daily.index = pd.to_datetime(daily.index, utc=True)

    points: list[TrendPoint] = []
    for ts, val in daily.items():
        if pd.isna(val):
            continue
        # Normalize to UTC midnight of the bucket day.
        midnight = datetime(ts.year, ts.month, ts.day, tzinfo=UTC)
        points.append(TrendPoint(day_unix=int(midnight.timestamp()), intensity=int(round(float(val)))))
    return points


def fetch(term: str, range: Literal["7d", "30d", "90d"]) -> TrendSeries:
    """Blocking fetch. Returns a TrendSeries with daily buckets, oldest → newest.

    Returns an empty-points TrendSeries on any of:
      - empty DataFrame from pytrends
      - term column missing from the DataFrame
    Lets pytrends exceptions (rate limit, network) propagate.
    """
    timeframe = RANGE_TO_TIMEFRAME[range]
    client = _build_client()
    client.build_payload([term], cat=0, timeframe=timeframe, geo="", gprop="")
    frame = client.interest_over_time()
    points = _to_daily_points(frame, term=term, range=range)
    return TrendSeries(range=range, points=points)
```

Notes for the implementer:
- Do **not** pass alias variants. Single `[term]` payload only.
- Do **not** call `asyncio.to_thread` or expose an async function. CLI is sync.
- Do **not** silently swallow pytrends exceptions. Let them bubble; the CLI catches at the top level.

---

## 6. `hype/related.py`

```python
"""Google Trends related-queries fetcher."""

from __future__ import annotations

from pytrends.request import TrendReq

from shared.models import RelatedQuery

_MAX_RELATED = 10


def _build_client() -> TrendReq:
    return TrendReq(hl="en-US", tz=0)


def fetch(term: str) -> list[RelatedQuery]:
    """Fetch combined rising + top related queries for `term`.

    Returns at most _MAX_RELATED items. Returns [] on any missing data.
    Does not raise on empty/None frames; pytrends transport errors propagate.
    """
    client = _build_client()
    client.build_payload([term], cat=0, timeframe="today 1-m", geo="", gprop="")
    data = client.related_queries()  # { term: { "top": DataFrame|None, "rising": DataFrame|None } }

    bucket = data.get(term) or {}
    top_frame = bucket.get("top")
    rising_frame = bucket.get("rising")

    items: list[RelatedQuery] = []

    if rising_frame is not None and not rising_frame.empty:
        for _, row in rising_frame.iterrows():
            raw_value = row["value"]
            if isinstance(raw_value, str) and raw_value.strip().lower() == "breakout":
                items.append(RelatedQuery(
                    query=str(row["query"]),
                    value=0,
                    kind="rising",
                    is_breakout=True,
                ))
            else:
                try:
                    numeric = int(raw_value)
                except (TypeError, ValueError):
                    continue
                items.append(RelatedQuery(
                    query=str(row["query"]),
                    value=numeric,
                    kind="rising",
                    is_breakout=False,
                ))

    if top_frame is not None and not top_frame.empty:
        for _, row in top_frame.iterrows():
            try:
                numeric = int(row["value"])
            except (TypeError, ValueError):
                continue
            items.append(RelatedQuery(
                query=str(row["query"]),
                value=numeric,
                kind="top",
                is_breakout=False,
            ))

    # Sort: breakouts first, then rising (by value desc), then top (by value desc).
    def sort_key(item: RelatedQuery) -> tuple[int, int, int]:
        is_breakout_rank = 0 if item.is_breakout else 1
        kind_rank = 0 if item.kind == "rising" else 1
        return (is_breakout_rank, kind_rank, -item.value)

    items.sort(key=sort_key)
    return items[:_MAX_RELATED]
```

---

## 7. `hype/score.py`

Pure function. **No I/O. No pytrends imports.** Trivially testable.

```python
"""Pure hype scoring logic (Trends-native)."""

from __future__ import annotations

import statistics
from typing import Literal

from shared.models import TrendPoint

# Thresholds — coverage-based confidence gating (non-zero days within 30d).
_HIGH_NONZERO   = 20
_MEDIUM_NONZERO = 10
_LOW_NONZERO    = 3

# Score blend weights and clip range.
_W_Z      = 0.6
_W_SLOPE  = 0.4
_SLOPE_SCALE = 10.0   # puts normalized slope on roughly the same scale as z
_SCORE_MIN = -3.0
_SCORE_MAX = 5.0

# Window split inside the 30d series.
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
    """Slope of best-fit line through (i, values[i]) for i in 0..len-1.

    Returns 0.0 if fewer than 2 points or zero variance in x (impossible here).
    Uses the closed-form OLS slope; no scipy dependency.
    """
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
    """Compute (score, confidence) from a 30-day TrendPoint list.

    `points` must be the 30d series, oldest → newest. Length need not be exactly 30
    (Trends sometimes returns fewer rows); compute over whatever is provided, but
    always returns "insufficient" when the non-zero-day count is below threshold.
    """
    intensities = [float(p.intensity) for p in points]
    non_zero = sum(1 for v in intensities if v > 0)
    confidence = _confidence(non_zero)
    if confidence == "insufficient":
        return None, confidence

    # Need at least _RECENT_DAYS+1 rows to split into recent vs baseline.
    if len(intensities) <= _RECENT_DAYS:
        # Edge case: short series but enough non-zero coverage. Bail safely.
        return 0.0, confidence

    recent   = intensities[-_RECENT_DAYS:]
    baseline = intensities[:-_RECENT_DAYS]

    baseline_mean = statistics.mean(baseline) if baseline else 0.0
    baseline_std  = statistics.pstdev(baseline) if baseline else 0.0
    recent_mean   = statistics.mean(recent)

    if baseline_std > 0:
        z = (recent_mean - baseline_mean) / baseline_std
    else:
        z = 0.0

    slope = _linear_slope(intensities)
    series_mean = statistics.mean(intensities)
    norm_slope = slope / max(1.0, series_mean)

    raw = (_W_Z * z) + (_W_SLOPE * norm_slope * _SLOPE_SCALE)
    return _clip(raw, _SCORE_MIN, _SCORE_MAX), confidence
```

---

## 8. `hype/cli.py` (rewrite)

```python
"""CLI entry point for hype scoring."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

from dotenv import load_dotenv

from hype import related, score, trends
from shared.models import HypeEvidence, HypeResult

_SPARK_CHARS = "▁▂▃▄▅▆▇█"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run hype score for one term.")
    parser.add_argument("term", help="Term to evaluate")
    parser.add_argument("--json", action="store_true", help="Print raw JSON response")
    return parser.parse_args()


def _sparkline(values: list[float]) -> str:
    if not values:
        return ""
    low, high = min(values), max(values)
    if high == low:
        base = _SPARK_CHARS[0] * len(values)
    else:
        span = high - low
        base = "".join(
            _SPARK_CHARS[
                min(int(round(((v - low) / span) * (len(_SPARK_CHARS) - 1))), len(_SPARK_CHARS) - 1)
            ]
            for v in values
        )
    if not base:
        return base
    return f"{base[:-1]}[{base[-1]}]"


def _print_summary(result: HypeResult) -> None:
    score_display = "—" if result.score is None else f"{result.score:.3f}"
    print(f"term={result.term}  score={score_display}  confidence={result.confidence}")
    print()

    for series in (result.series_7d, result.series_30d, result.series_90d):
        if series is None or not series.points:
            continue
        values = [float(p.intensity) for p in series.points]
        label = f"{series.range:>4}"
        print(f"{label}  {_sparkline(values)}")
    print()

    rising = [r for r in result.evidence.related if r.kind == "rising"]
    top    = [r for r in result.evidence.related if r.kind == "top"]
    if rising:
        print("related (rising)")
        for r in rising:
            tag = "⚡ breakout" if r.is_breakout else f"+{r.value}%"
            print(f"  {r.query:<24} {tag}")
    if top:
        print("related (top)")
        for r in top:
            print(f"  {r.query:<24} {r.value}")


def _run(term: str, as_json: bool) -> int:
    series_30d = trends.fetch(term, "30d")
    score_value, confidence = score.compute(series_30d.points)

    series_7d  = trends.fetch(term, "7d")
    series_90d = trends.fetch(term, "90d")
    related_items = related.fetch(term)

    result = HypeResult(
        term=term,
        score=score_value,
        confidence=confidence,
        series_30d=series_30d,
        series_7d=series_7d,
        series_90d=series_90d,
        evidence=HypeEvidence(related=related_items),
        fetched_at_unix=int(datetime.now(tz=UTC).timestamp()),
    )

    if as_json:
        print(result.model_dump_json(indent=2))
    else:
        _print_summary(result)
    return 0


def main() -> int:
    load_dotenv()
    args = _parse_args()
    try:
        return _run(term=args.term, as_json=args.json)
    except Exception as exc:  # pragma: no cover
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

Removed env vars: `HYPE_TRENDS_TIMEFRAME` (we hard-code three ranges now). `HYPE_TRENDS_GEO` is also removed; if/when geographic targeting is wanted, add it back as a CLI flag in a future spec.

---

## 9. Files to delete

- `hype/aliases.py`
- `hype/tests/test_aliases.py` (if it exists)

Do **not** keep these as dead code. They are tied to the Reddit-keyword-search world and obscure the new design.

---

## 10. Tests

All tests use `pytest`. No network calls in CI.

### `hype/tests/test_score.py`

Pure-function tests on `score.compute`:

| Case | Input | Expected |
|---|---|---|
| empty | `[]` | `(None, "insufficient")` |
| all zeros | 30 × `intensity=0` | `(None, "insufficient")` |
| 2 non-zero days | 28 zeros + 2 non-zero | `(None, "insufficient")` (below `_LOW_NONZERO=3`) |
| exactly 3 non-zero | hits `low` gate | `(some float, "low")` |
| 12 non-zero | `medium` gate | `(some float, "medium")` |
| 25 non-zero | `high` gate | `(some float, "high")` |
| flat-15 | 15 days flat at intensity=20, 15 at 0 | `(score, "medium")`, score ≈ 0 |
| hot spike | 23 days at intensity=10, 7 days at 80 | positive score |
| steady decline | linear ramp 80 → 5 over 30 days | negative score |
| all-equal-30 | 30 × intensity=50 | `(score, "high")`, score ≈ 0, no crash on std=0 |
| short series (5 pts) but high coverage | 5 × intensity=50 | `(0.0, "low")` (early-return branch) |
| clipping high | crafted series producing raw > 5 | `score == 5.0` |
| clipping low | crafted series producing raw < -3 | `score == -3.0` |

### `hype/tests/test_trends.py`

Mock `pytrends.request.TrendReq` (or patch `_build_client` to return a Mock). Build fake DataFrames with `pandas`:

- 30d daily DataFrame (30 rows, daily DatetimeIndex, term column + isPartial) → returns `TrendSeries(range="30d", points=[...])` with 30 points, intensities matching the column rounded to int, `day_unix` matching UTC midnights.
- 7d hourly DataFrame (168 rows, hourly DatetimeIndex) → returns 7 points; each point's intensity equals the integer mean of its 24 hourly source values.
- 90d daily DataFrame (90 rows) → 90 points pass-through.
- Empty DataFrame → `TrendSeries(range="...", points=[])`.
- DataFrame missing the term column → `TrendSeries(..., points=[])`.

### `hype/tests/test_related.py`

Mock `pytrends.related_queries()` return value:

- Both frames present, `rising` includes `"Breakout"` and `"+150"` rows, `top` has numeric values → result list has breakouts first, then rising sorted by value desc, then top sorted by value desc; capped at 10.
- `data = { term: { "top": None, "rising": None } }` → `[]`.
- `data = {}` (term key missing) → `[]`.
- `rising` with non-numeric, non-"Breakout" value → that row is skipped, others kept.

### `hype/tests/test_cli_smoke.py`

Patch `hype.trends.fetch` and `hype.related.fetch` with simple stubs returning a known-shape `TrendSeries` and `[RelatedQuery]`. Call `hype.cli.main()` via monkeypatching `sys.argv`, capture stdout with `capsys`, assert the output contains `term=` and `score=`. Also test the `--json` path: assert stdout parses as valid JSON with the expected top-level keys (`term`, `score`, `confidence`, `series_30d`).

---

## 11. Dependencies

Already present in `backend/requirements.txt`:
- `pytrends`
- `pydantic`
- `python-dotenv`

New requirement:
- `pandas` — used directly in `trends.py` for the 7d hourly→daily resample. (`pytrends` already pulls it in transitively, but add an explicit pin in `backend/requirements.txt` to make the dependency intentional.)

No removals.

---

## 12. Failure modes

| Failure | Behavior |
|---|---|
| Trends returns empty for the 30d range | `score.compute` sees `[]`, returns `(None, "insufficient")`. CLI prints `score=—  confidence=insufficient` and whatever 7d/90d/related came back. |
| Trends rate-limit or network error | pytrends raises; CLI's top-level `try` prints `error: <msg>` to stderr and exits 1. |
| Term has hits but very sparse (<3 non-zero days) | `confidence=insufficient`, `score=None`. Series and related still printed if available. |
| Related-queries call returns `None` frames | `evidence.related = []`. Score/series unaffected. |
| Single range fetch fails after 30d already succeeded | Exception propagates, CLI exits 1. (Acceptable for v1; we can soften this later if needed.) |

---

## 13. Open items deferred

- FastAPI router exposing `/hype` and `/hype/range` endpoints.
- Frontend chart with 7D/30D/90D range tabs (lazy-loading 7d/90d after 30d returns).
- Frontend rising-query chips below the chart.
- Caching layer (TTL per term per range).
- Geographic targeting (`geo` parameter from CLI / API).
- Multi-term comparison overlay.
- Tuning the `_SLOPE_SCALE = 10.0` constant once we have real-term data to look at.
- Reintroducing alias expansion if specific brands underperform under Trends' built-in topic matching.
- LLM narration of the score.
