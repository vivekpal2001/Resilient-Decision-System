# System Architecture

## What This System Does

At a high level — a request comes in, the system pulls the right workflow config (a JSON file), runs it through a series of stages (validation → external API calls → rule evaluation), and produces a final decision like APPROVED, REJECTED, or MANUAL_REVIEW.

Every step is tracked. Every rule evaluation is logged. If the server crashes mid-request, it recovers automatically on next startup.

---

## How a Request Flows Through the System

```
Client
  │
  │  POST /api/requests
  ▼
FastAPI (main.py)
  │  ← checks idempotency key
  │  ← creates request record in DB (status: RECEIVED)
  │  ← logs REQUEST_RECEIVED to audit
  ▼
Workflow Engine
  │  ← reads stages from workflow config
  │
  ├── [Validation Stage]
  │     checks required fields, types
  │     → transitions to EVALUATING on pass
  │
  ├── [External Call Stage]
  │     calls credit_bureau / identity_check with retry
  │     exponential backoff: 200ms → 400ms → 800ms
  │
  ├── [Rule Evaluation Stage]
  │     runs each rule through Rule Engine
  │     logs RULE_EVALUATED for every single rule
  │
  └── [Decision Stage]
        Decision Maker collects all stage outcomes
        priority: REJECTED > MANUAL_REVIEW > APPROVED
  │
  ▼
State Machine
  │  DECIDED → COMPLETED or MANUAL_REVIEW
  ▼
Response to client (with explanation)
```

---

## Modules

### `main.py`
FastAPI app. All routes are here. Handles idempotency (in-memory dict), request logging middleware, and wires up all the other modules on startup.

### `engine/workflow_engine.py`
The main orchestrator. Takes `(request_id, workflow_id, input_data)` and runs all stages in sequence. If any required stage fails, it stops and marks the request as FAILED. Uses dependency injection — gets config_loader, state_machine, audit_logger from constructor.

### `engine/rule_engine.py`
Evaluates a list of rules against input data. Has a dict of 12 operators (each is a small lambda). For every rule, produces a human-readable reasoning string like "✓ credit_score is 780, meets minimum of 750 → APPROVED". Mandatory rules halt evaluation early if they fail.

### `engine/decision_maker.py`
Gets all stage results and resolves the final outcome. Priority: REJECTED > MANUAL_REVIEW > APPROVED. Also builds the full text decision report.

### `state/__init__.py`
State machine with hardcoded valid transitions. Throws an error for invalid transitions. Every transition is persisted to `state_history` table.

Valid transitions:
```
RECEIVED → VALIDATING
VALIDATING → EVALUATING or FAILED
EVALUATING → DECIDED, FAILED, or RETRYING
DECIDED → COMPLETED or MANUAL_REVIEW
FAILED → RETRYING
```

### `audit/__init__.py`
Logs everything. Every rule eval, every state change, every external call, every decision — goes into the `audit_logs` table with JSON snapshots of inputs and outputs.

### `external/__init__.py`
Simulates 4 external services (credit bureau, document verification, identity check, compliance). Each has a configurable failure rate and latency. The `call_with_retry()` method does exponential backoff retries automatically.

### `config/config_loader.py`
Loads workflows in two passes:
1. Reads all `.json` files from `config/workflows/` at startup
2. Loads any workflows saved to the `workflows` DB table (these come from `POST /api/workflows`)

When you register a new workflow via API, it's saved to both memory and DB — so it survives server restarts.

### `db/database.py`
Async SQLite using aiosqlite. Runs migrations on every startup (CREATE TABLE IF NOT EXISTS). Includes `recover_stale_requests()` which finds stuck requests and either retries them or marks them FAILED.

---

## Database Tables

| Table | What it stores |
|-------|----------------|
| `requests` | Every incoming request — id, workflow_id, input data, status, outcome |
| `state_history` | Every state transition with from/to/reason and timestamp |
| `audit_logs` | Every event: rules, external calls, errors, decisions — with JSON snapshots |
| `workflows` | Workflow configs registered via API (persisted so they survive restarts) |
| `idempotency_keys` | Reserved for future DB-backed idempotency (currently in-memory) |

---

## Recovery

On every server startup, recovery runs automatically:

1. Finds all requests stuck in non-terminal states (`RECEIVED`, `VALIDATING`, `EVALUATING`, `RETRYING`) older than 5 minutes
2. Resets them to `RECEIVED` and re-processes through the workflow engine
3. Logs `RECOVERY_RETRY` event in audit trail

You can also trigger recovery manually via `POST /api/recover`:
- `"retry": true` — re-processes the request (gets a real outcome)
- `"retry": false` — just stamps as FAILED

The reason I chose retry-from-scratch over resume-from-stage is simplicity — resuming requires tracking which stages completed, which adds complexity. Re-running is cleaner and guarantees consistent state.

---

## Why SQLite

No setup, no separate process, zero config. For a hackathon with moderate load, it works fine. The repository pattern in `db/database.py` means swapping to Postgres later is a small change — just replace `aiosqlite` with `asyncpg` and fix datetime functions.
