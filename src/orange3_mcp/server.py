"""MCP server exposing tools to build/edit Orange3 workflows (.ows files)
and to search/install/remove Orange3 add-ons.
"""
from __future__ import annotations

from typing import Any

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
        "to build it up, describe_workflow to inspect the current state, and "
        "save_workflow to write the .ows file. Widget catalog entries are best-effort; "
        "open the saved file in Orange Canvas to confirm it loads as expected."
    ),
)

# in-memory workflow sessions, keyed by workflow id
_WORKFLOWS: dict[str, Workflow] = {}


def _get_workflow(workflow_id: str) -> Workflow:
    wf = _WORKFLOWS.get(workflow_id)
    if wf is None:
        raise WorkflowError(
            f"No workflow with id '{workflow_id}'. Use create_workflow or load_workflow first."
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
    """Create a new, empty Orange3 workflow in memory and return its id."""
    wf = Workflow(title=title, description=description)
    _WORKFLOWS[wf.id] = wf
    return wf.describe()


@mcp.tool()
def describe_workflow(workflow_id: str) -> dict:
    """Return the full current state (nodes, links) of a workflow."""
    return _get_workflow(workflow_id).describe()


@mcp.tool()
def list_workflows() -> list[dict]:
    """List all workflows currently held in memory by this server."""
    return [wf.describe() for wf in _WORKFLOWS.values()]


@mcp.tool()
def save_workflow(workflow_id: str, path: str) -> dict:
    """Write a workflow to an .ows file at the given path."""
    wf = _get_workflow(workflow_id)
    saved_path = wf.save(path)
    return {"workflow_id": workflow_id, "path": saved_path}


@mcp.tool()
def load_workflow(path: str) -> dict:
    """Load an existing .ows file into a new in-memory workflow session."""
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
    wf = _get_workflow(workflow_id)
    node = wf.add_node(widget, title=title, x=x, y=y, properties=properties)
    return {"node_id": node.id, "title": node.title, "qualified_name": node.qualified_name}


@mcp.tool()
def remove_node(workflow_id: str, node_id: str) -> dict:
    """Remove a node (and any links attached to it) from a workflow."""
    wf = _get_workflow(workflow_id)
    wf.remove_node(node_id)
    return wf.describe()


@mcp.tool()
def connect_nodes(workflow_id: str, source_node_id: str, source_channel: str,
                   sink_node_id: str, sink_channel: str) -> dict:
    """Connect an output channel of one node to an input channel of another."""
    wf = _get_workflow(workflow_id)
    link = wf.connect(source_node_id, source_channel, sink_node_id, sink_channel)
    return {"link_id": link.id}


@mcp.tool()
def remove_link(workflow_id: str, link_id: str) -> dict:
    """Remove a link between two nodes."""
    wf = _get_workflow(workflow_id)
    wf.remove_link(link_id)
    return wf.describe()


@mcp.tool()
def set_node_properties(workflow_id: str, node_id: str, properties: dict[str, Any]) -> dict:
    """Merge widget-specific configuration properties into a node (e.g. a file path
    for the File widget, or selected columns for Select Columns). Properties are
    stored as a Python-literal dict in the saved .ows (format="literal")."""
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
