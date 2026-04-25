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
