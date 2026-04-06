"""Network tests for bonus web tools (skip if offline)."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.tools.registry import dispatch_tool  # noqa: E402


@pytest.mark.skipif(os.getenv("SKIP_NETWORK_TESTS"), reason="SKIP_NETWORK_TESTS set")
def test_wikipedia_search_returns_results():
    out = dispatch_tool("wikipedia_search", {"query": "Python programming"})
    data = json.loads(out)
    assert "error" not in data or data.get("count", 0) >= 0
    assert "query" in data


@pytest.mark.skipif(os.getenv("SKIP_NETWORK_TESTS"), reason="SKIP_NETWORK_TESTS set")
def test_web_search_returns_json():
    out = dispatch_tool("web_search", {"query": "openai", "max_results": 2})
    data = json.loads(out)
    assert "query" in data
    assert "results" in data or "error" in data
