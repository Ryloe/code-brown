# Grailed Arbitrage Scraper — Design Spec

Date: 2026-04-24 (revised 2026-04-25, Algolia migration)
Author: Tyler (scraper module owner)
Status: Implemented (v2 — Algolia)
Target: Hackathon build, called per-request from backend

---

## 1. Purpose and Scope

The Grailed Scraper Module is an asynchronous, on-demand data ingestion
pipeline for a secondary-market fashion arbitrage engine. It is the
Extract + Load (EL) half of an ELT architecture. Output consumed by a
downstream analytics module responsible for embeddings, semantic
matching, and valuation.

### In Scope
- Run a Grailed scrape against Algolia for a typed `SearchParams` request
  (query text + facet filters: department, category, condition, location,
  strata, designer, price band).
- Per request: fetch up to N live listings (default 5, configurable) and
  per live listing up to M sold comparables (default 3).
- Enrich each listing with seller stats (`items_for_sale_count`,
  `posted_at_unix`) and optional full `description` (off by default).
- Normalize and validate via Pydantic models in `shared/models.py`.
- Persist sold listings to Supabase Postgres via a `ListingStore`
  injected at backend boot (not constructed by the scraper).
- Return a structured `GrailedScrapeResult` to the caller.

### Out of Scope (Delegated to Analytics Module)
- Semantic matching of live to sold listings.
- Vector embeddings.
- Valuation, margin calculation.
- Condition heuristics or NLP on descriptions.
- Cross-query dedup beyond store-level upsert.

### Non-Goals
- No proxy layer in v2; single IP polite crawl with a stable session.
- No persistent queue/worker model. Each `scrape(params)` call runs to
  completion and returns; the backend wraps it as one request lifecycle.
- No auth scraping flow. All endpoints (Algolia + listing detail) work
  unauthenticated using cookies seeded from a warm-up GET.

---

## 2. Architecture Overview

Single storage layer:

| Layer | Purpose | Location |
|-------|---------|----------|
| Supabase (Postgres) | Canonical sold-listing data consumed by analytics. | Cloud, free tier. |

The HTTP response cache from the v1 design was dropped. Algolia search
is fast and idempotent; the only repeat-cost is the listing-detail
fetch, and per-request scrapes from the backend don't benefit from
cross-process caching. If/when batch crawls return, cache reintroduces
as a thin SQLite wrapper.

### Data Flow (per `scrape(params)` call)

```
scrape(params)
└─> _search_live(client, params)            # POST Algolia Listing_production
└─> _search_sold_for_each(client, live_hits, params)
                                            # POST Algolia Listing_sold_production
                                            # one query per live hit (uses live.designer + name)
└─> _fetch_seller_stats(client, all_hits)   # one Algolia query per unique user.id
└─> _fetch_descriptions(client, all_hits)   # opt-in; one Grailed detail GET per id
└─> parse_live_hit / parse_sold_hit         # Algolia hit → Pydantic, with stats + description injected
└─> if persist: ListingStore.save_listing(sold_row) for each sold
└─> return GrailedScrapeResult
```

A single `GrailedClient` (httpx + tenacity + semaphore) spans the run.
Cookies persist in its jar across the warm-up + all detail calls.

---

## 3. Data Model

### 3.1 Supabase Schema (Postgres)

Schema is owned by the backend / `shared/store.py`. The scraper writes
sold rows via `ListingStore.save_listing(payload)` where `payload`
contains the sold listing dump plus a `category` field. Schema details
live in `shared/store.py`; not duplicated here.

### 3.2 Pydantic Models (`shared/models.py`)

