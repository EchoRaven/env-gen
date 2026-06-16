"""
Browser Tools Package - Headless browser operations for frontend debugging

Modules:
- _manager: BrowserManager and BrowserState
- core: Navigate, Screenshot, Console, NetworkErrors, Close
- interaction: Click, Fill, Select, Hover, PressKey, Scroll, Wait
- inspection: Elements, Eval, URL, Find, Text, Attribute, Visible, A11y
"""
import logging
from typing import List, Optional
from pathlib import Path

from utils.tool import BaseTool

# Manager
from ._manager import BrowserManager, BrowserState, PLAYWRIGHT_AVAILABLE

# Core tools
from .core import (
    BrowserNavigateTool,
    BrowserScreenshotTool,
    BrowserGetConsoleTool,
    BrowserGetNetworkErrorsTool,
    BrowserCloseTool,
)

# Interaction tools
from .interaction import (
    BrowserClickTool,
    BrowserFillTool,
    BrowserSelectTool,
    BrowserHoverTool,
    BrowserPressKeyTool,
    BrowserScrollTool,
    BrowserWaitTool,
)

# Inspection tools
from .inspection import (
    BrowserGetElementsTool,
    BrowserEvaluateTool,
    BrowserGetUrlTool,
    BrowserWaitForUrlTool,
    BrowserFindTool,
    BrowserGetAttributeTool,
    BrowserGetTextTool,
    BrowserCheckVisibleTool,
    BrowserCheckAccessibilityTool,
    BrowserAccessibilityTreeTool,
)


def create_browser_tools(workspace_root: Optional[Path] = None) -> List[BaseTool]:
    """Create all browser tools with shared browser manager.
    
    Args:
        workspace_root: Root directory of the workspace. Screenshots and other
                       browser-generated files will be saved within this directory.
    """
    if not PLAYWRIGHT_AVAILABLE:
        logging.warning("Playwright not installed. Browser tools will not be available.")
        return []
    
    browser_manager = BrowserManager.get_instance(workspace_root)
    
    return [
        # Core navigation and inspection
        BrowserNavigateTool(browser_manager),
        BrowserScreenshotTool(browser_manager),
        BrowserGetConsoleTool(browser_manager),
        BrowserGetNetworkErrorsTool(browser_manager),
        
        # Interaction
        BrowserClickTool(browser_manager),
        BrowserFillTool(browser_manager),
        BrowserSelectTool(browser_manager),
        BrowserHoverTool(browser_manager),
        BrowserPressKeyTool(browser_manager),
        
        # Waiting and scrolling
        BrowserWaitTool(browser_manager),
        BrowserScrollTool(browser_manager),
        
        # Element inspection
        BrowserGetElementsTool(browser_manager),
        BrowserGetTextTool(browser_manager),
        BrowserGetAttributeTool(browser_manager),
        BrowserCheckVisibleTool(browser_manager),
        
        # Advanced
        BrowserFindTool(browser_manager),
        BrowserGetUrlTool(browser_manager),
        BrowserWaitForUrlTool(browser_manager),
        BrowserEvaluateTool(browser_manager),
        BrowserCheckAccessibilityTool(browser_manager),
        BrowserAccessibilityTreeTool(browser_manager),
        
        # Lifecycle
        BrowserCloseTool(browser_manager),
    ]


__all__ = [
    # Manager
    "BrowserManager",
    "BrowserState",
    "PLAYWRIGHT_AVAILABLE",
    
    # Core
    "BrowserNavigateTool",
    "BrowserScreenshotTool",
    "BrowserGetConsoleTool",
    "BrowserGetNetworkErrorsTool",
    "BrowserCloseTool",
    
    # Interaction
    "BrowserClickTool",
    "BrowserFillTool",
    "BrowserSelectTool",
    "BrowserHoverTool",
    "BrowserPressKeyTool",
    "BrowserScrollTool",
    "BrowserWaitTool",
    
    # Inspection
    "BrowserGetElementsTool",
    "BrowserEvaluateTool",
    "BrowserGetUrlTool",
    "BrowserWaitForUrlTool",
    "BrowserFindTool",
    "BrowserGetAttributeTool",
    "BrowserGetTextTool",
    "BrowserCheckVisibleTool",
    "BrowserCheckAccessibilityTool",
    "BrowserAccessibilityTreeTool",
    
    # Factory
    "create_browser_tools",
]

