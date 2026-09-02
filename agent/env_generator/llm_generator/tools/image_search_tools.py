"""
Image Tools - Search, download, and capture images

Available tools:
- search_icons: Find icons and SVGs from Iconify
- search_photos: Find photos and UI screenshots via Google
- search_logos: Find company/brand logos
- save_image: Download any image URL to workspace
- capture_webpage: Take screenshot of live webpage
"""

import asyncio
import ipaddress
import logging
import re
import socket
import urllib.parse
from pathlib import Path
from typing import Optional, List, Dict, Any

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.tool import BaseTool, ToolResult, create_tool_param, ToolCategory
from workspace import Workspace


# SSRF guard — kept in sync with tools/web_tools.py::_ssrf_check via grep.
# Duplicated rather than imported to avoid cross-module coupling for a
# small, security-critical helper.
_ALLOWED_SCHEMES = {"http", "https"}


def _ssrf_check(url: str) -> Optional[str]:
    """Return None if URL is safe to fetch; else a rejection reason string.

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
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as e:
        return f"hostname resolution failed: {e}"
    for info in infos:
        ip_str = info[4][0]
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


# =============================================================================
# 1. ICON SEARCH - Iconify API for icons and SVGs
# =============================================================================

_CAPTURE_DIR = "design/captures"


def _redirect_readonly_capture_path(path: str) -> str:
    """Move a `screenshots/...` capture target into the writable capture dir.

    `screenshots/` is READ-ONLY in ROUTING_TABLE on purpose: it holds the
    ground-truth references the visual gate diffs against, so opening it would
    let a lane overwrite its own exam. But this tool used to advertise
    `screenshots/<domain>.png`, which taught agents to aim there -- denied
    across 23 distinct runs, always the frontend lane, defeating FIX #110 (the
    frontend must SEE its own render before self-certifying fidelity).

    Redirect rather than refuse: the agent is doing the right thing with the
    directory the schema told it to use, and a hard failure costs a turn to
    rediscover. The caller reports the redirect, so nothing is silent.
    """
    if not path:
        return path
    raw = str(path).lstrip("/")
    if raw == "screenshots" or raw.startswith("screenshots/"):
        from pathlib import Path as _P
        return f"{_CAPTURE_DIR}/{_P(raw).name}"
    return path


class IconSearchTool(BaseTool):
    """Search for icons and SVGs using Iconify API (100+ icon sets)."""
    
    NAME = "search_icons"
    
    DESCRIPTION = """Search for icons and SVGs.

Find icons from 100+ icon sets including Material Design, FontAwesome, Heroicons, etc.

Examples:
    search_icons "hamburger menu"
    search_icons "shopping cart"
    search_icons "notification bell"
    search_icons "user avatar"
    search_icons "arrow right"

Returns SVG URLs that can be saved with save_image tool.