```python
class SearchParams(BaseModel):
    query: str = ""
    department: str | None = None              # "menswear" | "womenswear"
    category: str | None = None                # "tops" | "footwear" | ...
    category_path: str | None = None           # e.g. "tops.short_sleeve_shirts"
    condition: str | None = None               # "is_new" | "is_gently_used" | ...
    location: str | None = None                # "United States" | "Europe" | ...
    strata: str | None = None                  # "basic" | "grailed" | "hype" | "sartorial"
    designer: str | None = None                # matches designers.name facet
    min_price_usd: int = 0
    max_price_usd: int = 1_000_000
    live_limit: int = 5
    sold_limit: int = 3
    include_sold: bool = True
    fetch_descriptions: bool = False           # opt-in; adds N+M Grailed detail GETs

class SellerBadges(BaseModel):
    verified: bool
    trusted_seller: bool
    quick_responder: bool
    speedy_shipper: bool

class Seller(BaseModel):
    seller_name: str
    reviews_count: int
    transactions_count: int
    items_for_sale_count: int
    posted_at_unix: int
    badges: SellerBadges

class LivePrice(BaseModel):
    listing_price_usd: int
    shipping_price_usd: int

class SoldPrice(BaseModel):
    sold_price_usd: int
    shipping_price_usd: int

class LiveListing(BaseModel):
    id: str
    url: str
    designer: str
    name: str
    size: str
    condition_raw: str
    location: str
    color: str
    image_urls: list[str]
    price: LivePrice
    seller: Seller
    description: str

class SoldListing(BaseModel):
    id: str
    url: str
    designer: str
    name: str
    size: str
    condition_raw: str
    location: str
    color: str
    image_urls: list[str]
    price: SoldPrice
    sold_at_unix: int
    seller: Seller
    description: str

class GrailedResultRow(BaseModel):
    live_listing: LiveListing
    sold_comparables: list[SoldListing] = Field(default_factory=list)

class ScrapeMetadata(BaseModel):
    query: str
    categories: list[str]
    live_limit_requested: int
    sold_limit_requested: int
    scraped_at_unix: int
    total_live_found: int

class GrailedScrapeResult(BaseModel):
    metadata: ScrapeMetadata
    results: list[GrailedResultRow] = Field(default_factory=list)
```

Required-int fields use `0` as the missing-value sentinel. Pydantic
validation runs on every model construction; a malformed Algolia hit
raises `SchemaValidationError` from `parser.py` / `algolia.py`.

---

## 4. Module Layout

```
scraper/
├── __init__.py        # Public exports: GrailedClient, scrape, set_store, save_listing, has_listing
├── config.py          # Algolia constants, facet enums, browser headers, throttle params
├── exceptions.py      # ScraperError, GrailedRateLimitExceeded, SchemaValidationError, ScrapeAborted
├── client.py          # GrailedClient: httpx + tenacity + semaphore + Cloudflare warm-up
├── algolia.py         # Payload builders + hit parsers + seller-stats helpers
├── parser.py          # (legacy) Pydantic parsing of pre-Algolia detail payloads; kept for tests
├── scraper.py         # scrape(params) entrypoint + persistence wiring (set_store, _persist_sold)
├── cli.py             # Interactive tester: prompts each SearchParams field, prints JSON
└── tests/
    ├── conftest.py
    ├── test_client.py
    ├── test_parser.py
    └── test_scraper.py
```

### Module Responsibilities

- **config.py** — `LIVE_CAP`, `SOLD_CAP_PER_LIVE`, `MAX_CONCURRENCY=2`,
  `REQUEST_DELAY_RANGE=(1.0, 2.0)`, `REQUEST_TIMEOUT_SEC=20`, three
  desktop User-Agents, `DEFAULT_HEADERS`, Algolia URL/keys/headers/index
  names + facet enums (`DEPARTMENT_VALUES`, `CATEGORY_VALUES`,
  `CONDITION_VALUES`, `LOCATION_VALUES`, `STRATA_VALUES`),
  `BROWSER_HEADERS_HTML` and `BROWSER_HEADERS_JSON` for Cloudflare-gated
  detail calls.
- **exceptions.py** — `ScraperError` base, `GrailedRateLimitExceeded`
  (raised after tenacity exhausts 429 retries), `SchemaValidationError`
  (raised by parsers), `ScrapeAborted` (reserved for caller-side abort).
- **client.py** — `GrailedClient` async context manager wraps
  `httpx.AsyncClient(http2=True, follow_redirects=True)`. Stable
  `User-Agent` per session (chosen at init from `USER_AGENTS`). Methods:
  - `get_json(url, params, headers)` and `post_json(url, json_payload,
    headers)` — both throttled by `asyncio.Semaphore(2)` and a 1–2 s
    jitter sleep, retried with tenacity on 429 (exp backoff, 3 attempts)
    and 5xx.
  - `get_listing_detail(listing_id)` — calls `_ensure_warmed_up()`, then
    `get_json` against `https://www.grailed.com/api/listings/{id}` with
    `BROWSER_HEADERS_JSON`. Cookies set during warm-up satisfy
    Cloudflare.
  - `_ensure_warmed_up()` — lock-guarded one-shot `GET https://www.grailed.com/`
    with `BROWSER_HEADERS_HTML`. Idempotent; subsequent calls cheap.
