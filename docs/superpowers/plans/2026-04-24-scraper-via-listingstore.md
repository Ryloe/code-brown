# Grailed Scraper (ListingStore-backed) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement an async Grailed scraper that, given a query + categories, returns a `GrailedScrapeResult` and persists every live + sold listing through the already-injected `ListingStore`.

**Architecture:** One package (`scraper/`) split into `config`, `exceptions`, `parser` (pure raw→Pydantic), `client` (httpx + throttle + retry), and `scraper.py` (orchestrator + persistence). The scraper does NOT construct a database; it uses the `ListingStore` registered via `scraper.set_store()` from `backend/main.py`'s lifespan. Each call drives `live_search → live_detail → sold_search → sold_detail`, validates with the Pydantic models in `shared/models.py`, **persists ONLY sold listings** via the store, and returns the assembled `GrailedScrapeResult` to the caller. Live listings are always scraped fresh per call and never written to the store.

**Tech Stack:** Python 3.11+, `httpx[http2]`, `tenacity`, `pydantic` v2 (already present), `pytest`, `pytest-asyncio`, `respx` for HTTP mocking.

**Key deviations from `2026-04-24-grailed-scraper-design.md`:**
- No SQLite raw-HTTP cache. No `cache.db`. No `db_cache.py`.
- No `user_queries` / `live_listings` / `sold_listings` / `listing_images` Postgres tables. The single `public.listings` table from `supabase/migrations/20260424194700_init_listings.sql` is the only sink.
- No `claim_next_query` RPC, no `mark_done`, no resume queue. Caller (backend orchestrator) drives one query per call.
- No `exporter.py`, no `cli.py`. Scraper exposes a single async function; the backend reads listings back via `ListingStore.list_recent` if it needs them after the call.
- `ListingStore.save_listing` expects a `dict` containing `id` + `category` + the rest of the payload. Only `SoldListing.model_dump()` rows are saved. No `kind` field — every row in `public.listings` is a sold listing.
- `category` column gets the FIRST entry of `metadata.categories` (e.g. `"menswear"`). Full list stays inside the payload.
- Live listings are ephemeral. They are scraped, returned in `GrailedScrapeResult`, and discarded. No `_persist_live`. No live-listing dedup against the store.
- The store IS the sold-listing cache. Before fetching a sold detail, check `store.has_listing(sold_id)`; on hit, rebuild the `SoldListing` from `store.get_listing(sold_id)` and skip the network call. On miss, fetch + parse + persist.

---

## File Structure

**Create:**
- `scraper/config.py` — constants only (caps, delay range, UA list, timeouts, headers).
- `scraper/exceptions.py` — `GrailedRateLimitExceeded`, `SchemaValidationError`, `ScrapeAborted`.
- `scraper/parser.py` — pure functions: raw response dict → `LiveListing` / `SoldListing` / list of ids. No I/O.
- `scraper/client.py` — `GrailedClient` async class wrapping `httpx.AsyncClient` with throttle + tenacity retry.
- `scraper/tests/__init__.py` — empty.
- `scraper/tests/conftest.py` — pytest-asyncio config, fixture loader.
- `scraper/tests/fixtures/live_search.json`, `live_detail.json`, `sold_search.json`, `sold_detail.json` — recorded raw responses (engineer records once, then commits).
- `scraper/tests/test_parser.py` — fixture-driven parser tests.
- `scraper/tests/test_client.py` — `respx`-mocked client tests (throttle, retry, headers).
- `scraper/tests/test_scrape_query.py` — orchestration test with mocked client + in-memory store double.

**Modify:**
- `scraper/scraper.py` — add `scrape_query(...)` and `_persist_sold`. Keep existing `set_store`, `_get_store`, `save_listing`, `has_listing`.
- `scraper/__init__.py` — re-export `scrape_query`, `set_store`.
- `backend/requirements.txt` — add `httpx[http2]`, `tenacity`, `pytest`, `pytest-asyncio`, `respx`, `pydantic` (transitively present, but pin minor).

**Out of scope (do not create):** `cli.py`, `exporter.py`, `db_cache.py`, `db_supabase.py`, `engine.py`, `supabase/schema.sql`. Already covered by `backend/main.py` + existing migration.

---

## Task 1: Add dependencies + scaffold scraper subpackage

**Files:**
- Modify: `backend/requirements.txt`
- Create: `scraper/config.py`, `scraper/exceptions.py`, `scraper/tests/__init__.py`, `scraper/tests/conftest.py`

- [ ] **Step 1: Add deps**

Edit `backend/requirements.txt`:

```
fastapi>=0.115,<1
uvicorn[standard]>=0.32,<1
supabase>=2,<3
python-dotenv>=1,<2
httpx[http2]>=0.27,<1
tenacity>=9,<10
pytest>=8,<9
pytest-asyncio>=0.23,<1
respx>=0.21,<1
```

