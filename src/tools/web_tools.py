"""
Bonus / lab extension: lightweight web search and Wikipedia lookup (no API keys).
Requires network. DuckDuckGo + Wikipedia; sends a proper User-Agent for API policy.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

WIKI_API = "https://en.wikipedia.org/w/api.php"


def _requests():
    """Lazy import so `import src.tools.registry` works before `pip install requests`."""
    try:
        import requests as req
    except ImportError as e:
        raise ImportError(
            "Install the 'requests' package: pip install requests"
        ) from e
    return req

# Wikipedia and many APIs block requests without a descriptive User-Agent.
HTTP_HEADERS = {
    "User-Agent": "VinUni-AI-Lab/1.0 (educational project; python requests)",
    "Accept": "application/json",
}


def _ddg_instant_answer(query: str) -> List[Dict[str, str]]:
    """Fallback: DuckDuckGo instant answer JSON (no HTML)."""
    try:
        requests = _requests()
    except ImportError:
        return []
    r = requests.get(
        "https://api.duckduckgo.com/",
        params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"},
        headers=HTTP_HEADERS,
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    out: List[Dict[str, str]] = []
    if data.get("AbstractText"):
        out.append(
            {
                "title": data.get("Heading") or query,
                "href": data.get("AbstractURL") or "",
                "body": (data.get("AbstractText") or "")[:800],
            }
        )
    for topic in (data.get("RelatedTopics") or [])[:5]:
        if isinstance(topic, dict) and topic.get("Text"):
            out.append(
                {
                    "title": topic.get("Text", "")[:120],
                    "href": topic.get("FirstURL") or "",
                    "body": topic.get("Text", "")[:600],
                }
            )
    return out


def web_search(query: str, max_results: int = 3) -> str:
    """
    Web search: try DuckDuckGo text results; if empty, use instant-answer API.
    """
    q = (query or "").strip()
    if not q:
        return json.dumps({"error": "empty_query"})
    n = max(1, min(10, int(max_results)))
    rows: List[Dict[str, str]] = []
    try:
        from duckduckgo_search import DDGS

        with DDGS() as ddgs:
            rows = list(ddgs.text(q, max_results=n))
        out = [
            {
                "title": r.get("title", ""),
                "href": r.get("href", ""),
                "body": (r.get("body") or "")[:600],
            }
            for r in rows
        ]
        if not out:
            out = _ddg_instant_answer(q)[:n]
        return json.dumps({"query": q, "results": out, "count": len(out), "source": "ddg"})
    except Exception as e:
        try:
            out = _ddg_instant_answer(q)[:n]
            return json.dumps(
                {
                    "query": q,
                    "results": out,
                    "count": len(out),
                    "source": "ddg_instant",
                    "note": f"text_search_failed: {e!s}",
                }
            )
        except Exception as e2:
            return json.dumps(
                {"error": "web_search_failed", "detail": str(e2), "query": q, "first_error": str(e)}
            )


def wikipedia_search(query: str) -> str:
    """
    Wikipedia opensearch: titles + snippets (read-only).
    """
    q = (query or "").strip()
    if not q:
        return json.dumps({"error": "empty_query"})
    try:
        requests = _requests()
    except ImportError as e:
        return json.dumps({"error": "missing_dependency", "detail": str(e)})
    try:
        params = {
            "action": "opensearch",
            "search": q,
            "limit": 5,
            "namespace": 0,
            "format": "json",
        }
        r = requests.get(WIKI_API, params=params, headers=HTTP_HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()
        titles = data[1] if len(data) > 1 else []
        descs = data[2] if len(data) > 2 else []
        urls = data[3] if len(data) > 3 else []
        items = [
            {"title": t, "snippet": d, "url": u}
            for t, d, u in zip(titles, descs, urls)
        ]
        return json.dumps({"query": q, "results": items, "count": len(items)})
    except Exception as e:
        return json.dumps({"error": "wikipedia_search_failed", "detail": str(e), "query": q})


WEB_META: List[Dict[str, Any]] = [
    {
        "name": "web_search",
        "description": (
            "Search the public web via DuckDuckGo. Returns titles, URLs, and short snippets. "
            "Use for real-world facts, news, or prices not in the local mock catalog."
        ),
        "args_format": 'query: string; max_results: optional number 1-10 (default 3).',
    },
    {
        "name": "wikipedia_search",
        "description": (
            "Search Wikipedia (English) for article titles and short descriptions. "
            "Good for definitions and background; not a full web browser."
        ),
        "args_format": "query: string.",
    },
]
