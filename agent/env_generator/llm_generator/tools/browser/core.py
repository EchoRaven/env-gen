"""
Browser Core Tools - Navigate, Screenshot, Console, Network, Close
"""
import asyncio
import base64
from typing import Dict, Any, Optional
from pathlib import Path
from datetime import datetime

from utils.tool import BaseTool, ToolResult, ToolCategory
from ._manager import BrowserManager, PLAYWRIGHT_AVAILABLE


import logging as _lg1189
import time as _t1189

# A real module logger: the #1189 wait line sits in a try/except, so without one the
# NameError would be swallowed and the wait would be invisible — the exact silence this
# session spent its time removing.
_LOG1189 = _lg1189.getLogger(__name__)


def _nav_wait_budget_1189() -> float:
    """Seconds to keep retrying a refused navigation. Bounded, and env-overridable.

    120s covers the P90 of the measured recycle windows (111s) with headroom; the P100 was
    250s, and waiting that long for every dead stack would be worse than failing. A value of
    0 restores #996's give-up-immediately behaviour for anyone who needs it.
    """
    import os as _os1189
    try:
        v = float(_os1189.environ.get("ENVGEN_NAV_WAIT_SEC", "") or 120.0)
    except (TypeError, ValueError):
        return 120.0
    return min(600.0, max(0.0, v))


class BrowserNavigateTool(BaseTool):
    NAME = "browser_navigate"
    """Navigate to a URL and capture page state"""
    
    def __init__(self, browser_manager: BrowserManager, **kwargs):
        super().__init__(name="browser_navigate", category=ToolCategory.RUNTIME, **kwargs)
        self.browser = browser_manager
    
    @property
    def tool_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "browser_navigate",
                "description": "Navigate browser to a URL and capture console errors, network errors, and page content. Use this to debug frontend issues.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "URL to navigate to (e.g., http://localhost:3000)"
                        },
                        "wait_for": {
                            "type": "string",
                            "enum": ["load", "domcontentloaded", "networkidle"],
                            "description": "Wait condition (default: networkidle)"
                        }
                    },
                    "required": ["url"]
                }
            }
        }
    
    async def execute(self, url: str, wait_for: str = "networkidle", **kwargs) -> ToolResult:
        if not PLAYWRIGHT_AVAILABLE:
            return ToolResult.fail("Playwright not installed. Run: pip install playwright && playwright install chromium")
        
        if not await self.browser.ensure_browser():
            return ToolResult.fail("Failed to start browser")
        
        try:
            # Clear previous logs
            self.browser.state.console_logs.clear()
            self.browser.state.network_errors.clear()
            
            # Navigate.
            # #996: RETRY a refused connection. A validation cycle recycles the compose
            # project (`down -v` -> build -> up), and anything touching the live stack in
            # that window gets nothing. Three surfaces have now paid for it — the browser
            # walk (item 374, 10 failures), test_api (item 400, 55 in r162) and
            # capture_webpage (22 in r162, all ERR_CONNECTION_REFUSED/RESET) — which is the
            # third-surface trigger item 400 wrote down.
            #
            # The fix item 374 rejected was holding the smoke lock across a multi-minute
            # walk, which would serialize every lane behind compose recycles. This one does
            # not serialize anything: the stack is DOWN for seconds, so waiting briefly and
            # retrying costs far less than a lost capture, and a genuinely dead stack still
            # fails — just three attempts later, with the same error.
            # #1189: #996's budget is an order of magnitude below the event it exists for.
            # Three attempts with 3s + 6s of sleep gives up after NINE seconds, and the
            # recycle it is waiting out is far longer. Measured over netflix-r22's resume,
            # pairing each `docker down` with the `docker up` that completed after it:
            #
            #     51 windows   median 20s   P75 28s   P90 111s   max 250s
            #     longer than #996's 9s budget: 50 of 51  (98%)
            #
            # So it abandoned the navigation while the stack was still coming up in 98% of
            # recycles. That resume ended holding three failing ui_flow records — title-
            # detail-open, login_auth_flow, profile_creation — every one of them an
            # ERR_CONNECTION_REFUSED, one of them refused by the FRONTEND's own origin, on
            # an app that answers register/login/titles correctly when probed by hand. The
            # orchestrator then stopped voluntarily because its pre-delivery run "aborted on
            # /health". #1154 discounts these records after the fact; this stops minting them.
            #
            # Waiting is bounded by a DEADLINE rather than an attempt count, so the cost is
            # paid only while the origin is actually down, and a genuinely dead stack still
            # fails with the same error — just later, after the window a recycle needs.
            _last_exc = None
            response = None
            _deadline = _t1189.monotonic() + _nav_wait_budget_1189()
            _waited = 0.0
            while True:
                try:
                    response = await self.browser.state.page.goto(
                        url,
                        wait_until=wait_for,
                        timeout=30000
                    )
                    break
                except Exception as _e:
                    _txt = str(_e)
                    if not any(k in _txt for k in ("ERR_CONNECTION_REFUSED",
                                                   "ERR_CONNECTION_RESET",
                                                   "ERR_EMPTY_RESPONSE")):
                        raise
                    _last_exc = _e
                    if _t1189.monotonic() >= _deadline:
                        break
                    await asyncio.sleep(3)
                    _waited += 3
            if response is None and _last_exc is not None:
                raise _last_exc
            if _waited:
                try:
                    _LOG1189.info("#1189 navigation to %s waited %.0fs for the origin to come "
                                "back (compose recycle); median recycle is ~20s.",
                                url, _waited)
                except Exception:
                    pass
            
            self.browser.state.current_url = url
            
            # Wait a bit for any async errors
            await asyncio.sleep(1)
            
            # Get page info
            title = await self.browser.state.page.title()
            # #689: the page can still be moving when we read it — "Unable to retrieve content
            # because the page is navigating" is 58 of the corpus's navigate failures, 26 of
            # them live. The navigation itself succeeded; only this read lost the race, so
            # settling once and re-reading is the whole fix. An SPA that redirects on mount
            # (login -> browse) hits this every time.
            try:
                content = await self.browser.state.page.content()
            except Exception as _ce:
                from tools.browser.inspection import (is_navigation_race_error,
                                                      settle_after_navigation_689)
                if not is_navigation_race_error(_ce):
                    raise
                await settle_after_navigation_689(self.browser.state.page)
                content = await self.browser.state.page.content()
            
            # Filter console errors (ignore browser extension errors)
            console_errors = [
                log for log in self.browser.state.console_logs 
                if log["type"] == "error" and not self._is_extension_error(log["text"])
            ]
            
            # Filter network errors for our domain
            our_network_errors = [
                err for err in self.browser.state.network_errors
                if "localhost" in err["url"]
            ]
            
            result = {
                "url": url,
                "title": title,
                "status": response.status if response else None,
                "console_errors": console_errors[:10],
                "network_errors": our_network_errors[:10],
                "content_preview": content[:500] + "..." if len(content) > 500 else content,
                "has_errors": len(console_errors) > 0 or len(our_network_errors) > 0,
            }
            
            return ToolResult.ok(result)
            
        except Exception as e:
            # #687: the same transport diagnosis test_api got in #677. Chromium reports
            # `net::ERR_CONNECTION_REFUSED` for exactly the condition #677 explains, and this
            # tool said only "Navigation failed: <raw>". Measured over the 249 run logs: 601
            # ERR_CONNECTION_REFUSED navigations, 161 of them in the LIVE era (r100+), plus 308
            # more reaching the browser lane's own failure list — retrying a navigation to a
            # process that is not running cannot succeed however many times it is tried.
            # Imported locally and best-effort: a diagnosis must never replace the real error.
            _why = ""
            try:
                from tools.runtime_tools import _request_failure_reason_677
                _why = _request_failure_reason_677(e, url)
                _why = _why.split("—", 1)[1].strip() if "—" in _why else ""
            except Exception:
                _why = ""
            return ToolResult.fail(f"Navigation failed: {str(e)}"
                                   + (f" — {_why}" if _why else ""))
    
    def _is_extension_error(self, text: str) -> bool:
        patterns = ["chrome-extension://", "moz-extension://", "extensions::", "background.js"]
        return any(p in text for p in patterns)


