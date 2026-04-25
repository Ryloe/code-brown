"""Tests for scraper persistence wiring and store helpers."""

from __future__ import annotations

from shared.models import SoldListing

import scraper.scraper as scraper_mod


class FakeStore:
    def __init__(self) -> None:
        self.saved: list[dict] = []
        self.items: dict[str, dict] = {}

    def save_listing(self, listing: dict) -> None:
        self.saved.append(listing)
        self.items[listing["id"]] = listing

    def has_listing(self, item_id: str) -> bool:
        return item_id in self.items

    def get_listing(self, item_id: str) -> dict | None:
        return self.items.get(item_id)


def test_store_injection_and_helpers():
    store = FakeStore()
    scraper_mod.set_store(store)

    assert not scraper_mod.has_listing("1")

    sold = SoldListing.model_validate(
        {
            "id": "1",
            "url": "https://www.grailed.com/listings/1",
            "designer": "Guidi",
            "name": "Boots",
            "size": "43",
            "condition_raw": "Gently Used",
            "location": "US",
            "color": "Black",
            "image_urls": ["https://example.com/1.jpg"],
            "price": {"sold_price_usd": 700, "shipping_price_usd": 45},
            "sold_at_unix": 1711500000,
            "seller": {
                "seller_name": "Tester",
                "reviews_count": 1,
                "transactions_count": 1,
                "items_for_sale_count": 0,
                "posted_at_unix": 1700000000,
                "badges": {
                    "verified": True,
                    "trusted_seller": False,
                    "quick_responder": False,
                    "speedy_shipper": False,
                },
            },
            "description": "Test.",
        }
    )

    scraper_mod._persist_sold(sold, category="menswear")

    assert scraper_mod.has_listing("1")
    stored = store.get_listing("1")
    assert stored is not None
    assert stored["id"] == "1"
    assert stored["category"] == "menswear"
    assert "kind" not in stored
