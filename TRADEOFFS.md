# Technical Tradeoffs

## Why Python + FastAPI

| Consideration | Choice | Reasoning |
|---------------|--------|-----------|
| Language | Python over Node.js | Type hints via Pydantic, better readability for decision logic, native async support |
| Framework | FastAPI over Flask/Django | Auto-generated OpenAPI docs, async-first, request validation baked in |
| Database | SQLite over Postgres | Zero setup, single-file DB, good enough for this workload. Easy to swap later |
| ORM | Raw SQL over SQLAlchemy | Fewer abstractions, full control over queries, simpler debugging |
| Testing | pytest over unittest | Async fixtures, cleaner syntax, better assertion introspection |

## Architecture Decisions

### 1. Single-file API (`main.py`) vs Router Split

**Chose:** Single file with all routes.

**Why:** ~10 routes total. Splitting into separate router files adds complexity without benefit at this scale. If this grows past 20+ routes, use `APIRouter` and split by domain (requests, workflows, admin).

### 2. In-memory Idempotency vs DB-backed

**Chose:** In-memory dictionary.

**Why:** Simpler, faster lookups. Tradeoff is that keys are lost on restart. The `idempotency_keys` table exists in the schema for future migration to DB-backed if persistence matters.

### 3. External Service Simulation vs Real Calls

**Chose:** Simulated services with configurable failure/latency.

**Why:** No real external APIs to call — simulation lets us test retry logic, failure handling, and latency without network dependencies. Each service has tunable `failureRate` and `latencyMs`.

### 4. SQLite vs Postgres

**Chose:** SQLite.

**Pros:**
- Zero config, embedded in the app
- Works offline, no separate process
- Good for ~1000 req/sec at this data size

**Cons:**
- No concurrent writes (WAL mode helps but has limits)
- No JSON column type (we store JSON as TEXT)
- Single-node only

**Migration path:** Swap `aiosqlite` for `asyncpg`, update SQL syntax (mainly datetime functions), everything else stays the same.

### 5. Workflow Config as JSON Files vs DB

**Chose:** JSON files loaded at startup + runtime API registration.

**Why:** Workflows change infrequently. Files are version-controllable (git), easy to review in PRs, and don't need a DB migration to update. Runtime registration via API handles dynamic use cases.

**Tradeoff:** API-registered workflows are in-memory only — lost on restart. Could persist to DB if needed.

### 6. Synchronous Processing vs Queue-based

**Chose:** Synchronous (process request inline, return result).

**Why:** Decision latency is < 1 second even with external call retries. Queue-based (Celery, RQ) adds operational complexity for no real gain here.

**When to switch:** If external calls take > 5 seconds or you need to handle 100+ concurrent requests, move to a task queue with webhook callbacks.

### 7. Recovery Strategy

**Chose:** Time-based stale request detection.

**How:** On startup (and via API), find requests stuck in non-terminal states for > 5 minutes and mark as FAILED.

**Alternative considered:** Transaction-based (wrap entire workflow in a DB transaction). Rejected because external calls can't be rolled back — if we call credit_bureau and then crash, we can't "undo" that call. Better to detect and recover.

### 8. Rule Engine Design

**Chose:** Lambda-based operator map with human-readable reasoning.

**Why:** Adding a new operator = adding one lambda. Each rule evaluation produces a reasoning string that explains *why* it passed/failed in plain English. This makes debugging and auditing much easier vs opaque true/false results.

**Tradeoff:** The reasoning generation code is verbose (~40 lines of string formatting). Worth it for auditability.

## What I'd Change in Production

1. **DB:** Switch to Postgres for concurrent writes and proper JSON columns
2. **Idempotency:** Move to DB-backed with TTL expiration
3. **Auth:** Add JWT or API key authentication
4. **Rate limiting:** Add per-client rate limits
5. **Monitoring:** Add structured logging (JSON), health metrics, request tracing
6. **Config:** Store workflows in DB with versioning, keep JSON files as seed data
7. **Queue:** Add Celery/RQ for workflows with slow external calls
