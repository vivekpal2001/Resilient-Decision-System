# main.py - FastAPI app + routes
import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI, Request, Response, HTTPException
from pydantic import BaseModel
from typing import Optional, Any

from db.database import get_db, close_db, recover_stale_requests
from config.config_loader import ConfigLoader
from state import StateMachine
from audit import AuditLogger
from engine.workflow_engine import WorkflowEngine


class WorkflowRequest(BaseModel):
    workflow_id: str
    data: dict


class RecoverRequest(BaseModel):
    max_age_minutes: int = 5


config_loader = ConfigLoader()
db = None
state_machine = None
audit_logger = None
workflow_engine = None
idempotency_cache: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db, state_machine, audit_logger, workflow_engine

    db = await get_db()
    state_machine = StateMachine(db)
    audit_logger = AuditLogger(db)
    workflow_engine = WorkflowEngine(config_loader, state_machine, audit_logger)

    workflows = config_loader.get_all_workflows()
    print(f"Loaded {len(workflows)} workflow(s):")
    for w in workflows:
        print(f"  - {w['workflowId']}: {w['name']} ({len(w['stages'])} stages)")

    # recover any requests that got stuck from a previous crash
    recovered = await recover_stale_requests(db, 5)
    if recovered:
        print(f"\n⚠️  Recovered {len(recovered)} stale request(s):")
        for r in recovered:
            print(f"  - {r['id']}: was stuck in '{r['status']}' → marked FAILED")

    print(f"\n🚀 Resilient Decision System running")
    print(f"📚 API docs: http://localhost:8000/docs")
    print(f"❤️  Health check: http://localhost:8000/api/health\n")

    yield

    await close_db()
    print("Shutdown complete.")


app = FastAPI(
    title="Resilient Decision System",
    description="A configurable workflow decision platform",
    version="1.0.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = datetime.utcnow()
    response = await call_next(request)
    ms = int((datetime.utcnow() - start).total_seconds() * 1000)
    print(f"[{datetime.utcnow().isoformat()}] {request.method} {request.url.path} {response.status_code} {ms}ms")
    return response


@app.get("/api/health")
async def health():
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "workflows_loaded": len(config_loader.get_all_workflows()),
    }


@app.post("/api/requests", status_code=201)
async def submit_request(req: WorkflowRequest, request: Request):
    idem_key = request.headers.get("x-idempotency-key")
    if idem_key and idem_key in idempotency_cache:
        cached = idempotency_cache[idem_key]
        return Response(
            content=json.dumps({**cached, "_cached": True, "_message": "Duplicate request. Returning cached response."}),
            status_code=200,
            media_type="application/json",
        )

    workflow = config_loader.get_workflow(req.workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail=f"Workflow '{req.workflow_id}' not found")

    request_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO requests (id, idempotency_key, workflow_id, input_data, status) VALUES (?,?,?,?,'RECEIVED')",
        (request_id, idem_key, req.workflow_id, json.dumps(req.data))
    )
    await db.commit()

    await audit_logger.log(request_id, 'REQUEST_RECEIVED',
                           input_snapshot={'workflow_id': req.workflow_id, 'data': req.data},
                           reasoning=f"New request for workflow '{req.workflow_id}'")

    result = await workflow_engine.process_request(request_id, req.workflow_id, req.data)

    response = {
        "success": result['outcome'] not in ('FAILED', 'REJECTED'),
        "request_id": request_id,
        "workflow_id": req.workflow_id,
        "outcome": result['outcome'],
        "explanation": result.get('explanation', result.get('error', '')),
        "stage_outcomes": result.get('stageOutcomes', []),
        "decided_at": result.get('decidedAt'),
    }

    if idem_key:
        idempotency_cache[idem_key] = response

    return response