Note: For photos/screenshots, use search_photos instead.
Note: For company logos, use search_logos instead.
"""
    
    def __init__(self, *, workspace: Workspace):
        super().__init__(name=self.NAME, category=ToolCategory.FILE)
        if workspace is None:
            raise ValueError(f"{self.NAME}: workspace is required (no bypass construction)")
        self.workspace = workspace
        self._logger = logging.getLogger(__name__)
    
    @property
    def tool_definition(self):
        return self.get_tool_param()
    
    def get_tool_param(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Icon to search for (e.g., 'shopping cart', 'menu', 'user')"
                    },
                    "style": {
                        "type": "string",
                        "enum": ["any", "outline", "filled", "rounded"],
                        "description": "Icon style preference (default: any)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default: 10)"
                    }
                },
                "required": ["query"]
            }
        )
    
    async def execute(self, query: str, style: str = "any", limit: int = 10) -> ToolResult:
        """Search Iconify for icons"""
        try:
            import aiohttp
            import ssl
            import certifi
        except ImportError:
            return ToolResult(
                success=False,
                error_message="Missing dependency. Run: pip install aiohttp certifi"
            )
        
        try:
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            
            async with aiohttp.ClientSession(connector=connector) as session:
                # Build query with style preference
                search_query = query
                if style != "any":
                    search_query = f"{query} {style}"
                
                encoded_query = urllib.parse.quote(search_query)
                url = f"https://api.iconify.design/search?query={encoded_query}&limit={limit}"
                
                async with session.get(url, timeout=10) as resp:
                    if resp.status != 200:
                        return ToolResult(success=False, error_message=f"Iconify API error: HTTP {resp.status}")
                    
                    data = await resp.json()
                    icons = data.get("icons", [])
                    
                    if not icons:
                        return ToolResult(
                            success=True,
                            data={
                                "query": query,
                                "results": [],
                                "count": 0,
                                "hint": f"No icons found for '{query}'. Try simpler keywords like 'cart', 'menu', 'user'."
                            }
                        )
                    
                    results = []
                    for icon in icons[:limit]:
                        parts = icon.split(":")
                        if len(parts) == 2:
                            prefix, name = parts
                            results.append({
                                "name": f"{prefix}:{name}",
                                "url": f"https://api.iconify.design/{prefix}/{name}.svg",
                                "preview": f"https://api.iconify.design/{prefix}/{name}.svg?width=64",
                                "set": prefix,
                                "format": "svg"
                            })
                    
                    return ToolResult(
                        success=True,
                        data={
                            "query": query,
                            "results": results,
                            "count": len(results),
                            "hint": "Use save_image to download: save_image <url> <path>"
                        }
                    )
                    
        except asyncio.TimeoutError:
            return ToolResult(success=False, error_message="Search timed out (10s)")
        except Exception as e:
            self._logger.error(f"Icon search failed: {e}")
            return ToolResult(success=False, error_message=f"Search failed: {e}")


# =============================================================================
# 2. PHOTO SEARCH - Google Custom Search API for photos and screenshots
# =============================================================================

class PhotoSearchTool(BaseTool):
    """Search for photos and UI screenshots using Google Custom Search."""
    
    NAME = "search_photos"
    
    DESCRIPTION = """Search for photos, screenshots, and UI designs.

The most powerful image search - finds real photos, app screenshots, and UI references.

Examples:
    search_photos "food delivery app screenshot"
    search_photos "restaurant website design"
    search_photos "mobile app checkout flow"
    search_photos "dashboard UI dark mode"
    search_photos "login page modern design"

Best for:
- Real-world UI/UX references
- App and website screenshots
- Design inspiration
- Stock photos

