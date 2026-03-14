# Technical Decisions and Tradeoffs

These are the decisions I made while building this and why. Some were obvious, some took more thought.

---

## Language and Framework

**Python + FastAPI**.

FastAPI gives you auto-generated Swagger docs for free, async support out of the box, and Pydantic for request validation. I like that you define the input schema once and it handles validation, docs, and type checking all together.

Flask was an option but it's not async-first, and Django felt like overkill for an API-only project with no ORM needed.

---

## Database: SQLite

I picked SQLite mostly for simplicity. No separate process to run, no connection strings to configure, just a file. For the load this system will see in a hackathon/demo setting, it's more than enough.

**What I'd lose at scale:**
- No concurrent writes (SQLite has one writer at a time)
- No native JSON column type (I store JSON as TEXT)
- Single-node only

**Migration path:** Swap `aiosqlite` for `asyncpg`, update datetime SQL syntax, and everything else stays the same. The DB layer is isolated in `db/database.py`.

---

## Raw SQL vs ORM (SQLAlchemy)

I went with raw SQL. The queries are simple — inserts, selects, updates. Using an ORM here would add a layer of abstraction without much benefit. Also makes debugging easier — I can just log the SQL and immediately see what's happening.

---

## All Routes in `main.py`

I put all 10 routes in one file. For this many routes, splitting into separate files would add complexity without benefit. If this grew to 30+ routes, I'd use `APIRouter` and split by domain (requests/, workflows/, admin/).

---

## Idempotency: In-Memory Dict

Idempotency keys are stored in a Python dict in memory. Fast lookup, zero DB queries. The downside is they're lost on server restart — send the same key after a restart and it'll be processed again.

The `idempotency_keys` DB table exists in the schema for a future migration if persistence matters. Wiring it up would take maybe 20 lines of code.

---

## Workflow Configs: JSON Files + DB

Built-in workflows (`loan_approval`, `vendor_approval`) are JSON files in `config/workflows/`. They load on startup, they're version-controlled in git, and changing them is just editing a file.

But if someone registers a workflow via `POST /api/workflows`, that needs to survive restarts too. So I added a `workflows` table in SQLite. On startup, the config loader first reads JSON files, then loads DB-registered workflows. Both go into the same in-memory dict.

This hybrid approach works well — files for stability, DB for flexibility.

---

## External Services: Simulated

The credit bureau, identity check, compliance check — they're all simulated with configurable failure rates and latency. This isn't ideal for production but it lets me test retry logic, failure handling, and latency behavior without depending on real APIs.

Each service has a `failureRate` (0.05 to 0.15) and a `latencyMs`. The retry logic uses exponential backoff: 200ms → 400ms → 800ms.

---

## Recovery: Retry vs Mark-Failed

When the server crashes mid-request, the request is stuck in a non-terminal state in the DB. On the next startup, `recover_stale_requests()` finds these and handles them.

I have two modes:
- **Retry** (default on startup): Re-run the request through the workflow engine from scratch
- **Mark-failed**: Just stamp it as FAILED

I chose retry-from-scratch over resume-from-stage because resume would require tracking which stages completed and which didn't — more state, more complexity. Starting fresh is simpler and gives a consistent result.

One tradeoff: if a request crashed after calling the credit bureau, retry will call it again. I accepted this because the external calls are idempotent by design in this system.

---

## Synchronous Processing

Requests are processed inline — client sends request, waits for result, gets it back. No queues, no webhooks.

This works because the full workflow (including external calls with retries) takes under 2 seconds. If external calls regularly took 10+ seconds, I'd switch to async processing with a task queue (Celery or RQ) and a webhook callback.

---

## Rule Engine Design

The rule engine is a dict of lambdas — one per operator. Adding a new operator is literally one line:

```python
'starts_with': lambda v, t, _: str(v).startswith(t),
```

Each rule evaluation produces a human-readable reasoning string like "✓ credit_score is 780, meets minimum of 750 → APPROVED". This makes the audit trail actually readable instead of just true/false values.

---

## What I'd Do Differently in Production

1. Postgres instead of SQLite (concurrent writes, JSON columns)
2. DB-backed idempotency with TTL
3. JWT or API key auth
4. Rate limiting per client
5. Structured JSON logging + distributed tracing
6. Celery/RQ for long-running workflows
7. Stage-level resume in recovery (skip stages that already completed)
