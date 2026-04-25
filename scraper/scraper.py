"""Grailed scraper. Backend wires a ``ListingStore`` via ``set_store`` at boot;
``scrape`` accepts ``SearchParams`` and returns a structured ``GrailedScrapeResult``.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from scraper.algolia import (
    build_search_payload,
    build_sold_comparable_payload,
    extract_hits,
    parse_live_hit,
    parse_sold_hit,
)
from scraper.client import GrailedClient
from scraper.config import (
    ALGOLIA_HEADERS,
    ALGOLIA_LIVE_INDEX,
    ALGOLIA_SOLD_INDEX,
    ALGOLIA_SEARCH_URL,
)
from shared.models import (
    GrailedResultRow,
    GrailedScrapeResult,
    LiveListing,
    ScrapeMetadata,
    SearchParams,
    SoldListing,
)

if TYPE_CHECKING:
    from shared.store import ListingStore

_store: "ListingStore | None" = None


def set_store(store: "ListingStore") -> None:
    """Called once from backend lifespan. Scraper must not construct the store."""
    global _store
    _store = store


def _get_store() -> "ListingStore":
    if _store is None:
        raise RuntimeError("ListingStore not configured; call set_store at app boot")
    return _store


def save_listing(listing: dict) -> None:
    """Upsert one sold listing. ``listing`` must include ``id`` and ``category``."""
    _get_store().save_listing(listing)


def has_listing(item_id: str) -> bool:
    """Cheap dedup check before scrape."""
    return _get_store().has_listing(item_id)


def _to_sold_row(listing: SoldListing, *, category: str) -> dict:
    payload = listing.model_dump(mode="json")
    payload["category"] = category
    return payload


def _persist_sold(listing: SoldListing, *, category: str) -> None:
    _get_store().save_listing(_to_sold_row(listing, category=category))


async def scrape(
    params: SearchParams, *, persist: bool = False
) -> GrailedScrapeResult:
    """Run a Grailed scrape against Algolia. Returns structured results.

    ``persist=True`` upserts each sold comparable through the configured
    ``ListingStore``; raises if no store wired.
    """
    async with GrailedClient() as client:
        live_listings = await _fetch_live(client, params)

        rows: list[GrailedResultRow] = []
        for live in live_listings:
            sold: list[SoldListing] = []
            if params.include_sold:
                sold = await _fetch_sold_for(client, live, params)
                if persist:
                    category = params.category or params.department or "unknown"
                    for s in sold:
                        _persist_sold(s, category=category)
            rows.append(GrailedResultRow(live_listing=live, sold_comparables=sold))

    metadata = ScrapeMetadata(
        query=params.query,
        categories=[v for v in (params.department, params.category) if v],
        live_limit_requested=params.live_limit,
        sold_limit_requested=params.sold_limit,
        scraped_at_unix=int(time.time()),
        total_live_found=len(live_listings),
    )
    return GrailedScrapeResult(metadata=metadata, results=rows)


async def _fetch_live(
    client: GrailedClient, params: SearchParams
) -> list[LiveListing]:
    payload = build_search_payload(params, ALGOLIA_LIVE_INDEX)
    raw = await client.post_json(ALGOLIA_SEARCH_URL, payload, headers=ALGOLIA_HEADERS)
    hits = extract_hits(raw)[: params.live_limit]
    return [parse_live_hit(h) for h in hits]


async def _fetch_sold_for(
    client: GrailedClient, live: LiveListing, params: SearchParams
) -> list[SoldListing]:
    payload = build_sold_comparable_payload(live, params, ALGOLIA_SOLD_INDEX)
    raw = await client.post_json(ALGOLIA_SEARCH_URL, payload, headers=ALGOLIA_HEADERS)
    hits = extract_hits(raw)[: params.sold_limit]
    return [parse_sold_hit(h) for h in hits]
