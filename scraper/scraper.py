"""Grailed scraper. Backend wires a ``ListingStore`` via ``set_store`` at boot;
``scrape`` accepts ``SearchParams`` and returns a structured ``GrailedScrapeResult``.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from scraper.algolia import (
    build_search_payload,
    build_seller_stats_payload,
    build_sold_comparable_payload,
    extract_hits,
    hit_user_id,
    parse_live_hit,
    parse_seller_stats,
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
        live_hits = await _search_live(client, params)
        live_hits = live_hits[: params.live_limit]

        sold_hits_per_live: list[list[dict[str, Any]]] = []
        if params.include_sold:
            sold_hits_per_live = await _search_sold_for_each(client, live_hits, params)

        seller_stats = await _fetch_seller_stats(client, live_hits, sold_hits_per_live)

        live_listings = [parse_live_hit(h, seller_stats) for h in live_hits]

        rows: list[GrailedResultRow] = []
        for live, sold_hits in zip(
            live_listings, sold_hits_per_live or [[] for _ in live_listings]
        ):
            sold = [parse_sold_hit(h, seller_stats) for h in sold_hits]
            if persist and sold:
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


async def _search_live(
    client: GrailedClient, params: SearchParams
) -> list[dict[str, Any]]:
    payload = build_search_payload(params, ALGOLIA_LIVE_INDEX)
    raw = await client.post_json(ALGOLIA_SEARCH_URL, payload, headers=ALGOLIA_HEADERS)
    return extract_hits(raw)


async def _search_sold_for_each(
    client: GrailedClient, live_hits: list[dict[str, Any]], params: SearchParams
) -> list[list[dict[str, Any]]]:
    out: list[list[dict[str, Any]]] = []
    for hit in live_hits:
        live_for_query = LiveListing.model_validate(_minimal_live_for_query(hit))
        payload = build_sold_comparable_payload(live_for_query, params, ALGOLIA_SOLD_INDEX)
        raw = await client.post_json(ALGOLIA_SEARCH_URL, payload, headers=ALGOLIA_HEADERS)
        sold_hits = extract_hits(raw)[: params.sold_limit]
        out.append(sold_hits)
    return out


def _minimal_live_for_query(hit: dict[str, Any]) -> dict[str, Any]:
    """Cheap stub for sold-comparable query construction; only ``name`` and
    ``designer`` are read from the LiveListing."""
    name = hit.get("title") or ""
    designers = hit.get("designers") or []
    designer = ""
    if isinstance(designers, list) and designers:
        first = designers[0]
        if isinstance(first, dict):
            designer = str(first.get("name") or "")
    if not designer:
        designer = str(hit.get("designer_names") or "")
    listing_id = str(hit.get("id") or hit.get("objectID") or "0")
    return {
        "id": listing_id,
        "url": f"https://www.grailed.com/listings/{listing_id}",
        "designer": designer,
        "name": name,
        "size": "",
        "condition_raw": "",
        "location": "",
        "color": "",
        "image_urls": [],
        "price": {"listing_price_usd": 0, "shipping_price_usd": 0},
        "seller": {
            "seller_name": "",
            "reviews_count": 0,
            "transactions_count": 0,
            "items_for_sale_count": 0,
            "posted_at_unix": 0,
            "badges": {
                "verified": False,
                "trusted_seller": False,
                "quick_responder": False,
                "speedy_shipper": False,
            },
        },
        "description": "",
    }


async def _fetch_seller_stats(
    client: GrailedClient,
    live_hits: list[dict[str, Any]],
    sold_hits_per_live: list[list[dict[str, Any]]],
) -> dict[int, tuple[int, int]]:
    """For each unique seller across live + sold hits, fetch (items_for_sale_count,
    posted_at_unix). Single Algolia query per unique user_id."""
    user_ids: set[int] = set()
    for h in live_hits:
        uid = hit_user_id(h)
        if uid is not None:
            user_ids.add(uid)
    for batch in sold_hits_per_live:
        for h in batch:
            uid = hit_user_id(h)
            if uid is not None:
                user_ids.add(uid)

    if not user_ids:
        return {}

    async def fetch(uid: int) -> tuple[int, tuple[int, int]]:
        payload = build_seller_stats_payload(uid, ALGOLIA_LIVE_INDEX)
        raw = await client.post_json(ALGOLIA_SEARCH_URL, payload, headers=ALGOLIA_HEADERS)
        return uid, parse_seller_stats(raw)

    results = await asyncio.gather(*(fetch(uid) for uid in user_ids))
    return dict(results)
