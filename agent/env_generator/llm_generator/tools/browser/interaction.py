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
# #1202uk: `title` joins the list, and the element's visible TEXT is collected separately
# below (it is not an attribute). Both are real locators, and without them a control whose
# only identity is what it says on screen was reported as `{type='button'}` or dropped.
_CANDIDATE_ATTRS = ("name", "id", "placeholder", "aria-label", "type", "data-testid", "title")


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

# #1202uk: how many elements the probe examines before ranking. MEASURED over 21 live pages
# across three running generated environments (r122/r126/r132; home, explore, login, profile,
# settings, messages, notifications): 6 to 47 interactable controls, median 19, busiest page
# 47. 400 leaves eight times the busiest page observed; the bound exists only so a
# pathological DOM cannot stall an error report, never to cut a real page short.
_SCAN_CAP_1202UK = 400


async def describe_interactive_candidates(page, limit: int = 12, wanted: str = "") -> str:
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
    # #1202uk: `limit * 3` capped how many elements were EXAMINED, and the ranking below
    # runs afterwards -- so on a page with more controls than the cap, the one the agent asked
    # for could never reach the ranking no matter how well it matched. The cap now bounds the
    # per-element `inner_text` round-trips (this runs on an already-failing path) rather than
    # the answer: generous enough that a real page fits, finite so a pathological one cannot
    # stall the error report.
    for el in (els or [])[:_SCAN_CAP_1202UK]:
        try:
            attrs = {}
            for a in _CANDIDATE_ATTRS:
                try:
                    v = await el.get_attribute(a)
                except Exception:
                    v = None
                if v:
                    attrs[a] = str(v)[:40]
            # #1202uk: A CONTROL WHOSE ONLY IDENTITY IS ITS VISIBLE TEXT WAS DROPPED HERE.
            # `_CANDIDATE_ATTRS` carries no text, so `<button>For You</button>` produced an
            # empty `attrs` and this `continue` deleted it from the list entirely. MEASURED
            # against a live generated app: the page offers 19 controls, this reported 10, and
            # the 9 it silently omitted were the ENTIRE left navigation -- For You, Shop,
            # Explore, Following, LIVE, Upload, Profile, More, Log in. Four more survived only
            # as `{type='button'}`, which names nothing and cannot be turned into a selector.
            #
            # That is the exact prose r134's verifier wrote onto eight delivery-blocking
            # checks: "only unlabeled buttons were interactable". It was reading this list.
            # The app was correct -- the controls were on screen in the verifier's own saved
            # screenshot -- so the frontend was sent P0s to add labels that already existed,
            # and the next rerun read the same noise. Across 151 run logs: 538 browser
            # click/fill failures, 230 carrying this list, and 90 of those (39%) majority
            # `{type='...'}` entries.
            #
            # #362 built this list so the model would stop GUESSING selectors. A list that
            # omits the page's primary navigation does the opposite. Text and `title` are
            # both real Playwright locators (`text=`, `[title=...]`), so an entry carrying
            # them is addressable in the same sense the attributes are.
            _text = ""
            try:
                _text = " ".join(((await el.inner_text()) or "").split())[:40]
            except Exception:
                _text = ""
            if _text:
                attrs["text"] = _text
            # The skip stays exactly what it was -- ONLY an element with no attribute AND no
            # text. My first version of this required one of the NAMING keys, which skipped
            # `{type='button'}`; on a page whose controls are all unlabelled icon buttons that
            # empties `out`, and an empty `out` returns "" -- which #688 defines as "could not
            # look", so the caller drops the hint entirely. That is the exact failure #688
            # exists to prevent, reintroduced. `{type='button'}` is poor, but "this page has
            # controls I cannot name" is a true and useful thing to say; the ranking below is
            # what keeps it from crowding out the answer.
            if not attrs:
                continue          # nothing addressable — a selector cannot name it
            out.append(attrs)
        except Exception:
            continue
    # #1202uk PART TWO: DOM ORDER PUTS THE CHROME FIRST AND TRUNCATES AWAY THE ANSWER.
    # Naming the text-only controls (above) made the list complete and therefore LONGER, and
    # `limit` then cut it at the navigation -- on the live page the agent asking for "Like"
    # got a list ending at "Get App", with the Like button three entries past the cut. That
    # is worse than the omission it replaced, so the list is now ranked by what was ASKED FOR
    # before it is truncated.
    #
    # It also repairs the mismatch that produced r134's eight blocked flows on its own. Agents
    # ask for the VERB (`name="Like"`) while generated apps label the control with verb plus
    # object ("Like video", "Open comments", "Toggle sound") -- and `role=button[name="Like"]`,
    # the selector the role branch builds, is an EXACT match, so it misses. Ranking surfaces
    # `{aria-label='Like video', data-testid='like-video'}` first, which hands the agent the
    # real string instead of leaving it to guess a second time.
    #
    # Substring both ways, case-folded: the wanted text may be shorter than the label ("Like"
    # in "Like video") or longer ("Add friend" where the control says "Add"). Ties keep DOM
    # order, so with no `wanted` the list is exactly what it was.
    _w = " ".join(str(wanted or "").split()).casefold()
    if _w:
        def _rank(item):
            for _v in item.values():
                _v = str(_v).casefold()
                if _v == _w:
                    return 0
                if _w in _v or _v in _w:
                    return 1
            return 2
        out = sorted(out, key=_rank)
    _shown = out[:limit]
    _rendered = ["{" + ", ".join(f"{k}={v!r}" for k, v in a.items()) + "}" for a in _shown]
    if len(out) > len(_shown):
        # #883: a truncated list that does not say so reads as an exhaustive one, and the
        # agent concludes the control is absent.
        _rendered.append(f"... and {len(out) - len(_shown)} more")
    return "; ".join(_rendered)


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
        # #1202ul: `role=button[name="Like"]` -- the string the role branch builds -- is an
        # EXACT match on the accessible name. `page.get_by_role("button", name="Like")`, the
        # API this tool's own description advertises ("role + name: ARIA role with accessible
        # name"), defaults to a case-insensitive SUBSTRING. The two disagree on exactly the
        # shape generated apps produce.
        #
        # MEASURED on a live generated app (r132), same page, same button:
        #     role=button[name="Like"]                -> 0 matches
        #     get_by_role("button", name="Like")      -> 1   (the control is "Like video")
        #     get_by_role("button", name="Comment")   -> 1   (the control is "Open comments")
        # ACROSS THE CORPUS: 2287 aria-labels in generated frontends, 927 of them (40%) are
        # multi-word verb-object labels -- "Previous video", "Close comments", "Add to My
        # List", "Email address", "Forward 10 seconds" -- spanning TikTok, Netflix and the
        # rest; and 814 of 2337 browser_click calls (34%), over 60 runs, pass role+name.
        #
        # THE COST, in r134: eight delivery-blocking ui_flow checks, each reported as "cannot
        # locate accessible Like/Comment/Follow control" while the control was on screen in
        # the check's own saved screenshot and carried the label in source. The frontend was
        # sent P0s to add labels that already existed.
        #
        # `.first` keeps the non-strict "first match wins" semantics `page.click(selector)`
        # already had for every other branch -- get_by_role returns a strict Locator, and
        # clicking it directly would turn two matches into a new class of failure.
        role_query = None
        
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
            role_query = (role, name)   # #1202ul
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
                
                # #1202ul: the role branch goes through the API, not the selector string.
                _target = None
                if role_query is not None:
                    try:
                        _r, _n = role_query
                        _loc = page.get_by_role(_r, name=_n) if _n else page.get_by_role(_r)
                        _target = _loc.first
                    except Exception:
                        # An unknown role, or any construction failure, falls back to the
                        # string form rather than losing the attempt.
                        _target = None

                # First, wait for element to be visible if requested
                if wait_for_visible and attempt == 0:
                    try:
                        if _target is not None:
                            await _target.wait_for(state="visible", timeout=timeout)
                        else:
                            await page.wait_for_selector(
                                final_selector,
                                state="visible",
                                timeout=timeout
                            )
                    except Exception:
                        pass  # Continue to click attempt even if wait fails
                
                # Attempt click
                if _target is not None:
                    await _target.click(timeout=timeout)
                else:
                    await page.click(final_selector, timeout=timeout)
                
                # Success
                result_msg = f"Clicked element ({selector_type})"
                if attempt > 0:
                    result_msg += f" after {attempt + 1} attempts"
                return ToolResult.ok(result_msg)
                
            except Exception as e:
                last_error = str(e)

                # #1202y: retrying a click against a driver that is GONE just spends the
                # remaining attempts on the same corpse. r32's 21:39 record is exactly that
                # shape — two attempts, both reporting the connection to the driver closed.
                # Rebuild first, then let the normal retry proceed against a live page.
                # Best-effort: if the rebuild fails, the loop behaves as before.
                #
                # The failure text is deliberately NOT quoted here: #362's test locates that
                # message by searching this file for it, so a second copy in a comment
                # becomes the match and the test reads the wrong window.
                try:
                    from ._manager import is_dead_driver_error_1202y
                    if is_dead_driver_error_1202y(e):
                        if await self.browser.recover_for_retry_1202y(e):
                            page = self.browser.state.page
                except Exception:
                    pass

                if attempt < retry - 1:
                    # Wait before retry
                    await asyncio.sleep(0.5)
                    
                    # Try scrolling element into view on retry
                    try:
                        await self.browser.state.page.evaluate(
                            f"document.querySelector('{final_selector}')?.scrollIntoView({{behavior: 'smooth', block: 'center'}})"
                        )
                        await asyncio.sleep(0.3)
                    # #1074: `except Exception`, NOT a bare `except`. This is the only
                    # bare handler in the package that wraps an `await`, and
                    # CancelledError is a BaseException — so cancelling this tool mid
                    # scroll (a step timeout, a lane torn down) was CAUGHT here and
                    # dropped. A cancellation is delivered once; swallowing it loses it,
                    # and the step then runs on to the click as if nothing had happened.
                    # The scroll itself stays best-effort, which is all it was ever for.
                    except Exception:
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
            getattr(getattr(self.browser, "state", None), "page", None),
            wanted=name or aria_label or text or testid or "")   # #1202uk
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
            _cands = await describe_interactive_candidates(
                self.browser.state.page, wanted=selector or "")   # #1202uk
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