- [ ] **Step 2: Install**

Run: `pip install -r backend/requirements.txt`
Expected: all packages resolve, no errors.

- [ ] **Step 3: Create `scraper/config.py`**

```python
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
```

- [ ] **Step 4: Create `scraper/exceptions.py`**

```python
"""Scraper-specific exceptions."""

from __future__ import annotations


class ScraperError(Exception):
    """Base for all scraper errors."""


class GrailedRateLimitExceeded(ScraperError):
    """Raised after tenacity exhausts retries on HTTP 429."""


class SchemaValidationError(ScraperError):
    """Raised when a raw response cannot be parsed into the expected Pydantic model."""


class ScrapeAborted(ScraperError):
    """Raised when the caller-provided abort signal fires mid-run."""
```

- [ ] **Step 5: Create `scraper/tests/__init__.py`**

Empty file.

- [ ] **Step 6: Create `scraper/tests/conftest.py`**

```python
"""Shared pytest fixtures for scraper tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def load_fixture():
    def _load(name: str) -> dict:
        return json.loads((FIXTURES_DIR / name).read_text())

    return _load
```

Add `pyproject.toml` minimum if absent — check first:

Run: `test -f pyproject.toml && cat pyproject.toml || echo MISSING`

If MISSING, create a minimal one in repo root:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["scraper/tests"]
```

- [ ] **Step 7: Verify scaffold imports**

Run: `python -c "from scraper import config, exceptions; print(config.LIVE_CAP, exceptions.ScraperError)"`
Expected: `40 <class 'scraper.exceptions.ScraperError'>`

- [ ] **Step 8: Commit**

```bash
git add backend/requirements.txt scraper/config.py scraper/exceptions.py scraper/tests/__init__.py scraper/tests/conftest.py pyproject.toml
git commit -m "feat(scraper): scaffold config, exceptions, test harness"
```

---

## Task 2: Record fixture responses

**Files:**
- Create: `scraper/tests/fixtures/live_search.json`, `live_detail.json`, `sold_search.json`, `sold_detail.json`

The parser tests (Task 3) need real shapes to assert against. Without recorded fixtures, tests assert hallucinated shapes and the parser breaks against production. **Record these once before continuing.**

- [ ] **Step 1: Identify the four endpoints**

The scraper module owner already has the endpoints (see `2026-04-24-grailed-scraper-design.md` §12 — sold endpoint confirmed working without auth). Capture, in your terminal or a short Python REPL session, one example of each:
1. live search by query (returns list of live listing summaries — must include each listing's id and a URL or slug).
2. live listing detail (returns full payload for a single live id).
3. sold search by designer + name tokens (returns sold summaries with ids).
4. sold listing detail.

Use real, polite single-shot `httpx.get(...)` calls with the headers from `scraper/config.DEFAULT_HEADERS` plus one `User-Agent` from `config.USER_AGENTS`.

- [ ] **Step 2: Save responses verbatim**

For each endpoint, write the raw decoded JSON body into the matching fixture file:
- `scraper/tests/fixtures/live_search.json`
- `scraper/tests/fixtures/live_detail.json`
- `scraper/tests/fixtures/sold_search.json`
- `scraper/tests/fixtures/sold_detail.json`

Do not edit, prune, or re-shape the JSON. The whole point is fidelity. Strip nothing except obvious PII (none expected from public Grailed listings).

- [ ] **Step 3: Sanity print the keys at the top level of each**

Run:

```bash
python - <<'PY'
import json, pathlib
for p in pathlib.Path("scraper/tests/fixtures").glob("*.json"):
    data = json.loads(p.read_text())
    print(p.name, "->", list(data.keys()) if isinstance(data, dict) else f"list[{len(data)}]")
PY
```

Expected: each file prints either a dict's top-level keys or `list[N]`. **Write down what you see** — these key names drive the parser implementation in Task 3. If a fixture is empty or a Cloudflare block page, re-record it (and add a longer User-Agent rotation if needed).

- [ ] **Step 4: Commit**

```bash
git add scraper/tests/fixtures/
git commit -m "test(scraper): record raw Grailed response fixtures"
```

---

## Task 3: Parser — raw responses to Pydantic models

**Files:**
- Create: `scraper/parser.py`
- Create: `scraper/tests/test_parser.py`

The parser is pure: dict in, Pydantic model (or list of strings) out, `SchemaValidationError` on failure. Keys referenced below (`hits`, `data`, `description`, etc.) are placeholders — **substitute the actual keys you wrote down in Task 2 Step 3**.

- [ ] **Step 1: Write failing parser tests**

Create `scraper/tests/test_parser.py`:

```python
"""Parser tests. Asserts shape transformation, not network behavior."""

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


