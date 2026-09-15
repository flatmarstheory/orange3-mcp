"""In-memory workflow sessions with on-disk persistence under a data directory
(so a docker-compose volume mount survives container restarts)."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from ..workflow import Workflow, WorkflowError

_SAFE_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\- ]{0,119}$")


def _data_dir() -> Path:
    return Path(os.environ.get("ORANGE3_MCP_DATA_DIR", "/data"))


class WorkflowStore:
    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or _data_dir()
        self.state_dir = self.data_dir / "state"
        self.exports_dir = self.data_dir / "workflows"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.exports_dir.mkdir(parents=True, exist_ok=True)

        self.workflows: dict[str, Workflow] = {}
        for state_file in sorted(self.state_dir.glob("*.json")):
            try:
                data = json.loads(state_file.read_text(encoding="utf-8"))
                wf = Workflow.from_state(data)
                self.workflows[wf.id] = wf
            except (json.JSONDecodeError, KeyError, OSError):
                continue

    def _persist(self, wf: Workflow) -> None:
        path = self.state_dir / f"{wf.id}.json"
        path.write_text(json.dumps(wf.to_state(), indent=2), encoding="utf-8")

    def _forget(self, workflow_id: str) -> None:
        path = self.state_dir / f"{workflow_id}.json"
        path.unlink(missing_ok=True)

    def list(self) -> list[Workflow]:
        return list(self.workflows.values())

    def get(self, workflow_id: str) -> Workflow:
        wf = self.workflows.get(workflow_id)
        if wf is None:
            raise WorkflowError(f"No workflow with id '{workflow_id}'.")
        return wf

    def create(self, title: str = "Untitled", description: str = "") -> Workflow:
        wf = Workflow(title=title, description=description)
        self.workflows[wf.id] = wf
        self._persist(wf)
        return wf

    def delete(self, workflow_id: str) -> None:
        self.get(workflow_id)
        del self.workflows[workflow_id]
        self._forget(workflow_id)

    def add_node(self, workflow_id: str, **kwargs):
        wf = self.get(workflow_id)
        node = wf.add_node(**kwargs)
        self._persist(wf)
        return node

    def remove_node(self, workflow_id: str, node_id: str) -> None:
        wf = self.get(workflow_id)
        wf.remove_node(node_id)
        self._persist(wf)

    def update_node(self, workflow_id: str, node_id: str, **kwargs):
        wf = self.get(workflow_id)
        node = wf.update_node(node_id, **kwargs)
        self._persist(wf)
        return node

    def set_node_properties(self, workflow_id: str, node_id: str, properties: dict):
        wf = self.get(workflow_id)
        node = wf.set_node_properties(node_id, properties)
        self._persist(wf)
        return node

    def connect(self, workflow_id: str, **kwargs):
        wf = self.get(workflow_id)
        link = wf.connect(**kwargs)
        self._persist(wf)
        return link

    def remove_link(self, workflow_id: str, link_id: str) -> None:
        wf = self.get(workflow_id)
        wf.remove_link(link_id)
        self._persist(wf)

    # -- .ows export/import, confined to the mounted data directory ---------

    def _safe_export_path(self, filename: str) -> Path:
        name = filename.strip()
        if not name.lower().endswith(".ows"):
            name += ".ows"
        if not _SAFE_NAME.match(name):
            raise WorkflowError(
                "Invalid filename: use letters, digits, spaces, '_', '-', '.' only."
            )
        return self.exports_dir / name

    def save(self, workflow_id: str, filename: str) -> Path:
        wf = self.get(workflow_id)
        path = self._safe_export_path(filename)
        wf.save(str(path))
        self._persist(wf)
        return path

    def list_exported_files(self) -> list[str]:
        return sorted(p.name for p in self.exports_dir.glob("*.ows"))

    def load_from_export(self, filename: str) -> Workflow:
        path = self._safe_export_path(filename)
        if not path.exists():
            raise WorkflowError(f"No such file: {filename}")
        wf = Workflow.load(str(path))
        self.workflows[wf.id] = wf
        self._persist(wf)
        return wf


_store: WorkflowStore | None = None


def get_store() -> WorkflowStore:
    global _store
    if _store is None:
        _store = WorkflowStore()
    return _store
