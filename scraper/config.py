"""Static config for the Grailed scraper. No env loading here."""

from __future__ import annotations

LIVE_CAP = 40
SOLD_CAP_PER_LIVE = 40
MAX_CONCURRENCY = 2
REQUEST_DELAY_RANGE = (1.0, 2.0)  # seconds, uniform jitter
REQUEST_TIMEOUT_SEC = 20.0

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]

DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.grailed.com/",
}

ALGOLIA_APP_ID = "MNRWEFSS2Q"
ALGOLIA_API_KEY = "c89dbaddf15fe70e1941a109bf7c2a3d"
ALGOLIA_SEARCH_URL = f"https://{ALGOLIA_APP_ID.lower()}-dsn.algolia.net/1/indexes/*/queries"
ALGOLIA_LIVE_INDEX = "Listing_production"
ALGOLIA_SOLD_INDEX = "Listing_sold_production"
ALGOLIA_HEADERS = {
    "Content-Type": "application/json",
    "X-Algolia-API-Key": ALGOLIA_API_KEY,
    "X-Algolia-Application-Id": ALGOLIA_APP_ID,
}
ALGOLIA_FACETS = [
    "badges",
    "category",
    "category_path",
    "category_size",
    "condition",
    "department",
    "designers.name",
    "location",
    "price_i",
    "strata",
]

DEPARTMENT_VALUES = ["menswear", "womenswear"]
CATEGORY_VALUES = [
    "tops",
    "bottoms",
    "outerwear",
    "footwear",
    "accessories",
    "tailoring",
    "womens_tops",
    "womens_bottoms",
    "womens_outerwear",
    "womens_footwear",
    "womens_dresses",
    "womens_accessories",
    "womens_bags_luggage",
    "womens_jewelry",
]
CONDITION_VALUES = [
    "is_new",
    "is_gently_used",
    "is_used",
    "is_worn",
    "is_not_specified",
]
LOCATION_VALUES = [
    "United States",
    "Europe",
    "Asia",
    "Canada",
    "United Kingdom",
    "Australia/NZ",
    "Other",
]
STRATA_VALUES = ["basic", "grailed", "hype", "sartorial"]