- **algolia.py** — pure functions:
  - `build_search_payload(params, index_name)` — encodes `SearchParams`
    into the Algolia multi-query body, applying facet filters in the
    canonical lowercase / dotted forms (verified by probing
    `facets:["*"]`).
  - `build_sold_comparable_payload(live, params, index)` — derives a
    sold search from a live listing's designer + name.
  - `extract_hits(raw)` — pulls `results[0].hits`.
  - `parse_live_hit(hit, seller_stats=None, descriptions=None)` and
    `parse_sold_hit(...)` — Algolia hit → Pydantic model. Optional
    enrichment dicts inject `Seller.items_for_sale_count`,
    `Seller.posted_at_unix`, and `description`.
  - `hit_user_id(hit)` — extracts seller `user.id` for dedup.
  - `build_seller_stats_payload(user_id, index)` — Algolia query
    `filters=user.id:{id}`, `hitsPerPage=1000`,
    `attributesToRetrieve=["created_at_i"]`. Returns nbHits +
    timestamps in one round-trip.
  - `parse_seller_stats(raw) -> (items_for_sale_count, posted_at_unix)` —
    `nbHits` is exact items count; `posted_at_unix` = `min(created_at_i)`
    across the (up to 1000) returned listings, used as a lower-bound
    proxy for account age.
- **parser.py** — kept untouched from v1. Maps the old Grailed JSON
  detail shape to Pydantic models. Currently unused by `scrape()` but
  referenced by `tests/test_parser.py`. Safe to delete once a parallel
  Algolia-hit test suite exists.
- **scraper.py** — owns `scrape(params, *, persist=False)`. Two-pass:
  1. Raw Algolia search calls collect live + sold hits.
  2. `_fetch_seller_stats` (one Algolia call per unique `user.id`) and
     `_fetch_descriptions` (one Grailed detail call per unique listing
     id, opt-in) run, results memoized into dicts.
  3. Hits parsed with enrichment dicts injected.
  4. If `persist=True`, sold rows upserted via injected `ListingStore`.
  Also exposes `set_store`, `save_listing`, `has_listing`,
  `_persist_sold`, `_to_sold_row`.
- **cli.py** — interactive tester. Prompts every `SearchParams` field
  via numbered menus (department, category, condition, location, strata)
  or free-text/int prompts. Calls `scrape(params)` (no persist). Prints
  metadata + each row as indented JSON. No Supabase coupling.

---

## 5. Network Behavior

### HTTP Layer
- `httpx.AsyncClient(http2=True, follow_redirects=True)` reused across
  requests (connection pooling + cookie jar shared).
- Stable `User-Agent` per `GrailedClient` instance (one of 3 desktop
  UAs, chosen at init). Browser-realistic `Sec-CH-UA*` and `Sec-Fetch-*`
  headers attached only on Grailed detail calls (Algolia doesn't need
  them).
- Cookie jar populated by the warm-up `GET https://www.grailed.com/`;
  subsequent listing-detail calls inherit `cf_clearance` etc.

### Throttle and Concurrency
- `asyncio.Semaphore(2)` — at most 2 in-flight requests at any moment.
- Per-request jitter: `asyncio.sleep(uniform(1.0, 2.0))` after each
  response.
- Sustained throughput: ~40–60 requests/min.

### Retry Strategy (tenacity)
- **HTTP 429**: exponential backoff (multiplier=30 s, max 120 s). Max 3
  attempts. Raises `GrailedRateLimitExceeded` on final failure.
- **HTTP 5xx**: same backoff schedule, max 3 attempts.
- **Description fetch failures**: swallowed; missing description yields
  `""` for that listing rather than failing the whole scrape.
- **Network errors**: surfaced via httpx; tenacity retries on the marker
  exception classes only.

### Algolia
- Endpoint: `https://mnrwefss2q-dsn.algolia.net/1/indexes/*/queries`.
- App ID + public search API key embedded in `config.py` (the same keys
  used by the public Grailed web UI; safe to ship client-side).
- Live index: `Listing_production`. Sold index: `Listing_sold_production`.
- All known Algolia replicas (`*_created_at_i_asc`, `*_oldest`) returned
  403; default ordering only.

### Cloudflare Cookie Warm-Up
- Without it, both `https://www.grailed.com/listings/{id}` and
  `https://www.grailed.com/api/listings/{id}` return 403.
