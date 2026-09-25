"""
Browser Inspection Tools - Elements, Text, Attributes, Visibility, Find, URL, A11y
"""
import re
from typing import Dict, List, Any, Optional

from utils.tool import BaseTool, ToolResult, ToolCategory
from ._manager import BrowserManager, PLAYWRIGHT_AVAILABLE


_ASYNC_FRAMING_ERRORS = (
    "illegal return statement",
    "await is only valid in async",
)


def is_navigation_race_error(message) -> bool:
    """True when the page moved UNDER the read — a transient, not a bad request (#689).

    Two engine messages, one condition:

        Page.evaluate: Execution context was destroyed, most likely because of a navigation
        Page.content:  Unable to retrieve content because the page is navigating

    The caller did nothing wrong and there is nothing for it to change; the page settles a
    moment later. `browser_click` already retries transients three times by default, but
    `browser_eval` retries only #364's framing rejection and the content read not at all, so
    these surfaced as plain failures.

    Measured over the 249 run logs: 132 of them, 50 in the LIVE era (r100+) — 74 destroyed
    contexts and 58 content reads. Same shape as #665 and #687: one member of a pair was
    treated and its twin was not.

    Follows #364's rule of letting the ENGINE's own error decide, so a genuine runtime error is
    never retried.
    """
    t = str(getattr(message, "message", message) or "").lower()
    return ("execution context was destroyed" in t
            or "page is navigating and changing the content" in t)


async def settle_after_navigation_689(page, timeout_ms: int = 3000) -> None:
    """Best-effort wait for the navigation that destroyed the context to finish.

    Never raises: this runs on an already-failing path, and a settle that times out must leave
    the caller free to report the ORIGINAL error rather than a new one about waiting.
    """
    if page is None:
        return
    for _state in ("domcontentloaded", "networkidle"):
        try:
            await page.wait_for_load_state(_state, timeout=timeout_ms)
        except Exception:
            return


def is_async_framing_error(message) -> bool:
    """True when the engine rejected the snippet's FRAMING, not its logic (#364).

    `page.evaluate` treats a snippet as an expression or a function body, so a
    top-level `return` or `await` is a syntax error even though the JavaScript
    is fine. 10 of the 15 browser_eval failures across r91/r92/r93 are exactly
    these two messages (6 illegal-return, 4 top-level-await); the other 5 are
    genuine runtime errors and must not be retried.
    """
    try:
        text = str(message or "").lower()
    except Exception:
        return False
    return any(m in text for m in _ASYNC_FRAMING_ERRORS)


def wrap_in_async_iife(script: str) -> str:
    """Re-frame a snippet as an async IIFE so top-level return/await are legal."""
    return "(async () => {\n" + str(script or "") + "\n})()"


class BrowserGetElementsTool(BaseTool):
    NAME = "browser_elements"
    """Get elements matching a selector"""
    
    def __init__(self, browser_manager: BrowserManager, **kwargs):
        super().__init__(name="browser_elements", category=ToolCategory.RUNTIME, **kwargs)
        self.browser = browser_manager
    
    @property
    def tool_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "browser_elements",
                "description": "Find elements on the page matching a selector. Returns element info.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {
                            "type": "string",
                            "description": "CSS selector to find elements"
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
            elements = await self.browser.state.page.query_selector_all(selector)
            
            element_info = []
            for i, el in enumerate(elements[:10]):
                tag = await el.evaluate("el => el.tagName")
                text = await el.inner_text() if await el.is_visible() else ""
                attrs = await el.evaluate("el => Array.from(el.attributes).map(a => ({name: a.name, value: a.value}))")
                
                element_info.append({
                    "index": i,
                    "tag": tag,
                    "text": text[:100] if text else "",
                    "attributes": attrs[:5],
                })
            
            return ToolResult.ok({
                "selector": selector,
                "count": len(elements),
                "elements": element_info,
            })
            
        except Exception as e:
            return ToolResult.fail(f"Query failed: {str(e)}")


