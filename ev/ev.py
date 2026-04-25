"""EV pipeline reads listings via ``ListingStore`` injected at boot."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shared.store import ListingStore

_store: ListingStore | None = None


def set_store(store: ListingStore) -> None:
    """Called once from backend lifespan."""
    global _store
    _store = store


def _get_store() -> ListingStore:
    if _store is None:
        raise RuntimeError("ListingStore not configured; call set_store at app boot")
    return _store


def list_recent_listings(category: str, since: datetime) -> list[dict]:
    """Listings in ``category`` created at or after ``since`` (payload dicts)."""
    return _get_store().list_recent(category, since)
