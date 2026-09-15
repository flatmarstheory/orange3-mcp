# orange3-mcp

An MCP server for building and configuring [Orange3](https://orangedatamining.com/) data-mining
workflows, and for managing Orange3 add-ons — driven from any MCP client (e.g. Claude Desktop,
Claude Code).

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
| `list_workflows()` | List all in-memory workflow sessions |
| `add_node(workflow_id, widget, title?, x?, y?, properties?)` | Add a widget node |
| `remove_node(workflow_id, node_id)` | Remove a node and its links |
| `connect_nodes(workflow_id, source_node_id, source_channel, sink_node_id, sink_channel)` | Link two nodes |
| `remove_link(workflow_id, link_id)` | Remove a link |
| `set_node_properties(workflow_id, node_id, properties)` | Configure a widget |
| `save_workflow(workflow_id, path)` | Write the `.ows` file |
| `load_workflow(path)` | Load an existing `.ows` file |
| `list_installed_addons()` | Add-ons installed in this environment |
| `search_addons(query?)` | Browse known community add-ons |
| `install_addon(name, version?)` | pip install, with confirmation prompt |
| `uninstall_addon(name)` | pip uninstall, with confirmation prompt |

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
