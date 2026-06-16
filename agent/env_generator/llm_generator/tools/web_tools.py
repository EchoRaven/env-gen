"""General web search and fetch tools for agents."""

from __future__ import annotations

import asyncio
import html
import ipaddress
import json
import re
import socket
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional

from utils.tool import BaseTool, ToolCategory, ToolResult, create_tool_param


DEFAULT_USER_AGENT = "env-gen-agent/1.0 (+https://example.invalid)"
MAX_FETCH_BYTES = 2_000_000

_ALLOWED_SCHEMES = {"http", "https"}


def _ssrf_check(url: str) -> Optional[str]:
    """Return None if URL is safe to fetch; else return a rejection reason string.

    Blocks: non-http(s) schemes, loopback, link-local, RFC1918 private,
    ULA IPv6, multicast, AWS instance metadata (169.254.169.254 is link-local).
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception as e:
        return f"unparseable URL: {e}"
    if (parsed.scheme or "").lower() not in _ALLOWED_SCHEMES:
        return f"scheme {parsed.scheme!r} not allowed (only http/https)"
    host = parsed.hostname
    if not host:
        return "URL has no hostname"
    # Resolve hostname to IP and check every resolved address.
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as e:
        return f"hostname resolution failed: {e}"
    for info in infos:
        ip_str = info[4][0]
        # Strip IPv6 scope ids like "fe80::1%eth0" before parsing.
        if "%" in ip_str:
            ip_str = ip_str.split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if (ip.is_loopback or ip.is_private or ip.is_link_local
                or ip.is_multicast or ip.is_reserved or ip.is_unspecified):
            return f"resolved IP {ip_str} is in a restricted range"
    return None


class _ReadableHTMLParser(HTMLParser):
    """Small dependency-free text extractor for fetched HTML pages."""

    _SKIP_TAGS = {"script", "style", "noscript", "svg", "canvas"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._title_parts: List[str] = []
        self._text_parts: List[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag in {"p", "div", "section", "article", "li", "br", "h1", "h2", "h3"}:
            self._text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False
            self.title = _clean_text(" ".join(self._title_parts))

    def handle_data(self, data: str) -> None:
        if not data or self._skip_depth:
            return
        if self._in_title:
            self._title_parts.append(data)
        self._text_parts.append(data)

    @property
    def text(self) -> str:
        return _clean_text(" ".join(self._text_parts))


class _DuckDuckGoParser(HTMLParser):
    """Parse DuckDuckGo HTML results without adding third-party dependencies."""

    def __init__(self, limit: int) -> None:
        super().__init__(convert_charrefs=True)
        self.limit = limit
        self.results: List[Dict[str, str]] = []
        self._current: Optional[Dict[str, str]] = None
        self._capture_title = False
        self._capture_snippet = False
        self._parts: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        attrs_dict = dict(attrs)
        classes = set((attrs_dict.get("class") or "").split())
        if tag == "a" and "result__a" in classes:
            href = _decode_ddg_href(attrs_dict.get("href") or "")
            self._current = {"title": "", "url": href, "snippet": ""}
            self._capture_title = True
            self._parts = []
        elif self._current is not None and "result__snippet" in classes:
            self._capture_snippet = True
            self._parts = []

    def handle_endtag(self, tag: str) -> None:
        if self._capture_title and tag == "a" and self._current is not None:
            self._current["title"] = _clean_text(" ".join(self._parts))
            self._capture_title = False
            self._parts = []
            if self._current.get("url") and len(self.results) < self.limit:
                self.results.append(self._current)
            self._current = None
        elif self._capture_snippet and tag in {"a", "div"}:
            if self.results:
                self.results[-1]["snippet"] = _clean_text(" ".join(self._parts))
            self._capture_snippet = False
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._capture_title or self._capture_snippet:
            self._parts.append(data)


def _clean_text(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _decode_ddg_href(href: str) -> str:
    if not href:
        return ""
    decoded = html.unescape(href)
    parsed = urllib.parse.urlparse(decoded)
    query = urllib.parse.parse_qs(parsed.query)
    if "uddg" in query and query["uddg"]:
        return query["uddg"][0]
    return decoded


def _read_url(url: str, *, timeout: float, max_bytes: int = MAX_FETCH_BYTES) -> tuple[str, str, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/json,text/plain;q=0.9,*/*;q=0.1",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content_type = response.headers.get("content-type", "")
        charset = response.headers.get_content_charset() or "utf-8"
        raw = response.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raw = raw[:max_bytes]
        final_url = response.geturl()
    return raw.decode(charset, errors="replace"), content_type, final_url


class WebSearchTool(BaseTool):
    """Search the public web for text results."""

    NAME = "web_search"
    DESCRIPTION = """Search the public web for current text information.

Use for external docs, examples, release notes, package information, or general facts.
Results are concise snippets and URLs. Use web_fetch(url=...) for full page text.
"""

    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.SEARCH)

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {"type": "integer", "description": "Maximum results, 1-10 (default: 5)"},
                },
                "required": ["query"],
            },
        )

    async def execute(self, query: str, limit: int = 5) -> ToolResult:
        query = str(query or "").strip()
        if not query:
            return ToolResult.fail("query is required")
        result_limit = max(1, min(10, int(limit or 5)))
        url = "https://duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})

        try:
            text, _content_type, final_url = await asyncio.to_thread(_read_url, url, timeout=15.0)
            parser = _DuckDuckGoParser(limit=result_limit)
            parser.feed(text)
            return ToolResult.ok(data={
                "query": query,
                "results": parser.results[:result_limit],
                "count": len(parser.results[:result_limit]),
                "source": final_url,
            })
        except Exception as e:
            return ToolResult.fail(f"web_search failed: {e}")


class WebFetchTool(BaseTool):
    """Fetch a web page and return readable text."""

    NAME = "web_fetch"
    DESCRIPTION = """Fetch a URL and return readable text content.

Use after web_search when an agent needs page details. This tool has size and
timeout limits and strips scripts/styles from HTML.
"""

    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.SEARCH)

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "HTTP or HTTPS URL to fetch"},
                    "max_chars": {"type": "integer", "description": "Max returned text chars, 500-20000 (default: 8000)"},
                },
                "required": ["url"],
            },
        )

    async def execute(self, url: str, max_chars: int = 8000) -> ToolResult:
        raw_url = str(url or "").strip()
        reason = _ssrf_check(raw_url)
        if reason is not None:
            return ToolResult.fail(f"refused for safety: {reason}")
        char_limit = max(500, min(20000, int(max_chars or 8000)))

        try:
            body, content_type, final_url = await asyncio.to_thread(_read_url, raw_url, timeout=15.0)
            title = ""
            if "html" in content_type.lower() or "<html" in body[:500].lower():
                parser = _ReadableHTMLParser()
                parser.feed(body)
                title = parser.title
                text = parser.text
            elif "json" in content_type.lower():
                try:
                    text = json.dumps(json.loads(body), indent=2, ensure_ascii=False)
                except Exception:
                    text = body
            else:
                text = body
            text = _clean_text(text)
            truncated = len(text) > char_limit
            return ToolResult.ok(data={
                "url": raw_url,
                "final_url": final_url,
                "content_type": content_type,
                "title": title,
                "text": text[:char_limit],
                "truncated": truncated,
                "chars": min(len(text), char_limit),
            })
        except Exception as e:
            return ToolResult.fail(f"web_fetch failed: {e}")


def create_web_tools() -> List[BaseTool]:
    """Create general web tools."""
    return [WebSearchTool(), WebFetchTool()]


__all__ = ["WebSearchTool", "WebFetchTool", "create_web_tools"]