def test_parse_live_search_ids_returns_strings(load_fixture):
    raw = load_fixture("live_search.json")
    ids = parse_live_search_ids(raw)
    assert isinstance(ids, list)
    assert len(ids) > 0
    assert all(isinstance(i, str) and i for i in ids)


def test_parse_live_detail_returns_validated_model(load_fixture):
    raw = load_fixture("live_detail.json")
    listing = parse_live_detail(raw)
    assert isinstance(listing, LiveListing)
    assert listing.id
    assert listing.designer
    assert listing.price.listing_price_usd >= 0


def test_parse_sold_search_ids_returns_strings(load_fixture):
    raw = load_fixture("sold_search.json")
    ids = parse_sold_search_ids(raw)
    assert isinstance(ids, list)
    assert all(isinstance(i, str) and i for i in ids)


def test_parse_sold_detail_returns_validated_model(load_fixture):
    raw = load_fixture("sold_detail.json")
    listing = parse_sold_detail(raw)
    assert isinstance(listing, SoldListing)
    assert listing.sold_at_unix > 0
    assert listing.price.sold_price_usd >= 0


def test_parse_live_detail_raises_on_garbage():
    with pytest.raises(SchemaValidationError):
        parse_live_detail({"totally": "wrong"})


def test_parse_sold_detail_raises_on_garbage():
    with pytest.raises(SchemaValidationError):
        parse_sold_detail({"nope": True})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest scraper/tests/test_parser.py -v`
Expected: ImportError (`scraper.parser` doesn't exist).

- [ ] **Step 3: Implement `scraper/parser.py`**

Replace the placeholder key names below (`hits`, `id`, `data`, `description`, `cover_photo`, `sold_at`, etc.) with the actual keys observed in the Task 2 fixtures. The structure of the file does not change — only the key strings inside each `_extract_*` helper.

```python
"""Pure transformations from raw Grailed responses to Pydantic models.

No I/O. No state. Each function: dict in -> model out, or SchemaValidationError.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from scraper.exceptions import SchemaValidationError
from shared.models import (
    LivePrice,
    LiveListing,
    Seller,
    SellerBadges,
    SoldListing,
    SoldPrice,
)


def parse_live_search_ids(raw: dict) -> list[str]:
    """Extract live listing ids from a search response."""
    try:
        hits = raw["hits"]  # TODO: replace with the real top-level key
        return [str(h["id"]) for h in hits]
    except (KeyError, TypeError) as e:
        raise SchemaValidationError(f"live_search shape unexpected: {e}") from e


def parse_sold_search_ids(raw: dict) -> list[str]:
    """Extract sold listing ids from a search response."""
    try:
        hits = raw["hits"]  # TODO: replace with the real top-level key
        return [str(h["id"]) for h in hits]
    except (KeyError, TypeError) as e:
        raise SchemaValidationError(f"sold_search shape unexpected: {e}") from e


def parse_live_detail(raw: dict) -> LiveListing:
    """Build a validated LiveListing from a detail response."""
    try:
        return LiveListing(**_live_fields(raw))
    except (KeyError, TypeError, ValidationError) as e:
        raise SchemaValidationError(f"live_detail invalid: {e}") from e


def parse_sold_detail(raw: dict) -> SoldListing:
    """Build a validated SoldListing from a detail response."""
    try:
        fields = _live_fields(raw)
        fields["price"] = SoldPrice(
            sold_price_usd=int(raw["sold_price"]),
            shipping_price_usd=int(raw.get("shipping_price", 0)),
        )
        fields["sold_at_unix"] = int(raw["sold_at"])
        return SoldListing(**fields)
    except (KeyError, TypeError, ValidationError) as e:
        raise SchemaValidationError(f"sold_detail invalid: {e}") from e


# ---- internals ----


def _live_fields(raw: dict) -> dict[str, Any]:
    """Common live-shape fields (also reused for sold detail)."""
    return {
        "id": str(raw["id"]),
        "url": str(raw["url"]),
        "designer": _designer(raw),
        "name": str(raw.get("title") or raw.get("name") or ""),
        "size": str(raw.get("size") or ""),
        "condition_raw": str(raw.get("condition") or ""),
        "location": str(raw.get("location") or ""),
        "color": str(raw.get("color") or ""),
        "image_urls": _image_urls(raw),
        "description": str(raw.get("description") or ""),
        "price": LivePrice(
            listing_price_usd=int(raw.get("price") or 0),
            shipping_price_usd=int(raw.get("shipping_price") or 0),
        ),
        "seller": _seller(raw),
    }


def _designer(raw: dict) -> str:
    designers = raw.get("designers") or []
    if designers and isinstance(designers, list):
        first = designers[0]
        return str(first.get("name") if isinstance(first, dict) else first)
    return str(raw.get("designer") or "")


def _image_urls(raw: dict) -> list[str]:
    photos = raw.get("photos") or []
    out: list[str] = []
    for p in photos:
        if isinstance(p, dict):
            url = p.get("url") or p.get("src")
        else:
            url = p
        if url:
            out.append(str(url))
    return out


def _seller(raw: dict) -> Seller:
    s = raw.get("user") or raw.get("seller") or {}
    badges_raw = s.get("badges") or {}
    return Seller(
        seller_name=str(s.get("username") or s.get("seller_name") or ""),
        reviews_count=int(s.get("reviews_count") or 0),
        transactions_count=int(s.get("transactions_count") or 0),
        items_for_sale_count=int(s.get("items_for_sale_count") or 0),
        posted_at_unix=int(raw.get("posted_at") or s.get("posted_at_unix") or 0),
        badges=SellerBadges(
            verified=bool(badges_raw.get("verified", False)),
            trusted_seller=bool(badges_raw.get("trusted_seller", False)),
            quick_responder=bool(badges_raw.get("quick_responder", False)),
            speedy_shipper=bool(badges_raw.get("speedy_shipper", False)),
        ),
    )
```

**After substituting real keys**, all "TODO" comments must be removed.

- [ ] **Step 4: Run tests until they pass**

Run: `pytest scraper/tests/test_parser.py -v`
Expected: all 6 tests pass. If a model field still fails validation against the real fixture, narrow the discrepancy (which field, which value), then either patch `_live_fields`/`_seller` or coerce the value. Do **not** loosen the Pydantic models in `shared/models.py` — they are the contract.

- [ ] **Step 5: Commit**

```bash
git add scraper/parser.py scraper/tests/test_parser.py
git commit -m "feat(scraper): parser raw->Pydantic with fixture tests"
```

---

## Task 4: HTTP client — throttle + retry + headers

**Files:**
- Create: `scraper/client.py`
- Create: `scraper/tests/test_client.py`

- [ ] **Step 1: Write failing client tests**

Create `scraper/tests/test_client.py`:

```python
"""Client tests. respx mocks all HTTP."""

from __future__ import annotations

import httpx
import pytest
import respx

from scraper.client import GrailedClient
from scraper.exceptions import GrailedRateLimitExceeded


@pytest.mark.asyncio
@respx.mock
async def test_get_json_returns_decoded_body():
    route = respx.get("https://example.test/x").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    async with GrailedClient(delay_range=(0.0, 0.0)) as c:
        body = await c.get_json("https://example.test/x")
    assert body == {"ok": True}
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_get_json_sets_user_agent_and_referer():
    captured: dict = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        captured["ua"] = request.headers.get("user-agent")
        captured["ref"] = request.headers.get("referer")
        return httpx.Response(200, json={})

    respx.get("https://example.test/x").mock(side_effect=_capture)
    async with GrailedClient(delay_range=(0.0, 0.0)) as c:
        await c.get_json("https://example.test/x")
    assert captured["ua"]
    assert captured["ref"] == "https://www.grailed.com/"


@pytest.mark.asyncio
@respx.mock
async def test_get_json_retries_on_429_then_succeeds():
    route = respx.get("https://example.test/y").mock(
        side_effect=[
            httpx.Response(429),
            httpx.Response(200, json={"ok": 1}),
        ]
    )
    async with GrailedClient(delay_range=(0.0, 0.0), retry_wait_initial=0.01) as c:
        body = await c.get_json("https://example.test/y")
    assert body == {"ok": 1}
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_get_json_raises_after_429_exhaustion():
    respx.get("https://example.test/z").mock(return_value=httpx.Response(429))
    async with GrailedClient(
        delay_range=(0.0, 0.0), retry_wait_initial=0.01, max_429_attempts=2
    ) as c:
        with pytest.raises(GrailedRateLimitExceeded):
            await c.get_json("https://example.test/z")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest scraper/tests/test_client.py -v`
Expected: ImportError (`scraper.client` doesn't exist).

- [ ] **Step 3: Implement `scraper/client.py`**

```python
"""Async HTTP client with throttle + retry + UA rotation. No business logic."""

from __future__ import annotations

import asyncio
import random
from types import TracebackType
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from scraper.config import (
    DEFAULT_HEADERS,
    MAX_CONCURRENCY,
    REQUEST_DELAY_RANGE,
    REQUEST_TIMEOUT_SEC,
    USER_AGENTS,
)
from scraper.exceptions import GrailedRateLimitExceeded


class _RateLimited(Exception):
    """Internal. Raised on 429 to trigger tenacity retry."""


class _ServerError(Exception):
    """Internal. Raised on 5xx to trigger tenacity retry."""


class GrailedClient:
    """Wraps httpx.AsyncClient with one-call-per-jitter throttle + retry."""

    def __init__(
        self,
        *,
        delay_range: tuple[float, float] = REQUEST_DELAY_RANGE,
        max_concurrency: int = MAX_CONCURRENCY,
        timeout: float = REQUEST_TIMEOUT_SEC,
        retry_wait_initial: float = 30.0,
        max_429_attempts: int = 3,
        max_5xx_attempts: int = 3,
    ) -> None:
        self._delay_range = delay_range
        self._sem = asyncio.Semaphore(max_concurrency)
        self._timeout = timeout
        self._retry_wait_initial = retry_wait_initial
        self._max_429_attempts = max_429_attempts
        self._max_5xx_attempts = max_5xx_attempts
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "GrailedClient":
        self._client = httpx.AsyncClient(
            http2=True,
            timeout=self._timeout,
            headers=DEFAULT_HEADERS,
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        assert self._client is not None
        await self._client.aclose()
        self._client = None

    async def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        """GET url with retry + jitter. Returns decoded JSON."""
        try:
            async for attempt in AsyncRetrying(
                retry=retry_if_exception_type((_RateLimited, _ServerError)),
                wait=wait_exponential(multiplier=self._retry_wait_initial, max=120),
                stop=stop_after_attempt(
                    max(self._max_429_attempts, self._max_5xx_attempts)
                ),
                reraise=True,
            ):
                with attempt:
                    return await self._do_get(url, params)
        except RetryError as e:
            raise GrailedRateLimitExceeded(str(e)) from e
        except _RateLimited as e:
            raise GrailedRateLimitExceeded(str(e)) from e

    async def _do_get(self, url: str, params: dict[str, Any] | None) -> Any:
        assert self._client is not None
        headers = {"User-Agent": random.choice(USER_AGENTS)}
        async with self._sem:
            r = await self._client.get(url, params=params, headers=headers)
            await asyncio.sleep(random.uniform(*self._delay_range))
        if r.status_code == 429:
            raise _RateLimited(f"429 from {url}")
        if 500 <= r.status_code < 600:
            raise _ServerError(f"{r.status_code} from {url}")
        r.raise_for_status()
        return r.json()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest scraper/tests/test_client.py -v`
Expected: all 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scraper/client.py scraper/tests/test_client.py
git commit -m "feat(scraper): async http client with throttle, retry, UA rotation"
```

---

## Task 5: Sold-listing persistence helper in `scraper/scraper.py`

**Files:**
- Modify: `scraper/scraper.py`

Add a private helper that turns a `SoldListing` + category into the dict shape `ListingStore.save_listing` expects. Live listings are NOT persisted, so no live helper exists.

- [ ] **Step 1: Add helper (keep existing module-level singleton intact)**

Replace the contents of `scraper/scraper.py` with:

```python
"""Grailed scraper. Sold-listing persistence goes through ``ListingStore`` injected at boot.