class BrowserEvaluateTool(BaseTool):
    NAME = "browser_eval"
    """Execute JavaScript in the page context"""
    
    def __init__(self, browser_manager: BrowserManager, **kwargs):
        super().__init__(name="browser_eval", category=ToolCategory.RUNTIME, **kwargs)
        self.browser = browser_manager
    
    @property
    def tool_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "browser_eval",
                "description": "Execute JavaScript code in the browser page context. Use to inspect state or debug.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "script": {
                            "type": "string",
                            "description": "JavaScript code to execute"
                        }
                    },
                    "required": ["script"]
                }
            }
        }
    
    async def execute(self, script: str, **kwargs) -> ToolResult:
        if not self.browser.state.page:
            return ToolResult.fail("No page open. Use browser_navigate first.")
        
        _ran = script
        try:
            result = await self.browser.state.page.evaluate(script)
        except Exception as e:
            # #364: only a FRAMING rejection is retried, and only once. Wrapping
            # unconditionally would break expression semantics —
            # `document.title` returns the title, `(async () => { document.title
            # })()` returns undefined — and sniffing for a top-level
            # return/await with a regex would misfire on a nested function or a
            # string literal. Letting the engine's own error decide has no false
            # positives: a script that works today is never touched.
            # #689: the page moved under the read. Settle once and re-run — the script is
            # fine and the agent has nothing to change, so failing here just burns a round.
            if is_navigation_race_error(e):
                await settle_after_navigation_689(self.browser.state.page)
                try:
                    result = await self.browser.state.page.evaluate(script)
                    return ToolResult.ok({
                        "script": script[:100] + "..." if len(script) > 100 else script,
                        "result": str(result)[:500] if result else None,
                    })
                except Exception as _e2:
                    return ToolResult.fail(
                        f"Eval failed: {str(e)}. Retried once after the navigation settled and "
                        f"it failed again ({str(_e2)[:120]}) — the page may be reloading in a "
                        "loop, or the script depends on state the navigation cleared.")
            if not is_async_framing_error(e):
                return ToolResult.fail(f"Eval failed: {str(e)}")
            _ran = wrap_in_async_iife(script)
            try:
                result = await self.browser.state.page.evaluate(_ran)
            except Exception:
                # Report the ORIGINAL failure — the retry is an implementation
                # detail and its error would only mislead.
                return ToolResult.fail(f"Eval failed: {str(e)}")
        return ToolResult.ok({
            "script": script[:100] + "..." if len(script) > 100 else script,
            "result": str(result)[:500] if result else None,
        })


class BrowserGetUrlTool(BaseTool):
    NAME = "browser_get_url"
    """Get the current page URL"""

    def __init__(self, browser_manager: BrowserManager, **kwargs):
        super().__init__(name="browser_get_url", category=ToolCategory.RUNTIME, **kwargs)
        self.browser = browser_manager

    @property
    def tool_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "browser_get_url",
                "description": "Return the current browser URL.",
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
        try:
            url = self.browser.state.page.url
            return ToolResult.ok({"url": url})
        except Exception as e:
            return ToolResult.fail(f"Get URL failed: {str(e)}")


