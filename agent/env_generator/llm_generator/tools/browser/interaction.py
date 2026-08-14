"""
Browser Interaction Tools - Click, Fill, Select, Hover, Key Press, Scroll, Wait
"""
from typing import Dict, Any, Optional

from utils.tool import BaseTool, ToolResult, ToolCategory
from ._manager import BrowserManager, PLAYWRIGHT_AVAILABLE


def _unescape_model_selector(selector: str) -> str:
    """#581 — a model composing a CSS selector inside a JSON tool argument naturally writes
    ``input[placeholder=\\"Email or phone number\\"]``. JSON decoding already removed one level,
    so what reaches the browser still carries the backslashes and the engine rejects it
    outright:

        SyntaxError: Failed to execute 'querySelectorAll' on 'Document':
        'input[placeholder=\\"Email or phone number\\"]' is not a valid selector.

    24 occurrences across the netflix arc (also ``input[aria-label=\\"…\\"]``, ``input[
    placeholder=\\"Full name\\"]``), each one a wasted browser step whose error teaches the
    model nothing about the page. Drop the stray escapes before the selector is used.

    Deliberately narrow: only ``\\"`` and ``\\'`` are unescaped, and only when the result still
    contains the quote character they were escaping — so a selector that legitimately needs a
    CSS escape (``.foo\\:bar``, an escaped ``\\\\``) is untouched."""
    s = str(selector or "")
    for esc, raw in (('\\"', '"'), ("\\'", "'")):
        if esc in s:
            s = s.replace(esc, raw)
    return s


_CANDIDATE_SELECTOR = "input, textarea, select, button, a[href], [role='button'], [contenteditable]"
_CANDIDATE_ATTRS = ("name", "id", "placeholder", "aria-label", "type", "data-testid")


def _candidates_hint_688(cands: str) -> str:
    """Render #362's candidate list, keeping "empty page" distinct from "could not look"."""
    if cands == _EMPTY_PAGE_688:
        return (" This page has NO interactable elements at all — it is blank or never "
                "hydrated, so no selector can match. Do not try another selector: check that "
                "the route rendered (navigate again and read the content) before interacting.")
    return f" Interactable elements on this page: {cands}" if cands else ""


# #688: the sentinel for "the probe RAN and the page offers nothing", as distinct from "" which
# still means "could not look". Callers must render these two differently.
_EMPTY_PAGE_688 = "\x00empty-page"


async def describe_interactive_candidates(page, limit: int = 12) -> str:
    """A short list of what IS interactable on the page (#362).

    A selector miss returned only "Timeout 5000ms exceeded", so the model had no
    way to learn what the page actually offers and guessed the next selector --
    52 identical browser_fill failures on `input[name='username']` in r91's
    verifier alone, plus 17 browser_click, each costing a 5s timeout AND a
    full-context round.

    Runs on an ALREADY-failing path, so it must never raise and never mask the
    real error: any problem returns "".
    """
    # #688: "" MEANT THREE DIFFERENT THINGS AND THE CALLER COULD NOT TELL THEM APART.
    # No page, a failed probe, and a page that genuinely offers NOTHING all returned "", so the
    # caller dropped the hint entirely and the agent saw the bare "Timeout 5000ms exceeded".
    # The third case is the one that matters and it is the opposite diagnosis: the selector is
    # not wrong, the PAGE never rendered. Measured over the 249 run logs: browser_fill fails
    # 1238 times (830 of them in the LIVE era r100+, up from 408 before — it is getting worse)
    # and browser_click 410 (214 live), and the live samples carry no hint at all, which is only
    # possible when this returned "".
    #
    # `_EMPTY_PAGE_688` is returned ONLY when the query succeeded and found nothing. A probe
    # that could not run still returns "" — unchanged — because saying "the page is empty" when
    # we failed to look would be worse than saying nothing.
    if page is None:
        return ""
    try:
        els = await page.query_selector_all(_CANDIDATE_SELECTOR)
    except Exception:
        return ""
    if not els:
        return _EMPTY_PAGE_688
    out = []
    for el in (els or [])[:limit * 3]:
        try:
            attrs = {}
            for a in _CANDIDATE_ATTRS:
                try:
                    v = await el.get_attribute(a)
                except Exception:
                    v = None
                if v:
                    attrs[a] = str(v)[:40]
            if not attrs:
                continue          # nothing addressable — a selector cannot name it
            out.append("{" + ", ".join(f"{k}={v!r}" for k, v in attrs.items()) + "}")
            if len(out) >= limit:
                break
        except Exception:
            continue
    return "; ".join(out)


