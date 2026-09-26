"""Drives the MCP tool functions against a real selfoss instance.

Reuses the repo's existing Python integration harness (tests/integration/helpers)
instead of duplicating it: this file is not shipped as part of selfoss-mcp, so
depending on a path outside mcp/ does not affect the package itself.
"""

import os
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "tests" / "integration"))
sys.path.insert(0, str(_REPO_ROOT / "mcp"))

from helpers.data_server import FIBONACCI_FEED_LENGTH  # noqa: E402
from helpers.integration import SelfossIntegration  # noqa: E402

from selfoss_mcp import server as selfoss_mcp_server  # noqa: E402


class ToolWorkflowTest(SelfossIntegration):
    def setUp(self) -> None:
        super().setUp()
        os.environ["SELFOSS_URL"] = (
            f"http://{self.selfoss_host_name}:{self.selfoss_port}"
        )
        os.environ["SELFOSS_USERNAME"] = self.selfoss_username
        os.environ["SELFOSS_PASSWORD"] = self.selfoss_password
        # Force a fresh SelfossClient bound to the instance started above.
        selfoss_mcp_server._client = None

    def test_tool_workflow(self) -> None:
        s = selfoss_mcp_server

        fibonacci_feed_uri = (
            f"http://{self.data_host_name}:{self.data_port}/fibonacci.xml"
        )
        source = s.add_source(url=fibonacci_feed_uri)
        self.assertTrue(source["success"])
        self.assertEqual(source["title"], "20 numbers")
        source_id = source["id"]

        s.refresh_source(source_id)

        items = s.list_items(type="newest", limit=100)
        self.assertEqual(len(items), FIBONACCI_FEED_LENGTH)
        self.assertTrue(items[0]["unread"])
        self.assertFalse(items[0]["starred"])

        s.mark_read([items[0]["id"]])
        s.star(items[0]["id"])
        items = s.list_items(type="newest", limit=100)
        self.assertFalse(items[0]["unread"])
        self.assertTrue(items[0]["starred"])

        starred = s.list_items(type="starred")
        self.assertEqual([i["id"] for i in starred], [items[0]["id"]])

        s.update_source(source_id, tags=["fibonacci"])
        tagged = s.list_items(tag="fibonacci", limit=100)
        self.assertEqual(len(tagged), FIBONACCI_FEED_LENGTH)

        s.set_tag_color("fibonacci", "#ff8800")
        tags = s.list_tags()
        self.assertIn("fibonacci", [t["tag"] for t in tags])

        s.delete_source(source_id)
        self.assertEqual(s.list_sources(), [])


if __name__ == "__main__":
    unittest.main()