Requires GOOGLE_API_KEY and GOOGLE_CX environment variables.
Use search_icons for icons, search_logos for company logos.
"""
    
    def __init__(self, *, workspace: Workspace, api_key: Optional[str] = None, cx: Optional[str] = None):
        super().__init__(name=self.NAME, category=ToolCategory.FILE)
        if workspace is None:
            raise ValueError(f"{self.NAME}: workspace is required (no bypass construction)")
        self.workspace = workspace
        self._logger = logging.getLogger(__name__)
        
        import os
        self.api_key = api_key or os.environ.get("GOOGLE_IMAGE_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self.cx = cx or os.environ.get("GOOGLE_CX")
    
    @property
    def tool_definition(self):
        return self.get_tool_param()
    
    def get_tool_param(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search for (be specific, e.g., 'uber eats app home screen')"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default: 10, max: 10)"
                    },
                    "size": {
                        "type": "string",
                        "enum": ["any", "large", "medium", "small"],
                        "description": "Image size preference (default: any)"
                    }
                },
                "required": ["query"]
            }
        )
    
    async def execute(self, query: str, limit: int = 10, size: str = "any") -> ToolResult:
        """Search Google for photos"""
        
        if not self.api_key or not self.cx:
            return ToolResult(
                success=False,
                error_message="Google API not configured. Set GOOGLE_API_KEY and GOOGLE_CX environment variables.\nGet credentials at: https://programmablesearchengine.google.com/"
            )
        
        try:
            import aiohttp
            import ssl
            import certifi
        except ImportError:
            return ToolResult(
                success=False,
                error_message="Missing dependency. Run: pip install aiohttp certifi"
            )
        
        # Build API request
        params = {
            "key": self.api_key,
            "cx": self.cx,
            "q": query,
            "searchType": "image",
            "num": min(limit, 10),
        }
        
        if size != "any":
            size_map = {"large": "huge", "medium": "medium", "small": "icon"}
            params["imgSize"] = size_map.get(size, "")
        
        try:
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            
            async with aiohttp.ClientSession(connector=connector) as session:
                url = f"https://www.googleapis.com/customsearch/v1?{urllib.parse.urlencode(params)}"
                
                async with session.get(url, timeout=15) as resp:
                    if resp.status == 403:
                        return ToolResult(success=False, error_message="API access denied. Check API key and quota.")
                    elif resp.status == 400:
                        return ToolResult(success=False, error_message="Invalid request. Check GOOGLE_CX value.")
                    elif resp.status != 200:
                        return ToolResult(success=False, error_message=f"API error: HTTP {resp.status}")
                    
                    data = await resp.json()
                    items = data.get("items", [])
                    
                    if not items:
                        return ToolResult(
                            success=True,
                            data={
                                "query": query,
                                "results": [],
                                "count": 0,
                                "hint": f"No photos found for '{query}'. Try different keywords."
                            }
                        )
                    
                    results = []
                    for item in items:
                        image = item.get("image", {})
                        results.append({
                            "url": item.get("link", ""),
                            "title": item.get("title", "")[:60],
                            "source_page": image.get("contextLink", ""),
                            "thumbnail": image.get("thumbnailLink", ""),
                            "size": f"{image.get('width', 0)}x{image.get('height', 0)}",
                            "format": item.get("mime", "").split("/")[-1] or "unknown"
                        })
                    
                    return ToolResult(
                        success=True,
                        data={
                            "query": query,
                            "results": results,
                            "count": len(results),
                            "hint": "Use save_image to download: save_image <url> <path>"
                        }
                    )
                    
        except asyncio.TimeoutError:
            return ToolResult(success=False, error_message="Search timed out (15s)")
        except Exception as e:
            self._logger.error(f"Photo search failed: {e}")
            return ToolResult(success=False, error_message=f"Search failed: {e}")


# =============================================================================
# 3. LOGO SEARCH - Company and brand logos
# =============================================================================

class LogoSearchTool(BaseTool):
    """Search for company and brand logos."""
    
    NAME = "search_logos"
    
    DESCRIPTION = """Search for company and brand logos.

Find high-quality logos by company name or domain.

Examples:
    search_logos "apple"
    search_logos "google"
    search_logos "stripe"
    search_logos "airbnb"
    search_logos "doordash"

Best for:
- Brand logos for UI
- Company directories
- Partner/integration pages

