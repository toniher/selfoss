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

## Tools

| Tool | What it does |
|------|--------------|
| `get_stats()` | Total, unread and starred item counts. |
| `list_items(type, tag, source_id, search, offset, limit, updated_since, include_content)` | Lists items. `type` is `newest` (default), `unread` or `starred`. `limit` defaults to 50, max 200. |
| `mark_read(ids)` | Marks a list of items as read. |
| `mark_unread(id)` | Marks one item as unread. |
| `star(id)` / `unstar(id)` | Stars or unstars one item. |
| `list_tags()` | Tags with their colors and unread counts. |
| `set_tag_color(tag, color)` | Sets a tag's color. Takes any CSS color, e.g. `#ff8800`. |
| `list_sources()` | Sources with their tags, filter and spout params. |
| `list_spouts()` | Source types (spouts) and the params each one needs. |
| `add_source(url, title, spout, tags, filter, params)` | Adds an RSS/Atom feed at `url`. selfoss detects the title if you omit it. For other spouts, pass their params in `params`. |
| `update_source(id, title, tags, filter, params)` | Changes the fields you pass and keeps the rest. To add or remove tags, pass the full new tag list. |
| `delete_source(id)` | Deletes a source. |
| `refresh_source(id)` | Fetches one source now. |

`list_items` returns id, title, source, tags, date, link and the read/starred
flags. Pass `include_content=True` to add the item text as plain text, cut at
4000 characters.

Clients see the read-only tools marked `readOnlyHint` and `delete_source`
marked `destructiveHint`, so they can auto-approve the first group and ask you
before a delete.

`refresh_source` calls `POST /source/{id}/update`, which
`docs/api-description.json` does not document. A rebase on upstream can
break it. selfoss also skips a refresh that arrives within 20 seconds of the
last one.

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
