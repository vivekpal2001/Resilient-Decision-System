# state/__init__.py - manages workflow lifecycle state transitions

VALID_TRANSITIONS = {
    'RECEIVED': ['VALIDATING'],
    'VALIDATING': ['EVALUATING', 'FAILED'],
    'EVALUATING': ['DECIDED', 'FAILED', 'RETRYING'],
    'RETRYING': ['EVALUATING', 'FAILED'],
    'DECIDED': ['COMPLETED', 'MANUAL_REVIEW', 'FAILED'],
    'COMPLETED': [],
    'MANUAL_REVIEW': [],
    'FAILED': ['RETRYING'],
}

TERMINAL_STATES = {'COMPLETED', 'MANUAL_REVIEW', 'FAILED'}


class StateMachine:
    def __init__(self, db):
        self.db = db

    async def transition(self, request_id: str, from_state: str, to_state: str, reason: str = ''):
        allowed = VALID_TRANSITIONS.get(from_state, [])
        if to_state not in allowed:
            raise ValueError(f"Invalid transition: {from_state} → {to_state}")

        await self.db.execute(
            "INSERT INTO state_history (request_id, from_state, to_state, reason) VALUES (?,?,?,?)",
            (request_id, from_state, to_state, reason)
        )
        await self.db.execute(
            "UPDATE requests SET status=?, updated_at=datetime('now') WHERE id=?",
            (to_state, request_id)
        )
        await self.db.commit()

    async def get_history(self, request_id: str) -> list:
        cursor = await self.db.execute(
            "SELECT * FROM state_history WHERE request_id=? ORDER BY created_at ASC, id ASC",
            (request_id,)
        )
        return [dict(row) for row in await cursor.fetchall()]

    @staticmethod
    def is_terminal(state: str) -> bool:
        return state in TERMINAL_STATES
