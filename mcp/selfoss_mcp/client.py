"""Thin client for selfoss's documented REST API (docs/api-description.json)."""

from __future__ import annotations

import os
from html.parser import HTMLParser
from typing import Any

import httpx


class SelfossError(RuntimeError):
    """Raised for selfoss API errors: HTTP errors, jsonError payloads, failed login."""


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.chunks: list[str] = []

    def handle_data(self, data: str) -> None:
        self.chunks.append(data)


def html_to_text(markup: str, limit: int | None = None) -> str:
    """Strip HTML tags and collapse whitespace, for token-cheap tool output."""
    parser = _TextExtractor()
    parser.feed(markup or "")
    text = " ".join("".join(parser.chunks).split())
    if limit is not None and len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return text


class SelfossClient:
    """Thin wrapper around the selfoss REST API described in docs/api-description.json."""

    SUPPORTED_APIVERSION_MAJOR = 8

    def __init__(
        self,
        base_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self.base_url = (base_url or os.environ["SELFOSS_URL"]).rstrip("/")
        self.username = (
            username if username is not None else os.environ.get("SELFOSS_USERNAME")
        )
        self.password = (
            password if password is not None else os.environ.get("SELFOSS_PASSWORD")
        )
        self._http = httpx.Client(base_url=self.base_url, timeout=30.0)
        self._logged_in = False
        self._version_checked = False
        # Managed by hand instead of relying on httpx's cookie jar: PHP sets
        # the session cookie's Domain to the bare hostname (e.g. "selfoss" on
        # a compose network), and stdlib http.cookiejar silently refuses to
        # send back cookies for a domain with no dot in it.
        self._session_cookie: str | None = None

    def _check_version(self) -> None:
        if self._version_checked:
            return
        resp = self._http.get("/api/about")
        resp.raise_for_status()
        apiversion = resp.json().get("apiversion", "0.0.0")
        major = int(apiversion.split(".")[0])
        if major != self.SUPPORTED_APIVERSION_MAJOR:
            raise SelfossError(
                f"selfoss reports apiversion {apiversion}, but this server was written against "
                f"apiversion {self.SUPPORTED_APIVERSION_MAJOR}.x. The documented API may have "
                "changed; check docs/api-description.json after the next rebase."
            )
        self._version_checked = True

    def _remember_session_cookie(self, resp: httpx.Response) -> None:
        sid = resp.cookies.get("PHPSESSID")
        if sid:
            self._session_cookie = sid

    def _login(self) -> None:
        if self._logged_in or not self.username:
            return
        resp = self._http.post(
            "/login", data={"username": self.username, "password": self.password or ""}
        )
        resp.raise_for_status()
        if not resp.json().get("success"):
            raise SelfossError(
                "selfoss login failed: check SELFOSS_USERNAME/SELFOSS_PASSWORD."
            )
        self._remember_session_cookie(resp)
        self._logged_in = True

    def _do_request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        if self._session_cookie:
            kwargs["cookies"] = {
                **kwargs.get("cookies", {}),
                "PHPSESSID": self._session_cookie,
            }
        resp = self._http.request(method, path, **kwargs)
        self._remember_session_cookie(resp)
        return resp

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        self._check_version()
        self._login()
        resp = self._do_request(method, path, **kwargs)
        if resp.status_code == 403 and self.username:
            # Session cookie may have expired; retry once after a fresh login.
            self._logged_in = False
            self._login()
            resp = self._do_request(method, path, **kwargs)
        if resp.status_code >= 400:
            try:
                payload = resp.json()
            except ValueError:
                payload = None
            if isinstance(payload, dict) and "error" in payload:
                raise SelfossError(str(payload["error"]))
            resp.raise_for_status()
        return resp

    # -- Items -----------------------------------------------------------------

    def get_stats(self) -> dict:
        return self._request("GET", "/stats").json()

    def list_items(
        self,
        type: str | None = None,
        tag: str | None = None,
        source: int | None = None,
        search: str | None = None,
        offset: int = 0,
        items: int = 50,
        updatedsince: str | None = None,
    ) -> list[dict]:
        params: dict[str, object] = {"offset": offset, "items": min(items, 200)}
        if type is not None:
            params["type"] = type
        if tag is not None:
            params["tag"] = tag
        if source is not None:
            params["source"] = source
        if search is not None:
            params["search"] = search
        if updatedsince is not None:
            params["updatedsince"] = updatedsince
        return self._request("GET", "/items", params=params).json()

    def mark(self, ids: list[int]) -> None:
        self._request("POST", "/mark", json=[int(i) for i in ids])

    def unmark(self, id: int) -> None:
        self._request("POST", f"/unmark/{int(id)}")

    def starr(self, id: int) -> None:
        self._request("POST", f"/starr/{int(id)}")

    def unstarr(self, id: int) -> None:
        self._request("POST", f"/unstarr/{int(id)}")

    # -- Tags --------------------------------------------------------------------

    def list_tags(self) -> list[dict]:
        return self._request("GET", "/tags").json()

    def set_tag_color(self, tag: str, color: str) -> None:
        self._request("POST", "/tags/color", json={"tag": tag, "color": color})

    # -- Sources -------------------------------------------------------------------

    def list_sources(self) -> list[dict]:
        return self._request("GET", "/sources/list").json()

    def list_spouts(self) -> dict:
        return self._request("GET", "/sources/spouts").json()

    def add_source(
        self,
        spout: str = "spouts\\rss\\feed",
        title: str | None = None,
        tags: list[str] | None = None,
        filter: str | None = None,
        **params: object,
    ) -> dict:
        payload: dict[str, object] = {"spout": spout, **params}
        if title is not None:
            payload["title"] = title
        if tags is not None:
            payload["tags"] = list(tags)
        if filter is not None:
            payload["filter"] = filter
        return self._request("POST", "/source", json=payload).json()

    def update_source(
        self,
        id: int,
        title: str | None = None,
        tags: list[str] | None = None,
        filter: str | None = None,
        params: dict | None = None,
    ) -> dict:
        current = next((s for s in self.list_sources() if s["id"] == id), None)
        if current is None:
            raise SelfossError(f"No source with id {id}.")
        # /source/{id} replaces the whole record, so unset fields are carried over from the current one.
        payload = {
            "spout": current["spout"],
            "title": title if title is not None else current["title"],
            "tags": list(tags) if tags is not None else current.get("tags", []),
            "filter": filter if filter is not None else current.get("filter"),
            **(current.get("params") or {}),
            **(params or {}),
        }
        return self._request("POST", f"/source/{int(id)}", json=payload).json()

    def delete_source(self, id: int) -> None:
        self._request("DELETE", f"/source/{int(id)}")

    def refresh_source(self, id: int) -> None:
        # Undocumented endpoint (not in docs/api-description.json); best-effort.
        self._request("POST", f"/source/{int(id)}/update")
