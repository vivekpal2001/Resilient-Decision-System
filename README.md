# Resilient Decision System

I built this as a configurable workflow engine that can take any business decision request (like loan approval, vendor onboarding, etc), run it through a set of stages, evaluate rules, call external services, and return a clear decision with a full explanation of why.

The idea was to make something that doesn't just say "approved" or "rejected" — it tells you *exactly* which rules passed, which failed, and why.

---

## How to Run

```bash
# 1. create virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. install dependencies
pip install -r requirements.txt

# 3. start the server
python main.py
```

Server runs at: `http://localhost:8000`
Swagger UI (interactive docs): `http://localhost:8000/docs`

---

## Running Tests

```bash
source venv/bin/activate
python -m pytest tests/ -v
```

17 tests, all passing.

---

## All API Endpoints with Examples

### Health Check

```
GET /api/health
```

Response:
```json
{
  "status": "healthy",
  "timestamp": "2026-03-14T10:00:00Z",
  "workflows_loaded": 2
}
```

---

### Submit a Request (Loan Approval — Approved)

```
POST /api/requests
Content-Type: application/json
X-Idempotency-Key: loan-test-001
```

```json
{
  "workflow_id": "loan_approval",
  "data": {
    "applicant_name": "Vivek Kumar",
    "credit_score": 780,
    "annual_income": 120000,
    "loan_amount": 50000,
    "employment_status": "employed"
  }
}
```

Response:
```json
{
  "success": true,
  "request_id": "abc-123",
  "workflow_id": "loan_approval",
  "outcome": "APPROVED",
  "explanation": "=== Decision Report ===\nFinal Outcome: APPROVED\n...",
  "stage_outcomes": [],
  "decided_at": "2026-03-14T10:00:00Z"
}
```

---

### Submit a Request (Rejected — Unemployed)

```
POST /api/requests
Content-Type: application/json
```

```json
{
  "workflow_id": "loan_approval",
  "data": {
    "applicant_name": "Rahul Singh",
    "credit_score": 820,
    "annual_income": 0,
    "loan_amount": 50000,
    "employment_status": "unemployed"
  }
}
```

Response:
```json
{
  "success": false,
  "outcome": "REJECTED",
  "explanation": "Employment Status Check: employment_status is 'unemployed' ..."
}
```

---

### Submit a Request (Manual Review — Borderline Credit)

```
POST /api/requests
Content-Type: application/json
```

```json
{
  "workflow_id": "loan_approval",
  "data": {
    "applicant_name": "Priya Sharma",
    "credit_score": 640,
    "annual_income": 60000,
    "loan_amount": 30000,
    "employment_status": "employed"
  }
}
```

Response:
```json
{
  "success": false,
  "outcome": "MANUAL_REVIEW",
  "explanation": "Credit score 640 falls in moderate range — flagged for manual review"
}
```

---

### Get Request Status

```
GET /api/requests/{request_id}
```

Response:
```json
{
  "request": {
    "id": "abc-123",
    "workflow_id": "loan_approval",
    "status": "COMPLETED",
    "outcome": "APPROVED",
    "created_at": "2026-03-14T10:00:00Z"
  },
  "state_history": [
    { "from_state": "RECEIVED", "to_state": "VALIDATING", "reason": "Starting input validation" },
    { "from_state": "VALIDATING", "to_state": "EVALUATING", "reason": "Processing stages" },
    { "from_state": "EVALUATING", "to_state": "DECIDED", "reason": "Decision: APPROVED" },
    { "from_state": "DECIDED", "to_state": "COMPLETED", "reason": "Final outcome: APPROVED" }
  ]
}
```

---

### Get Decision Explanation (with Rule Trace)

```
GET /api/requests/{request_id}/decision
```

Response:
```json
{
  "request_id": "abc-123",
  "outcome": "APPROVED",
  "explanation": "=== Decision Report ===\nFinal Outcome: APPROVED\n\n[credit_evaluation]:\n  ✓ Excellent Credit: credit_score is 780, meets minimum of 750 → APPROVED",
  "rule_trace": [
    {
      "event_type": "RULE_EVALUATED",
      "stage_name": "credit_evaluation",
      "rule_name": "Excellent Credit",
      "reasoning": "✓ credit_score is 780, meets minimum of 750 → APPROVED"
    }
  ]
}
```

---

### Get Full Audit Trail

```
GET /api/requests/{request_id}/audit
```

Response:
```json
{
  "request_id": "abc-123",
  "total_events": 8,
  "audit_trail": [
    { "event_type": "REQUEST_RECEIVED", "reasoning": "New request for workflow 'loan_approval'" },
    { "event_type": "STATE_CHANGED", "reasoning": "Starting input validation" },
    { "event_type": "RULE_EVALUATED", "stage_name": "employment_check", "reasoning": "✓ Employment check passed" },
    { "event_type": "EXTERNAL_CALL", "stage_name": "credit_check", "reasoning": "External call to credit_bureau: success" },
    { "event_type": "DECISION_MADE", "reasoning": "Final outcome: APPROVED" }
  ],
  "state_history": [...]
}
```