class BrowserWaitForUrlTool(BaseTool):
    NAME = "browser_wait_for_url"
    """Wait for the page URL to match a substring or regex"""

    def __init__(self, browser_manager: BrowserManager, **kwargs):
        super().__init__(name="browser_wait_for_url", category=ToolCategory.RUNTIME, **kwargs)
        self.browser = browser_manager

    @property
    def tool_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "browser_wait_for_url",
                "description": "Wait until the current URL matches the expected substring or regex.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "expected": {"type": "string", "description": "Expected URL substring or regex pattern"},
                        "mode": {"type": "string", "enum": ["text", "regex"], "description": "Match mode (default: text)"},
                        "timeout": {"type": "integer", "description": "Timeout in ms (default: 10000)"}
                    },
                    "required": ["expected"]
                }
            }
        }

    async def execute(self, expected: str, mode: str = "text", timeout: int = 10000, **kwargs) -> ToolResult:
        if not self.browser.state.page:
            return ToolResult.fail("No page open. Use browser_navigate first.")
        try:
            page = self.browser.state.page
            if mode == "regex":
                await page.wait_for_function(
                    "(re) => new RegExp(re).test(window.location.href)",
                    arg=expected,
                    timeout=timeout,
                )
                return ToolResult.ok({"matched": True, "url": page.url, "mode": "regex", "expected": expected})
            else:
                await page.wait_for_url(f"**{expected}**", timeout=timeout)
                return ToolResult.ok({"matched": True, "url": page.url, "mode": "text", "expected": expected})
        except Exception as e:
            return ToolResult.fail(f"Wait for URL failed: {str(e)}")


def _widen_to_accessible_names_1202um(scope, query, text_loc):
    """#1202um: the recovery path this tool IS could not see the controls that need it.

    `browser_click`'s failure hint tells the agent, in so many words, "Try using
    browser_find() first to check if element exists". browser_find searched VISIBLE TEXT
    only -- so for an icon button, whose whole identity is `aria-label`, the recommended
    recovery returns nothing and the agent concludes the control is absent.

    MEASURED on a live generated app (r132 home), per query, text search vs accessible name:

        'Like'          get_by_text 0   aria-label 1     ("Like video")
        'Comment'       get_by_text 0   aria-label 1     ("Open comments")
        'Toggle sound'  get_by_text 0   aria-label 1
        'Explore'       get_by_text 1   aria-label 0     (a text nav link)

    The two are COMPLEMENTARY, not redundant: text search finds the navigation, accessible
    names find the action controls, and the tool offered only the first. 765 browser_find
    calls across 66 runs went through it.

    Widening only ADDS matches -- the text results are still in the union and still first --
    so a query that worked before works identically. Regex mode is left alone: its pattern is
    written against page text, and silently applying it to attributes would change what an
    existing regex means.
    """
    try:
        q = str(query or "")
        if not q or '"' in q:
            # A quote would break out of the attribute selector; the text result stands
            # rather than risking a malformed selector on a recovery path.
            return text_loc
        attrs = ", ".join(
            f'[{a}*="{q}" i]' for a in ("aria-label", "title", "placeholder", "alt", "name")
        )
        return text_loc.or_(scope.locator(attrs))
    except Exception:
        # Runs on a recovery path: a failure here must cost the widening, not the search.
        return text_loc


class BrowserFindTool(BaseTool):
    NAME = "browser_find"
    """Find elements by text (substring) or regex for reliable targeting"""

    def __init__(self, browser_manager: BrowserManager, **kwargs):
        super().__init__(name="browser_find", category=ToolCategory.RUNTIME, **kwargs)
        self.browser = browser_manager

    @property
    def tool_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "browser_find",
                "description": "Find elements by visible text (substring) or regex. Returns up to 10 matches with basic metadata to help you choose what to click.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Text to search for (substring) or regex pattern"
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["text", "regex"],
                            "description": "Search mode (default: text)"
                        },
                        "selector": {
                            "type": "string",
                            "description": "Optional CSS selector to scope the search (e.g. 'nav', 'main', '.sidebar')"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Max matches to return (default: 10, max: 20)"
                        }
                    },
                    "required": ["query"]
                }
            }
        }

    async def execute(self, query: str, mode: str = "text", selector: Optional[str] = None, limit: int = 10, **kwargs) -> ToolResult:
        if not self.browser.state.page:
            return ToolResult.fail("No page open. Use browser_navigate first.")

        limit = max(1, min(int(limit or 10), 20))

        try:
            page = self.browser.state.page
            scope = page.locator(selector) if selector else page

            if mode == "regex":
                pattern = re.compile(query, re.IGNORECASE)
                loc = scope.get_by_text(pattern)
            else:
                loc = scope.get_by_text(query, exact=False)
                loc = _widen_to_accessible_names_1202um(scope, query, loc)

            count = await loc.count()
            out = []

            for i in range(min(count, limit)):
                item = loc.nth(i)
                meta = await item.evaluate(
                    """(el) => {
                      const tag = el.tagName?.toLowerCase() || null;
                      const id = el.id || null;
                      const className = el.className ? String(el.className).slice(0, 200) : null;
                      const text = (el.innerText || el.textContent || '').trim().slice(0, 200);
                      const href = el.getAttribute ? el.getAttribute('href') : null;
                      const role = el.getAttribute ? el.getAttribute('role') : null;
                      return { tag, id, className, text, href, role };
                    }"""
                )
                out.append(meta)

            return ToolResult.ok({
                "query": query,
                "mode": mode,
                "selector": selector,
                "count": count,
                "matches": out,
            })
        except Exception as e:
            return ToolResult.fail(f"Find failed: {str(e)}")


