"""MCP server exposing a selfoss instance's REST API to MCP clients.

Transports: stdio (default, for local clients) and Streamable HTTP (for
exposure behind a reverse proxy, see docker/nginx-proxy.conf). HTTP mode
requires a Bearer token because the SDK's OAuth-oriented auth machinery
would be overkill for a single static token.
"""

from __future__ import annotations

import argparse
import hmac
import os
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .client import SelfossClient, html_to_text

# Tool errors (SelfossError, httpx errors) need no wrapping: FastMCP turns any
# exception raised by a tool into an MCP tool error carrying its message.
# ponytail: tools are sync, so FastMCP runs them on the event loop and a slow
# selfoss call blocks every session; make them async or use anyio.to_thread
# if more than one client ever shares this server.
mcp = FastMCP("selfoss")
_client: SelfossClient | None = None


def get_client() -> SelfossClient:
    global _client
    if _client is None:
        _client = SelfossClient()
    return _client


def _compact_item(item: dict[str, Any], include_content: bool) -> dict[str, Any]:
    out = {
        "id": item["id"],
        "title": html_to_text(item.get("title", "")),
        "source": item.get("sourcetitle"),
        "tags": item.get("tags", []),
        "datetime": item.get("datetime"),
        "link": item.get("link"),
        "unread": item.get("unread"),
        "starred": item.get("starred"),
    }
    if include_content:
        out["content"] = html_to_text(item.get("content", ""), limit=4000)
    return out


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def get_stats() -> dict[str, Any]:
    """Total, unread and starred item counts."""
    return get_client().get_stats()


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def list_items(
    type: str = "newest",
    tag: str | None = None,
    source_id: int | None = None,
    search: str | None = None,
    offset: int = 0,
    limit: int = 50,
    updated_since: str | None = None,
    include_content: bool = False,
) -> list[dict[str, Any]]:
    """List items. type is "newest", "unread" or "starred".

    Returns compact items (title, source, tags, link, dates, unread/starred)
    by default; pass include_content=True for the plain-text body, at the
    cost of more tokens.
    """
    items = get_client().list_items(
        type=None if type == "newest" else type,
        tag=tag,
        source=source_id,
        search=search,
        offset=offset,
        items=limit,
        updatedsince=updated_since,
    )
    return [_compact_item(item, include_content) for item in items]


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False, idempotentHint=True))
def mark_read(ids: list[int]) -> None:
    """Mark one or more items as read."""
    get_client().mark(ids)


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False, idempotentHint=True))
def mark_unread(id: int) -> None:
    """Mark a single item as unread."""
    get_client().unmark(id)


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False, idempotentHint=True))
def star(id: int) -> None:
    """Star an item."""
    get_client().starr(id)


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False, idempotentHint=True))
def unstar(id: int) -> None:
    """Unstar an item."""
    get_client().unstarr(id)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def list_tags() -> list[dict[str, Any]]:
    """List tags with their colors and unread counts."""
    return get_client().list_tags()


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False, idempotentHint=True))
def set_tag_color(tag: str, color: str) -> None:
    """Set a tag's display color (any CSS color, e.g. "#ff8800")."""
    get_client().set_tag_color(tag, color)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def list_sources() -> list[dict[str, Any]]:
    """List configured sources (feeds), with their tags, filter and spout params."""
    return get_client().list_sources()


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def list_spouts() -> dict[str, Any]:
    """List available spout (source type) classes and the params each one needs."""
    return get_client().list_spouts()


@mcp.tool()
def add_source(
    url: str | None = None,
    title: str | None = None,
    spout: str = "spouts\\rss\\feed",
    tags: list[str] | None = None,
    filter: str | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Add a source. Defaults to an RSS/Atom feed at url; title is auto-detected
    if omitted. For non-RSS spouts, call list_spouts() first and pass its extra
    params via the params dict.
    """
    extra = dict(params or {})
    if url is not None:
        extra["url"] = url
    return get_client().add_source(
        spout=spout, title=title, tags=tags, filter=filter, **extra
    )


@mcp.tool()
def update_source(
    id: int,
    title: str | None = None,
    tags: list[str] | None = None,
    filter: str | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Update a source. Only given fields change; this is also how tags are
    added to or removed from a source (pass the full new tag list).
    """
    return get_client().update_source(
        id, title=title, tags=tags, filter=filter, params=params
    )


@mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
def delete_source(id: int) -> None:
    """Delete a source."""
    get_client().delete_source(id)


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False, idempotentHint=True))
def refresh_source(id: int) -> None:
    """Refresh a single source now. Uses an undocumented selfoss endpoint,
    so it is best-effort and may stop working after an upstream rebase.
    """
    get_client().refresh_source(id)


class _BearerAuthMiddleware:
    """Rejects any request without the configured Bearer token."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive)
        if not hmac.compare_digest(
            request.headers.get("authorization", ""), f"Bearer {self.token}"
        ):
            response = PlainTextResponse("Unauthorized", status_code=401)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def main() -> None:
    parser = argparse.ArgumentParser(prog="selfoss-mcp")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run(transport="stdio")
        return

    token = os.environ.get("SELFOSS_MCP_TOKEN")
    if not token:
        sys.exit("SELFOSS_MCP_TOKEN must be set to run in --transport http mode.")

    import uvicorn

    mcp.settings.host = args.host
    mcp.settings.port = args.port
    # FastMCP("selfoss") was built with its default host 127.0.0.1, which
    # enabled DNS-rebinding protection with a localhost-only Host allowlist,
    # whatever --host says. Extend it with the reverse proxy's public host(s),
    # otherwise proxied requests get 421 Invalid Host header.
    extra_hosts = [
        h.strip()
        for h in os.environ.get("SELFOSS_MCP_ALLOWED_HOSTS", "").split(",")
        if h.strip()
    ]
    security = mcp.settings.transport_security
    if security is not None and extra_hosts:
        security.allowed_hosts += extra_hosts
        security.allowed_origins += [f"https://{h}" for h in extra_hosts]
    app = _BearerAuthMiddleware(mcp.streamable_http_app(), token)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
