# Hype Score — Design Spec

**Status:** approved, pending implementation plan
**Owner:** Oliver
**Last updated:** 2026-04-24
**Related:** SPEC.md (parent project — Grailed Arbitrage)

---

## 1. Summary

A standalone "hype score" feature that sits alongside the EV stack. Given a search term, it returns a numeric signal (with confidence and LLM narration) indicating whether the term is heating up on Reddit. Runs in parallel with the existing scrape → EV pipeline; not on the critical path.

Core bet: Reddit upvote-weighted mention velocity is a leading indicator for collectible/streetwear demand. We surface that signal next to EV so the reseller sees both "underpriced now" and "about to be hot."

---

## 2. Scope

**In scope (v1):**
- Per-search-term score (one number per query, not per listing).
- Reddit-only signal source.
- Subreddit allowlist of 6 fashion/resell subs.
- Fuzzy term matching via alias dictionary.
- Live baseline computation per query (no cache).
- LLM narration of the result.
- Standalone HTTP endpoint, called in parallel with the EV search by the frontend.

**Out of scope (v1):**
- Sentiment analysis (sarcasm breaks it; upvotes already encode validation).
- Google Trends / pytrends (flaky, scope down).
- Per-category or per-brand rollups (search-term-first; expand once signal is proven).
- Cross-platform signals (Twitter, TikTok, Discord).
- Caching layer (live every query; revisit only if latency forces it).
- LLM-based term expansion (alias dict for v1).
- Modifications to the orchestrator, EV calculator, or scraper.

---

## 3. Architecture

```
Frontend
  ├── POST /search     ──> Backend orchestrator ──> scraper + EV
  └── POST /hype       ──> Hype router (this spec)
                              │
                              ├── alias expand (T → variants)
                              ├── for each sub in ALLOWLIST (parallel):
                              │     PRAW search(query, time_filter='month')
                              ├── score (pure function)
                              └── LLM narrate
```

The frontend issues `/search` and `/hype` as two independent requests against the same backend process. The hype path does not block the EV path and vice versa. No orchestrator changes required.

---

## 4. Components

All under `hype/`, mounted as a router on the existing FastAPI app in `backend/main.py`.

### 4.1 `hype/aliases.py`

Holds the brand/term alias dictionary and the normalization function.

- `ALIASES: dict[str, list[str]]` — canonical term → known variants. Examples: `"bape": ["bape", "a bathing ape", "bathing ape"]`, `"stussy": ["stussy", "stüssy"]`, `"cdg": ["cdg", "comme des garcons", "comme des garçons"]`.
- `expand(term: str) -> list[str]` — lowercase, strip diacritics, look up in `ALIASES`, return list of search variants. If no entry, returns `[normalized_term]`.

Pure module. No I/O.

### 4.2 `hype/reddit.py`

Thin PRAW wrapper.

- `search_sub(subreddit: str, queries: list[str], time_filter: str = "month") -> list[Post]` — issues one search per query against the given sub, dedupes results by post ID, returns a list of `Post` (id, created_utc, score, subreddit, title).
- Reads Reddit OAuth credentials from env (`REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT`).
- Uses async PRAW (`asyncpraw`) so the orchestrator can `asyncio.gather` across subs.

### 4.3 `hype/score.py`

Pure function that turns posts into a score. No I/O, no PRAW imports — trivially unit-testable with fixture post lists.

```python
def score(posts_by_sub: dict[str, list[Post]], now: datetime) -> HypeResult
```

Algorithm (per sub, then aggregated):

1. **Weight each mention** by `weight = log(1 + max(0, post.score))`.
2. **Bucket by age** relative to `now`:
   - `last_24h`: posts where `now - created_utc <= 24h`
   - `prev_24h`: posts where `24h < now - created_utc <= 48h`
   - `baseline_14d`: posts where `48h < now - created_utc <= 14d`, split into 12 daily buckets for mean/std
3. **Per-sub velocity (z-score):**
   `velocity_s = (sum(last_24h_weights) - mean(daily_baseline_weights)) / std(daily_baseline_weights)`
   If `std == 0` (sparse sub), velocity = 0 for that sub.
4. **Per-sub acceleration:**
   `accel_s = (sum(last_24h_weights) - sum(prev_24h_weights)) / max(1, mean(daily_baseline_weights))`
5. **Aggregate across subs:** weighted mean of `velocity_s` and `accel_s`, weighted by per-sub total weighted volume over the 14d window. Subs with zero mentions contribute zero weight.
6. **Final score:** `score = 0.7 * agg_velocity + 0.3 * agg_accel`. Clipped to a presentable range (e.g. [-3, 5]).
7. **Confidence:** `confidence = "high" if total_mentions_14d >= 50 else "medium" if >= 20 else "low"`. Below 20 mentions, the score is suppressed and the result is marked as "insufficient signal."

