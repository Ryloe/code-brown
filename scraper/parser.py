"""Pure transformations from raw Grailed responses to shared Pydantic models."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from scraper.exceptions import SchemaValidationError
from shared.models import LiveListing, SoldListing


def parse_live_search_ids(raw: dict[str, Any]) -> list[str]:
    """Extract a list of live listing ids from a Grailed search response."""
    items = _extract_search_items(raw)
    ids = [_extract_item_id(item) for item in items]
    ids = [item for item in ids if item]
    if not ids:
        raise SchemaValidationError("live search response contains no listing ids")
    return ids


def parse_sold_search_ids(raw: dict[str, Any]) -> list[str]:
    """Extract a list of sold listing ids from a Grailed sold-search response."""
    items = _extract_search_items(raw)
    ids = [_extract_item_id(item) for item in items]
    ids = [item for item in ids if item]
    if not ids:
        raise SchemaValidationError("sold search response contains no listing ids")
    return ids


def parse_live_detail(raw: dict[str, Any]) -> LiveListing:
    """Validate a raw live listing payload into the shared LiveListing model."""
    try:
        payload = _extract_listing_payload(raw)
        return LiveListing.model_validate(payload)
    except (KeyError, TypeError, ValidationError) as exc:
        raise SchemaValidationError(f"live detail invalid: {exc}") from exc


def parse_sold_detail(raw: dict[str, Any]) -> SoldListing:
    """Validate a raw sold listing payload into the shared SoldListing model."""
    try:
        source = raw
        if isinstance(raw.get("data"), dict):
            source = raw["data"]
        payload = _extract_listing_payload(raw)
        payload["sold_at_unix"] = _coerce_int(
            _pick_first(source, ["sold_at_unix", "sold_at", "sold_date", "soldAt"])
        )
        return SoldListing.model_validate(payload)
    except (KeyError, TypeError, ValidationError) as exc:
        raise SchemaValidationError(f"sold detail invalid: {exc}") from exc


def _extract_search_items(raw: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(raw.get("data"), list) and raw["data"]:
        return [item for item in raw["data"] if isinstance(item, dict)]

    if isinstance(raw.get("hits"), list) and raw["hits"]:
        return [item for item in raw["hits"] if isinstance(item, dict)]

    if isinstance(raw.get("results"), list) and raw["results"]:
        return [item for item in raw["results"] if isinstance(item, dict)]

    raise SchemaValidationError("search response shape not understood")


def _extract_item_id(raw: dict[str, Any]) -> str:
    for key in ("id", "listing_id", "item_id", "listingId", "slug", "objectID"):
        value = raw.get(key)
        if value is not None:
            return str(value)
    raise SchemaValidationError("search item missing id")


def _extract_listing_payload(raw: dict[str, Any]) -> dict[str, Any]:
    source = raw
    if isinstance(raw.get("data"), dict):
        source = raw["data"]

    payload: dict[str, Any] = {
        "id": str(_pick_first(source, ["id", "listing_id", "item_id", "listingId"])),
        "url": str(_pick_first(source, ["url", "listing_url", "permalink"])),
        "designer": str(_pick_first(source, ["designer", "brand", "label"])),
        "name": str(_pick_first(source, ["name", "title", "headline"])),
        "size": str(_pick_first(source, ["size", "size_label", "sizeRaw"])),
        "condition_raw": str(
            _pick_first(source, ["condition_raw", "condition", "conditionText"])
        ),
        "location": str(_pick_first(source, ["location", "origin", "ship_from"])),
        "color": str(_pick_first(source, ["color", "colour", "shade"])),
        "image_urls": _extract_image_urls(source),
        "price": _extract_price(source),
        "seller": _extract_seller(source),
        "description": str(_pick_first(source, ["description", "details", "body", "listing_description"])),
    }
    return payload


def _extract_image_urls(raw: dict[str, Any]) -> list[str]:
    candidates = raw.get("image_urls") or raw.get("images") or raw.get("photos") or []
    urls: list[str] = []
    if isinstance(candidates, dict):
        candidates = list(candidates.values())
    for item in candidates:
        if isinstance(item, str):
            urls.append(item)
        elif isinstance(item, dict):
            url = _pick_first(item, ["url", "src", "image_url"])
            if url is not None:
                urls.append(str(url))
    return urls


def _extract_seller(raw: dict[str, Any]) -> dict[str, Any]:
    seller = _pick_first(raw, ["seller", "user", "seller_info", "sellerData"])
    if not isinstance(seller, dict):
        seller = {}

    badges = _pick_first(seller, ["badges", "seller_badges"]) or {}
    return {
        "seller_name": str(_pick_first(seller, ["seller_name", "username", "name"])),
        "reviews_count": _coerce_int(
            _pick_first(seller, ["reviews_count", "review_count", "ratings_count", "reviews_count"])
        ),
        "transactions_count": _coerce_int(
            _pick_first(seller, ["transactions_count", "transaction_count"])
        ),
        "items_for_sale_count": _coerce_int(
            _pick_first(seller, ["items_for_sale_count", "inventory_count", "listings_count"])
        ),
        "posted_at_unix": _coerce_int(
            _pick_first(seller, ["posted_at_unix", "joined_at", "created_at", "posted_at"])
        ),
        "badges": {
            "verified": bool(badges.get("verified", False)),
            "trusted_seller": bool(badges.get("trusted_seller", False)),
            "quick_responder": bool(badges.get("quick_responder", False)),
            "speedy_shipper": bool(badges.get("speedy_shipper", False)),
        },
    }


def _extract_price(raw: dict[str, Any]) -> dict[str, Any]:
    price_value = raw.get("price")
    if isinstance(price_value, dict):
        result: dict[str, Any] = {}
        if "listing_price_usd" in price_value or "price_usd" in price_value:
            result["listing_price_usd"] = _coerce_int(
                _pick_first(price_value, ["listing_price_usd", "price_usd", "amount"])
            )
        if "sold_price_usd" in price_value:
            result["sold_price_usd"] = _coerce_int(price_value["sold_price_usd"])
        result["shipping_price_usd"] = _coerce_optional_int(
            _pick_first(price_value, ["shipping_price_usd", "shipping_price", "shipping_usd"])
        )
        return result

    return {
        "listing_price_usd": _coerce_int(
            _pick_first(raw, ["price", "listing_price_usd", "price_usd"])
        ),
        "shipping_price_usd": _coerce_optional_int(
            _pick_first(raw, ["shipping_price", "shipping_price_usd", "shipping_usd"])
        ),
    }


def _pick_first(raw: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in raw and raw[key] is not None:
            return raw[key]
    raise KeyError(f"missing expected key in payload: one of {keys}")


def _coerce_int(value: Any) -> int:
    if value is None or value == "":
        return 0
    return int(value)


def _coerce_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)