class BrowserClickTool(BaseTool):
    NAME = "browser_click"
    """Click an element on the page with auto-retry and smart waiting"""
    
    def __init__(self, browser_manager: BrowserManager, **kwargs):
        super().__init__(name="browser_click", category=ToolCategory.RUNTIME, **kwargs)
        self.browser = browser_manager
    
    @property
    def tool_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "browser_click",
                "description": """Click an element on the page with auto-retry and smart waiting.

PREFERRED locators (stable, recommended):
- testid: data-testid attribute (most reliable)
- aria_label: aria-label attribute
- role + name: ARIA role with accessible name

FALLBACK locators:
- selector: CSS selector
- text: element containing text

Features:
- Auto-waits for element to be visible
- Retries up to 3 times on timeout
- 500ms delay between retries
""",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {
                            "type": "string",
                            "description": "CSS selector (e.g., '#login-btn', 'button[type=submit]')"
                        },
                        "text": {
                            "type": "string",
                            "description": "Alternative: click element containing this text"
                        },
                        "testid": {
                            "type": "string",
                            "description": "Preferred: data-testid value (clicks element [data-testid=\"...\"])"
                        },
                        "aria_label": {
                            "type": "string",
                            "description": "Preferred: aria-label value (clicks element matching [aria-label=\"...\"])"
                        },
                        "role": {
                            "type": "string",
                            "description": "Preferred: ARIA role for get_by_role (e.g., 'button', 'link', 'textbox')"
                        },
                        "name": {
                            "type": "string",
                            "description": "Accessible name used with role-based queries (works with role)"
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "Timeout in ms per attempt (default: 5000)"
                        },
                        "retry": {
                            "type": "integer",
                            "description": "Number of retry attempts (default: 3)"
                        },
                        "wait_for_visible": {
                            "type": "boolean",
                            "description": "Wait for element to be visible before clicking (default: true)"
                        }
                    },
                    "required": []
                }
            }
        }
    
    async def execute(
        self,
        selector: Optional[str] = None,
        text: Optional[str] = None,
        testid: Optional[str] = None,
        aria_label: Optional[str] = None,
        role: Optional[str] = None,
        name: Optional[str] = None,
        timeout: int = 5000,
        retry: int = 3,
        wait_for_visible: bool = True,
        **kwargs
    ) -> ToolResult:
        import asyncio
        
        if not self.browser.state.page:
            return ToolResult.fail("No page open. Use browser_navigate first.")
        
        # Build the selector to use
        final_selector = None
        selector_type = None
        
        if testid:
            final_selector = f'[data-testid="{testid}"]'
            selector_type = f"testid={testid}"
        elif aria_label:
            final_selector = f'[aria-label="{aria_label}"]'
            selector_type = f"aria-label={aria_label}"
        elif role:
            final_selector = f'role={role}'
            if name:
                final_selector += f'[name="{name}"]'
            selector_type = f"role={role}" + (f" name={name}" if name else "")
        elif selector:
            final_selector = _unescape_model_selector(selector)
            selector_type = f"selector={final_selector}"
        elif text:
            final_selector = f"text={text}"
            selector_type = f"text={text}"
        else:
            return ToolResult.fail("Provide one of: testid, aria_label, role, selector, or text")
        
        last_error = None
        
        for attempt in range(retry):
            try:
                page = self.browser.state.page
                
                # First, wait for element to be visible if requested
                if wait_for_visible and attempt == 0:
                    try:
                        await page.wait_for_selector(
                            final_selector, 
                            state="visible", 
                            timeout=timeout
                        )
                    except Exception:
                        pass  # Continue to click attempt even if wait fails
                
                # Attempt click
                await page.click(final_selector, timeout=timeout)
                
                # Success
                result_msg = f"Clicked element ({selector_type})"
                if attempt > 0:
                    result_msg += f" after {attempt + 1} attempts"
                return ToolResult.ok(result_msg)
                
            except Exception as e:
                last_error = str(e)
                
                if attempt < retry - 1:
                    # Wait before retry
                    await asyncio.sleep(0.5)
                    
                    # Try scrolling element into view on retry
                    try:
                        await self.browser.state.page.evaluate(
                            f"document.querySelector('{final_selector}')?.scrollIntoView({{behavior: 'smooth', block: 'center'}})"
                        )
                        await asyncio.sleep(0.3)
                    except:
                        pass
        
        # All retries failed - provide helpful error message
        error_hints = []
        if "Timeout" in last_error:
            error_hints.append("Element may not exist or is not visible")
            error_hints.append("Try using browser_find() first to check if element exists")
            error_hints.append("Consider using a more specific selector or data-testid")
        if "strict mode violation" in last_error.lower():
            error_hints.append("Multiple elements match - use a more specific selector")
        
        error_msg = f"Click failed after {retry} attempts: {last_error}"
        # #362: same reasoning as the fill path above.
        _cands = await describe_interactive_candidates(
            getattr(getattr(self.browser, "state", None), "page", None))
        error_msg += _candidates_hint_688(_cands)   # #688: same distinction for click
        if error_hints:
            error_msg += "\n\nHints:\n- " + "\n- ".join(error_hints)
        
        return ToolResult.fail(error_msg)


