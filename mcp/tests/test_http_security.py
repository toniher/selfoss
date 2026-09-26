"""Checks the HTTP transport's Bearer token and Host/Origin allowlist.

Needs no selfoss instance: requests stop at `initialize`, which never calls it.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from starlette.testclient import TestClient  # noqa: E402

from selfoss_mcp import server  # noqa: E402

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1"},
    },
}


class HttpSecurityTest(unittest.TestCase):
    def test_allowlist_and_token(self) -> None:
        env = {
            "SELFOSS_URL": "http://selfoss.invalid",
            "SELFOSS_MCP_TOKEN": "tok",
            "SELFOSS_MCP_ALLOWED_HOSTS": "rss.example.org",
        }
        argv = ["selfoss-mcp", "--transport", "http", "--host", "0.0.0.0"]
        with (
            mock.patch.dict(os.environ, env),
            mock.patch.object(sys, "argv", argv),
            mock.patch("uvicorn.run") as run,
        ):
            server.main()
        app = run.call_args.args[0]

        base = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "Authorization": "Bearer tok",
        }
        cases = [
            ("proxied host", {"Host": "rss.example.org"}, 200),
            ("localhost", {"Host": "127.0.0.1:8765"}, 200),
            ("other host", {"Host": "evil.example"}, 421),
            (
                "other origin",
                {"Host": "rss.example.org", "Origin": "https://evil.example"},
                403,
            ),
            ("no token", {"Host": "rss.example.org", "Authorization": ""}, 401),
        ]
        with TestClient(app) as client:
            for name, headers, status in cases:
                with self.subTest(name):
                    response = client.post(
                        "/mcp", headers={**base, **headers}, json=INITIALIZE
                    )
                    self.assertEqual(response.status_code, status)


if __name__ == "__main__":
    unittest.main()