class BrowserGetAttributeTool(BaseTool):
    NAME = "browser_get_attribute"
    """Get an attribute from an element"""
    
    def __init__(self, browser_manager: BrowserManager, **kwargs):
        super().__init__(name="browser_get_attribute", category=ToolCategory.RUNTIME, **kwargs)
        self.browser = browser_manager
    
    @property
    def tool_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "browser_get_attribute",
                "description": "Get the value of an attribute from an element. Use to check src, href, disabled, etc.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {
                            "type": "string",
                            "description": "CSS selector for the element"
                        },
                        "attribute": {
                            "type": "string",
                            "description": "Attribute name to get (e.g., 'href', 'src', 'disabled')"
                        }
                    },
                    "required": ["selector", "attribute"]
                }
            }
        }
    
    async def execute(self, selector: str, attribute: str, **kwargs) -> ToolResult:
        if not self.browser.state.page:
            return ToolResult.fail("No page open. Use browser_navigate first.")
        
        try:
            value = await self.browser.state.page.get_attribute(selector, attribute, timeout=5000)
            return ToolResult.ok({
                "selector": selector,
                "attribute": attribute,
                "value": value
            })
        except Exception as e:
            return ToolResult.fail(f"Get attribute failed: {str(e)}")


class BrowserGetTextTool(BaseTool):
    NAME = "browser_get_text"
    """Get text content from an element"""
    
    def __init__(self, browser_manager: BrowserManager, **kwargs):
        super().__init__(name="browser_get_text", category=ToolCategory.RUNTIME, **kwargs)
        self.browser = browser_manager
    
    @property
    def tool_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "browser_get_text",
                "description": "Get text content from an element. Use to verify displayed content.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {
                            "type": "string",
                            "description": "CSS selector for the element"
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
            text = await self.browser.state.page.inner_text(selector, timeout=5000)
            return ToolResult.ok({
                "selector": selector,
                "text": text
            })
        except Exception as e:
            return ToolResult.fail(f"Get text failed: {str(e)}")


class BrowserCheckVisibleTool(BaseTool):
    NAME = "browser_is_visible"
    """Check if an element is visible"""
    
    def __init__(self, browser_manager: BrowserManager, **kwargs):
        super().__init__(name="browser_is_visible", category=ToolCategory.RUNTIME, **kwargs)
        self.browser = browser_manager
    
    @property
    def tool_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "browser_is_visible",
                "description": "Check if an element is visible on the page. Use for verifying UI state.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {
                            "type": "string",
                            "description": "CSS selector for the element"
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
            is_visible = await self.browser.state.page.is_visible(selector, timeout=5000)
            return ToolResult.ok({
                "selector": selector,
                "is_visible": is_visible
            })
        except Exception as e:
            return ToolResult.fail(f"Visibility check failed: {str(e)}")