class BrowserFillTool(BaseTool):
    NAME = "browser_fill"
    """Fill an input field"""
    
    def __init__(self, browser_manager: BrowserManager, **kwargs):
        super().__init__(name="browser_fill", category=ToolCategory.RUNTIME, **kwargs)
        self.browser = browser_manager
    
    @property
    def tool_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "browser_fill",
                "description": "Fill an input field with text.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {
                            "type": "string",
                            "description": "CSS selector for the input field"
                        },
                        "value": {
                            "type": "string",
                            "description": "Text to fill"
                        }
                    },
                    "required": ["selector", "value"]
                }
            }
        }
    
    async def execute(self, selector: str, value: str, **kwargs) -> ToolResult:
        if not self.browser.state.page:
            return ToolResult.fail("No page open. Use browser_navigate first.")
        
        selector = _unescape_model_selector(selector)   # #581
        try:
            await self.browser.state.page.fill(selector, value, timeout=5000)
            return ToolResult.ok(f"Filled {selector} with '{value}'")
        except Exception as e:
            # #362: name what IS on the page so one failure answers the question
            # instead of seeding N more selector guesses.
            _cands = await describe_interactive_candidates(self.browser.state.page)
            _hint = _candidates_hint_688(_cands)
            return ToolResult.fail(f"Fill failed: {str(e)}.{_hint}")


class BrowserSelectTool(BaseTool):
    NAME = "browser_select"
    """Select an option from a dropdown"""
    
    def __init__(self, browser_manager: BrowserManager, **kwargs):
        super().__init__(name="browser_select", category=ToolCategory.RUNTIME, **kwargs)
        self.browser = browser_manager
    
    @property
    def tool_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "browser_select",
                "description": "Select an option from a <select> dropdown.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {
                            "type": "string",
                            "description": "CSS selector for the <select> element"
                        },
                        "value": {
                            "type": "string",
                            "description": "Option value to select"
                        },
                        "label": {
                            "type": "string",
                            "description": "Alternative: option text to select"
                        }
                    },
                    "required": ["selector"]
                }
            }
        }
    
    async def execute(self, selector: str, value: Optional[str] = None, label: Optional[str] = None, **kwargs) -> ToolResult:
        if not self.browser.state.page:
            return ToolResult.fail("No page open. Use browser_navigate first.")
        
        try:
            if value:
                await self.browser.state.page.select_option(selector, value=value, timeout=5000)
                return ToolResult.ok(f"Selected value '{value}' in {selector}")
            elif label:
                await self.browser.state.page.select_option(selector, label=label, timeout=5000)
                return ToolResult.ok(f"Selected label '{label}' in {selector}")
            else:
                return ToolResult.fail("Provide either value or label")
        except Exception as e:
            return ToolResult.fail(f"Select failed: {str(e)}")


class BrowserHoverTool(BaseTool):
    NAME = "browser_hover"
    """Hover over an element"""
    
    def __init__(self, browser_manager: BrowserManager, **kwargs):
        super().__init__(name="browser_hover", category=ToolCategory.RUNTIME, **kwargs)
        self.browser = browser_manager
    
    @property
    def tool_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "browser_hover",
                "description": "Hover over an element. Use to reveal tooltips, dropdown menus, or hover states.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {
                            "type": "string",
                            "description": "CSS selector for the element to hover over"
                        }
                    },
                    "required": ["selector"]
                }
            }
        }
    
    async def execute(self, selector: str, **kwargs) -> ToolResult:
        if not self.browser.state.page:
            return ToolResult.fail("No page open. Use browser_navigate first.")
        
        try:
            await self.browser.state.page.hover(selector, timeout=5000)
            return ToolResult.ok(f"Hovered over: {selector}")
        except Exception as e:
            return ToolResult.fail(f"Hover failed: {str(e)}")


