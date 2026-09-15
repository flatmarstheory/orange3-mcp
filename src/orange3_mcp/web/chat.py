"""Chat panel backed by OpenAI function-calling, driving the same workflow store
the visual builder uses. Read/edit workflow tools only - add-on installation
stays behind the explicit, confirmed buttons in the Add-ons panel, never
something the model can trigger on its own."""
from __future__ import annotations

import json
import os

from .. import addons
from ..widgets import list_widgets as _list_widgets
from ..workflow import WorkflowError
from .store import WorkflowStore

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
MAX_TOOL_ROUNDS = 6

SYSTEM_PROMPT = (
    "You are an assistant embedded in a web app for building Orange3 (data mining "
    "software) workflows. Use the provided tools to inspect and edit workflows on the "
    "user's behalf: create workflows, add widget nodes, connect their input/output "
    "channels, configure widget properties, and save the result to a .ows file. "
    "Always call list_widgets first if you're unsure of a widget's catalog id or its "
    "channel names before adding nodes or connecting them. Keep replies short. "
    "You cannot install or remove Orange3 add-ons yourself - if asked, tell the user "
    "to use the Add-ons tab, which asks for confirmation before touching anything."
)

TOOLS = [
    {"type": "function", "function": {
        "name": "list_widgets",
        "description": "List known Orange3 widgets, optionally filtered by category.",
        "parameters": {"type": "object", "properties": {
            "category": {"type": "string", "description": "Data, Visualize, Model, Evaluate, or Unsupervised"},
        }},
    }},
    {"type": "function", "function": {
        "name": "list_workflows",
        "description": "List all in-memory workflow sessions.",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "describe_workflow",
        "description": "Get the current nodes and links of a workflow.",
        "parameters": {"type": "object", "properties": {
            "workflow_id": {"type": "string"},
        }, "required": ["workflow_id"]},
    }},
    {"type": "function", "function": {
        "name": "create_workflow",
        "description": "Create a new, empty workflow. Returns its workflow_id.",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"},
        }},
    }},
    {"type": "function", "function": {
        "name": "add_node",
        "description": "Add a widget node to a workflow.",
        "parameters": {"type": "object", "properties": {
            "workflow_id": {"type": "string"},
            "widget": {"type": "string", "description": "Catalog id, display name, or qualified class name"},
            "title": {"type": "string"},
            "x": {"type": "number"},
            "y": {"type": "number"},
        }, "required": ["workflow_id", "widget"]},
    }},
    {"type": "function", "function": {
        "name": "remove_node",
        "description": "Remove a node (and its links) from a workflow.",
        "parameters": {"type": "object", "properties": {
            "workflow_id": {"type": "string"},
            "node_id": {"type": "string"},
        }, "required": ["workflow_id", "node_id"]},
    }},
    {"type": "function", "function": {
        "name": "connect_nodes",
        "description": "Connect an output channel of one node to an input channel of another.",
        "parameters": {"type": "object", "properties": {
            "workflow_id": {"type": "string"},
            "source_node_id": {"type": "string"},
            "source_channel": {"type": "string"},
            "sink_node_id": {"type": "string"},
            "sink_channel": {"type": "string"},
        }, "required": ["workflow_id", "source_node_id", "source_channel", "sink_node_id", "sink_channel"]},
    }},
    {"type": "function", "function": {
        "name": "remove_link",
        "description": "Remove a link between two nodes.",
        "parameters": {"type": "object", "properties": {
            "workflow_id": {"type": "string"},
            "link_id": {"type": "string"},
        }, "required": ["workflow_id", "link_id"]},
    }},
    {"type": "function", "function": {
        "name": "set_node_properties",
        "description": "Merge configuration properties into a widget node.",
        "parameters": {"type": "object", "properties": {
            "workflow_id": {"type": "string"},
            "node_id": {"type": "string"},
            "properties": {"type": "object"},
        }, "required": ["workflow_id", "node_id", "properties"]},
    }},
    {"type": "function", "function": {
        "name": "save_workflow",
        "description": "Save a workflow to a .ows file (by filename, stored in the shared data volume).",
        "parameters": {"type": "object", "properties": {
            "workflow_id": {"type": "string"},
            "filename": {"type": "string"},
        }, "required": ["workflow_id", "filename"]},
    }},
    {"type": "function", "function": {
        "name": "list_installed_addons",
        "description": "List Orange3 add-ons installed in this environment.",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "search_addons",
        "description": "Search known Orange3 community add-ons by name/description.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"},
        }},
    }},
]