Uses Logo.dev (if LOGO_DEV_TOKEN set) or free alternatives.
Use search_icons for icons, search_photos for photos.
"""
    
    def __init__(self, *, workspace: Workspace, api_token: Optional[str] = None):
        super().__init__(name=self.NAME, category=ToolCategory.FILE)
        if workspace is None:
            raise ValueError(f"{self.NAME}: workspace is required (no bypass construction)")
        self.workspace = workspace
        self._logger = logging.getLogger(__name__)
        
        import os
        self.api_token = api_token or os.environ.get("LOGO_DEV_TOKEN")
    
    @property
    def tool_definition(self):
        return self.get_tool_param()
    
    def get_tool_param(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Company name or domain (e.g., 'apple', 'google.com')"
                    },
                    "size": {
                        "type": "integer",
                        "description": "Logo size in pixels (default: 256)"
                    }
                },
                "required": ["query"]
            }
        )
    
    async def execute(self, query: str, size: int = 256) -> ToolResult:
        """Search for company logos"""
        try:
            import aiohttp
            import ssl
            import certifi
        except ImportError:
            return ToolResult(
                success=False,
                error_message="Missing dependency. Run: pip install aiohttp certifi"
            )
        
        try:
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            
            async with aiohttp.ClientSession(connector=connector) as session:
                # Step 1: Find company domain via Clearbit
                search_url = f"https://autocomplete.clearbit.com/v1/companies/suggest?query={urllib.parse.quote(query)}"
                
                companies = []
                try:
                    async with session.get(search_url, timeout=10) as resp:
                        if resp.status == 200:
                            companies = await resp.json()
                except Exception as e:
                    self._logger.debug(f"Clearbit lookup failed: {e}")
                
                # Fallback: construct domain from query
                if not companies:
                    domain = query.lower().strip()
                    if "." not in domain:
                        domain = f"{domain}.com"
                    domain = domain.replace("https://", "").replace("http://", "").replace("www.", "").split("/")[0]
                    companies = [{"name": query.title(), "domain": domain}]
                
                # Step 2: Get logo for first match
                company = companies[0]
                domain = company.get("domain", "")
                name = company.get("name", domain)
                
                if not domain:
                    return ToolResult(
                        success=True,
                        data={"query": query, "results": [], "count": 0, "hint": "Company not found. Try exact domain (e.g., 'apple.com')."}
                    )
                
                # Try logo sources in order of quality
                results = []
                sources_tried = []
                
                # Source 1: Logo.dev (best quality, needs token)
                if self.api_token:
                    logo_url = f"https://img.logo.dev/{domain}?token={self.api_token}&size={size}&format=png"
                    if await self._check_url(session, logo_url, use_get=True):
                        results.append({
                            "url": logo_url,
                            "company": name,
                            "domain": domain,
                            "source": "logo.dev",
                            "quality": "high",
                            "size": f"{size}x{size}"
                        })
                    sources_tried.append("logo.dev")
                
                # Source 2: Uplead (free, medium quality)
                if not results:
                    uplead_url = f"https://logo.uplead.com/{domain}"
                    if await self._check_url(session, uplead_url):
                        results.append({
                            "url": uplead_url,
                            "company": name,
                            "domain": domain,
                            "source": "uplead",
                            "quality": "medium"
                        })
                    sources_tried.append("uplead")
                
                # Source 3: Google Favicon (always works, lower quality)
                if not results:
                    favicon_url = f"https://www.google.com/s2/favicons?domain={domain}&sz=128"
                    results.append({
                        "url": favicon_url,
                        "company": name,
                        "domain": domain,
                        "source": "google_favicon",
                        "quality": "low",
                        "note": "Favicon only - for better quality, set LOGO_DEV_TOKEN"
                    })
                    sources_tried.append("google_favicon")
                
                return ToolResult(
                    success=True,
                    data={
                        "query": query,
                        "results": results,
                        "count": len(results),
                        "primary_url": results[0]["url"] if results else None,
                        "hint": "Use save_image to download: save_image <url> <path>"
                    }
                )
                
        except asyncio.TimeoutError:
            return ToolResult(success=False, error_message="Search timed out")
        except Exception as e:
            self._logger.error(f"Logo search failed: {e}")
            return ToolResult(success=False, error_message=f"Search failed: {e}")
    
    async def _check_url(self, session, url: str, use_get: bool = False) -> bool:
        """Check if URL returns a valid image"""
        try:
            method = "get" if use_get else "head"
            async with session.request(method, url, timeout=5, allow_redirects=True) as resp:
                if resp.status == 200:
                    ct = resp.headers.get("Content-Type", "")
                    return "image" in ct or "octet" in ct or "logo" in url
        except:
            pass
        return False


# =============================================================================
# 4. SAVE IMAGE - Download images to workspace
# =============================================================================

class SaveImageTool(BaseTool):
    """Download an image from URL to workspace."""
    
    NAME = "save_image"
    
    DESCRIPTION = """Download an image from URL to your workspace.

Use after search_icons, search_photos, or search_logos to save images.

