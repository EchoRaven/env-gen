"""
Browser Manager - Manages browser lifecycle and state
"""
import logging
from typing import Dict, List, Any, Optional
from pathlib import Path
from dataclasses import dataclass, field

try:
    from playwright.async_api import async_playwright, Page, Browser, BrowserContext
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


@dataclass
class BrowserState:
    """Tracks browser session state"""
    browser: Optional[Any] = None
    context: Optional[Any] = None
    page: Optional[Any] = None
    console_logs: List[Dict] = field(default_factory=list)
    network_errors: List[Dict] = field(default_factory=list)
    current_url: str = ""


class BrowserManager:
    """Manages browser lifecycle and state"""
    
    _instance: Optional['BrowserManager'] = None
    
    def __init__(self, workspace_root: Optional[Path] = None):
        self.state = BrowserState()
        # Always use absolute path based on workspace
        self.workspace_root = workspace_root.resolve() if workspace_root else Path.cwd().resolve()
        self.screenshot_dir = self.workspace_root / "screenshots"
        self._playwright = None
        self._logger = logging.getLogger(__name__)
    
    @classmethod
    def get_instance(cls, workspace_root: Optional[Path] = None) -> 'BrowserManager':
        if cls._instance is None:
            cls._instance = cls(workspace_root)
        return cls._instance
    
    def resolve_path(self, path: str) -> Path:
        """Resolve a path relative to workspace root, ensuring it stays within workspace."""
        if Path(path).is_absolute():
            resolved = Path(path)
        else:
            # Strip workspace path prefix if LLM accidentally included it
            # e.g., "generated/expedia/screenshots/x.png" -> "screenshots/x.png"
            clean_path = path
            workspace_name = self.workspace_root.name  # e.g., "expedia"
            
            # Check for patterns like "generated/expedia/..." or "expedia/..."
            parts = Path(path).parts
            for i, part in enumerate(parts):
                if part == workspace_name:
                    # Found workspace name, strip everything up to and including it
                    clean_path = str(Path(*parts[i+1:])) if i+1 < len(parts) else ""
                    self._logger.debug(f"Stripped workspace prefix: {path} -> {clean_path}")
                    break
                elif part == "generated":
                    # "generated/projectname/..." - check next part
                    if i+1 < len(parts) and parts[i+1] == workspace_name:
                        clean_path = str(Path(*parts[i+2:])) if i+2 < len(parts) else ""
                        self._logger.debug(f"Stripped generated prefix: {path} -> {clean_path}")
                        break
            
            resolved = self.workspace_root / clean_path if clean_path else self.workspace_root
        
        # Ensure it's within workspace (security check)
        try:
            resolved.resolve().relative_to(self.workspace_root)
            return resolved.resolve()
        except ValueError:
            # Path escapes workspace - force it back
            self._logger.warning(f"Path {path} escapes workspace, using screenshots dir")
            return self.screenshot_dir / Path(path).name
    
    async def ensure_browser(self) -> bool:
        """Ensure browser is started"""
        if not PLAYWRIGHT_AVAILABLE:
            return False
        
        if self.state.browser is None:
            try:
                self._playwright = await async_playwright().start()
                self.state.browser = await self._playwright.chromium.launch(
                    headless=True,
                    args=['--no-sandbox', '--disable-setuid-sandbox']
                )
                self.state.context = await self.state.browser.new_context(
                    viewport={'width': 1280, 'height': 720}
                )
                self.state.page = await self.state.context.new_page()
                
                # Setup console and network listeners
                self.state.page.on("console", self._on_console)
                self.state.page.on("response", self._on_response)
                self.state.page.on("requestfailed", self._on_request_failed)
                self.state.page.on("pageerror", self._on_page_error)
                
                return True
            except Exception as e:
                self._logger.error(f"Failed to start browser: {e}")
                return False
        return True
    
    def _on_console(self, msg):
        """Capture console messages"""
        self.state.console_logs.append({
            "type": msg.type,
            "text": msg.text,
            "location": str(msg.location) if msg.location else None,
        })
    
    def _on_response(self, response):
        """Capture network errors"""
        if response.status >= 400:
            self.state.network_errors.append({
                "url": response.url,
                "status": response.status,
                "method": response.request.method,
                "type": "http_error",
            })
    
    def _on_request_failed(self, request):
        """Capture request failures (DNS, connection reset, CORS preflight failures, etc.)."""
        try:
            failure = request.failure
            error_text = failure.error_text if failure else "request_failed"
        except Exception:
            error_text = "request_failed"

        self.state.network_errors.append({
            "url": request.url,
            "status": None,
            "method": request.method,
            "type": "request_failed",
            "error": error_text,
        })

    def _on_page_error(self, error):
        """Capture page errors"""
        self.state.console_logs.append({
            "type": "error",
            "text": str(error),
            "location": "page",
        })
    
    async def close(self):
        """Close browser"""
        if self.state.page:
            await self.state.page.close()
        if self.state.context:
            await self.state.context.close()
        if self.state.browser:
            await self.state.browser.close()
        if self._playwright:
            await self._playwright.stop()
        
        self.state = BrowserState()
        BrowserManager._instance = None

