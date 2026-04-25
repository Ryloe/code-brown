"""Algolia request building and hit-to-model parsing for Grailed."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

from scraper.config import ALGOLIA_FACETS
from scraper.exceptions import SchemaValidationError
from shared.models import LiveListing, SearchParams, SoldListing


def build_search_payload(params: SearchParams, index_name: str) -> dict[str, Any]:
    """Build the Algolia multi-query payload for one index."""
    return {
        "requests": [
            {
                "indexName": index_name,
                "params": _encode_params(params),
            }
        ]
    }


def build_sold_comparable_payload(
    live: LiveListing, params: SearchParams, index_name: str
) -> dict[str, Any]:
    """Search the sold index for comparables of a given live listing.

    Scopes by designer to keep matches relevant; falls back to title query.
    """
    derived = params.model_copy(
        update={
            "query": live.name,
            "designer": live.designer or params.designer,
            "live_limit": params.sold_limit,
        }
    )
    return build_search_payload(derived, index_name)


def extract_hits(raw: dict[str, Any]) -> list[dict[str, Any]]:
    results = raw.get("results")
    if not isinstance(results, list) or not results:
        raise SchemaValidationError("Algolia response missing 'results'")
    hits = results[0].get("hits")
    if not isinstance(hits, list):
        raise SchemaValidationError("Algolia results[0] missing 'hits'")
    return [h for h in hits if isinstance(h, dict)]


def parse_live_hit(hit: dict[str, Any]) -> LiveListing:
    return LiveListing.model_validate(_base_payload(hit))


def parse_sold_hit(hit: dict[str, Any]) -> SoldListing:
    payload = _base_payload(hit)
    payload["price"] = {
        "sold_price_usd": _coerce_int(hit.get("sold_price") or hit.get("price_i")),
        "shipping_price_usd": _coerce_int(hit.get("sold_shipping_price")),
    }
    payload["sold_at_unix"] = _coerce_int(hit.get("sold_at_i"))
    return SoldListing.model_validate(payload)


def _encode_params(params: SearchParams) -> str:
    facet_filters: list[list[str]] = []
    if params.department:
        facet_filters.append([f"department:{params.department}"])
    if params.category:
        facet_filters.append([f"category:{params.category}"])
    if params.category_path:
        facet_filters.append([f"category_path:{params.category_path}"])
    if params.condition:
        facet_filters.append([f"condition:{params.condition}"])
    if params.location:
        facet_filters.append([f"location:{params.location}"])
    if params.strata:
        facet_filters.append([f"strata:{params.strata}"])
    if params.designer:
        facet_filters.append([f"designers.name:{params.designer}"])

    encoded = {
        "analytics": "false",
        "clickAnalytics": "false",
        "enableABTest": "false",
        "enablePersonalization": "false",
        "facetFilters": json.dumps(facet_filters),
        "facets": json.dumps(ALGOLIA_FACETS),
        "filters": "",
        "highlightPostTag": "</ais-highlight-0000000000>",
        "highlightPreTag": "<ais-highlight-0000000000>",
        "hitsPerPage": str(max(1, params.live_limit)),
        "maxValuesPerFacet": "200",
        "numericFilters": json.dumps(
            [f"price_i>={params.min_price_usd}", f"price_i<={params.max_price_usd}"]
        ),
        "page": "0",
        "personalizationImpact": "0",
        "query": params.query or "",
    }
    return urlencode(encoded)


def _base_payload(hit: dict[str, Any]) -> dict[str, Any]:
    listing_id = str(hit.get("id") or hit.get("objectID") or "")
    if not listing_id:
        raise SchemaValidationError("hit missing id/objectID")

    seller = _extract_seller(hit.get("user") or {})
    return {
        "id": listing_id,
        "url": f"https://www.grailed.com/listings/{listing_id}",
        "designer": _extract_designer(hit),
        "name": str(hit.get("title") or ""),
        "size": str(hit.get("size") or ""),
        "condition_raw": str(hit.get("condition") or ""),
        "location": str(hit.get("location") or ""),
        "color": str(hit.get("color") or ""),
        "image_urls": _extract_image_urls(hit),
        "price": {
            "listing_price_usd": _coerce_int(hit.get("price_i") or hit.get("price")),
            "shipping_price_usd": _coerce_int(hit.get("shipping")),
        },
        "seller": seller,
        "description": "",
    }


def _extract_designer(hit: dict[str, Any]) -> str:
    name = hit.get("designer_names")
    if isinstance(name, str) and name:
        return name
    designers = hit.get("designers")
    if isinstance(designers, list) and designers:
        first = designers[0]
        if isinstance(first, dict) and first.get("name"):
            return str(first["name"])
    return ""


def _extract_image_urls(hit: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    cover = hit.get("cover_photo")
    if isinstance(cover, dict):
        for key in ("url", "image_url"):
            value = cover.get(key)
            if isinstance(value, str) and value:
                urls.append(value)
                break
    photos = hit.get("photos")
    if isinstance(photos, list):
        for item in photos:
            if isinstance(item, dict):
                value = item.get("url") or item.get("image_url")
                if isinstance(value, str) and value:
                    urls.append(value)
    return urls


def _extract_seller(user: dict[str, Any]) -> dict[str, Any]:
    seller_score = user.get("seller_score") or {}
    return {
        "seller_name": str(user.get("username") or ""),
        "reviews_count": _coerce_int(
            seller_score.get("rating_count") if isinstance(seller_score, dict) else 0
        ),
        "transactions_count": _coerce_int(user.get("total_bought_and_sold")),
        "items_for_sale_count": _coerce_int(user.get("listings_for_sale_count")),
        "posted_at_unix": _coerce_int(user.get("created_at_i")),
        "badges": {
            "verified": bool(user.get("verified", False)),
            "trusted_seller": bool(user.get("trusted_seller", False)),
            "quick_responder": bool(user.get("quick_responder", False)),
            "speedy_shipper": bool(user.get("speedy_shipper", False)),
        },
    }


def _coerce_int(value: Any) -> int:
    if value is None or value == "":
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
