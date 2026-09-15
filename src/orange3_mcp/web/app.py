"""FastAPI backend serving the REST API and the static web GUI."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import addons
from ..widgets import list_widgets as _list_widgets
from ..workflow import WorkflowError
from .chat import get_session
from .store import get_store

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Orange3 MCP Web")


@app.exception_handler(WorkflowError)
async def workflow_error_handler(request, exc: WorkflowError):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@app.get("/api/config")
def get_config() -> dict:
    return {
        "openai_enabled": bool(os.environ.get("OPENAI_API_KEY")),
        "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
    }


# ---------------------------------------------------------------------------
# Widget catalog
# ---------------------------------------------------------------------------

@app.get("/api/widgets")
def api_list_widgets(category: str | None = None) -> list[dict]:
    return [w.to_dict() for w in _list_widgets(category)]


# ---------------------------------------------------------------------------
# Workflows
# ---------------------------------------------------------------------------

class CreateWorkflowBody(BaseModel):
    title: str = "Untitled"
    description: str = ""


@app.get("/api/workflows")
def api_list_workflows() -> list[dict]:
    return [wf.describe() for wf in get_store().list()]


@app.post("/api/workflows")
def api_create_workflow(body: CreateWorkflowBody) -> dict:
    wf = get_store().create(title=body.title, description=body.description)
    return wf.describe()


@app.get("/api/workflows/{workflow_id}")
def api_get_workflow(workflow_id: str) -> dict:
    return get_store().get(workflow_id).describe()


@app.delete("/api/workflows/{workflow_id}")
def api_delete_workflow(workflow_id: str) -> dict:
    get_store().delete(workflow_id)
    return {"status": "deleted"}


class AddNodeBody(BaseModel):
    widget: str
    title: str | None = None
    x: float = 0
    y: float = 0
    properties: dict[str, Any] | None = None


@app.post("/api/workflows/{workflow_id}/nodes")
def api_add_node(workflow_id: str, body: AddNodeBody) -> dict:
    node = get_store().add_node(
        workflow_id, widget_identifier=body.widget, title=body.title,
        x=body.x, y=body.y, properties=body.properties,
    )
    return {"node_id": node.id, "title": node.title, "qualified_name": node.qualified_name}


class UpdateNodeBody(BaseModel):
    title: str | None = None
    x: float | None = None
    y: float | None = None
    properties: dict[str, Any] | None = None


@app.patch("/api/workflows/{workflow_id}/nodes/{node_id}")
def api_update_node(workflow_id: str, node_id: str, body: UpdateNodeBody) -> dict:
    store = get_store()
    if body.title is not None or body.x is not None or body.y is not None:
        store.update_node(workflow_id, node_id, title=body.title, x=body.x, y=body.y)
    if body.properties is not None:
        store.set_node_properties(workflow_id, node_id, body.properties)
    return store.get(workflow_id).describe()


@app.delete("/api/workflows/{workflow_id}/nodes/{node_id}")
def api_remove_node(workflow_id: str, node_id: str) -> dict:
    get_store().remove_node(workflow_id, node_id)
    return get_store().get(workflow_id).describe()


class ConnectBody(BaseModel):
    source_node_id: str
    source_channel: str
    sink_node_id: str
    sink_channel: str


@app.post("/api/workflows/{workflow_id}/links")
def api_connect(workflow_id: str, body: ConnectBody) -> dict:
    link = get_store().connect(workflow_id, **body.model_dump())
    return {"link_id": link.id}


@app.delete("/api/workflows/{workflow_id}/links/{link_id}")
def api_remove_link(workflow_id: str, link_id: str) -> dict:
    get_store().remove_link(workflow_id, link_id)
    return get_store().get(workflow_id).describe()


class SaveBody(BaseModel):
    filename: str


@app.post("/api/workflows/{workflow_id}/save")
def api_save(workflow_id: str, body: SaveBody) -> dict:
    path = get_store().save(workflow_id, body.filename)
    return {"filename": path.name}


@app.get("/api/workflows/{workflow_id}/download")
def api_download(workflow_id: str):
    wf = get_store().get(workflow_id)
    if not wf.path or not Path(wf.path).exists():
        raise HTTPException(status_code=404, detail="Workflow has not been saved to a file yet.")
    return FileResponse(wf.path, filename=Path(wf.path).name, media_type="application/xml")


@app.get("/api/files")
def api_list_files() -> list[str]:
    return get_store().list_exported_files()


class LoadBody(BaseModel):
    filename: str


@app.post("/api/workflows/load")
def api_load(body: LoadBody) -> dict:
    wf = get_store().load_from_export(body.filename)
    return wf.describe()


# ---------------------------------------------------------------------------
# Add-ons
# ---------------------------------------------------------------------------

@app.get("/api/addons/installed")
def api_installed_addons() -> list[dict]:
    return addons.list_installed_addons()


@app.get("/api/addons/search")
def api_search_addons(q: str = "") -> list[dict]:
    return addons.search_addons(q)


class AddonNameBody(BaseModel):
    name: str
    version: str | None = None


@app.post("/api/addons/install")
def api_install_addon(body: AddonNameBody) -> dict:
    result = addons.install_addon(body.name, body.version)
    if not result["ok"]:
        raise HTTPException(status_code=422, detail=result["stderr"] or "pip install failed")
    return {"status": "installed", **result}


@app.post("/api/addons/uninstall")
def api_uninstall_addon(body: AddonNameBody) -> dict:
    result = addons.uninstall_addon(body.name)
    if not result["ok"]:
        raise HTTPException(status_code=422, detail=result["stderr"] or "pip uninstall failed")
    return {"status": "uninstalled", **result}


# ---------------------------------------------------------------------------
# Chat (OpenAI function-calling)
# ---------------------------------------------------------------------------

class ChatBody(BaseModel):
    message: str


@app.post("/api/chat")
def api_chat(body: ChatBody) -> dict:
    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY is not configured on the server.")
    try:
        return get_session().send(get_store(), body.message)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # openai/network errors etc.
        raise HTTPException(status_code=502, detail=f"Chat backend error: {e}")


@app.post("/api/chat/reset")
def api_chat_reset() -> dict:
    get_session().reset()
    return {"status": "reset"}


# Static GUI, mounted last so /api/* routes above take precedence.
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
