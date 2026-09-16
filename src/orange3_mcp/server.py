"""MCP server exposing tools to build/edit Orange3 workflows (.ows files)
and to search/install/remove Orange3 add-ons.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from typing import Iterator

from pydantic import BaseModel, Field

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.context import Context

from . import addons
from .widgets import find_widget, list_widgets as _list_widgets
from .workflow import Workflow, WorkflowError

mcp = MCPServer(
    "orange3-mcp",
    instructions=(
        "Tools for building Orange3 (data mining GUI) workflows and saving them as "
        ".ows files, and for managing Orange3 add-ons. Start with list_widgets to see "
        "available widgets, create_workflow to start a scheme, add_node/connect_nodes "
        "to build it up. Pass create_workflow's returned id as workflow_id, and "
        "pass the widget catalog id as add_node's widget argument (not widget_id). Use "
        "describe_workflow to inspect the current state, and "
        "save_workflow to write the .ows file. "
        "For downloads, use export_workflow to get the XML content and write it to "
        "a client-side .ows attachment. save_workflow also returns content; its path "
        "is inside the server container, not a client download URL. "
        "Widget catalog entries are best-effort; open the saved file in Orange "
        "Canvas to confirm it loads as expected."
    ),
)

# The dict is a process-local cache; the JSON file is the source of truth so a
# Toolkit-launched container can serve successive MCP calls independently.
_WORKFLOWS: dict[str, Workflow] = {}
_STATE_FILENAME = "mcp_workflows.json"
_PROCESS_LOCK = threading.RLock()


def _state_path() -> Path:
    state_dir = Path(os.environ.get("ORANGE3_MCP_DATA_DIR", "data")) / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / _STATE_FILENAME


@contextmanager
def _state_lock(path: Path) -> Iterator[None]:
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+") as lock_file:
        # Lock and unlock the same byte even if the lock file already exists.
        lock_file.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _read_workflows(path: Path) -> dict[str, Workflow]:
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as state_file:
            data = json.load(state_file)
        return {
            item["id"]: Workflow.from_state(item)
            for item in data.get("workflows", [])
        }
    except (OSError, KeyError, TypeError, ValueError, AttributeError) as exc:
        raise WorkflowError(f"Could not read workflow state from {path}: {exc}") from exc


def _write_workflows(path: Path, workflows: dict[str, Workflow]) -> None:
    payload = {"workflows": [workflow.to_state() for workflow in workflows.values()]}
    fd, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=".mcp_workflows-", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as state_file:
            json.dump(payload, state_file, indent=2)
            state_file.write("\n")
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


@contextmanager
def _workflow_state(*, write: bool = True) -> Iterator[dict[str, Workflow]]:
    path = _state_path()
    # File locks serialize processes; this lock also protects the shared cache
    # from simultaneous tool calls in the same process.
    with _PROCESS_LOCK, _state_lock(path):
        workflows = _read_workflows(path)
        _WORKFLOWS.clear()
        _WORKFLOWS.update(workflows)
        yield _WORKFLOWS
        if write:
            _write_workflows(path, _WORKFLOWS)


def _get_workflow(workflow_id: str) -> Workflow:
    wf = _WORKFLOWS.get(workflow_id)
    if wf is None:
        raise WorkflowError(
            f"No workflow with id '{workflow_id}' in {_state_path()}. "
            "Use create_workflow or load_workflow first. If a previously created "
            "workflow is missing, ensure every server uses the same persistent "
            "ORANGE3_MCP_DATA_DIR (mount /data when running in Docker)."
        )
    return wf


# ---------------------------------------------------------------------------
# Widget catalog
# ---------------------------------------------------------------------------

@mcp.tool()
def list_widgets(category: str | None = None) -> list[dict]:
    """List known Orange3 widgets, optionally filtered by category
    (Data, Visualize, Model, Evaluate, Unsupervised)."""
    return [w.to_dict() for w in _list_widgets(category)]


# ---------------------------------------------------------------------------
# Workflow lifecycle
# ---------------------------------------------------------------------------

@mcp.tool()
def create_workflow(title: str = "Untitled", description: str = "") -> dict:
    """Create a new, empty Orange3 workflow and return its id."""
    with _workflow_state():
        wf = Workflow(title=title, description=description)
        _WORKFLOWS[wf.id] = wf
        return wf.describe()


@mcp.tool()
def describe_workflow(workflow_id: str) -> dict:
    """Return the full current state (nodes, links) of a workflow."""
    with _workflow_state(write=False):
        return _get_workflow(workflow_id).describe()


@mcp.tool()
def list_workflows() -> list[dict]:
    """List all persisted workflows known to this server."""
    with _workflow_state(write=False):
        return [wf.describe() for wf in _WORKFLOWS.values()]


@mcp.tool()
def save_workflow(workflow_id: str, path: str) -> dict:
    """Write an .ows file on the server and return its XML content for download.

    The path is server/container-local, not a client download URL. Prefer /data
    in Docker for persistent files. Write the returned content to a client-side
    attachment to let the user download it, or use export_workflow without saving.
    """
    with _workflow_state():
        wf = _get_workflow(workflow_id)
        saved_path = wf.save(path)
        return {"workflow_id": workflow_id, "path": saved_path,
                **_workflow_export(wf, Path(path).name)}


def _workflow_export(wf: Workflow, filename: str) -> dict:
    return {"filename": filename, "mime_type": "application/xml",
            "encoding": "utf-8", "content": wf.to_xml()}


@mcp.tool()
def export_workflow(workflow_id: str) -> dict:
    """Return a workflow as .ows XML content for a client-side file/download.

    No container filesystem access or prior save is needed. Write content as
    UTF-8 using the returned filename in the client's artifact/output directory,
    then offer that file to the user. This does not create a hosted download URL.
    """
    with _workflow_state(write=False):
        wf = _get_workflow(workflow_id)
        return {"workflow_id": workflow_id,
                **_workflow_export(wf, f"workflow-{wf.id}.ows")}


@mcp.tool()
def load_workflow(path: str) -> dict:
    """Load an existing .ows file into a new in-memory workflow session."""
    with _workflow_state():
        wf = Workflow.load(path)
        _WORKFLOWS[wf.id] = wf
        return wf.describe()


# ---------------------------------------------------------------------------
# Node / link editing
# ---------------------------------------------------------------------------

@mcp.tool()
def add_node(workflow_id: str, widget: str, title: str | None = None,
             x: float = 0, y: float = 0, properties: dict[str, Any] | None = None) -> dict:
    """Add a widget node to a workflow. `widget` may be a catalog id (e.g. "file"),
    a display name (e.g. "File"), or a fully qualified widget class name."""
    with _workflow_state():
        wf = _get_workflow(workflow_id)
        node = wf.add_node(widget, title=title, x=x, y=y, properties=properties)
        return {"node_id": node.id, "title": node.title, "qualified_name": node.qualified_name}


@mcp.tool()
def remove_node(workflow_id: str, node_id: str) -> dict:
    """Remove a node (and any links attached to it) from a workflow."""
    with _workflow_state():
        wf = _get_workflow(workflow_id)
        wf.remove_node(node_id)
        return wf.describe()


@mcp.tool()
def connect_nodes(workflow_id: str, source_node_id: str, source_channel: str,
                   sink_node_id: str, sink_channel: str) -> dict:
    """Connect an output channel of one node to an input channel of another."""
    with _workflow_state():
        wf = _get_workflow(workflow_id)
        link = wf.connect(source_node_id, source_channel, sink_node_id, sink_channel)
        return {"link_id": link.id}


@mcp.tool()
def remove_link(workflow_id: str, link_id: str) -> dict:
    """Remove a link between two nodes."""
    with _workflow_state():
        wf = _get_workflow(workflow_id)
        wf.remove_link(link_id)
        return wf.describe()


@mcp.tool()
def set_node_properties(workflow_id: str, node_id: str, properties: dict[str, Any]) -> dict:
    """Merge widget-specific configuration properties into a node (e.g. a file path
    for the File widget, or selected columns for Select Columns). Properties are
    stored as a Python-literal dict in the saved .ows (format="literal")."""
    with _workflow_state():
        wf = _get_workflow(workflow_id)
        node = wf.set_node_properties(node_id, properties)
        return {"node_id": node.id, "properties": node.properties}


# ---------------------------------------------------------------------------
# Add-on / plugin management
# ---------------------------------------------------------------------------

@mcp.tool()
def list_installed_addons() -> list[dict]:
    """List Orange3 add-ons currently installed in this Python environment."""
    return addons.list_installed_addons()


@mcp.tool()
def search_addons(query: str = "") -> list[dict]:
    """Search known Orange3 add-ons (community plugins) by name/description substring."""
    return addons.search_addons(query)


class _ConfirmInstall(BaseModel):
    confirm: bool = Field(description="Proceed with installing this add-on?")


class _ConfirmUninstall(BaseModel):
    confirm: bool = Field(description="Proceed with uninstalling this add-on?")


@mcp.tool()
async def install_addon(name: str, version: str | None = None, ctx: Context = None) -> dict:
    """Install (or upgrade) an Orange3 add-on via pip, after user confirmation."""
    spec = f"{name}=={version}" if version else name
    result = await ctx.elicit(
        message=f"Install Orange3 add-on '{spec}' into this Python environment via pip?",
        schema=_ConfirmInstall,
    )
    if result.action != "accept" or not result.data.confirm:
        return {"status": "cancelled", "name": name}
    outcome = addons.install_addon(name, version)
    return {"status": "installed" if outcome["ok"] else "failed", "name": name, **outcome}


@mcp.tool()
async def uninstall_addon(name: str, ctx: Context = None) -> dict:
    """Uninstall an Orange3 add-on via pip, after user confirmation."""
    result = await ctx.elicit(
        message=f"Uninstall Orange3 add-on '{name}' from this Python environment via pip?",
        schema=_ConfirmUninstall,
    )
    if result.action != "accept" or not result.data.confirm:
        return {"status": "cancelled", "name": name}
    outcome = addons.uninstall_addon(name)
    return {"status": "uninstalled" if outcome["ok"] else "failed", "name": name, **outcome}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
