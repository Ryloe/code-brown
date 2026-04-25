\# Grailed Arbitrage Scraper --- Design Spec

Date: 2026-04-24 Author: Tyler (scraper module owner) Status: Approved
for implementation Target: 12-hour hackathon build + overnight batch
crawl

\-\--

\## 1. Purpose and Scope

The Grailed Scraper Module is an asynchronous, resume-safe data
ingestion pipeline for a secondary-market fashion arbitrage engine. It
is the Extract + Load (EL) half of an ELT architecture. Its output is
consumed by a downstream analytics module (owned by a teammate)
responsible for embeddings, semantic matching, and valuation.

\### In Scope - Query Grailed for a configurable list of user queries
(e.g., \"Guidi 788Z\", \"Number (N)ine\"). - For each user query: fetch
up to 40 live listings and, for each live listing, up to 40 sold
comparables. - Fetch full detail payloads for both live and sold
listings. - Normalize and validate all data through Pydantic schemas. -
Persist clean data to a Supabase Postgres database. - Cache raw HTTP
responses in a local SQLite file to avoid re-hitting the network on
reruns. - Expose an exporter that produces the JSON payload shape the
analytics module expects. - Resume safely after a crash or manual kill.

\### Out of Scope (Delegated to Analytics Module) - Semantic matching of
live to sold listings. - Vector embeddings (FAISS or similar). -
Valuation, margin calculation, filtering by variance. -
Condition-heuristic regex or NLP on descriptions (scraper stores raw
\`description\` only; analytics parses). - Deduplication of listings
across queries beyond primary-key conflict handling.

\### Non-Goals - No proxy layer in v1. Single IP polite crawl. Proxy
integration deferred to v2 (see Section 10). - No real-time scraping
during demo. Data is pre-scraped overnight and served from Supabase. -
No authentication scraping flow; sold data is accessible from tested
endpoints without login.

\-\--

\## 2. Architecture Overview

Two storage layers:

\| Layer \| Purpose \| Location \|
\|\-\-\-\-\-\--\|\-\-\-\-\-\-\-\--\|\-\-\-\-\-\-\-\-\--\| \| Supabase
(Postgres) \| Canonical clean data consumed by analytics. \| Cloud, free
tier. \| \| Local SQLite \| Raw HTTP response cache. Never shipped to
cloud. \| \`./cache.db\` in repo. \|

Separation prevents raw HTML/JSON blobs from consuming the 500 MB
Supabase free-tier quota while keeping reruns cheap during development.

\### Data Flow (per user query)

\`\`\` claim_next_query() \# Postgres RPC, FOR UPDATE SKIP LOCKED └─\>
scrape_live_search(query) \# paginate scroll cursors, cap 40 listings
└─\> for each live_listing_id: fetch_live_detail(id) \# cached in
SQLite, then parsed upsert live_listings row \# batched in chunks of 50
scrape_sold_search(designer + name tokens) └─\> for each sold_id:
fetch_sold_detail(id) upsert sold_listings row mark_done(query_id)
\`\`\`

Engine is crash-safe: interrupted runs resume from whichever query is
still \`pending\` or stuck \`running\` beyond a staleness threshold.

\-\--

\## 3. Data Model

\### 3.1 Supabase Schema (Postgres)

\`\`\`sql CREATE TABLE user_queries ( id BIGSERIAL PRIMARY KEY, query
TEXT UNIQUE NOT NULL, categories JSONB, status TEXT NOT NULL DEFAULT
\'pending\', \-- pending \| running \| done \| failed last_error TEXT,
started_at BIGINT, finished_at BIGINT, created_at TIMESTAMPTZ NOT NULL
DEFAULT now() );

CREATE TABLE live_listings ( id TEXT PRIMARY KEY, query_id BIGINT NOT
NULL REFERENCES user_queries(id) ON DELETE CASCADE, payload JSONB NOT
NULL, \-- validated Pydantic dump scraped_at BIGINT NOT NULL );

CREATE TABLE sold_listings ( id TEXT PRIMARY KEY, live_listing_id TEXT
NOT NULL REFERENCES live_listings(id) ON DELETE CASCADE, payload JSONB
NOT NULL, sold_at_unix BIGINT, scraped_at BIGINT NOT NULL );

CREATE TABLE listing_images ( listing_id TEXT NOT NULL, \-- references
either live or sold url TEXT NOT NULL, position INTEGER NOT NULL,
PRIMARY KEY (listing_id, position) );

CREATE INDEX idx_sold_live ON sold_listings(live_listing_id); CREATE
INDEX idx_live_query ON live_listings(query_id); CREATE INDEX
idx_queries_status ON user_queries(status); \`\`\`

Image URLs are stored in a separate table as TEXT because JSONB array
overhead is wasteful for plain strings. This saves \~40% on row size for
image-heavy listings.

\### 3.2 Atomic Claim RPC

\`\`\`sql CREATE OR REPLACE FUNCTION claim_next_query() RETURNS
user_queries LANGUAGE plpgsql AS \$\$ DECLARE q user_queries; BEGIN
SELECT \* INTO q FROM user_queries WHERE status = \'pending\' ORDER BY
id LIMIT 1 FOR UPDATE SKIP LOCKED;

IF q.id IS NULL THEN RETURN NULL; END IF;

UPDATE user_queries SET status = \'running\', started_at = EXTRACT(epoch
FROM now())::bigint WHERE id = q.id;

RETURN q; END; \$\$; \`\`\`

Callable from Python: \`supabase.rpc(\'claim_next_query\').execute()\`.
Safe for future concurrent workers thanks to \`FOR UPDATE SKIP LOCKED\`.

\### 3.3 Local SQLite Cache Schema

\`\`\`sql CREATE TABLE http_cache ( cache_key TEXT PRIMARY KEY, \--
sha256(method + url + sorted_query_params) status_code INTEGER NOT NULL,
body TEXT NOT NULL, \-- raw response body (JSON or HTML) fetched_at
INTEGER NOT NULL \-- unix seconds ); \`\`\`

Cache policy: hit if \`now - fetched_at \< TTL\` (default 6 hours; set
to effectively infinity during development reruns).

\### 3.4 Pydantic Models

\`\`\`python class Seller(BaseModel): seller_name: str reviews_count:
int \| None = None transactions_count: int \| None = None
items_for_sale_count: int \| None = None posted_at_unix: int \| None =
None badges: dict\[str, bool\]

class LivePrice(BaseModel): listing_price_usd: float shipping_price_usd:
float \| None = None

class SoldPrice(BaseModel): sold_price_usd: float shipping_price_usd:
float \| None = None

class ListingBase(BaseModel): id: str url: HttpUrl designer: str name:
str size: str \| None = None condition_raw: str \| None = None location:
str \| None = None color: str \| None = None image_urls: list\[HttpUrl\]
= \[\] description: str seller: Seller

class LiveListing(ListingBase): price: LivePrice

class SoldListing(ListingBase): price: SoldPrice sold_at_unix: int \|
None = None

class ResultPair(BaseModel): live_listing: LiveListing sold_comparables:
list\[SoldListing\]

class Metadata(BaseModel): query: str categories: list\[str\]
scraped_at_unix: int total_live_found: int live_limit_requested: int
sold_limit_requested: int

class ScrapePayload(BaseModel): metadata: Metadata results:
list\[ResultPair\] \`\`\`

Shape matches the FinalJSON.json reference file exactly.

\-\--

\## 4. Module Layout

\`\`\` grailed_scraper/ ├── \_\_init\_\_.py \# Exposes entrypoints ├──
config.py \# Rate limits, caps, seed queries, env loader ├── models.py
\# Pydantic schemas above ├── parser.py \# Pure functions: raw response
-\> Pydantic models ├── client.py \# httpx.AsyncClient + tenacity
retry + cache wrap ├── db_cache.py \# Local SQLite http_cache CRUD ├──
db_supabase.py \# supabase-py client: upserts, batch flush, RPC claim
├── engine.py \# Orchestration: resume-safe scrape loop ├── exporter.py
\# Supabase -\> FinalJSON payload for analytics ├── exceptions.py \#
GrailedRateLimitExceeded, SchemaValidationError, etc. ├── cli.py \#
python -m grailed_scraper {init-db,seed,run,resume,export} ├── supabase/
│ └── schema.sql \# All Postgres DDL + RPC └── tests/ ├── fixtures/ \#
Recorded JSON/HTML responses ├── test_parser.py ├── test_models.py └──
test_engine.py \`\`\`

\### Module Responsibilities

\- \*\*config.py\*\* --- loads \`.env\` (Supabase URL, service-role
key), defines \`LIVE_CAP = 40\`, \`SOLD_CAP_PER_LIVE = 40\`,
\`REQUEST_DELAY_SEC = (1.0, 2.0)\` jitter range, \`MAX_CONCURRENCY =
2\`, default seed query list. - \*\*models.py\*\* --- schemas only, no
side effects. - \*\*parser.py\*\* --- pure transformation functions.
Input: raw response. Output: Pydantic model or
\`SchemaValidationError\`. Easily unit-tested against fixtures. -
\*\*client.py\*\* --- all network activity. Every \`get()\` call routes
through the cache. On cache miss, fires \`httpx\` request with retry +
throttle, writes response to cache, returns. - \*\*db_cache.py\*\* ---
thin wrapper around SQLite3 for \`http_cache\` table. No business
logic. - \*\*db_supabase.py\*\* --- wraps \`supabase-py\`. Offers
batched \`upsert_live_listings(rows)\`, \`upsert_sold_listings(rows)\`,
\`insert_images(rows)\`, \`claim_next_query()\`, \`mark_done(id)\`,
\`mark_failed(id, err)\`. - \*\*engine.py\*\* --- the loop. Claims a
query, drives client + parser + db_supabase, handles per-query
try/except, marks status transitions. - \*\*exporter.py\*\* ---
\`export_query_to_json(query_id) -\> dict\` reconstructs the exact
\`FinalJSON.json\` shape by joining \`user_queries\`, \`live_listings\`,
\`sold_listings\`, \`listing_images\`. - \*\*exceptions.py\*\* ---
\`GrailedRateLimitExceeded\`, \`SchemaValidationError\`,
\`ProxyPoolExhausted\` (placeholder for v2), \`ScrapeAborted\`. -
\*\*cli.py\*\* --- argparse entrypoints for the five subcommands.

\-\--

\## 5. Network Behavior (No Proxy, v1)

\### HTTP Layer - \`httpx.AsyncClient(http2=True)\` reused across
requests (connection pooling). - Browser-realistic headers copied from
DevTools: \`User-Agent\`, \`Sec-CH-UA\`, \`Sec-CH-UA-Platform\`,
\`Accept\`, \`Accept-Language\`, \`Referer\`. - \`User-Agent\` rotated
from a small list of 3 current desktop UAs (Chrome, Safari, Firefox). -
Cookies persisted across the lifetime of a single run via the client\'s
cookie jar.

\### Throttle and Concurrency - Global \`asyncio.Semaphore(2)\` --- at
most 2 in-flight requests at any moment. - Per-request jitter sleep:
\`asyncio.sleep(uniform(1.0, 2.0))\` after each response. - Expected
sustained throughput: \~40--60 requests per minute.

\### Retry Strategy (tenacity) - \*\*HTTP 429\*\*: exponential backoff
--- 30s, 60s, 120s. Max 3 attempts. Raises \`GrailedRateLimitExceeded\`
on final failure. - \*\*HTTP 5xx\*\*: 5s, 15s, 30s. Max 3 attempts. -
\*\*Network errors\*\* (timeout, connection reset): 5s, 10s. Max 2
attempts. - All failures logged to \`user_queries.last_error\` for
observability.

\### Cache-First Every GET routes through \`client.get_cached(url,
params)\`: 1. Compute \`cache_key = sha256(method + url +
sorted(params))\`. 2. SELECT from \`http_cache\` --- if fresh, return
body without network. 3. On miss: fire request, UPSERT result into
cache, return.

TTL defaults to 6 hours in production and effectively infinity during
development (set via \`CACHE_TTL_SEC\` env var).

\-\--

\## 6. Resume and Failure Handling

\### Startup Sequence 1. Load config, connect Supabase, open local
SQLite. 2. Re-arm stale \`running\` queries: \`UPDATE user_queries SET
status=\'pending\' WHERE status=\'running\' AND started_at \< now -
30min\`. Guards against a crash that left a row mid-flight. 3. Enter
main loop.

\### Main Loop \`\`\`python while True: q =
db_supabase.claim_next_query() if q is None: break try:
scrape_one_query(q) db_supabase.mark_done(q.id) except
(GrailedRateLimitExceeded, ScrapeAborted) as e:
db_supabase.mark_failed(q.id, str(e)) \# continue to next query except
Exception as e: db_supabase.mark_failed(q.id, repr(e)) \# log and
continue \`\`\`

\### Per-Query Partial Progress Within \`scrape_one_query\`, listings
are upserted as they are parsed. A crash mid-query leaves partial rows
in Supabase; on resume the query row is re-armed and will be re-scraped,
but cached HTTP responses mean no duplicate network calls. Upserts use
\`ON CONFLICT (id) DO UPDATE\`, so re-scraping is idempotent.

\### Exit Conditions - No more \`pending\` queries. -
\`KeyboardInterrupt\` --- flushes any buffered upserts, marks current
query back to \`pending\`, exits cleanly. - Unrecoverable auth failure
(Supabase 401) --- logs and exits.

\-\--

\## 7. Output Contract for Analytics

The analytics teammate has two options:

1\. \*\*Direct Supabase access\*\* (preferred for speed): use
\`supabase-py\` or a Postgres connection string to query
\`live_listings\`, \`sold_listings\`, \`listing_images\` directly. 2.
\*\*Static JSON export\*\*: call
\`exporter.export_query_to_json(query_id)\` or CLI \`python -m
grailed_scraper export \--query \"Guidi 788Z\" \> out.json\`. Output
shape matches \`FinalJSON.json\`:

\`\`\`json { \"metadata\": { \"query\": \"Guidi 788Z\", \"categories\":
\[\"menswear\", \"footwear\"\], \"scraped_at_unix\": 1713995645,
\"total_live_found\": 38, \"live_limit_requested\": 40,
\"sold_limit_requested\": 40 }, \"results\": \[ { \"live_listing\": {
/\* full Pydantic dump with image_urls rejoined \*/ },
\"sold_comparables\": \[ { /\* \... \*/ } \] } \] } \`\`\`

\-\--

\## 8. Configuration

\### Environment Variables (loaded via python-dotenv) \`\`\`
SUPABASE_URL=\... SUPABASE_SERVICE_ROLE_KEY=\... \# server-side only,
never committed CACHE_TTL_SEC=21600 \# 6 hours default LOG_LEVEL=INFO
\`\`\`

\### config.py Constants \`\`\`python LIVE_CAP = 40 SOLD_CAP_PER_LIVE =
40 MAX_CONCURRENCY = 2 REQUEST_DELAY_RANGE = (1.0, 2.0) \# seconds,
uniform jitter STALE_RUNNING_THRESHOLD = 1800 \# 30 min USER_AGENTS = \[
\... \] \# 3 real desktop UAs DEFAULT_SEED_QUERIES = \[ \"Guidi 788Z\",
\"Number (N)ine\", \"Rick Owens Ramones\", \# \... 10--20 hardcoded for
v1, teammate can insert more via Supabase directly \] \`\`\`

\### .gitignore Additions \`\`\` .env cache.db cache.db-journal \`\`\`

\-\--

\## 9. Testing

\### Unit Tests - \`test_parser.py\` --- fixtures of recorded
live-search, sold-search, and detail responses. Asserts parser produces
valid Pydantic models and raises \`SchemaValidationError\` on malformed
input. - \`test_models.py\` --- boundary cases (missing optional fields,
null shipping, empty image lists). - \`test_engine.py\` --- mocks
\`client\` and \`db_supabase\`, asserts state machine transitions
(\`pending -\> running -\> done\` and \`-\> failed\`).

\### Integration Smoke Test A CLI command \`python -m grailed_scraper
smoke\` runs one real user query end-to-end with \`LIVE_CAP=2\` and
\`SOLD_CAP_PER_LIVE=2\`. Used manually before the overnight run to catch
endpoint drift or schema changes.

\-\--

\## 10. Future Work --- Proxy Integration (v2)

Trigger condition: the v1 single-IP crawl produces sustained 429s that
tenacity cannot recover from, or the account gets Cloudflare-blocked.

\### Rollout Plan 1. Sign up for a residential rotating proxy provider.
Preferred candidates:  - Oxylabs (residential PAYG \~\$15/GB, enterprise
quality).  - IPRoyal (\~\$7/GB, cheapest reputable residential).  -
Smartproxy (\~\$7/GB, similar). 2. Add \`PROXY_URL\` env var (single
endpoint for rotating providers; they rotate IPs server-side per
request). 3. Patch \`client.py\`: pass \`proxy=settings.PROXY_URL\` to
\`httpx.AsyncClient\` when set. Zero other code changes required. 4.
Increase \`MAX_CONCURRENCY\` to 10--15 and drop \`REQUEST_DELAY_RANGE\`
to \`(0.1, 0.3)\` once proxy is stable. 5. Expected runtime drop: 2 hr
-\> 15--20 min for a 40-query night.

The interface is small on purpose: v1 runs without a proxy, v2 flips two
config values.

\-\--

\## 11. Runtime Estimates

\### Capacity (Supabase free tier, 500 MB cap) - 40 live + (40 × 40 =
1,600) sold = 1,640 rows per user query. - Average JSONB payload \~1.5
KB/row (image URLs offloaded to separate TEXT table). - With
sold-listing dedup (30--50% overlap across queries) and Postgres
indexes/bloat:  - 100 user queries ≈ 240 MB used (safe).  - 150 user
queries ≈ 300 MB used (safe).  - 200 user queries ≈ 470 MB used (near
cap). - Target for v1: 150 user queries, leaves 40% headroom.

\### Runtime (single-IP polite, no proxy) - \~50 requests/minute
sustained. - 40 user queries × 1,641 requests = 66k requests. - Raw
runtime: \~22 hours. - With cache hits from dedup (\~30%): \~15 hours. -
Realistic overnight delivery: \~30 user queries per night. - Full
150-query target: \~5 nights, or add proxies in v2 to collapse to one.

\### Egress (Supabase free tier, 2 GB/month) - Analytics pulling all
240k rows via supabase-py ≈ 370 MB. Fine unless re-pulled many times.

\-\--

\## 12. Open Questions Resolved

\| Question \| Resolution \|
\|\-\-\-\-\-\-\-\-\--\|\-\-\-\-\-\-\-\-\-\-\--\| \| Proxy provider? \|
None in v1. Oxylabs or IPRoyal if banned (see Section 10). \| \| Dedup
owner? \| Scraper handles via PK collision on upsert. Analytics dedupes
again defensively if needed. \| \| NLP / condition parsing? \| Cut
entirely. Scraper only persists raw \`description\`. \| \| Sold endpoint
access? \| Confirmed working without auth (tested). \| \| Output shape?
\| Matches \`FinalJSON.json\` exactly (nested results, not flat arrays).
\| \| SQL flavor? \| Postgres via Supabase. Local SQLite only for HTTP
cache. \| \| Seed queries? \| Hardcoded list in \`config.py\` for v1.
Teammate can insert more rows directly into \`user_queries\`. \| \|
Image URLs? \| Stored in separate \`listing_images\` TEXT table (cheaper
than JSONB array). \| \| Caps? \| 40 live × 40 sold per user query. \|

\-\--

\## 13. Acceptance Criteria

The scraper module is considered complete when:

1\. \`python -m grailed_scraper init-db\` creates all Supabase tables
and the RPC. 2. \`python -m grailed_scraper seed\` loads the default
query list into \`user_queries\`. 3. \`python -m grailed_scraper smoke\`
completes a 2×2 end-to-end run without error. 4. \`python -m
grailed_scraper run\` processes the full \`pending\` queue and survives
a simulated mid-run kill via \`python -m grailed_scraper resume\`. 5.
\`python -m grailed_scraper export \--query \"Guidi 788Z\"\` produces
JSON matching the \`FinalJSON.json\` shape exactly. 6. All three unit
test suites pass. 7. Analytics teammate can connect to Supabase and read
\`live_listings\` + \`sold_listings\` without scraper-side intervention.
