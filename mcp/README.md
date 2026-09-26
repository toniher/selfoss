# selfoss-mcp

MCP server exposing a selfoss instance to MCP clients (Claude Code, Claude
Desktop, etc.): read newest/unread/starred items, mark/star them, manage
tags, and add/edit/delete sources. It is a thin client of selfoss's
documented REST API (`docs/api-description.json`), so it needs no changes
to the PHP or client code.

## Configuration

Environment variables:

- `SELFOSS_URL` (required): base URL of the selfoss instance, e.g. `http://127.0.0.1:8000`.
- `SELFOSS_USERNAME` / `SELFOSS_PASSWORD` (optional): omit if selfoss runs with no login,
  or if you rely on its trusted-localhost bypass (not recommended over a network).
- `SELFOSS_MCP_TOKEN` (required only for `--transport http`): Bearer token clients must send.

## Running

```sh
cd mcp
uv sync
uv run selfoss-mcp                                   # stdio, for local clients
uv run selfoss-mcp --transport http --host 127.0.0.1 --port 8765
```

### Claude Code

```sh
claude mcp add selfoss -e SELFOSS_URL=http://127.0.0.1:8000 -- uv run --directory mcp selfoss-mcp
```

### Exposing HTTP mode behind a reverse proxy

Bind `--host 127.0.0.1` (the default) and put a reverse proxy in front; see
`docker/nginx-proxy.conf` in the repo root for a ready-to-adapt `location /mcp`
block (Bearer token pass-through, buffering off for streaming responses).

## Tests

`tests/test_e2e.py` reuses the repo's existing Python integration harness
(`tests/integration/helpers`) to spin up a real selfoss instance and a test
feed server, then drives the MCP tool functions directly:

```sh
SELFOSS_TEST_STORAGE_BACKEND=sqlite uv run --with-editable . python -m pytest mcp/tests
```

## Docker

See the `docker/` directory in the repo root: `docker/compose.yaml` runs
this server next to a selfoss image built from this checkout.
