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
            
            # Navigate
            response = await self.browser.state.page.goto(
                url, 
                wait_until=wait_for,
                timeout=30000
            )
            
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
        try:
            await self.browser.close()
            return ToolResult.ok("Browser closed")
        except Exception as e:
            return ToolResult.fail(f"Failed to close browser: {str(e)}")