---

### List All Workflows

```
GET /api/workflows
```

Response:
```json
{
  "total": 2,
  "workflows": [
    {
      "workflowId": "loan_approval",
      "name": "Loan Approval Workflow",
      "stages": [
        { "name": "field_validation", "type": "validation" },
        { "name": "credit_check", "type": "external_call" },
        { "name": "credit_evaluation", "type": "rule_evaluation" }
      ]
    },
    {
      "workflowId": "vendor_approval",
      "name": "Vendor Approval Workflow"
    }
  ]
}
```

---

### Get a Specific Workflow

```
GET /api/workflows/loan_approval
```

Returns the full workflow config JSON.

---

### Register a New Workflow (persisted to DB)

```
POST /api/workflows
Content-Type: application/json
```

```json
{
  "workflowId": "scholarship_approval",
  "name": "Scholarship Approval",
  "description": "Evaluates student scholarship applications",
  "version": "1.0.0",
  "inputSchema": {
    "required": ["student_name", "gpa"],
    "properties": {
      "student_name": { "type": "string" },
      "gpa": { "type": "number" }
    }
  },
  "stages": [
    {
      "name": "gpa_check",
      "type": "rule_evaluation",
      "rules": [
        { "name": "High GPA", "field": "gpa", "operator": ">=", "value": 3.5, "outcome": "APPROVED" },
        { "name": "Low GPA", "field": "gpa", "operator": "<", "value": 2.5, "outcome": "REJECTED" }
      ]
    },
    { "name": "final_decision", "type": "decision" }
  ]
}
```

Response:
```json
{
  "success": true,
  "message": "Workflow 'scholarship_approval' registered and persisted to DB",
  "persisted": true
}
```

> This workflow survives server restarts — it's saved in SQLite.

---

### Idempotency (Duplicate Request Detection)

Send the same request twice with the same `X-Idempotency-Key` header.

Second call response:
```json
{
  "outcome": "APPROVED",
  "_cached": true,
  "_message": "Duplicate request. Returning cached response."
}
```

---

### Recovery — Mark Stuck Requests as FAILED

```
POST /api/recover
Content-Type: application/json
```

```json
{
  "max_age_minutes": 5,
  "retry": false
}
```

Response:
```json
{
  "success": true,
  "mode": "mark_failed",
  "recovered_count": 1,
  "recovered_requests": [
    {
      "id": "abc-456",
      "previous_state": "EVALUATING",
      "retried": false,
      "new_outcome": "FAILED"
    }
  ]
}
```

---

### Recovery — Retry Stuck Requests (re-process them)

```
POST /api/recover
Content-Type: application/json
```

```json
{
  "max_age_minutes": 5,
  "retry": true
}
```

Response:
```json
{
  "success": true,
  "mode": "retry",
  "recovered_count": 1,
  "recovered_requests": [
    {
      "id": "abc-789",
      "previous_state": "EVALUATING",
      "retried": true,
      "new_outcome": "APPROVED"
    }
  ]
}
```

> **retry: true** means the system actually re-runs the workflow on the stuck request. You can verify this by checking the audit trail — it will have `RECOVERY_RETRY`, `RULE_EVALUATED`, `EXTERNAL_CALL`, and `DECISION_MADE` events.

---

### Test — Create a Stuck Request (for testing recovery)

```
POST /api/test/simulate-stuck
```

Response:
```json
{
  "success": true,
  "stuck_request_id": "abc-999",
  "status": "EVALUATING",
  "message": "Stuck request created. Call POST /api/recover to recover it."
}
```

---

## Project Structure

```
Resilient-Decision-System/
├── main.py                    # FastAPI app + all routes
├── requirements.txt
├── pytest.ini
│
├── config/
│   ├── config_loader.py       # loads workflows from JSON files + DB
│   └── workflows/
│       ├── loan-approval.json
│       └── vendor-approval.json
│
├── engine/
│   ├── rule_engine.py         # evaluates rules (12 operators)
│   ├── decision_maker.py      # picks final outcome from stage results
│   └── workflow_engine.py     # runs each stage in order
│
├── state/
│   └── __init__.py            # state machine (RECEIVED → COMPLETED)
│
├── audit/
│   └── __init__.py            # logs every event to DB
│
├── external/
│   └── __init__.py            # simulates external services + retry
│
├── db/
│   └── database.py            # SQLite setup, migrations, recovery
│
└── tests/
    └── test_system.py         # 17 tests
```

---

## Rule Operators Supported

| Operator | Example |
|----------|---------|
| `>=` | credit_score >= 750 |
| `<=` | loan_amount <= 500000 |
| `>` | annual_income > 50000 |
| `<` | debt_ratio < 0.4 |
| `==` | employment_status == "employed" |
| `!=` | employment_status != "unemployed" |
| `in` | country in ["US", "IN", "UK"] |
| `not_in` | status not_in ["blacklisted"] |
| `range` | credit_score range 550–749 |
| `regex` | email matches pattern |
| `exists` | field is present |
| `not_exists` | field is absent |
