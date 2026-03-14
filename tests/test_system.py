"""
Tests for the Resilient Decision System (Python version).
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport


@pytest_asyncio.fixture
async def client():
    """Create a test client with a fresh in-memory database."""
    import aiosqlite
    from main import app
    from db.database import run_migrations

    test_db = await aiosqlite.connect(":memory:")
    test_db.row_factory = aiosqlite.Row
    await run_migrations(test_db)

    import main
    main.db = test_db
    from state import StateMachine
    from audit import AuditLogger
    from engine.workflow_engine import WorkflowEngine
    main.state_machine = StateMachine(test_db)
    main.audit_logger = AuditLogger(test_db)
    main.workflow_engine = WorkflowEngine(main.config_loader, main.state_machine, main.audit_logger)
    main.idempotency_cache.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    await test_db.close()


@pytest.mark.asyncio
async def test_health_check(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["workflows_loaded"] == 2


@pytest.mark.asyncio
async def test_list_workflows(client):
    resp = await client.get("/api/workflows")
    assert resp.status_code == 200
    assert resp.json()["total"] == 2


@pytest.mark.asyncio
async def test_get_workflow(client):
    resp = await client.get("/api/workflows/loan_approval")
    assert resp.status_code == 200
    assert resp.json()["workflowId"] == "loan_approval"


@pytest.mark.asyncio
async def test_loan_approved_excellent_credit(client):
    resp = await client.post("/api/requests", json={
        "workflow_id": "loan_approval",
        "data": {
            "applicant_name": "John Doe", "credit_score": 780,
            "annual_income": 120000, "loan_amount": 50000, "employment_status": "employed",
        }
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["success"] is True
    assert data["outcome"] == "APPROVED"


@pytest.mark.asyncio
async def test_loan_rejected_poor_credit(client):
    resp = await client.post("/api/requests", json={
        "workflow_id": "loan_approval",
        "data": {
            "applicant_name": "Jane Smith", "credit_score": 420,
            "annual_income": 25000, "loan_amount": 200000, "employment_status": "unemployed",
        }
    })
    assert resp.status_code == 201
    assert resp.json()["outcome"] == "REJECTED"


@pytest.mark.asyncio
async def test_loan_manual_review_moderate_credit(client):
    resp = await client.post("/api/requests", json={
        "workflow_id": "loan_approval",
        "data": {
            "applicant_name": "Bob Wilson", "credit_score": 650,
            "annual_income": 80000, "loan_amount": 30000, "employment_status": "employed",
        }
    })
    assert resp.status_code == 201
    assert resp.json()["outcome"] == "MANUAL_REVIEW"


@pytest.mark.asyncio
async def test_missing_required_fields(client):
    resp = await client.post("/api/requests", json={
        "workflow_id": "loan_approval",
        "data": {"applicant_name": "Missing Fields"}
    })
    assert resp.status_code == 201
    assert resp.json()["outcome"] in ("REJECTED", "FAILED")


@pytest.mark.asyncio
async def test_unknown_workflow(client):
    resp = await client.post("/api/requests", json={
        "workflow_id": "does_not_exist", "data": {"foo": "bar"}
    })
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_idempotency_returns_cached(client):
    body = {
        "workflow_id": "loan_approval",
        "data": {
            "applicant_name": "Idem Test", "credit_score": 780,
            "annual_income": 100000, "loan_amount": 50000, "employment_status": "employed",
        }
    }
    headers = {"X-Idempotency-Key": "test-idem-001"}
    resp1 = await client.post("/api/requests", json=body, headers=headers)
    resp2 = await client.post("/api/requests", json=body, headers=headers)
    assert resp1.status_code == 201
    assert resp2.status_code == 200
    assert resp2.json()["_cached"] is True
    assert resp1.json()["request_id"] == resp2.json()["request_id"]


@pytest.mark.asyncio
async def test_request_status_and_audit(client):
    resp = await client.post("/api/requests", json={
        "workflow_id": "loan_approval",
        "data": {
            "applicant_name": "Audit Test", "credit_score": 780,
            "annual_income": 100000, "loan_amount": 30000, "employment_status": "employed",
        }
    })
    req_id = resp.json()["request_id"]

    status_resp = await client.get(f"/api/requests/{req_id}")
    assert status_resp.status_code == 200
    assert status_resp.json()["request"]["status"] in ("COMPLETED", "MANUAL_REVIEW")

    decision_resp = await client.get(f"/api/requests/{req_id}/decision")
    assert decision_resp.status_code == 200
    assert "rule_trace" in decision_resp.json()

    audit_resp = await client.get(f"/api/requests/{req_id}/audit")
    assert audit_resp.status_code == 200
    assert audit_resp.json()["total_events"] > 0
    event_types = [e["event_type"] for e in audit_resp.json()["audit_trail"]]
    assert "STATE_CHANGED" in event_types
    assert "DECISION_MADE" in event_types


@pytest.mark.asyncio
async def test_simulate_and_recover(client):
    resp = await client.post("/api/test/simulate-stuck")
    assert resp.status_code == 201
    stuck_id = resp.json()["stuck_request_id"]

    recover_resp = await client.post("/api/recover", json={"max_age_minutes": 5})
    assert recover_resp.status_code == 200
    data = recover_resp.json()
    assert data["recovered_count"] >= 1
    assert any(r["id"] == stuck_id for r in data["recovered_requests"])


@pytest.mark.asyncio
async def test_vendor_approved(client):
    resp = await client.post("/api/requests", json={
        "workflow_id": "vendor_approval",
        "data": {
            "company_name": "Acme Corp", "registration_number": "REG-12345",
            "annual_revenue": 500000, "years_in_business": 5,
            "country": "US", "tax_compliant": True,
        }
    })
    assert resp.status_code == 201
    assert resp.json()["outcome"] == "APPROVED"


def test_rule_engine_operators():
    from engine.rule_engine import RuleEngine
    engine = RuleEngine()
    rules = [{"name": "Credit", "field": "score", "operator": ">=", "value": 700, "outcome": "APPROVED"}]
    assert engine.evaluate(rules, {"score": 750})["outcome"] == "APPROVED"
    rules = [{"name": "Credit", "field": "score", "operator": "<", "value": 550, "outcome": "REJECTED"}]
    assert engine.evaluate(rules, {"score": 780})["outcome"] is None


def test_rule_engine_mandatory():
    from engine.rule_engine import RuleEngine
    engine = RuleEngine()
    rules = [{"name": "Employment", "field": "status", "operator": "!=", "value": "unemployed",
              "mandatory": True, "failOutcome": "REJECTED"}]
    assert engine.evaluate(rules, {"status": "unemployed"})["outcome"] == "REJECTED"


def test_rule_engine_range():
    from engine.rule_engine import RuleEngine
    engine = RuleEngine()
    rules = [{"name": "Moderate", "field": "score", "operator": "range", "min": 550, "max": 749, "outcome": "MANUAL_REVIEW"}]
    assert engine.evaluate(rules, {"score": 650})["outcome"] == "MANUAL_REVIEW"
    assert engine.evaluate(rules, {"score": 800})["outcome"] is None


@pytest.mark.asyncio
async def test_state_machine_transitions():
    import aiosqlite
    from db.database import run_migrations
    from state import StateMachine
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    await run_migrations(db)
    sm = StateMachine(db)
    await db.execute("INSERT INTO requests (id, workflow_id, input_data, status) VALUES ('sm-1','test','{}','RECEIVED')")
    await db.commit()
    await sm.transition('sm-1', 'RECEIVED', 'VALIDATING', 'test')
    await sm.transition('sm-1', 'VALIDATING', 'EVALUATING', 'test')
    history = await sm.get_history('sm-1')
    assert len(history) == 2
    assert history[0]['to_state'] == 'VALIDATING'
    await db.close()


@pytest.mark.asyncio
async def test_state_machine_invalid_transition():
    import aiosqlite
    from db.database import run_migrations
    from state import StateMachine
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    await run_migrations(db)
    sm = StateMachine(db)
    with pytest.raises(ValueError, match="Invalid transition"):
        await sm.transition('x', 'RECEIVED', 'COMPLETED', 'bad')
    await db.close()