class BrowserCheckAccessibilityTool(BaseTool):
    NAME = "browser_check_a11y"
    """Check page accessibility - find elements without proper labels, alt text, etc."""
    
    def __init__(self, browser_manager: BrowserManager, **kwargs):
        super().__init__(name="browser_check_a11y", category=ToolCategory.RUNTIME, **kwargs)
        self.browser = browser_manager
    
    @property
    def tool_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "browser_check_a11y",
                "description": "Check basic accessibility issues: images without alt, buttons without labels, form inputs without labels.",
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
        
        try:
            issues = await self.browser.state.page.evaluate("""
                () => {
                    const issues = [];
                    
                    // Images without alt
                    document.querySelectorAll('img').forEach((img, i) => {
                        if (!img.alt && !img.getAttribute('aria-label')) {
                            issues.push({type: 'img-no-alt', selector: `img:nth-of-type(${i+1})`, src: img.src});
                        }
                    });
                    
                    // Buttons without accessible text
                    document.querySelectorAll('button').forEach((btn, i) => {
                        const text = btn.textContent?.trim();
                        const ariaLabel = btn.getAttribute('aria-label');
                        const title = btn.getAttribute('title');
                        if (!text && !ariaLabel && !title) {
                            issues.push({type: 'button-no-label', selector: `button:nth-of-type(${i+1})`});
                        }
                    });
                    
                    // Form inputs without labels
                    document.querySelectorAll('input, select, textarea').forEach((input, i) => {
                        const id = input.id;
                        const ariaLabel = input.getAttribute('aria-label');
                        const placeholder = input.placeholder;
                        const hasLabel = id && document.querySelector(`label[for="${id}"]`);
                        
                        if (!hasLabel && !ariaLabel && !placeholder) {
                            issues.push({type: 'input-no-label', selector: `${input.tagName.toLowerCase()}:nth-of-type(${i+1})`});
                        }
                    });
                    
                    // Links without text
                    document.querySelectorAll('a').forEach((link, i) => {
                        const text = link.textContent?.trim();
                        const ariaLabel = link.getAttribute('aria-label');
                        if (!text && !ariaLabel) {
                            issues.push({type: 'link-no-text', selector: `a:nth-of-type(${i+1})`, href: link.href});
                        }
                    });
                    
                    return issues;
                }
            """)
            
            return ToolResult.ok({
                "url": self.browser.state.current_url,
                "total_issues": len(issues),
                "issues": issues[:20],
            })
        except Exception as e:
            return ToolResult.fail(f"Accessibility check failed: {str(e)}")


