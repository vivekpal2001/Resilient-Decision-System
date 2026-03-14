# db/database.py - async SQLite layer
import aiosqlite
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'decisions.db')
_db = None


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is not None:
        return _db
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    _db = await aiosqlite.connect(DB_PATH)
    _db.row_factory = aiosqlite.Row
    await run_migrations(_db)
    return _db


async def run_migrations(db: aiosqlite.Connection):
    await db.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            id TEXT PRIMARY KEY,
            idempotency_key TEXT UNIQUE,
            workflow_id TEXT NOT NULL,
            input_data TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'RECEIVED',
            outcome TEXT,
            decision_explanation TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS state_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id TEXT NOT NULL,
            from_state TEXT,
            to_state TEXT NOT NULL,
            reason TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (request_id) REFERENCES requests(id)
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            stage_name TEXT,
            rule_name TEXT,
            input_snapshot TEXT,
            output_snapshot TEXT,
            reasoning TEXT,
            duration_ms INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (request_id) REFERENCES requests(id)
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS idempotency_keys (
            key TEXT PRIMARY KEY,
            request_id TEXT NOT NULL,
            response TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (request_id) REFERENCES requests(id)
        )
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_state_history_request ON state_history(request_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_request ON audit_logs(request_id)")
    await db.commit()


async def close_db():
    global _db
    if _db:
        await _db.close()
        _db = None


async def create_test_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    await run_migrations(db)
    return db


async def recover_stale_requests(db: aiosqlite.Connection, max_age_minutes: int = 5) -> list:
    """Finds requests stuck in non-terminal states and marks them FAILED."""
    from datetime import datetime, timedelta
    cutoff = (datetime.utcnow() - timedelta(minutes=max_age_minutes)).strftime('%Y-%m-%d %H:%M:%S')
    non_terminal = ('RECEIVED', 'VALIDATING', 'EVALUATING', 'RETRYING')

    placeholders = ','.join('?' for _ in non_terminal)
    cursor = await db.execute(
        f"SELECT id, status FROM requests WHERE status IN ({placeholders}) AND updated_at < ?",
        (*non_terminal, cutoff)
    )
    stale = [dict(row) for row in await cursor.fetchall()]

    for req in stale:
        try:
            await db.execute(
                "UPDATE requests SET status='FAILED', outcome='FAILED', "
                "decision_explanation=?, updated_at=datetime('now') WHERE id=?",
                (f"Recovered from stale state '{req['status']}'.", req['id'])
            )
            await db.execute(
                "INSERT INTO state_history (request_id, from_state, to_state, reason) VALUES (?,?,'FAILED',?)",
                (req['id'], req['status'], f"Auto-recovered: stuck in '{req['status']}' for over {max_age_minutes} min")
            )
            await db.execute(
                "INSERT INTO audit_logs (request_id, event_type, reasoning) VALUES (?,'RECOVERY',?)",
                (req['id'], f"Auto-recovered from stale state '{req['status']}'.")
            )
            await db.commit()
        except Exception as e:
            print(f"Failed to recover {req['id']}: {e}")

    return stale