@app.get("/api/requests/{request_id}")
async def get_request(request_id: str):
    cursor = await db.execute("SELECT * FROM requests WHERE id=?", (request_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Request '{request_id}' not found")

    req = dict(row)
    req['input_data'] = json.loads(req['input_data'])
    history = await state_machine.get_history(request_id)
    return {"request": req, "state_history": history}


@app.get("/api/requests/{request_id}/decision")
async def get_decision(request_id: str):
    cursor = await db.execute("SELECT * FROM requests WHERE id=?", (request_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Request '{request_id}' not found")

    req = dict(row)
    if not req.get('outcome'):
        raise HTTPException(status_code=400, detail="Request has not been decided yet")

    cursor = await db.execute(
        "SELECT * FROM audit_logs WHERE request_id=? AND event_type IN ('RULE_EVALUATED','DECISION_MADE','EXTERNAL_CALL') ORDER BY id",
        (request_id,)
    )
    trace = []
    for r in await cursor.fetchall():
        d = dict(r)
        if d.get('input_snapshot'): d['input_snapshot'] = json.loads(d['input_snapshot'])
        if d.get('output_snapshot'): d['output_snapshot'] = json.loads(d['output_snapshot'])
        trace.append(d)

    return {
        "request_id": req['id'],
        "workflow_id": req['workflow_id'],
        "outcome": req['outcome'],
        "explanation": req['decision_explanation'],
        "input_data": json.loads(req['input_data']),
        "rule_trace": trace,
    }


@app.get("/api/requests/{request_id}/audit")
async def get_audit(request_id: str):
    cursor = await db.execute("SELECT id FROM requests WHERE id=?", (request_id,))
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail=f"Request '{request_id}' not found")

    trail = await audit_logger.get_audit_trail(request_id)
    history = await state_machine.get_history(request_id)
    return {
        "request_id": request_id,
        "audit_trail": trail,
        "state_history": history,
        "total_events": len(trail),
    }


@app.get("/api/workflows")
async def list_workflows():
    workflows = [{
        'workflowId': w['workflowId'],
        'name': w['name'],
        'description': w.get('description', ''),
        'version': w.get('version', ''),
        'stages': [{'name': s['name'], 'type': s['type']} for s in w['stages']],
    } for w in config_loader.get_all_workflows()]
    return {"workflows": workflows, "total": len(workflows)}


@app.get("/api/workflows/{workflow_id}")
async def get_workflow(workflow_id: str):
    w = config_loader.get_workflow(workflow_id)
    if not w:
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' not found")
    return w


@app.post("/api/workflows", status_code=201)
async def register_workflow(config: dict):
    try:
        registered = config_loader.register_workflow(config)
        return {"success": True, "message": f"Workflow '{registered['workflowId']}' registered", "workflow": registered}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/recover")
async def recover(req: RecoverRequest):
    recovered = await recover_stale_requests(db, req.max_age_minutes)
    return {
        "success": True,
        "recovered_count": len(recovered),
        "recovered_requests": [{
            "id": r['id'],
            "previous_state": r['status'],
            "new_state": "FAILED",
            "reason": f"Auto-recovered: stuck in '{r['status']}' for over {req.max_age_minutes} min",
        } for r in recovered],
        "message": f"Recovered {len(recovered)} stale request(s)." if recovered else "No stale requests found.",
    }


@app.post("/api/test/simulate-stuck", status_code=201)
async def simulate_stuck():
    """Test endpoint: creates a fake stuck request for recovery testing."""
    stuck_id = str(uuid.uuid4())
    ten_min_ago = (datetime.utcnow() - timedelta(minutes=10)).strftime('%Y-%m-%d %H:%M:%S')
    await db.execute(
        "INSERT INTO requests (id, workflow_id, input_data, status, updated_at, created_at) VALUES (?,?,?,?,?,?)",
        (stuck_id, 'loan_approval', json.dumps({"applicant_name": "Stuck Request"}), 'EVALUATING', ten_min_ago, ten_min_ago)
    )
    await db.commit()
    return {
        "success": True,
        "stuck_request_id": stuck_id,
        "status": "EVALUATING",
        "updated_at": ten_min_ago,
        "message": "Stuck request created. Call POST /api/recover to recover it.",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
