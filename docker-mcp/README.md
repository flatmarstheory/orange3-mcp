# Docker MCP Toolkit

This directory contains the Docker MCP Registry-style definition for the
stdio-only Orange3 MCP server. It does not include the web application.

## Local Docker MCP Toolkit

From the repository root, build the updated image and create a profile from the
runtime server entry. This explicitly mounts a persistent named volume:

```powershell
docker build -f Dockerfile.mcp -t orange3-mcp:local .
docker volume create orange3-mcp-data
$orangeDockerConfig = if ($env:DOCKER_CONFIG) { $env:DOCKER_CONFIG } else { Join-Path $env:USERPROFILE '.docker' }
$orangeCatalogDir = Join-Path $orangeDockerConfig 'mcp/catalogs'
New-Item -ItemType Directory -Force -Path $orangeCatalogDir | Out-Null
Copy-Item -LiteralPath ./docker-mcp/local-server.yaml -Destination (Join-Path $orangeCatalogDir 'orange3-local-server.yaml')
$orangeProfileId = 'orange3_persistent'
$profileExists = docker mcp profile list | Select-String -SimpleMatch $orangeProfileId
if (-not $profileExists) {
  docker mcp profile create --name orange3-persistent --server file://orange3-local-server.yaml
  if ($LASTEXITCODE -ne 0) { throw 'Profile creation failed; do not start the gateway yet.' }
} else {
  Write-Host "Reusing existing profile $orangeProfileId"
}
# Toolkit stores this profile id with underscores.
docker mcp gateway run --profile $orangeProfileId --long-lived
```

Toolkit resolves `file://` references under its catalogs directory and can reject
paths outside that directory. Copy the runtime entry there first; an absolute
path to the repository does not bypass this restriction. The PowerShell commands
above use `DOCKER_CONFIG` when set, otherwise the user's `.docker` directory.
If profile creation fails, fix that error before running the gateway.

Configure the MCP client's existing Docker gateway entry to launch that profile:

```json
{
  "mcpServers": {
    "orange3-mcp": {
      "command": "docker",
      "args": ["mcp", "gateway", "run", "--profile", "orange3_persistent", "--long-lived"]
    }
  }
}
```

Merge this entry into the client's configuration, preserving any other servers.
Restart/reconnect that client after building the image and changing its gateway
arguments. Running a separate gateway in a terminal does not change the gateway
already used by your client. The example profile contains only Orange3; include
your other required servers if replacing a profile that supplies additional tools.

For a direct, catalog-free smoke test, use `docker run --rm -i
orange3-mcp:local`. The `server.yaml` file is the Docker MCP Registry-style
submission metadata; update its pinned commit after publishing changes before
submitting it upstream.

The image communicates over stdio, so the Toolkit gateway can expose it to
Claude Code and other MCP clients without opening a network port. The
`--long-lived` flag keeps the server available across calls. The server
stores session state under `/data/state` and workflow files under paths below
`/data`. The `longLived` setting keeps one server process available for the MCP
session, while the mounted directory preserves state if the container restarts.
The `local-server.yaml` entry supplies the volume to the runtime profile.
Importing only `docker://orange3-mcp:local` does not apply the settings from
`server.yaml`; that file is Registry submission metadata, not a runtime profile.
The runtime format is documented in Docker's
[server entry specification](https://github.com/docker/mcp-gateway/blob/main/docs/server-entry-spec.md).

## Errors in create/add workflows

`widget: Field required` means the call used `widget_id` instead of `widget`.
Use the `id` returned by `create_workflow` as `workflow_id`, for example:

```json
{"workflow_id": "<returned id>", "widget": "tree", "x": 350, "y": 50}
```

If `list_workflows` is empty immediately after creation, the calls are not seeing
the same saved state. Check the active image and gateway profile: rebuild this
checkout, use the persistent profile above, and reconnect the actual MCP client.
Retrying widget names cannot recover a missing workflow. A generic tool error
alone does not establish its cause; inspect the gateway/server error output if
the failure persists with this setup.

## Getting a downloadable .ows file

`save_workflow` writes inside the server container. A returned path such as
`/tmp/iris_classification.ows` is not accessible from a separate chat sandbox,
and `/tmp` is not preserved by the `/data` volume.

After rebuilding the image and reconnecting the MCP client to refresh its tools,
call `export_workflow` with the existing workflow ID. It returns `filename`,
`mime_type`, `encoding`, and the complete XML in `content`. The client should
write that content as UTF-8 to its own output/attachment directory and offer the
resulting `.ows` file for download. This works without a prior save and can
recover a persisted workflow even when a previously exported `/tmp` file is gone.
`save_workflow` also returns these content fields alongside its existing path.

For the workflow in the reported extraction failure:

```json
{"workflow_id": "f13191915b95"}
```

Pass this to `export_workflow`. If the workflow ID is no longer listed by
`list_workflows`, recreate the workflow or load an existing saved `.ows` first.
The server returns file content, not a hosted URL; clients without attachment
creation can present the XML for saving manually. For a persistent server-side
copy, save under `/data` rather than `/tmp`.

## Persistent direct connection

For a reproducible setup without Toolkit catalog configuration, build the image
above and configure your MCP client's stdio server with:

```json
{
  "mcpServers": {
    "orange3": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "--mount", "type=volume,source=orange3-mcp-data,target=/data",
        "orange3-mcp:local"
      ]
    }
  }
}
```

Every invocation must use the same named volume (or the same host directory
mounted at `/data`). JSON state inside an unmounted container is lost when that
container is removed, even though each create call succeeds. With shared storage,
the server reloads state for every call, so it also supports fresh processes.

After changing server code, rebuild the image and reconnect the client/gateway
so it starts the updated image. Check `create_workflow`, then `list_workflows`
and `add_node` using the returned `id`; reconnect and check `describe_workflow`
with that same ID. Workflows already lost from a removed container must be
recreated or loaded from a saved `.ows` file.