def _describe(wf) -> dict:
    return wf.describe()


def run_tool(store: WorkflowStore, name: str, args: dict) -> dict:
    try:
        if name == "list_widgets":
            return {"widgets": [w.to_dict() for w in _list_widgets(args.get("category"))]}
        if name == "list_workflows":
            return {"workflows": [_describe(wf) for wf in store.list()]}
        if name == "describe_workflow":
            return _describe(store.get(args["workflow_id"]))
        if name == "create_workflow":
            wf = store.create(title=args.get("title", "Untitled"), description=args.get("description", ""))
            return _describe(wf)
        if name == "add_node":
            node = store.add_node(
                args["workflow_id"], widget_identifier=args["widget"], title=args.get("title"),
                x=args.get("x", 0), y=args.get("y", 0),
            )
            return {"node_id": node.id, "title": node.title, "qualified_name": node.qualified_name}
        if name == "remove_node":
            store.remove_node(args["workflow_id"], args["node_id"])
            return _describe(store.get(args["workflow_id"]))
        if name == "connect_nodes":
            link = store.connect(
                args["workflow_id"], source_node_id=args["source_node_id"],
                source_channel=args["source_channel"], sink_node_id=args["sink_node_id"],
                sink_channel=args["sink_channel"],
            )
            return {"link_id": link.id}
        if name == "remove_link":
            store.remove_link(args["workflow_id"], args["link_id"])
            return _describe(store.get(args["workflow_id"]))
        if name == "set_node_properties":
            node = store.set_node_properties(args["workflow_id"], args["node_id"], args["properties"])
            return {"node_id": node.id, "properties": node.properties}
        if name == "save_workflow":
            path = store.save(args["workflow_id"], args["filename"])
            return {"saved_as": path.name}
        if name == "list_installed_addons":
            return {"addons": addons.list_installed_addons()}
        if name == "search_addons":
            return {"addons": addons.search_addons(args.get("query", ""))}
        return {"error": f"Unknown tool '{name}'"}
    except WorkflowError as e:
        return {"error": str(e)}


class ChatSession:
    """Keeps one running conversation. A single shared session is fine for a
    localhost, single-user tool; not meant for multi-tenant use."""

    def __init__(self):
        self.messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

    def reset(self) -> None:
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    def send(self, store: WorkflowStore, user_message: str) -> dict:
        from openai import OpenAI

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set on the server.")
        client = OpenAI(api_key=api_key)

        self.messages.append({"role": "user", "content": user_message})
        tool_calls_made: list[dict] = []

        for _ in range(MAX_TOOL_ROUNDS):
            response = client.chat.completions.create(
                model=MODEL, messages=self.messages, tools=TOOLS, tool_choice="auto",
            )
            choice = response.choices[0].message
            self.messages.append(choice.model_dump(exclude_none=True))

            if not choice.tool_calls:
                return {"reply": choice.content or "", "tool_calls": tool_calls_made}

            for call in choice.tool_calls:
                args = json.loads(call.function.arguments or "{}")
                result = run_tool(store, call.function.name, args)
                tool_calls_made.append({"name": call.function.name, "arguments": args, "result": result})
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result, default=str),
                })

        return {
            "reply": "Reached the tool-call limit for this turn; ask me to continue.",
            "tool_calls": tool_calls_made,
        }


_session: ChatSession | None = None


def get_session() -> ChatSession:
    global _session
    if _session is None:
        _session = ChatSession()
    return _session
