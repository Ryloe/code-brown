"""Unit tests for Grailed parser functions."""

from __future__ import annotations

import pytest

from scraper.exceptions import SchemaValidationError
from scraper.parser import (
    parse_live_detail,
    parse_live_search_ids,
    parse_sold_detail,
    parse_sold_search_ids,
)
from shared.models import LiveListing, SoldListing


def test_parse_live_search_ids_returns_strings():
    raw = {"data": [{"id": "L1"}, {"id": "L2"}]}
    ids = parse_live_search_ids(raw)
    assert ids == ["L1", "L2"]


def test_parse_sold_search_ids_returns_strings():
    raw = {"data": [{"id": "S1"}, {"id": "S2"}]}
    ids = parse_sold_search_ids(raw)
    assert ids == ["S1", "S2"]


def test_parse_live_detail_returns_validated_model():
    raw = {
        "data": {
            "id": "14589321",
            "url": "https://www.grailed.com/listings/14589321-guidi-788z-back-zip-boots",
            "designer": "Guidi",
            "name": "788Z Back Zip Boots",
            "size": "43",
            "condition_raw": "Gently Used",
            "location": "US",
            "color": "Black",
            "image_urls": [
                "https://media-assets.grailed.com/prd/listing/14589321/photo1.jpg"
            ],
            "price": {"listing_price_usd": 850, "shipping_price_usd": 20},
            "seller": {
                "seller_name": "ArchiveArchivist",
                "reviews_count": 150,
                "transactions_count": 175,
                "items_for_sale_count": 12,
                "posted_at_unix": 1713000000,
                "badges": {
                    "verified": True,
                    "trusted_seller": True,
                    "quick_responder": False,
                    "speedy_shipper": True,
                },
            },
            "description": "Vibramed since day one.",
        }
    }
    listing = parse_live_detail(raw)
    assert isinstance(listing, LiveListing)
    assert listing.id == "14589321"
    assert listing.price.listing_price_usd == 850


def test_parse_sold_detail_returns_validated_model():
    raw = {
        "data": {
            "id": "13904822",
            "url": "https://www.grailed.com/listings/13904822-guidi-788z-horse-full-grain",
            "designer": "Guidi",
            "name": "788Z Horse Full Grain",
            "size": "43",
            "condition_raw": "Used",
            "location": "EU",
            "color": "Black",
            "image_urls": [
                "https://media-assets.grailed.com/prd/listing/13904822/photo1.jpg"
            ],
            "price": {"sold_price_usd": 720, "shipping_price_usd": 45},
            "sold_at_unix": 1711500000,
            "seller": {
                "seller_name": "DarkwearEU",
                "reviews_count": 89,
                "transactions_count": 94,
                "items_for_sale_count": 3,
                "posted_at_unix": 1709000000,
                "badges": {
                    "verified": True,
                    "trusted_seller": False,
                    "quick_responder": True,
                    "speedy_shipper": False,
                },
            },
            "description": "Classic backzips.",
        }
    }
    listing = parse_sold_detail(raw)
    assert isinstance(listing, SoldListing)
    assert listing.id == "13904822"
    assert listing.sold_at_unix == 1711500000
    assert all(isinstance(url, str) for url in listing.image_urls)


def test_parse_live_detail_image_urls_are_strings():
    raw = {
        "data": {
            "id": "14589321",
            "url": "https://www.grailed.com/listings/14589321-guidi-788z-back-zip-boots",
            "designer": "Guidi",
            "name": "788Z Back Zip Boots",
            "size": "43",
            "condition_raw": "Gently Used",
            "location": "US",
            "color": "Black",
            "image_urls": [
                "https://media-assets.grailed.com/prd/listing/14589321/photo1.jpg",
                "https://media-assets.grailed.com/prd/listing/14589321/photo2.jpg",
            ],
            "price": {"listing_price_usd": 850, "shipping_price_usd": 20},
            "seller": {
                "seller_name": "ArchiveArchivist",
                "reviews_count": 150,
                "transactions_count": 175,
                "items_for_sale_count": 12,
                "posted_at_unix": 1713000000,
                "badges": {
                    "verified": True,
                    "trusted_seller": True,
                    "quick_responder": False,
                    "speedy_shipper": True,
                },
            },
            "description": "Vibramed since day one.",
        }
    }
    listing = parse_live_detail(raw)
    assert all(isinstance(url, str) for url in listing.image_urls)


def test_parse_live_detail_raises_on_garbage():
    with pytest.raises(SchemaValidationError):
        parse_live_detail({"totally": "wrong"})


def test_parse_sold_detail_raises_on_garbage():
    with pytest.raises(SchemaValidationError):
        parse_sold_detail({"nope": True})
