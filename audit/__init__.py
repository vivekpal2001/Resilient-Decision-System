# audit/__init__.py - logs all events for compliance and debugging
import json


class AuditLogger:
    def __init__(self, db):
        self.db = db

    async def log(self, request_id: str, event_type: str, stage_name: str = None,
                  rule_name: str = None, input_snapshot: dict = None,
                  output_snapshot: dict = None, reasoning: str = None, duration_ms: int = None):
        await self.db.execute(
            """INSERT INTO audit_logs
               (request_id, event_type, stage_name, rule_name, input_snapshot, output_snapshot, reasoning, duration_ms)
               VALUES (?,?,?,?,?,?,?,?)""",
            (request_id, event_type, stage_name, rule_name,
             json.dumps(input_snapshot) if input_snapshot else None,
             json.dumps(output_snapshot) if output_snapshot else None,
             reasoning, duration_ms)
        )
        await self.db.commit()

    async def log_state_change(self, request_id, from_state, to_state, reason):
        await self.log(request_id, 'STATE_CHANGED',
                       input_snapshot={'fromState': from_state},
                       output_snapshot={'toState': to_state},
                       reasoning=reason)

    async def log_rule_evaluation(self, request_id, stage_name, rule_result):
        await self.log(request_id, 'RULE_EVALUATED',
                       stage_name=stage_name,
                       rule_name=rule_result.get('ruleName'),
                       input_snapshot={'field': rule_result.get('field'), 'value': rule_result.get('fieldValue')},
                       output_snapshot={'passed': rule_result.get('passed'), 'outcome': rule_result.get('outcome')},
                       reasoning=rule_result.get('reasoning'))

    async def log_external_call(self, request_id, stage_name, service, result, duration_ms):
        await self.log(request_id, 'EXTERNAL_CALL',
                       stage_name=stage_name,
                       input_snapshot={'service': service},
                       output_snapshot=result,
                       reasoning=f"External call to {service}: {'success' if result.get('success') else 'failed'}",
                       duration_ms=duration_ms)

    async def log_error(self, request_id, stage_name, error):
        await self.log(request_id, 'ERROR', stage_name=stage_name, reasoning=f"Error: {error}")

    async def log_decision(self, request_id, outcome, explanation):
        await self.log(request_id, 'DECISION_MADE',
                       output_snapshot={'outcome': outcome},
                       reasoning=explanation)

    async def get_audit_trail(self, request_id: str) -> list:
        cursor = await self.db.execute(
            "SELECT * FROM audit_logs WHERE request_id=? ORDER BY created_at ASC, id ASC",
            (request_id,)
        )
        rows = await cursor.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            if d.get('input_snapshot'):
                d['input_snapshot'] = json.loads(d['input_snapshot'])
            if d.get('output_snapshot'):
                d['output_snapshot'] = json.loads(d['output_snapshot'])
            result.append(d)
        return result