Examples:
    save_image "https://api.iconify.design/mdi/home.svg" "assets/icons/home.svg"
    save_image "https://example.com/photo.jpg" "images/hero.jpg"
    save_image "https://picsum.photos/800/600" "images/placeholder.jpg"

Tip: Use picsum.photos for placeholder images:
    save_image "https://picsum.photos/seed/unique123/800/600" "images/bg.jpg"
"""
    
    def __init__(self, *, workspace: Workspace):
        super().__init__(name=self.NAME, category=ToolCategory.FILE)
        if workspace is None:
            raise ValueError(f"{self.NAME}: workspace is required (no bypass construction)")
        self.workspace = workspace
        self._logger = logging.getLogger(__name__)
    
    @property
    def tool_definition(self):
        return self.get_tool_param()
    
    def get_tool_param(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Image URL to download"
                    },
                    "path": {
                        "type": "string",
                        "description": "Where to save (e.g., 'images/logo.png', 'assets/icon.svg')"
                    }
                },
                "required": ["url", "path"]
            }
        )
    
    async def execute(self, url: str, path: str) -> ToolResult:
        """Download image to workspace"""
        # SSRF guard — must short-circuit BEFORE any aiohttp/network call.
        reason = _ssrf_check(url)
        if reason is not None:
            return ToolResult.fail(f"refused for safety: {reason}")

        try:
            import aiohttp
            import ssl
            import certifi
        except ImportError:
            return ToolResult(
                success=False,
                error_message="Missing dependency. Run: pip install aiohttp certifi"
            )
        
        # Resolve path
        try:
            dest = self.workspace.resolve(path)
        except Exception as e:
            return ToolResult(success=False, error_message=f"Invalid path: {e}")
        
        dest.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get(url, timeout=30, allow_redirects=True) as resp:
                    if resp.status != 200:
                        return ToolResult(success=False, error_message=f"Download failed: HTTP {resp.status}")
                    
                    content = await resp.read()
                    
                    # Check size (max 50MB)
                    if len(content) > 50 * 1024 * 1024:
                        return ToolResult(success=False, error_message=f"Image too large ({len(content) / 1024 / 1024:.1f}MB > 50MB)")
                    
                    dest.write_bytes(content)
                    
                    size_kb = len(content) / 1024
                    size_str = f"{size_kb:.1f}KB" if size_kb < 1024 else f"{size_kb/1024:.1f}MB"
                    
                    return ToolResult(
                        success=True,
                        data={
                            "saved_to": str(self.workspace.relative(dest)),
                            "size": size_str,
                            "url": url
                        }
                    )
                    
        except asyncio.TimeoutError:
            return ToolResult(success=False, error_message="Download timed out (30s)")
        except Exception as e:
            self._logger.error(f"Download failed: {e}")
            return ToolResult(success=False, error_message=f"Download failed: {e}")


# =============================================================================
# 5. CAPTURE WEBPAGE - Screenshot live webpages
# =============================================================================

class CaptureWebpageTool(BaseTool):
    """Take screenshot of a live webpage."""
    
    NAME = "capture_webpage"
    
    DESCRIPTION = """Take a screenshot of a live webpage for design reference.

Captures the current state of any webpage using Playwright.

Examples:
    capture_webpage "https://doordash.com"
    capture_webpage "https://github.com" "design/captures/github.png"
    capture_webpage "https://stripe.com" "design/stripe_ref.png" full_page=true

Best for:
- Up-to-date design references
- Competitor analysis
- Before/after comparisons

