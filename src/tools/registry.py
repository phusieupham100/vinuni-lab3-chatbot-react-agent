"""
Unified tool registry: e-commerce mocks + web search / Wikipedia (bonus tools).
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from src.tools import ecommerce
from src.tools.web_tools import WEB_META, web_search, wikipedia_search


def get_tool_specs_for_prompt() -> List[Dict[str, str]]:
    base = ecommerce.get_tool_specs_for_prompt()
    extra = [
        {"name": m["name"], "description": m["description"], "args": m["args_format"]}
        for m in WEB_META
    ]
    return base + extra


def get_tool_by_name(name: str) -> Optional[Dict[str, Any]]:
    t = ecommerce.get_tool_by_name(name)
    if t:
        return t
    for m in WEB_META:
        if m["name"] == name:
            return m  # type: ignore[return-value]
    return None


def dispatch_tool(name: str, arguments: Dict[str, Any]) -> str:
    if name == "web_search":
        try:
            q = arguments["query"]
        except KeyError as e:
            return json.dumps({"error": "missing_argument", "detail": str(e)})
        mr = arguments.get("max_results", 3)
        try:
            mr_int = int(mr)
        except (TypeError, ValueError):
            mr_int = 3
        return web_search(str(q), max_results=mr_int)

    if name == "wikipedia_search":
        try:
            q = arguments["query"]
        except KeyError as e:
            return json.dumps({"error": "missing_argument", "detail": str(e)})
        return wikipedia_search(str(q))

    return ecommerce.dispatch_tool(name, arguments)