Live listings are returned to the caller but never written to the store.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from shared.models import SoldListing

if TYPE_CHECKING:
    from shared.store import ListingStore

_store: "ListingStore | None" = None


def set_store(store: "ListingStore") -> None:
    """Called once from backend lifespan. Scraper must not construct the store."""
    global _store
    _store = store


def _get_store() -> "ListingStore":
    if _store is None:
        raise RuntimeError("ListingStore not configured; call set_store at app boot")
    return _store


def save_listing(listing: dict) -> None:
    """Upsert one sold-listing dict directly. Caller owns the shape."""
    _get_store().save_listing(listing)


def has_listing(item_id: str) -> bool:
    """Cheap existence check (used only for sold ids)."""
    return _get_store().has_listing(item_id)


def _to_sold_row(listing: SoldListing, *, category: str) -> dict:
    """Build the dict shape ListingStore.save_listing expects for a sold listing."""
    payload = listing.model_dump(mode="json")
    payload["category"] = category
    return payload


def _persist_sold(listing: SoldListing, *, category: str) -> None:
    _get_store().save_listing(_to_sold_row(listing, category=category))
```

- [ ] **Step 2: Verify import**

Run: `python -c "from scraper.scraper import _persist_sold, _to_sold_row; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add scraper/scraper.py
git commit -m "feat(scraper): sold-listing persistence helper, live stays ephemeral"
```

---

## Task 6: Orchestrator — `scrape_query`

**Files:**
- Modify: `scraper/scraper.py`
- Create: `scraper/tests/test_scrape_query.py`

`scrape_query` ties it all together: live search + live detail (always network), sold search (always network), sold detail (cache-first via store) → assemble `GrailedScrapeResult`. The store is **looked up via `_get_store()`** — backend already calls `set_store` in lifespan. Caller passes nothing store-related.

**Sold dedup contract:** for each sold id, call `store.has_listing(id)`. On hit, call `store.get_listing(id)`, strip the `category` key, validate into `SoldListing`. On miss, fetch detail, parse, persist. This is the only purpose of the store from the scraper's perspective.

The endpoint URL builders (`_live_search_url`, `_live_detail_url`, etc.) are stubbed below — fill them in with real URLs the same way you filled keys in Task 3.

- [ ] **Step 1: Write the orchestrator test**

Create `scraper/tests/test_scrape_query.py`:

```python
"""scrape_query orchestration test. Mocks the client; uses an in-memory store double."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

import scraper.scraper as scraper_mod
from shared.models import GrailedScrapeResult, LiveListing, SoldListing


class FakeStore:
    def __init__(self) -> None:
        self.saved: list[dict] = []
        self._by_id: dict[str, dict] = {}

    def save_listing(self, listing: dict) -> None:
        self.saved.append(listing)
        self._by_id[listing["id"]] = listing

    def has_listing(self, item_id: str) -> bool:
        return item_id in self._by_id

    def get_listing(self, item_id: str) -> dict | None:
        return self._by_id.get(item_id)


def _live(id_: str) -> LiveListing:
    return LiveListing.model_validate(
        {
            "id": id_,
            "url": f"https://www.grailed.com/listings/{id_}",
            "designer": "Guidi",
            "name": "788Z",
            "size": "43",
            "condition_raw": "Used",
            "location": "US",
            "color": "Black",
            "image_urls": ["https://img/1.jpg"],
            "price": {"listing_price_usd": 800, "shipping_price_usd": 20},
            "seller": {
                "seller_name": "x",
                "reviews_count": 1,
                "transactions_count": 1,
                "items_for_sale_count": 1,
                "posted_at_unix": 1,
                "badges": {
                    "verified": True,
                    "trusted_seller": False,
                    "quick_responder": False,
                    "speedy_shipper": False,
                },
            },
            "description": "d",
        }
    )


def _sold(id_: str) -> SoldListing:
    return SoldListing.model_validate(
        {
            **_live(id_).model_dump(mode="json"),
            "price": {"sold_price_usd": 700, "shipping_price_usd": 30},
            "sold_at_unix": 1700000000,
        }
    )


@pytest.mark.asyncio
async def test_scrape_query_persists_only_sold_and_returns_assembled_result():
    store = FakeStore()
    scraper_mod.set_store(store)

    fake_client = AsyncMock()
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None
    fake_client.get_json = AsyncMock()

    with (
        patch("scraper.scraper.GrailedClient", return_value=fake_client),
        patch("scraper.scraper.parse_live_search_ids", return_value=["L1", "L2"]),
        patch("scraper.scraper.parse_sold_search_ids", side_effect=[["S1"], ["S2"]]),
        patch(
            "scraper.scraper.parse_live_detail",
            side_effect=[_live("L1"), _live("L2")],
        ),
        patch(
            "scraper.scraper.parse_sold_detail",
            side_effect=[_sold("S1"), _sold("S2")],
        ),
    ):
        result = await scraper_mod.scrape_query(
            query="Guidi 788Z",
            categories=["menswear", "footwear"],
            live_limit=2,
            sold_limit=1,
        )

    assert isinstance(result, GrailedScrapeResult)
    assert result.metadata.query == "Guidi 788Z"
    assert result.metadata.total_live_found == 2
    assert result.metadata.live_limit_requested == 2
    assert result.metadata.sold_limit_requested == 1
    assert len(result.results) == 2
    assert result.results[0].live_listing.id == "L1"
    assert [s.id for s in result.results[0].sold_comparables] == ["S1"]
    assert [s.id for s in result.results[1].sold_comparables] == ["S2"]

    saved_ids = [row["id"] for row in store.saved]
    assert set(saved_ids) == {"S1", "S2"}, "only sold listings should be persisted"
    assert all(row["category"] == "menswear" for row in store.saved)
    assert all("kind" not in row for row in store.saved)


@pytest.mark.asyncio
async def test_scrape_query_uses_cached_sold_and_skips_detail_fetch():
    store = FakeStore()
    cached = _sold("S1")
    store.save_listing({**cached.model_dump(mode="json"), "category": "menswear"})
    store.saved.clear()  # ignore the seed for assertion purposes
    scraper_mod.set_store(store)

    fake_client = AsyncMock()
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None
    fake_client.get_json = AsyncMock()
    detail_spy = patch(
        "scraper.scraper.parse_sold_detail",
        side_effect=AssertionError("must not parse sold detail on cache hit"),
    )

    with (
        patch("scraper.scraper.GrailedClient", return_value=fake_client),
        patch("scraper.scraper.parse_live_search_ids", return_value=["L1"]),
        patch("scraper.scraper.parse_sold_search_ids", return_value=["S1"]),
        patch("scraper.scraper.parse_live_detail", side_effect=[_live("L1")]),
        detail_spy,
    ):
        result = await scraper_mod.scrape_query(
            query="x",
            categories=["menswear"],
            live_limit=1,
            sold_limit=1,
        )

    assert [s.id for s in result.results[0].sold_comparables] == ["S1"]
    assert store.saved == [], "cache hit must not re-persist"


@pytest.mark.asyncio
async def test_scrape_query_caps_live_results_at_limit():
    store = FakeStore()
    scraper_mod.set_store(store)

    fake_client = AsyncMock()
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None
    fake_client.get_json = AsyncMock()

    with (
        patch("scraper.scraper.GrailedClient", return_value=fake_client),
        patch(
            "scraper.scraper.parse_live_search_ids",
            return_value=[f"L{i}" for i in range(50)],
        ),
        patch("scraper.scraper.parse_sold_search_ids", return_value=[]),
        patch(
            "scraper.scraper.parse_live_detail",
            side_effect=[_live(f"L{i}") for i in range(50)],
        ),
    ):
        result = await scraper_mod.scrape_query(
            query="x", categories=["menswear"], live_limit=3, sold_limit=0
        )

    assert len(result.results) == 3
    assert store.saved == [], "no sold scraped, nothing should be persisted"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest scraper/tests/test_scrape_query.py -v`
Expected: AttributeError on `scraper_mod.scrape_query` or import errors.

- [ ] **Step 3: Append orchestrator to `scraper/scraper.py`**

Append (do not replace) to the bottom of `scraper/scraper.py`:

```python
import asyncio
import time
from urllib.parse import urlencode

from scraper.client import GrailedClient
from scraper.config import LIVE_CAP, SOLD_CAP_PER_LIVE
from scraper.parser import (
    parse_live_detail,
    parse_live_search_ids,
    parse_sold_detail,
    parse_sold_search_ids,
)
from shared.models import (
    GrailedResultRow,
    GrailedScrapeResult,
    LiveListing,
    ScrapeMetadata,
)


def _live_search_url(query: str) -> str:
    """Replace with the real search endpoint discovered during fixture recording."""
    return f"https://www.grailed.com/api/listings/search?{urlencode({'query': query})}"


def _live_detail_url(listing_id: str) -> str:
    return f"https://www.grailed.com/api/listings/{listing_id}"


def _sold_search_url(designer: str, name: str) -> str:
    return (
        "https://www.grailed.com/api/listings/sold?"
        + urlencode({"designer": designer, "q": name})
    )


def _sold_detail_url(listing_id: str) -> str:
    return f"https://www.grailed.com/api/listings/{listing_id}"


def _sold_from_cached_payload(payload: dict) -> SoldListing:
    """Rebuild a SoldListing from a cached store payload (strip the category key)."""
    data = {k: v for k, v in payload.items() if k != "category"}
    return SoldListing.model_validate(data)


async def _scrape_sold_for(
    client: GrailedClient,
    live: LiveListing,
    *,
    sold_limit: int,
    category: str,
) -> list[SoldListing]:
    if sold_limit <= 0:
        return []
    raw = await client.get_json(_sold_search_url(live.designer, live.name))
    ids = parse_sold_search_ids(raw)[:sold_limit]
    store = _get_store()
    sold: list[SoldListing] = []
    for sid in ids:
        if store.has_listing(sid):
            cached = store.get_listing(sid)
            if cached is not None:
                sold.append(_sold_from_cached_payload(cached))
                continue
        raw_detail = await client.get_json(_sold_detail_url(sid))
        listing = parse_sold_detail(raw_detail)
        _persist_sold(listing, category=category)
        sold.append(listing)
    return sold


async def scrape_query(
    *,
    query: str,
    categories: list[str],
    live_limit: int = LIVE_CAP,
    sold_limit: int = SOLD_CAP_PER_LIVE,
) -> GrailedScrapeResult:
    """Run one full scrape for one query.

    Live listings are scraped fresh and returned in the result. Sold listings
    are cache-first via the injected ListingStore: ids already in the store
    skip the detail fetch entirely. Newly fetched sold listings are persisted.
    """
    if not categories:
        raise ValueError("at least one category required")
    primary_category = categories[0]

    async with GrailedClient() as client:
        raw = await client.get_json(_live_search_url(query))
        live_ids = parse_live_search_ids(raw)[:live_limit]

        rows: list[GrailedResultRow] = []
        for lid in live_ids:
            raw_detail = await client.get_json(_live_detail_url(lid))
            live = parse_live_detail(raw_detail)
            comps = await _scrape_sold_for(
                client, live, sold_limit=sold_limit, category=primary_category
            )
            rows.append(GrailedResultRow(live_listing=live, sold_comparables=comps))

    return GrailedScrapeResult(
        metadata=ScrapeMetadata(
            query=query,
            categories=categories,
            live_limit_requested=live_limit,
            sold_limit_requested=sold_limit,
            scraped_at_unix=int(time.time()),
            total_live_found=len(rows),
        ),
        results=rows,
    )
```

- [ ] **Step 4: Run orchestrator tests until they pass**

Run: `pytest scraper/tests/test_scrape_query.py -v`
Expected: both tests pass.

- [ ] **Step 5: Run the full scraper test suite**

Run: `pytest scraper/tests/ -v`
Expected: all parser, client, and orchestrator tests pass.

- [ ] **Step 6: Commit**

```bash
git add scraper/scraper.py scraper/tests/test_scrape_query.py
git commit -m "feat(scraper): scrape_query orchestrator persists via ListingStore"
```

---

## Task 7: Re-export public surface

**Files:**
- Modify: `scraper/__init__.py`

- [ ] **Step 1: Update `scraper/__init__.py`**

```python
"""Grailed scraper package."""

from scraper.scraper import (
    has_listing,
    save_listing,
    scrape_query,
    set_store,
)

__all__ = ["has_listing", "save_listing", "scrape_query", "set_store"]
```

- [ ] **Step 2: Verify the public surface**

Run:

```bash
python -c "from scraper import scrape_query, set_store, has_listing, save_listing; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Verify backend still imports cleanly**

Run: `python -c "from backend.main import app; print('ok')"`
Expected: `ok` (no env vars are read until lifespan runs).

- [ ] **Step 4: Commit**

```bash
git add scraper/__init__.py
git commit -m "feat(scraper): export scrape_query from package root"
```

---

## Task 8: Smoke test against real Grailed

**Files:**
- Create: `scripts/scraper_smoke.py`

A one-shot script the engineer runs manually before the overnight crawl. Lives in `scripts/` (not `scraper/cli.py`) because we are intentionally not building a CLI.

- [ ] **Step 1: Create `scripts/scraper_smoke.py`**

```python
"""Hits real Grailed for ONE small query. Persists via the real ListingStore.