class BrowserScreenshotTool(BaseTool):
    NAME = "browser_screenshot"
    """Take a screenshot of the current page"""
    
    def __init__(self, browser_manager: BrowserManager, **kwargs):
        super().__init__(name="browser_screenshot", category=ToolCategory.RUNTIME, **kwargs)
        self.browser = browser_manager
    
    @property
    def tool_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "browser_screenshot",
                "description": "Take a screenshot of the current browser page. Saves to disk (recommended). Base64 is optional (can be large).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "full_page": {
                            "type": "boolean",
                            "description": "Capture full page or just viewport (default: false)"
                        },
                        "save_path": {
                            "type": "string",
                            "description": "Optional path to save screenshot"
                        },
                        "include_base64": {
                            "type": "boolean",
                            "description": "If true, include a small base64 preview in the result (default: false)"
                        }
                    },
                    "required": []
                }
            }
        }
    
    async def execute(
        self,
        full_page: bool = False,
        save_path: Optional[str] = None,
        include_base64: bool = False,
        **kwargs
    ) -> ToolResult:
        if not PLAYWRIGHT_AVAILABLE:
            return ToolResult.fail("Playwright not installed")
        
        if not self.browser.state.page:
            return ToolResult.fail("No page open. Use browser_navigate first.")
        
        try:
            screenshot_bytes = await self.browser.state.page.screenshot(full_page=full_page)
            
            # Determine save path - always within workspace
            if save_path:
                # Resolve relative to workspace
                resolved_path = self.browser.resolve_path(save_path)
            else:
                # Default to workspace/screenshots/
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                self.browser.screenshot_dir.mkdir(parents=True, exist_ok=True)
                resolved_path = self.browser.screenshot_dir / f"screenshot_{ts}.png"

            # Create parent directories and save
            resolved_path.parent.mkdir(parents=True, exist_ok=True)
            with open(resolved_path, 'wb') as f:
                f.write(screenshot_bytes)
            
            # Use relative path for display
            try:
                display_path = str(self.browser.workspace.relative(resolved_path))
            except (ValueError, AttributeError):
                display_path = save_path or resolved_path.name
            
            data: Dict[str, Any] = {
                "saved_to": display_path,
                "size_bytes": len(screenshot_bytes),
            }

            if include_base64:
                screenshot_b64 = base64.b64encode(screenshot_bytes).decode()
                data["base64_preview"] = screenshot_b64[:200] + "..." if len(screenshot_b64) > 200 else screenshot_b64

            return ToolResult.ok(data)
            
        except Exception as e:
            return ToolResult.fail(f"Screenshot failed: {str(e)}")


