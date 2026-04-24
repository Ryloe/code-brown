"""Single concrete listing persistence. Supabase-backed today; swap instance at app boot."""

from __future__ import annotations

from datetime import datetime

from supabase import Client


class ListingStore:
    """Wraps DB access for scraper + EV. No supabase imports outside this module.

    ``save_listing`` expects a dict shaped like ``LiveListing.model_dump()`` with an
    extra top-level ``category`` string (from scrape metadata / filters).
    """

    _TABLE = "listings"

    def __init__(self, db: Client) -> None:
        self._db = db

    def save_listing(self, listing: dict) -> None:
        row = {
            "item_id": listing["id"],
            "category": listing["category"],
            "payload": listing,
        }
        self._db.table(self._TABLE).upsert(row, on_conflict="item_id").execute()

    def get_listing(self, item_id: str) -> dict | None:
        res = (
            self._db.table(self._TABLE)
            .select("payload")
            .eq("item_id", item_id)
            .limit(1)
            .execute()
        )
        return res.data[0]["payload"] if res.data else None

    def has_listing(self, item_id: str) -> bool:
        res = (
            self._db.table(self._TABLE)
            .select("item_id")
            .eq("item_id", item_id)
            .limit(1)
            .execute()
        )
        return bool(res.data)

    def list_recent(self, category: str, since: datetime) -> list[dict]:
        res = (
            self._db.table(self._TABLE)
            .select("payload")
            .eq("category", category)
            .gte("created_at", since.isoformat())
            .order("created_at", desc=True)
            .execute()
        )
        return [r["payload"] for r in (res.data or [])]