class BrowserAccessibilityTreeTool(BaseTool):
    NAME = "browser_a11y_tree"
    """Return a pruned accessibility tree snapshot to help the agent decide how to interact"""

    def __init__(self, browser_manager: BrowserManager, **kwargs):
        super().__init__(name="browser_a11y_tree", category=ToolCategory.RUNTIME, **kwargs)
        self.browser = browser_manager

    @property
    def tool_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "browser_a11y_tree",
                "description": "Get a pruned accessibility tree snapshot (roles/names/states) to help choose stable interactions. Use when debugging or when selectors/text clicks are unreliable.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {
                            "type": "string",
                            "description": "Optional CSS selector to scope snapshot (e.g. 'main', 'nav', '.sidebar')"
                        },
                        "interesting_only": {
                            "type": "boolean",
                            "description": "If true, only include 'interesting' nodes (default: true)"
                        },
                        "max_nodes": {
                            "type": "integer",
                            "description": "Max nodes to return (default: 300)"
                        }
                    },
                    "required": []
                }
            }
        }

    async def execute(
        self,
        selector: Optional[str] = None,
        interesting_only: bool = True,
        max_nodes: int = 300,
        **kwargs
    ) -> ToolResult:
        if not PLAYWRIGHT_AVAILABLE:
            return ToolResult.fail("Playwright not installed")
        if not self.browser.state.page:
            return ToolResult.fail("No page open. Use browser_navigate first.")

        max_nodes = max(50, min(int(max_nodes or 300), 2000))

        try:
            page = self.browser.state.page
            ctx = self.browser.state.context
            if not ctx:
                return ToolResult.fail("Browser context not available")

            cdp = await ctx.new_cdp_session(page)
            await cdp.send("Accessibility.enable")

            nodes: List[Dict[str, Any]] = []
            if selector:
                try:
                    await cdp.send("DOM.enable")
                    doc = await cdp.send("DOM.getDocument", {"depth": 1, "pierce": True})
                    root_id = (doc.get("root") or {}).get("nodeId")
                    if root_id:
                        q = await cdp.send("DOM.querySelector", {"nodeId": root_id, "selector": selector})
                        dom_node_id = q.get("nodeId")
                        if dom_node_id:
                            partial = await cdp.send(
                                "Accessibility.getPartialAXTree",
                                {"nodeId": dom_node_id, "fetchRelatives": True},
                            )
                            nodes = partial.get("nodes", []) or []
                except Exception:
                    nodes = []

            if not nodes:
                full = await cdp.send("Accessibility.getFullAXTree")
                nodes = full.get("nodes", []) or []

            if not nodes:
                return ToolResult.ok({"total_nodes": 0, "text": "", "nodes": []})

            by_id = {n.get("nodeId"): n for n in nodes if n.get("nodeId") is not None}

            def _val(obj: Any) -> Any:
                if isinstance(obj, dict):
                    return obj.get("value")
                return obj

            def _role(n: Dict[str, Any]) -> str:
                r = n.get("role") or {}
                return str(_val(r) or "")

            def _name(n: Dict[str, Any]) -> str:
                nm = n.get("name") or {}
                return str(_val(nm) or "")

            interactive_roles = {
                "button", "link", "textbox", "searchbox", "combobox",
                "menuitem", "tab", "checkbox", "radio", "option", "switch",
            }

            def _props_map(n: Dict[str, Any]) -> Dict[str, Any]:
                out = {}
                for p in n.get("properties", []) or []:
                    k = p.get("name")
                    v = _val(p.get("value"))
                    if k:
                        out[str(k)] = v
                return out

            def _is_interesting(n: Dict[str, Any]) -> bool:
                if not interesting_only:
                    return True
                if n.get("ignored"):
                    return False
                role = _role(n).lower()
                name = _name(n).strip()
                if role in interactive_roles:
                    return True
                if name:
                    return True
                props = _props_map(n)
                for k in ["focusable", "focused", "checked", "pressed", "expanded", "selected", "disabled"]:
                    if k in props:
                        return True
                return False

            root = None
            for n in nodes:
                if _role(n) == "RootWebArea":
                    root = n
                    break
            if root is None:
                root = nodes[0]

            lines: List[str] = []
            emitted = 0
            visited = set()

            def walk(node_id: Any, depth: int = 0):
                nonlocal emitted
                if emitted >= max_nodes:
                    return
                if node_id in visited:
                    return
                visited.add(node_id)
                n = by_id.get(node_id)
                if not n:
                    return

                if _is_interesting(n):
                    role = _role(n)
                    name = _name(n).strip()
                    props = _props_map(n)
                    parts = [f"role={role}"]
                    if name:
                        parts.append(f"name={name!r}")
                    for k in ["checked", "pressed", "expanded", "disabled", "focused", "focusable"]:
                        if k in props and props[k] is not None:
                            parts.append(f"{k}={props[k]}")
                    indent = "  " * depth
                    lines.append(indent + ", ".join(parts))
                    emitted += 1

                for child_id in n.get("childIds", []) or []:
                    walk(child_id, depth + 1)

            walk(root.get("nodeId"), 0)

            return ToolResult.ok({
                "url": self.browser.state.current_url,
                "selector": selector,
                "interesting_only": interesting_only,
                "total_nodes": len(nodes),
                "returned_lines": len(lines),
                "text": "\n".join(lines),
            })
        except Exception as e:
            return ToolResult.fail(f"A11y snapshot failed: {str(e)}")