`HypeResult` (pydantic, in `shared/models.py`):
```python
class HypeResult(BaseModel):
    term: str
    score: float | None      # null if insufficient signal
    confidence: Literal["high", "medium", "low", "insufficient"]
    evidence: HypeEvidence    # per-sub breakdown for narration + debugging
    narration: str            # filled by hype/narrate.py
```

`HypeEvidence` includes per-sub mention counts (24h / prev 24h / 14d), top 3 highest-upvoted posts in the last 24h (id, title, score, permalink), and the per-sub velocity/accel components.

### 4.4 `hype/narrate.py`

Single LLM call. Takes a `HypeResult` (without `narration`), returns a 1–3 sentence string.

- Prompt is fixed; receives the score, confidence, per-sub evidence, and top-upvoted post titles.
- Explicit instruction: "Do not invent numbers. Do not editorialize beyond what the evidence shows. If confidence is low, say so."
- Model: cheap/fast tier (Haiku or equivalent). This is on the request hot path.
- If confidence is `"insufficient"`, skip the LLM call entirely and return a fixed string ("Not enough Reddit activity in the last two weeks to call this one.").

### 4.5 `hype/api.py`

FastAPI router. One endpoint:

```
POST /hype
body: { "term": str }
response: HypeResult
```

Orchestration:
1. `variants = aliases.expand(term)`
2. `posts_by_sub = await asyncio.gather(*[reddit.search_sub(s, variants) for s in ALLOWLIST])`
3. `result = score.score(posts_by_sub, now=datetime.utcnow())`
4. `result.narration = await narrate.narrate(result)`
5. Return `result`.

Error handling: if Reddit returns an error or times out for a given sub, that sub contributes zero posts (score continues with the rest). If all subs fail, return a `HypeResult` with `confidence="insufficient"` and a narration explaining the upstream failure. No retries on the hot path.

### 4.6 `backend/main.py` change

Single line: mount `hype.api.router` on the FastAPI app. No other backend files touched.

---

## 5. Configuration

Env vars (read at startup):
- `REDDIT_CLIENT_ID`
- `REDDIT_CLIENT_SECRET`
- `REDDIT_USER_AGENT`
- `HYPE_SUBREDDIT_ALLOWLIST` — comma-separated, defaults to: `Grailed,streetwear,sneakers,Repsneakers,frugalmalefashion,malefashionadvice`
- `HYPE_LLM_MODEL` — defaults to a fast/cheap tier model id

---

## 6. Testing

- **`hype/aliases.py`** — unit tests on `expand()` for known brands, unknown terms, diacritic stripping.
- **`hype/score.py`** — unit tests with fixture post lists covering: empty input, single sub, all subs sparse, hot spike (high 24h, low baseline), steady-state (24h ≈ baseline), insufficient-signal gate, std=0 edge case.
- **`hype/reddit.py`** — integration test against real Reddit (one sub, one query), gated behind an env flag so CI doesn't hit the network.
- **`hype/api.py`** — end-to-end test with mocked `reddit.search_sub` and mocked LLM call, verifying response shape.

No mocking of `score.py` — it's a pure function, test it directly.

---

## 7. Rate-limit budget

- PRAW OAuth limit: 100 QPM.
- Per query: 6 subs × ~3 alias variants worst case = ~18 calls. Reddit's `search` accepts a single query string, so we issue one call per (sub, variant) pair.
- At 18 calls/query, sustained throughput cap is ~5 queries/minute before hitting the limit. Acceptable for demo and small-scale use. If a real workload exceeds this, the next move is the cache layer (deferred — see §2).

---

## 8. Failure modes and how we handle them

| Failure | Behavior |
|---------|----------|
| Reddit API down | All subs fail → return `confidence="insufficient"` with explanatory narration |
| Single sub errors | That sub contributes 0 posts; score computed from remaining subs |
| Term has no Reddit hits | `total_mentions_14d == 0` → `confidence="insufficient"`, narration is the canned fallback |
| LLM call fails | Return `HypeResult` with `narration=""` and a server log entry; frontend should render the score without prose |
| Rate limit hit | PRAW raises; the offending sub contributes 0 posts. Logged for ops awareness |

---

## 9. Open items deferred to v2

- Cache layer (per-term baseline, ~6h TTL).
- LLM-driven term expansion (replaces or augments the alias dict).
- Hybrid firehose+allowlist signal (allowlist weighted higher).
- Cross-platform signals.
- Per-category aggregation.
- Sentiment as a confidence dampener (not a score input).