- With it (one prior `GET /` from the same `httpx` client carrying
  browser headers + stable UA), the API call returns 200 with full
  detail JSON including `description`.

---

## 6. Failure Handling

### Per-Request Lifecycle
- A single `scrape()` call is a unit. If it fails partway, the caller
  (backend handler) decides retry policy; the scraper does not persist
  partial state to a queue.
- If `persist=True`, the sold rows that completed before a mid-run
  failure remain in Supabase. `ListingStore.save_listing` upserts on
  primary key, so a retried scrape is idempotent.

### Caller Contract
- `scrape(params, persist=False) -> GrailedScrapeResult` may raise:
  - `GrailedRateLimitExceeded` — Algolia or Grailed is rate-limiting
    persistently.
  - `SchemaValidationError` — an Algolia hit shape changed unexpectedly.
  - `RuntimeError("ListingStore not configured…")` — `persist=True` was
    passed without a prior `set_store(store)` call.
  - Any `httpx.HTTPError` for unrecoverable transport problems.
- The interactive CLI prints to stdout and exits 0 on success, 130 on
  Ctrl-C.

---

## 7. Output Contract for Analytics

Two consumption modes:

1. **In-process call** (preferred when scraper and analytics share a
   Python runtime): `result = await scrape(params)` returns a fully
   typed `GrailedScrapeResult`. Analytics consumes
   `result.results[i].live_listing` and `.sold_comparables` directly.
2. **Supabase read** (when persistence is enabled): analytics queries
   the sold-listings table populated via `ListingStore.save_listing`.
   Schema owned by `shared/store.py`.

JSON shape from `result.model_dump(mode="json")`:

```json
{
  "metadata": {
    "query": "jordan 4",
    "categories": ["menswear", "footwear"],
    "live_limit_requested": 5,
    "sold_limit_requested": 3,
    "scraped_at_unix": 1777093530,
    "total_live_found": 5
  },
  "results": [
    {
      "live_listing": { /* full LiveListing dump */ },
      "sold_comparables": [ { /* SoldListing dump */ }, ... ]
    },
    ...
  ]
}
```

---

## 8. Configuration

### Environment Variables (loaded via python-dotenv, only when persisting)
```
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...   # server-side only, never committed
```

The interactive CLI does not read Supabase env vars; persistence is
backend-side only.

### config.py Constants (excerpt)
```python
LIVE_CAP = 40
SOLD_CAP_PER_LIVE = 40
MAX_CONCURRENCY = 2
REQUEST_DELAY_RANGE = (1.0, 2.0)
REQUEST_TIMEOUT_SEC = 20.0

ALGOLIA_APP_ID = "MNRWEFSS2Q"
ALGOLIA_API_KEY = "c89dbaddf15fe70e1941a109bf7c2a3d"
ALGOLIA_LIVE_INDEX = "Listing_production"
ALGOLIA_SOLD_INDEX = "Listing_sold_production"

DEPARTMENT_VALUES = ["menswear", "womenswear"]
CATEGORY_VALUES   = ["tops", "bottoms", "outerwear", "footwear",
                     "accessories", "tailoring", "womens_tops",
                     "womens_bottoms", "womens_outerwear",
                     "womens_footwear", "womens_dresses",
                     "womens_accessories", "womens_bags_luggage",
                     "womens_jewelry"]
CONDITION_VALUES  = ["is_new", "is_gently_used", "is_used", "is_worn",
                     "is_not_specified"]
LOCATION_VALUES   = ["United States", "Europe", "Asia", "Canada",
                     "United Kingdom", "Australia/NZ", "Other"]
STRATA_VALUES     = ["basic", "grailed", "hype", "sartorial"]
```

Facet values verified against a live Algolia probe with
`facets:["*"]` on 2026-04-25.

### .gitignore Additions
```
.env
```

---

## 9. Testing

### Unit Tests (12 passing as of 2026-04-25)
- `test_client.py` — verifies `get_json` returns decoded body, sets
  `User-Agent` and `Referer`, retries on 429 then succeeds, raises
  `GrailedRateLimitExceeded` after exhaustion. Uses `respx` to mock
  httpx.
- `test_parser.py` — exercises the legacy detail-payload parsers
  (`parse_live_detail`, `parse_sold_detail`, `parse_*_search_ids`). Will
  be replaced by an Algolia-hit test suite when `parser.py` is removed.
- `test_scraper.py` — exercises `set_store` / `_persist_sold` /
  `has_listing` against a `FakeStore`. Confirms `category` field is
  attached to the sold dump.

