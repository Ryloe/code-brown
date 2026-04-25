"""Google Trends related-queries fetcher."""

from __future__ import annotations

from pytrends.request import TrendReq

from shared.models import RelatedQuery

_MAX_RELATED = 10


def _build_client() -> TrendReq:
    return TrendReq(hl="en-US", tz=0)


def fetch(term: str) -> list[RelatedQuery]:
    """Fetch combined rising + top related queries for a term."""
    client = _build_client()
    client.build_payload([term], cat=0, timeframe="today 1-m", geo="", gprop="")
    data = client.related_queries()

    bucket = data.get(term) or {}
    top_frame = bucket.get("top")
    rising_frame = bucket.get("rising")

    items: list[RelatedQuery] = []

    if rising_frame is not None and not rising_frame.empty:
        for _, row in rising_frame.iterrows():
            raw_value = row["value"]
            if isinstance(raw_value, str) and raw_value.strip().lower() == "breakout":
                items.append(
                    RelatedQuery(
                        query=str(row["query"]),
                        value=0,
                        kind="rising",
                        is_breakout=True,
                    )
                )
            else:
                try:
                    numeric = int(raw_value)
                except (TypeError, ValueError):
                    continue
                items.append(
                    RelatedQuery(
                        query=str(row["query"]),
                        value=numeric,
                        kind="rising",
                        is_breakout=False,
                    )
                )

    if top_frame is not None and not top_frame.empty:
        for _, row in top_frame.iterrows():
            try:
                numeric = int(row["value"])
            except (TypeError, ValueError):
                continue
            items.append(
                RelatedQuery(
                    query=str(row["query"]),
                    value=numeric,
                    kind="top",
                    is_breakout=False,
                )
            )

    def sort_key(item: RelatedQuery) -> tuple[int, int, int]:
        is_breakout_rank = 0 if item.is_breakout else 1
        kind_rank = 0 if item.kind == "rising" else 1
        return (is_breakout_rank, kind_rank, -item.value)

    items.sort(key=sort_key)
    return items[:_MAX_RELATED]