Run: python scripts/scraper_smoke.py
Requires: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY in env or .env.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scraper import scrape_query, set_store  # noqa: E402
from shared.store import ListingStore  # noqa: E402


async def _main() -> None:
    load_dotenv()
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    set_store(ListingStore(create_client(url, key)))

    result = await scrape_query(
        query="Guidi 788Z",
        categories=["menswear", "footwear"],
        live_limit=2,
        sold_limit=2,
    )
    print(json.dumps(result.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
```

- [ ] **Step 2: Run the smoke test**

Run: `python scripts/scraper_smoke.py`
Expected: prints a JSON document with `metadata` + 1–2 `results` entries, each with up to 2 `sold_comparables`. No tracebacks. Then verify in Supabase that 2–6 rows landed in `public.listings`.

If it fails:
- 4xx/5xx from Grailed → re-record fixtures, the parser keys may have drifted.
- ValidationError in the parser → narrow which field, fix in `_live_fields`/`_seller`, re-run tests.
- Supabase 401 → check `.env` matches `.env.example` shape and key has `service_role` privileges.

- [ ] **Step 3: Commit**

```bash
git add scripts/scraper_smoke.py
git commit -m "chore(scraper): add manual smoke script against real Grailed"
```

---

## Self-review checklist (run before handing off to executor)

- Spec coverage: §3.4 Pydantic models → use `shared/models.py` as-is (Task 3, 5, 6). §5 throttle/retry/UA rotation → Task 4. §6 resume → out of scope per user direction (caller drives). §7 output contract → `scrape_query` returns `GrailedScrapeResult` directly (Task 6). §3.1 Postgres tables → replaced by `public.listings` (existing). §3.3 SQLite cache → dropped; the store itself is the sold-listing cache.
- Placeholders: `_live_search_url` / `_live_detail_url` / `_sold_search_url` / `_sold_detail_url` and the parser key strings (`hits`, `id`, etc.) are explicit "fill from fixtures" points, not silent TODOs. Task 2 + Task 3 Step 3 require the engineer to substitute real values discovered during fixture recording. Acceptable because the spec confirms endpoints exist and were tested by the spec author.
- Type consistency: `_persist_sold(SoldListing, category=str)`. `_to_sold_row` returns `dict` matching `ListingStore.save_listing`'s contract. `_sold_from_cached_payload` is the inverse (drops `category`, validates back into `SoldListing`). Models imported from `shared.models` are the single source.
- Persistence scope: ONLY sold listings are written. Live listings are returned in `GrailedScrapeResult` and discarded. Sold listings are cache-first: `store.has_listing(sold_id)` short-circuits the network detail fetch via `store.get_listing(sold_id)`. Both behaviors asserted in Task 6 tests.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-24-scraper-via-listingstore.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