Requires Playwright: pip install playwright && playwright install
"""
    
    def __init__(self, *, workspace: Workspace):
        super().__init__(name=self.NAME, category=ToolCategory.FILE)
        if workspace is None:
            raise ValueError(f"{self.NAME}: workspace is required (no bypass construction)")
        self.workspace = workspace
        self._logger = logging.getLogger(__name__)
    
    @property
    def tool_definition(self):
        return self.get_tool_param()
    
    def get_tool_param(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Webpage URL to capture"
                    },
                    "path": {
                        "type": "string",
                        "description": "Where to save (default: design/captures/<domain>.png). NOTE: screenshots/ is the read-only reference dir the visual gate diffs against; a path there is redirected to design/captures/."
                    },
                    "full_page": {
                        "type": "boolean",
                        "description": "Capture full scrollable page (default: false)"
                    },
                    "width": {
                        "type": "integer",
                        "description": "Viewport width (default: 1280)"
                    },
                    "height": {
                        "type": "integer",
                        "description": "Viewport height (default: 800)"
                    }
                },
                "required": ["url"]
            }
        )
    
    async def execute(
        self, 
        url: str, 
        path: Optional[str] = None,
        full_page: bool = False,
        width: int = 1280,
        height: int = 800
    ) -> ToolResult:
        """Capture webpage screenshot"""
        
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return ToolResult(
                success=False,
                error_message="Playwright not installed. Run: pip install playwright && playwright install"
            )
        
        # Determine save path. `screenshots/` is the visual gate READ-ONLY
        # reference dir; captures go to the writable capture dir instead (#341).
        _redirected = None
        if path:
            _fixed = _redirect_readonly_capture_path(path)
            if _fixed != path:
                _redirected = _fixed
            dest = self.workspace.resolve(_fixed)
        else:
            from urllib.parse import urlparse
            domain = urlparse(url).netloc.replace("www.", "").replace(".", "_")
            dest = self.workspace.resolve(_CAPTURE_DIR) / f"{domain}.png"
        
        dest.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(viewport={"width": width, "height": height})
                page = await context.new_page()
                
                await page.goto(url, wait_until="networkidle", timeout=30000)
                await page.screenshot(path=str(dest), full_page=full_page)
                await browser.close()
                
                size = dest.stat().st_size
                size_str = f"{size/1024:.1f}KB" if size < 1024*1024 else f"{size/1024/1024:.1f}MB"
                
                return ToolResult(
                    success=True,
                    data={
                        "saved_to": str(self.workspace.relative(dest)),
                        "redirected_from": _redirected,
                        "url": url,
                        "size": size_str,
                        "dimensions": f"{width}x{height}" if not full_page else "full page"
                    }
                )
                
        except Exception as e:
            # #1202ba: a refused connection is not a page bug, and the raw Playwright
            # text does not say so. netflix-r30 got `net::ERR_CONNECTION_REFUSED at
            # http://localhost:8042/` eight times over 100 minutes while the run's stack
            # was down, and the gate it feeds (validation_ui_evidence_failed) was one of
            # the two still failing at the 148-minute no-convergence abort. Nothing in
            # that message tells a lane that editing its page cannot help, so name the
            # cause and the one action that can.
            _msg = f"Screenshot failed: {e}"
            if "ERR_CONNECTION_REFUSED" in str(e) or "ECONNREFUSED" in str(e):
                _msg += (" — NOTHING IS LISTENING on that port. The app is not running, "
                         "so this is not a page you can fix by editing it: no change to "
                         "the frontend will make this capture succeed. Bring the stack "
                         "up (compose up) and retry, or report the stack as down.")
            self._logger.error(_msg)
            return ToolResult(success=False, error_message=_msg)


# =============================================================================
# FACTORY FUNCTION - Create all image tools
# =============================================================================

def create_image_search_tools(
    workspace: Optional[Workspace] = None, 
    google_api_key: Optional[str] = None, 
    google_cx: Optional[str] = None, 
    logo_dev_token: Optional[str] = None
) -> List[BaseTool]:
    """Create all image tools.
    
    Returns:
        List of tools: [search_icons, search_photos, search_logos, save_image, capture_webpage]
    """
    return [
        IconSearchTool(workspace=workspace),
        PhotoSearchTool(workspace=workspace, api_key=google_api_key, cx=google_cx),
        LogoSearchTool(workspace=workspace, api_token=logo_dev_token),
        SaveImageTool(workspace=workspace),
        CaptureWebpageTool(workspace=workspace),
    ]
