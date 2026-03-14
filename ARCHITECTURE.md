# System Architecture

## Overview

The system is a configurable decision engine that processes requests through a series of stages defined in JSON workflow configs. It validates input, calls external services, evaluates rules, and produces a final decision with a human-readable explanation.

## High-Level Flow

```
Client Request
     │
     ▼
┌──────────┐
│ FastAPI   │  ← idempotency check, input parsing
│ (main.py) │
└────┬─────┘
     │
     ▼
┌──────────────────┐
│ Workflow Engine   │  ← loads config, runs stages in sequence
└────┬─────────────┘
     │
     ├──→ Validation Stage     → checks required fields + types
     ├──→ External Call Stage  → calls service simulator w/ retry
     ├──→ Rule Evaluation Stage → runs rules through rule engine
     └──→ Decision Stage       → placeholder (handled by decision maker)
     │
     ▼
┌──────────────────┐
│ Decision Maker   │  ← collects stage outcomes, picks final result
└────┬─────────────┘    REJECTED > MANUAL_REVIEW > APPROVED
     │
     ▼
  Response (with full explanation)
```

## Module Breakdown

### API Layer (`main.py`)
FastAPI app. Handles routing, idempotency (in-memory dict), request logging middleware. All routes live here for simplicity.

### Workflow Engine (`engine/workflow_engine.py`)
Core orchestrator. Takes a request + workflow config, runs each stage sequentially. Manages state transitions and audit logging at every step. If a required stage fails, it short-circuits.

### Rule Engine (`engine/rule_engine.py`)
Evaluates a list of rules against input data. Supports 12 operators (>=, <=, range, regex, etc). Each rule produces a human-readable reasoning string with ✓/✗/· indicators. Mandatory rules can halt evaluation early.

### Decision Maker (`engine/decision_maker.py`)
Takes all stage results and determines the final outcome using priority ordering. Also generates the full decision report text.

### State Machine (`state/__init__.py`)
Enforces valid lifecycle transitions (RECEIVED → VALIDATING → EVALUATING → DECIDED → COMPLETED). Invalid transitions raise errors. Every transition is persisted to `state_history` table.

### Audit Logger (`audit/__init__.py`)
Records every event: state changes, rule evaluations, external calls, errors, final decisions. Stored in `audit_logs` table with JSON snapshots of inputs/outputs.

### External Service Simulator (`external/__init__.py`)
Simulates external API calls (credit bureau, identity verification, etc) with configurable latency and failure rates. Includes retry with exponential backoff.

### Config Loader (`config/config_loader.py`)
Loads workflow JSON files from `config/workflows/` on startup. Also supports runtime registration via API.

### Database (`db/database.py`)
Async SQLite via aiosqlite. Runs schema migrations on startup. Includes `recover_stale_requests()` to handle crash recovery — finds requests stuck in non-terminal states and marks them as FAILED.

## Database Schema

```
requests          ← main table: id, workflow_id, input_data, status, outcome
state_history     ← every state transition with from/to/reason
audit_logs        ← all events: rules, external calls, errors, decisions
idempotency_keys  ← reserved for DB-backed idempotency (currently in-memory)
```

## State Machine Diagram

```
RECEIVED → VALIDATING → EVALUATING → DECIDED → COMPLETED
              │              │           │
              ▼              ▼           ▼
            FAILED ←──── RETRYING   MANUAL_REVIEW
```

- Terminal states: COMPLETED, MANUAL_REVIEW, FAILED
- FAILED can transition to RETRYING (for future retry support)

## Recovery Mechanism

On server startup, `recover_stale_requests()` runs automatically:
1. Finds requests in non-terminal states with `updated_at` older than 5 minutes
2. Marks them as FAILED with a recovery explanation
3. Logs a RECOVERY audit event

This handles the case where the server crashed mid-processing — the request was saved to DB but never reached a terminal state.
