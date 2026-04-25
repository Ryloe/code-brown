"""CLI playground for hype scoring."""

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
    low = min(values)
    high = max(values)
    if high == low:
        base = _SPARK_CHARS[0] * len(values)
    else:
        span = high - low
        mapped = []
        for value in values:
            ratio = (value - low) / span
            idx = min(int(round(ratio * (len(_SPARK_CHARS) - 1))), len(_SPARK_CHARS) - 1)
            mapped.append(_SPARK_CHARS[idx])
        base = "".join(mapped)
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
    top = [r for r in result.evidence.related if r.kind == "top"]
    if rising:
        print("related (rising)")
        for item in rising:
            tag = "breakout" if item.is_breakout else f"+{item.value}%"
            print(f"  {item.query:<24} {tag}")
    if top:
        print("related (top)")
        for item in top:
            print(f"  {item.query:<24} {item.value}")


def _run(term: str, as_json: bool) -> int:
    series_30d = trends.fetch(term, "30d")
    score_value, confidence = score.compute(series_30d.points)

    series_7d = trends.fetch(term, "7d")
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

