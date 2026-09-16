# orange3-mcp

Tools for building and configuring [Orange3](https://orangedatamining.com/) data-mining workflows
and managing Orange3 add-ons, in two forms sharing the same core logic ([`src/orange3_mcp/workflow.py`](src/orange3_mcp/workflow.py),
[`widgets.py`](src/orange3_mcp/widgets.py), [`addons.py`](src/orange3_mcp/addons.py)):

- **MCP server** (below) — for MCP clients like Claude Desktop/Code.
- **[Web app](#web-app-docker-compose)** — a self-contained Docker Compose deployment with a
  browser GUI, for running on your own machine.

## MCP server

An MCP server driven from any MCP client (e.g. Claude Desktop, Claude Code).

It does **not** require Orange3 itself to be installed: workflows are created and edited as
in-memory graphs and serialized directly to Orange's `.ows` scheme XML format, so it works
headless. Add-on management shells out to `pip` in whatever Python environment the server runs in
— install Orange3 there if you want to open/run the workflows it produces.

## What it does

- **Workflows**: create a scheme, add widget nodes, connect their input/output channels, set
  widget properties, and save/load `.ows` files.
- **Widget catalog**: a curated set of ~50 core Orange3 widgets (Data, Visualize, Model, Evaluate,
  Unsupervised) with their qualified class names and channel names. It's best-effort — verify by
  opening a saved workflow in Orange Canvas — and it's extensible (see below).
- **Add-ons**: list installed Orange3 add-ons, browse known community add-ons, and install/remove
  them via `pip`. Install/uninstall ask for confirmation through the MCP client's own UI
  (MCP "elicitation") before touching the environment.

## Install

```bash
pip install -e .
```

Requires Python 3.10+.

## Run

As a standalone process (stdio transport):

```bash
orange3-mcp
```

### Claude Desktop / Claude Code configuration

Add to your MCP client's server config (e.g. `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "orange3": {
      "command": "orange3-mcp"
    }
  }
}
```

Or, without installing the console script, point at the module directly:

```json
{
  "mcpServers": {
    "orange3": {
      "command": "python",
      "args": ["-m", "orange3_mcp.server"]
    }
  }
}
```

## Tools

| Tool | Purpose |
|---|---|
| `list_widgets(category?)` | Browse the widget catalog |
| `create_workflow(title, description?)` | Start a new workflow, returns `workflow_id` |
| `describe_workflow(workflow_id)` | Inspect current nodes/links |
| `list_workflows()` | List all persisted workflow sessions |
| `export_workflow(workflow_id)` | Return .ows XML content for a client-side file/download; no container copying needed |
| `add_node(workflow_id, widget, title?, x?, y?, properties?)` | Add a widget node |
| `remove_node(workflow_id, node_id)` | Remove a node and its links |
| `connect_nodes(workflow_id, source_node_id, source_channel, sink_node_id, sink_channel)` | Link two nodes |
| `remove_link(workflow_id, link_id)` | Remove a link |
| `set_node_properties(workflow_id, node_id, properties)` | Configure a widget |
| `save_workflow(workflow_id, path)` | Write the server-side `.ows` file and return its XML content |
| `load_workflow(path)` | Load an existing `.ows` file |
| `list_installed_addons()` | Add-ons installed in this environment |
| `search_addons(query?)` | Browse known community add-ons |
| `install_addon(name, version?)` | pip install, with confirmation prompt |
| `uninstall_addon(name)` | pip uninstall, with confirmation prompt |

## Docker MCP Toolkit

The server can also run as a stdio container managed by Docker MCP Toolkit. The
server-only image is built from [`Dockerfile.mcp`](Dockerfile.mcp), and the
Docker MCP Registry-style metadata is in [`docker-mcp/server.yaml`](docker-mcp/server.yaml).
Neither starts the web GUI. See [`docker-mcp/README.md`](docker-mcp/README.md)
for local build and Toolkit setup commands.

Workflow sessions are saved after each edit and reloaded on each call. Set
`ORANGE3_MCP_DATA_DIR` to a shared persistent directory; local runs default to
`./data`, and the Docker image uses `/data`. Mount a named volume or host
directory at `/data` so sessions survive container replacement. The Docker
setup guide includes a client configuration with a named volume.

Docker MCP Toolkit can expose enabled servers through its MCP gateway, so Claude
Code can use this server's workflow tools after the gateway is connected. Keep
the gateway long-lived for multi-call workflow editing (`--long-lived`). This
integration does not add retrieval-augmented generation (RAG): the project has
no document ingestion, embeddings, vector store, or retrieval tool. RAG would
require enabling another MCP retrieval server or adding those capabilities to
this project.

## Web app (Docker Compose)

A standalone webapp — a FastAPI backend plus a plain HTML/CSS/JS GUI — running the same workflow
and add-on logic as the MCP server, with no MCP client required.

```bash
cp .env.example .env   # optional: set OPENAI_API_KEY to enable the Chat tab
docker compose up --build
```

Open **http://localhost:8000**. Saved `.ows` files and in-progress workflow state live under
`./data` on the host (mounted into the container), so they survive `docker compose down`/`up`.

The GUI has three tabs:

- **Builder** — a visual node canvas: add widgets from the palette, drag nodes to reposition them
  (or set their X/Y directly in the node editor), connect ports by clicking an output then an input
  (or use the plain "Connect nodes" form, fully keyboard-operable), edit a widget's properties as
  JSON, and save/load `.ows` files from the mounted data volume.
- **Chat** — natural-language workflow editing via OpenAI function-calling, using the same tools
  as the Builder. Requires `OPENAI_API_KEY`; without it the tab explains how to enable it and stays
  disabled rather than failing silently. The model can read/edit workflows but cannot install or
  remove add-ons — that stays behind the explicit, confirmed buttons in the Add-ons tab.
- **Add-ons** — list installed Orange3 add-ons and browse/install known community ones (`pip`
  install/uninstall inside the container), each gated by a confirmation dialog.

This deployment intentionally does **not** expose the MCP protocol — it's a standalone webapp. Run
the MCP server (above) separately if you also want to drive it from an MCP client.

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | unset | Enables the Chat tab. Without it, everything else still works. |
| `OPENAI_MODEL` | `gpt-4o-mini` | Model used for the Chat tab. |
| `ORANGE3_MCP_DATA_DIR` | `/data` (container) | Where `.ows` files and workflow session state are stored; set via `docker-compose.yml`'s volume mount, not usually overridden directly. |

## Extending the widget catalog

Point the `ORANGE3_MCP_WIDGET_CATALOG` environment variable at your own JSON file (same shape as
[`src/orange3_mcp/widgets_catalog.json`](src/orange3_mcp/widgets_catalog.json)) to add widgets from
installed add-ons or override the bundled entries.

## Notes / limitations

- `set_node_properties` writes properties using the `.ows` `format="literal"` encoding (a Python
  literal dict), which is safe and human-readable but only covers widgets whose settings are plain
  literals (str/int/float/bool/list/dict) — some widgets store richer state Orange itself would
  normally pickle.
- `search_addons` uses a small curated list of known community add-ons (PyPI dropped its public
  search API); `install_addon` accepts any exact PyPI package name, known or not.