class BrowserPressKeyTool(BaseTool):
    NAME = "browser_press_key"
    """Press a keyboard key"""
    
    def __init__(self, browser_manager: BrowserManager, **kwargs):
        super().__init__(name="browser_press_key", category=ToolCategory.RUNTIME, **kwargs)
        self.browser = browser_manager
    
    @property
    def tool_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "browser_press_key",
                "description": "Press a keyboard key. Use for Enter, Escape, Tab, shortcuts, etc.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Key to press (e.g., 'Enter', 'Escape', 'Tab', 'ArrowDown', 'Control+a')"
                        }
                    },
                    "required": ["key"]
                }
            }
        }
    
    async def execute(self, key: str, **kwargs) -> ToolResult:
        if not self.browser.state.page:
            return ToolResult.fail("No page open. Use browser_navigate first.")
        
        try:
            await self.browser.state.page.keyboard.press(key)
            return ToolResult.ok(f"Pressed key: {key}")
        except Exception as e:
            return ToolResult.fail(f"Key press failed: {str(e)}")


class BrowserScrollTool(BaseTool):
    NAME = "browser_scroll"
    """Scroll the page"""
    
    def __init__(self, browser_manager: BrowserManager, **kwargs):
        super().__init__(name="browser_scroll", category=ToolCategory.RUNTIME, **kwargs)
        self.browser = browser_manager
    
    @property
    def tool_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "browser_scroll",
                "description": "Scroll the page. Use to navigate long pages or reveal lazy-loaded content.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "direction": {
                            "type": "string",
                            "enum": ["up", "down", "top", "bottom"],
                            "description": "Scroll direction or position"
                        },
                        "pixels": {
                            "type": "integer",
                            "description": "Pixels to scroll (for up/down). Default: 500"
                        },
                        "selector": {
                            "type": "string",
                            "description": "Optional: scroll to this element"
                        }
                    },
                    "required": []
                }
            }
        }
    
    async def execute(self, direction: str = "down", pixels: int = 500, selector: Optional[str] = None, **kwargs) -> ToolResult:
        if not self.browser.state.page:
            return ToolResult.fail("No page open. Use browser_navigate first.")
        
        try:
            if selector:
                await self.browser.state.page.locator(selector).scroll_into_view_if_needed()
                return ToolResult.ok(f"Scrolled to element: {selector}")
            elif direction == "top":
                await self.browser.state.page.evaluate("window.scrollTo(0, 0)")
                return ToolResult.ok("Scrolled to top")
            elif direction == "bottom":
                await self.browser.state.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                return ToolResult.ok("Scrolled to bottom")
            elif direction == "up":
                await self.browser.state.page.evaluate(f"window.scrollBy(0, -{pixels})")
                return ToolResult.ok(f"Scrolled up {pixels}px")
            else:
                await self.browser.state.page.evaluate(f"window.scrollBy(0, {pixels})")
                return ToolResult.ok(f"Scrolled down {pixels}px")
        except Exception as e:
            return ToolResult.fail(f"Scroll failed: {str(e)}")


class BrowserWaitTool(BaseTool):
    NAME = "browser_wait"
    """Wait for an element to appear or a condition to be met"""
    
    def __init__(self, browser_manager: BrowserManager, **kwargs):
        super().__init__(name="browser_wait", category=ToolCategory.RUNTIME, **kwargs)
        self.browser = browser_manager
    
    @property
    def tool_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "browser_wait",
                "description": "Wait for an element to appear, become visible, or for a timeout. Use for waiting after page navigation or AJAX calls.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {
                            "type": "string",
                            "description": "CSS selector to wait for"
                        },
                        "state": {
                            "type": "string",
                            "enum": ["attached", "visible", "hidden", "detached"],
                            "description": "Element state to wait for (default: visible)"
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "Timeout in milliseconds (default: 10000)"
                        }
                    },
                    "required": ["selector"]
                }
            }
        }
    
    async def execute(self, selector: str, state: str = "visible", timeout: int = 10000, **kwargs) -> ToolResult:
        if not self.browser.state.page:
            return ToolResult.fail("No page open. Use browser_navigate first.")
        
        try:
            await self.browser.state.page.wait_for_selector(
                selector, 
                state=state,
                timeout=timeout
            )
            return ToolResult.ok(f"Element '{selector}' is now {state}")
        except Exception as e:
            return ToolResult.fail(f"Wait failed: {str(e)}")

