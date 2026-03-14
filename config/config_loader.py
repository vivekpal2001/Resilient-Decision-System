# config/config_loader.py - loads workflows from JSON files + SQLite
import json
import os
from typing import Optional

WORKFLOW_DIR = os.path.join(os.path.dirname(__file__), 'workflows')


class ConfigLoader:
    def __init__(self, workflow_dir: str = WORKFLOW_DIR):
        self.workflow_dir = workflow_dir
        self.workflows: dict = {}
        self.db = None
        self._load_all()

    def _load_all(self):
        """Load workflows from JSON files on disk."""
        if not os.path.isdir(self.workflow_dir):
            os.makedirs(self.workflow_dir, exist_ok=True)
            return

        for filename in os.listdir(self.workflow_dir):
            if filename.endswith('.json'):
                filepath = os.path.join(self.workflow_dir, filename)
                try:
                    with open(filepath, 'r') as f:
                        config = json.load(f)
                    wid = config.get('workflowId')
                    if wid:
                        self.workflows[wid] = config
                except Exception as e:
                    print(f"Warning: Failed to load {filename}: {e}")

    async def load_from_db(self, db):
        """Load workflows stored in the DB (registered via API)."""
        self.db = db
        try:
            cursor = await db.execute("SELECT id, config FROM workflows")
            rows = await cursor.fetchall()
            for row in rows:
                config = json.loads(row['config'])
                self.workflows[row['id']] = config
            if rows:
                print(f"  Loaded {len(rows)} workflow(s) from database")
        except Exception as e:
            print(f"Warning: Could not load workflows from DB: {e}")

    def get_workflow(self, workflow_id: str) -> Optional[dict]:
        return self.workflows.get(workflow_id)

    def get_all_workflows(self) -> list:
        return list(self.workflows.values())

    async def register_workflow(self, config: dict) -> dict:
        """Register a workflow: save to memory + persist to DB."""
        wid = config.get('workflowId')
        if not wid:
            raise ValueError("Config must have 'workflowId'")
        if not config.get('stages'):
            raise ValueError("Config must have 'stages'")

        self.workflows[wid] = config

        # persist to DB so it survives restarts
        if self.db:
            config_json = json.dumps(config)
            version = config.get('version', '1.0.0')
            await self.db.execute(
                "INSERT OR REPLACE INTO workflows (id, config, version, updated_at) VALUES (?,?,?,datetime('now'))",
                (wid, config_json, version)
            )
            await self.db.commit()

        return config

    def reload_workflow(self, workflow_id: str) -> Optional[dict]:
        for filename in os.listdir(self.workflow_dir):
            if filename.endswith('.json'):
                filepath = os.path.join(self.workflow_dir, filename)
                with open(filepath, 'r') as f:
                    config = json.load(f)
                if config.get('workflowId') == workflow_id:
                    self.workflows[workflow_id] = config
                    return config
        return None
