# config/config_loader.py - loads workflow definitions from JSON files
import json
import os
from typing import Optional

WORKFLOW_DIR = os.path.join(os.path.dirname(__file__), 'workflows')


class ConfigLoader:
    def __init__(self, workflow_dir: str = WORKFLOW_DIR):
        self.workflow_dir = workflow_dir
        self.workflows: dict = {}
        self._load_all()

    def _load_all(self):
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

    def get_workflow(self, workflow_id: str) -> Optional[dict]:
        return self.workflows.get(workflow_id)

    def get_all_workflows(self) -> list:
        return list(self.workflows.values())

    def register_workflow(self, config: dict) -> dict:
        wid = config.get('workflowId')
        if not wid:
            raise ValueError("Config must have 'workflowId'")
        if not config.get('stages'):
            raise ValueError("Config must have 'stages'")
        self.workflows[wid] = config
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
