"""Web fetch. Off by default -- enable the 'web' toolset to use it."""

import requests

from .base import tool, Risk, ToolError

MAX_CHARS = 40_000


@tool(toolset="web", risk=Risk.EXEC)
def fetch_url(url: str) -> dict:
    """Fetch a URL and return its text content.

    Args:
        url: Absolute http(s) URL to fetch.
    """
    if not url.startswith(("http://", "https://")):
        raise ToolError("URL must start with http:// or https://")

    try:
        resp = requests.get(url, timeout=20, headers={"User-Agent": "hermes-agent/1.0"})
    except requests.RequestException as e:
        raise ToolError(f"Request failed: {e}")

    text = resp.text
    return {
        "url": resp.url,
        "status": resp.status_code,
        "content_type": resp.headers.get("content-type", ""),
        "content": text[:MAX_CHARS],
        "truncated": len(text) > MAX_CHARS,
    }
