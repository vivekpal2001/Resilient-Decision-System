# Resilient Decision System (Python)

A configurable workflow decision platform built with **FastAPI + SQLite**.

## Quick Start

```bash
cd python
source venv/bin/activate
python main.py
```

Server runs at `http://localhost:8000`  
Swagger docs at `http://localhost:8000/docs`

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Health check |
| POST | `/api/requests` | Submit workflow request |
| GET | `/api/requests/:id` | Request status + state history |
| GET | `/api/requests/:id/decision` | Decision explanation + rule trace |
| GET | `/api/requests/:id/audit` | Full audit trail |
| GET | `/api/workflows` | List all workflows |
| GET | `/api/workflows/:id` | Get workflow config |
| POST | `/api/workflows` | Register new workflow |
| POST | `/api/recover` | Recover stale requests |

## Example Request

```bash
curl -X POST http://localhost:8000/api/requests \
  -H "Content-Type: application/json" \
  -H "X-Idempotency-Key: test-001" \
  -d '{
    "workflow_id": "loan_approval",
    "data": {
      "applicant_name": "Vivek Kumar",
      "credit_score": 780,
      "annual_income": 120000,
      "loan_amount": 50000,
      "employment_status": "employed"
    }
  }'
```

## Running Tests

```bash
source venv/bin/activate
python -m pytest tests/ -v
```

## Project Structure

```
python/
├── main.py                  # FastAPI app + all routes
├── config/
│   ├── config_loader.py     # JSON workflow loader
│   └── workflows/           # Workflow JSON configs
├── engine/
│   ├── rule_engine.py       # 12 operators + explanations
│   ├── decision_maker.py    # Outcome resolution
│   └── workflow_engine.py   # Stage orchestration
├── state/                   # State machine
├── audit/                   # Audit logger
├── external/                # Service simulator + retry
├── db/
│   └── database.py          # SQLite + transactions + recovery
└── tests/
    └── test_system.py       # 17 tests
```

## Key Features

- **12 rule operators**: `>=`, `<=`, `>`, `<`, `==`, `!=`, `in`, `not_in`, `range`, `regex`, `exists`, `not_exists`
- **Human-readable explanations**: ✓/·/✗ indicators with clear reasoning
- **Idempotency**: Duplicate requests return cached responses
- **Partial save recovery**: Transactions + auto-recovery on startup
- **Full audit trail**: Every event logged for compliance
- **Configurable workflows**: JSON-driven, no code changes needed