class BrowserGetConsoleTool(BaseTool):
    NAME = "browser_console"
    """Get console logs from current page"""
    
    def __init__(self, browser_manager: BrowserManager, **kwargs):
        super().__init__(name="browser_console", category=ToolCategory.RUNTIME, **kwargs)
        self.browser = browser_manager
    
    @property
    def tool_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "browser_console",
                "description": "Get JavaScript console logs from the current page. Use this to see frontend errors.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filter_type": {
                            "type": "string",
                            "enum": ["all", "error", "warning", "log"],
                            "description": "Filter by message type (default: all)"
                        }
                    },
                    "required": []
                }
            }
        }
    
    async def execute(self, filter_type: str = "all", **kwargs) -> ToolResult:
        if not self.browser.state.page:
            return ToolResult.fail("No page open. Use browser_navigate first.")
        
        logs = self.browser.state.console_logs
        
        if filter_type != "all":
            logs = [log for log in logs if log["type"] == filter_type]
        
        # Filter out extension errors
        logs = [
            log for log in logs 
            if not any(p in log.get("text", "") for p in ["chrome-extension://", "moz-extension://"])
        ]
        
        return ToolResult.ok({
            "url": self.browser.state.current_url,
            "total_logs": len(logs),
            "logs": logs[:20],
        })


class BrowserGetNetworkErrorsTool(BaseTool):
    NAME = "browser_network_errors"
    """Get network errors (4xx, 5xx) from current page"""
    
    def __init__(self, browser_manager: BrowserManager, **kwargs):
        super().__init__(name="browser_network_errors", category=ToolCategory.RUNTIME, **kwargs)
        self.browser = browser_manager
    
    @property
    def tool_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "browser_network_errors",
                "description": "Get network errors (4xx, 5xx status codes) from the current page. Use this to see API failures.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
    
    async def execute(self, **kwargs) -> ToolResult:
        if not self.browser.state.page:
            return ToolResult.fail("No page open. Use browser_navigate first.")
        
        # Filter for our domain
        errors = [
            err for err in self.browser.state.network_errors
            if "localhost" in err.get("url", "")
        ]
        
        return ToolResult.ok({
            "url": self.browser.state.current_url,
            "total_errors": len(errors),
            "errors": errors[:20],
        })


class BrowserCloseTool(BaseTool):
    NAME = "browser_close"
    """Close the browser session"""
    
    def __init__(self, browser_manager: BrowserManager, **kwargs):
        super().__init__(name="browser_close", category=ToolCategory.RUNTIME, **kwargs)
        self.browser = browser_manager
    
    @property
    def tool_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "browser_close",
                "description": "Close the browser session",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
    
    async def execute(self, **kwargs) -> ToolResult:
        # #1199: this used to tear down the SHARED driver — the one every lane holds.
        # `BrowserManager` is a singleton handed to all browser tools ("Create all browser
        # tools with shared browser manager"), so one lane tidying up after itself would
        # take down the other eleven mid-walk: their pages, their contexts, their logins.
        # Since #1198 the next caller rebuilds it, but a rebuild is a NEW session — cookies
        # and auth state are gone, and a walk that was three steps into a logged-in flow
        # fails for a reason no lane can see from its own transcript.
        #
        # No agent has ever called it (r22-r26: every `browser_close` line in the logs is a
        # tool-surface registration), so this is a hazard that has not fired yet rather than
        # a fix for an observed failure — and nothing else in the codebase calls
        # `manager.close()`, so the teardown path has no other user to preserve.
        #
        # The tool stays on the surface and stays honest: the session is shared, so the
        # caller is told what actually happened rather than being handed "Browser closed".
        return ToolResult.ok(
            "Nothing to close: this browser session is shared by every lane in the run, so "
            "it stays up. Navigate somewhere else if you are done with the current page.")

