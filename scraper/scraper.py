"""Grailed scraper. Listing persistence goes through ``ListingStore`` injected at boot."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shared.store import ListingStore

_store: ListingStore | None = None


def set_store(store: ListingStore) -> None:
    """Called once from backend lifespan. Scraper must not construct the store."""
    global _store
    _store = store


def _get_store() -> ListingStore:
    if _store is None:
        raise RuntimeError("ListingStore not configured; call set_store at app boot")
    return _store


def save_listing(listing: dict) -> None:
    """Upsert one listing. ``listing`` must include ``id`` and ``category``."""
    _get_store().save_listing(listing)


def has_listing(item_id: str) -> bool:
    """Cheap dedup check before scrape."""
    return _get_store().has_listing(item_id)