### Manual Smoke Test
The `scraper/cli.py` interactive tester is the smoke harness. Run
`python -m scraper.cli`, accept defaults or pick filters, watch real
results print. Any silent zero-result scrape signals an Algolia facet
drift; verify by re-running the live `_probe_algolia.py` style query
with `facets:["*"]`.

---

## 10. Future Work

### Re-add HTTP Cache
If the backend grows a batch-crawl path (overnight refresh of a fixed
seed list), reintroduce the SQLite `http_cache` table from the v1
design. Per-request scrapes from the API don't need it.

### Proxy Layer
Trigger condition: sustained 429s from Algolia or Cloudflare blocks on
the listing-detail endpoint.

Rollout (unchanged from v1 plan):
1. Sign up for a residential rotating proxy provider (Oxylabs, IPRoyal,
   or Smartproxy).
2. Add `PROXY_URL` env var.
3. Pass `proxy=settings.PROXY_URL` into `httpx.AsyncClient` in
   `client.py`.
4. Increase `MAX_CONCURRENCY` to 10–15 and drop
   `REQUEST_DELAY_RANGE` to `(0.1, 0.3)` once stable.

### Description Fetch Performance
With `fetch_descriptions=True` the scrape adds `live_limit + sold_limit
× live_limit` Grailed detail GETs (e.g. 5 + 15 = 20 calls × 1–2 s × 2
concurrency ≈ 10–20 s). Options if this becomes a hot path:
- Persist descriptions in the listing store and only fetch on cache
  miss.
- Move description fetching behind the proxy layer once available so
  concurrency can be raised.

### Cleanup
- Remove `scraper/parser.py` and the matching test cases once the
  legacy detail-fetch path is confirmed unused everywhere.
- Add an Algolia-hit fixture-based test suite to replace it.

---

## 11. Runtime Estimates

### Per-Request Latency (no descriptions)
- Live search (1 Algolia call) + sold search (N Algolia calls) +
  seller-stats (≤ N+M unique sellers) ≈ 1 + N + (N+M) Algolia calls.
- N=5, M=3: ~1 + 5 + 20 = 26 Algolia calls. At ~250 ms each, throttled
  to 2-concurrent + 1–2 s jitter, ~15–25 s wall time.

### Per-Request Latency (with descriptions)
- Add (N + N×M) Grailed detail calls ≈ 5 + 15 = 20 extra calls. Same
  throttle applies → +10–20 s wall time. Total ~30–45 s.

### Egress
- A single response with descriptions stays well under 1 MB JSON.
  Negligible.

---

## 12. Open Questions Resolved

| Question | Resolution |
|----------|------------|
| Algolia migration? | Done. Live and sold both via Algolia. Detail JSON via Grailed `api/listings/{id}` with Cloudflare warm-up. |
| Algolia facet values? | Verified by probing `facets:["*"]` on 2026-04-25. Stored in `config.py`. |
| Items-for-sale count? | Algolia `nbHits` for `filters=user.id:{id}`. One call per unique seller. |
| `posted_at_unix`? | Min `created_at_i` across user's first ≤ 1000 listings. Lower-bound proxy for account creation. |
| Description source? | `https://www.grailed.com/api/listings/{id}` with cookies seeded from a warm-up `GET /`. Opt-in via `SearchParams.fetch_descriptions`. |
| Persistence ownership? | Backend constructs `ListingStore`, calls `set_store(store)` once at lifespan. Scraper never instantiates a store. |
| Proxy provider? | None in v2. Plan unchanged from v1 (Oxylabs / IPRoyal / Smartproxy). |
| Output shape? | `GrailedScrapeResult` Pydantic dump (see Section 7). |

---

## 13. Acceptance Criteria

The scraper module is considered complete when:

1. `await scrape(SearchParams(...))` returns a populated
   `GrailedScrapeResult` against a real Algolia query.
2. Seller fields `items_for_sale_count` and `posted_at_unix` are
   populated from the seller-stats enrichment pass.
3. With `fetch_descriptions=True`, every returned listing has a
   non-empty `description`.
4. With `persist=True` and a `set_store(store)` call, sold listings
   land in Supabase via the `ListingStore`.
5. `python -m scraper.cli` prompts each `SearchParams` field, runs a
   real scrape, and prints the result as JSON.
6. All scraper unit tests pass.
7. Backend can `from scraper import scrape, set_store` and wire
   without touching scraper internals.
