"""
Browser Manager - Manages browser lifecycle and state
"""
import asyncio
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


import time as _time1203hn


# #1198: how many times the shared driver may be rebuilt in one process. A death is a flake
# worth one retry; repeated deaths are a crash loop, and relaunching into it would burn the
# run's remaining ticks re-dying instead of reporting.
_MAX_RELAUNCH_1198 = 5
# #1203hn: and the count is of CONSECUTIVE deaths, because #1198's own distinction --
# "a flake, not a crash loop" -- is about deaths that come one on top of another, while the
# lifetime count it actually kept punishes a run for doing browser work.
#
# MEASURED over every log on disk: 78 rebuilds across 42 runs, and the dominant cause is
# the Playwright driver exhausting Node's heap -- 36 occurrences across 29 runs, the most
# recent being r171, r173, r177 and r178. Those are not crash loops: the driver's own GC
# report gives its uptime at death, and the MINIMUM over all 36 is **693 seconds**, median
# 4588 (76 minutes), longest 10479. It died because it had been working, and every one of
# those rebuilds succeeded.
#
# Of the 35 gaps between consecutive rebuilds, 10 are under 60 seconds -- those are the
# crash loops #1198 is for. Projected (#1203d9) over the corpus with the reset below: the
# lifetime peak of 5 (r119, r120 and r171 all reached the cap, r171 with three heap deaths)
# becomes a consecutive peak of 3, no run reaches the cap, and the 10 rapid rebuilds still
# count toward it -- r127 and r164 still peak at 3. So the guard keeps every case it was
# built for and stops firing on throughput.
#
# r171 is the one that spent it: 5 of 5, one death short of losing every browser gate for
# the rest of a run that delivered 5 releases.
_RELAUNCH_RESET_AFTER_SEC_1203HN = 60.0


# #1202y: the error text a dead driver produces, whichever tool trips over it first.
_DEAD_DRIVER_MARKS_1202Y = (
    "Connection closed while reading from the driver",
    "Target page, context or browser has been closed",
    "Browser has been closed",
    "Target closed",
    "browserContext.newPage",
)


def is_dead_driver_error_1202y(exc: Any) -> bool:
    """Is this exception the shared driver having gone away? (#1202y)"""
    try:
        t = str(exc)
    except Exception:
        return False
    return any(m in t for m in _DEAD_DRIVER_MARKS_1202Y)


def _request_method_1202uq(response) -> str:
    """The request's method, or "" if the request object has gone away. See below."""
    try:
        return str(response.request.method or "")
    except Exception:
        return ""


def _authorization_sent_1202uq(response) -> bool:
    """True if the request behind this response carried an `Authorization` header.

    #1202uq: separates "the app called a protected endpoint with no credentials" from "the
    browser is still carrying a token from an earlier flow". Both produce a 401 and the record
    could not tell them apart, so a verifier reported the second as the first.

    Runs inside a response event handler: it must never raise, or a diagnostic costs the
    capture. `request.headers` is the synchronous view and carries headers the page SET --
    verified against a live page: a fetch with `Authorization` reads True, the same fetch
    without it reads False.
    """
    try:
        return bool((response.request.headers or {}).get("authorization"))
    except Exception:
        return False


def page_error_fields_1202br(error) -> Dict[str, str]:
    """A Playwright pageerror, read the way a lane can act on.

    #1203iu lifted this out of `BrowserManager._on_page_error` so a SECOND reader cannot
    re-learn its scar (#1032). `test_user_validation`'s auth-flow probe is that second
    reader: it attached no pageerror listener at all, so a submit handler that threw was
    reported as "submit sent NO /auth request -- the form is not wired to the API".

    The scar, in #1202br's own words: `str(error)` yields only a minified location, and
    netflix-r33 recorded exactly that as the evidence for two blocking UI flows --
    "Error at http://localhost:8053/assets/index--TCHSJCV.js:49:360" -- which names no
    source a lane can open. `.message` is the one it can search for. Each attribute is read
    defensively: a reader that raises here would lose the error entirely, which is worse
    than a vague one.
    """
    def _attr(name):
        try:
            v = getattr(error, name, None)
            return str(v) if v else ""
        except Exception:
            return ""

    msg, kind, stack = _attr("message"), _attr("name"), _attr("stack")
    try:
        text = str(error)
    except Exception:
        text = ""
    if msg and msg not in text:
        text = f"{kind or 'Error'}: {msg} — {text}" if kind else f"{msg} — {text}"
    return {
        "text": text,
        "message": msg,
        "error_name": kind,
        # Bounded: a bundled stack is long and repetitive, and the frames that name
        # the lane's own files are at the top.
        "stack": "\n".join(stack.splitlines()[:6]) if stack else "",
    }


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
    
    async def recover_for_retry_1202y(self, exc: Any) -> bool:
        """Rebuild if `exc` says the driver died, so the caller can retry ONCE. (#1202y)

        #1198 made a dead driver recoverable, and r30 proved it: the driver died twice and
        was rebuilt twice, with no permanent failures. What it does not do is save the call
        that DISCOVERS the death — `ensure_browser` runs at the start of a tool, so the
        in-flight `goto`/`click` still fails and the lane still writes a FAIL record for it.
        r32 measured the residue: two rebuilds, and two failures that reached the verifier —

            21:39  browser_click FAILED: Page.click: Connection closed while reading ...
            00:24  browser_navigate FAILED (113778ms): Page.goto: Connection closed ...

        Both are the probe, not the product, and both become prose in a check record that
        someone then has to triage. Rebuilding here and retrying once makes the death
        invisible to the caller, which is where it belongs.

        Returns True only when it both recognised the error AND rebuilt, so a caller can
        retry without having to re-check anything. Never raises.
        """
        try:
            if not is_dead_driver_error_1202y(exc):
                return False
            await self._discard_dead_driver_1198()
            return bool(await self.ensure_browser())
        except Exception:
            return False

    async def _driver_is_live_1198(self) -> bool:
        """Is the shared driver actually reachable, or only non-None? (#1198)

        `ensure_browser` used to ask ONLY `self.state.browser is None`. A driver that has
        DIED leaves a perfectly non-None object behind, so the check passed forever and every
        later call failed instantly against a dead pipe. r26: 214 of its 232 navigation
        failures are one line — `Page.goto: Connection closed while reading from the driver`,
        returning in 7ms, preceded by asyncio's `pipe closed by peer`. There is no recovery
        path anywhere in this module: `is_connected`/`is_closed` appear nowhere and
        `state.browser` is never reset outside the explicit `close()`. One death therefore
        blinds every browser gate for the REST OF THE RUN, across all 12 browser_test_user
        lanes, which share this one manager.

        `is_connected()` alone is not enough — it can still report True over a pipe whose peer
        is gone — so this also does one cheap protocol round-trip, which is precisely what
        comes back instantly when the driver is gone.

        #234 healed a MISSING browser binary and stopped there; this is the same class of
        fault one step later in the lifecycle. Any error here means "not live": the caller
        rebuilds, which is always safe.
        """
        try:
            if self.state.browser is None or not self.state.browser.is_connected():
                return False
            if self.state.page is None or self.state.page.is_closed():
                return False
            # #1199c: probe the CONTEXT, not the page. Both raise TargetClosedError on a dead
            # driver (measured), but `cookies()` costs 2.1ms against `title()`'s 17.3ms and
            # this runs on every browser tool call. It also asks nothing of the main frame,
            # which is one less thing that can be busy while eleven other lanes share this
            # manager — though to be exact, a pending navigation did NOT block `title()` when
            # tested, so the reason to prefer it is the cost, not a reproduced hang.
            await asyncio.wait_for(self.state.context.cookies(), timeout=10)
            return True
        except Exception:
            return False

    async def _discard_dead_driver_1198(self) -> None:
        """Drop every handle to a driver that is gone. Best-effort; never raises. (#1198)"""
        for handle in (self.state.page, self.state.context, self.state.browser):
            try:
                if handle is not None:
                    await handle.close()
            except Exception:
                pass
        try:
            if self._playwright is not None:
                await self._playwright.stop()
        except Exception:
            pass
        self._playwright = None
        self.state = BrowserState()

    async def ensure_browser(self) -> bool:
        """Ensure browser is started"""
        if not PLAYWRIGHT_AVAILABLE:
            return False

        # #1198: a dead driver is not a started browser. Rebuild it, bounded, so a crash
        # costs one retry instead of every remaining UI gate in the run.
        if self.state.browser is not None and not await self._driver_is_live_1198():
            # #1203hn: a death more than _RELAUNCH_RESET_AFTER_SEC_1203HN after the last
            # rebuild is a fresh incident, not the next beat of a crash loop.
            _now1203hn = _time1203hn.monotonic()
            _last1203hn = getattr(self, "_last_relaunch_at_1203hn", None)
            if _last1203hn is not None and (
                    _now1203hn - _last1203hn) > _RELAUNCH_RESET_AFTER_SEC_1203HN:
                self._relaunch_count_1198 = 0
            self._last_relaunch_at_1203hn = _now1203hn
            self._relaunch_count_1198 = getattr(self, "_relaunch_count_1198", 0) + 1
            if self._relaunch_count_1198 > _MAX_RELAUNCH_1198:
                self._logger.error(
                    "#1198 shared browser driver died again (%d times); not relaunching. "
                    "Every browser gate from here on will fail — this is a crash loop, not "
                    "a flake.", self._relaunch_count_1198)
                return False
            self._logger.warning(
                "#1198 shared browser driver is gone (relaunch %d/%d) — rebuilding. Before "
                "this, one death blinded every UI gate for the rest of the run (r26: 214 "
                "identical navigation failures).",
                self._relaunch_count_1198, _MAX_RELAUNCH_1198)
            await self._discard_dead_driver_1198()

        if self.state.browser is None:
            try:
                # #1203m2: the shared driver is the long-lived one, so it is the one that
                # fills its 4288 MB default heap and takes the browser down with it.
                from ._bootstrap import driver_heap_1203m2
                with driver_heap_1203m2():
                    self._playwright = await async_playwright().start()
                try:
                    self.state.browser = await self._playwright.chromium.launch(
                        headless=True,
                        args=['--no-sandbox', '--disable-setuid-sandbox']
                    )
                except Exception as _launch_exc:
                    # #234: a MISSING browser binary never self-clears (r25: 102
                    # silent failures, runtime gates blind all run) — heal once
                    # in-process and retry; any other failure re-raises as before.
                    from ._bootstrap import heal_missing_browser
                    if not heal_missing_browser(_launch_exc):
                        raise
                    self.state.browser = await self._playwright.chromium.launch(
                        headless=True,
                        args=['--no-sandbox', '--disable-setuid-sandbox']
                    )
                from ._bootstrap import CANONICAL_VIEWPORT_646  # #646: one viewport
                self.state.context = await self.state.browser.new_context(
                    viewport=dict(CANONICAL_VIEWPORT_646)
                )
                self.state.page = await self.state.context.new_page()
                
                # Setup console and network listeners
                self.state.page.on("console", self._on_console)
                self.state.page.on("response", self._on_response)
                self.state.page.on("requestfailed", self._on_request_failed)
                self.state.page.on("pageerror", self._on_page_error)
                
                return True
            except Exception as e:
                # #1203ib: MEASURED, SEEN, DELIBERATELY NOT CLASSIFIED (2026-10-12).
                #
                # A launch failure here can be the HOST's rather than the app's -- the two
                # causes in the corpus are `ENOSPC: no space left on device` (25, tiktok-r183)
                # and `Executable doesn't exist at ~/.cache/ms-playwright` (179, r24+r25).
                # Neither says anything about the product, and the framework already owns the
                # principle: #1202de's `_boot_failure_result_1202de` routes a host-caused boot
                # failure to `capture_unavailable` ("A host fault is not a verdict about the
                # app"), and `"no space left on device"` is already a token in
                # `_COMPOSE_FATAL_1202DC`. That classifier has three callers and ALL THREE are
                # on the compose/docker_up path; this path has none, so an unlaunchable browser
                # does reach the gate as a page verdict. r183 04:43-04:45 is the whole chain on
                # record: ENOSPC -> `browser_navigate FAILED` -> `validation_ui_evidence_failed
                # on 3 record(s)` -> `GATE-CHECK remediation dispatched to verifier`.
                #
                # It is NOT wired up, because the premise for a behaviour change does not hold:
                #   * r183's three failing ui_evidence records were all PASSING again once the
                #     disk was reclaimed (38 ui-ish checks, 0 failing at the end), so the cost
                #     was wasted lane work during a host outage, not a wrong verdict shipped.
                #   * that outage was an operator accident (the root filesystem was filled from
                #     outside this run), i.e. a denominator of one.
                #   * r24/r25 are 2026-07 runs on a different framework generation; their 553
                #     launch failures cannot support a decision about today's gate.
                # Routing a host fault into `capture_unavailable` ALSO refunds the attempt, so
                # getting the predicate wrong here buys an app a free pass at the gate -- the
                # expensive direction. Classifying on this evidence would be writing a rule for
                # a world the corpus does not show.
                #
                # WHAT WOULD CHANGE IT: one run where a host-caused browser failure reaches a
                # FINAL gate verdict (a failing ui_evidence/ui_flow record still failing at the
                # last gate snapshot) without the host fault being named. Then classify here and
                # give the browser path its own token set -- do NOT widen
                # `_COMPOSE_FATAL_1202DC`, which would silently change the compose path too.
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
                # #1202uq: `response.request.method` was read UNGUARDED inside an event
                # handler. A request object that has gone away raises here, which loses the
                # whole record AND throws inside Playwright's dispatch -- found by asserting
                # the handler never raises, not by reading it.
                "method": _request_method_1202uq(response),
                "type": "http_error",
                # #1202uq: DID THIS REQUEST CARRY CREDENTIALS? The record held url, status and
                # method, so a 401 said nothing about WHY. r135's verifier wrote "unexpected
                # anonymous GET /auth/me 401" onto ELEVEN of its fifteen delivery-blocking UI
                # flows -- and "anonymous" was an INFERENCE it had no way to check. The
                # generated client only calls /auth/me when a decodable, unexpired JWT is in
                # localStorage, and it attaches `Authorization` whenever a token exists, so a
                # genuinely anonymous page cannot issue that request at all. The likelier
                # story is a token left by an earlier flow in the SAME browser context (the
                # verifier's context is created once per run and never reset; test_user_runner
                # and visual_fidelity each open their own).
                #
                # The agent already has the means to act -- `browser_eval` is called 13,673
                # times across the corpus and can clear storage -- but `localStorage.clear`
                # appears ZERO times, because nothing ever told it there was state to clear.
                # This is the missing fact, not a missing capability.
                #
                # Cookie-borne sessions are NOT covered: the browser adds `Cookie` after this
                # header view is taken, and calling a cookie an auth credential would be a
                # guess. Generated clients use bearer tokens (`Authorization: Bearer`), which
                # is what this sees.
                "authorization_sent": _authorization_sent_1202uq(response),
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
        """Capture page errors — the MESSAGE, not just where it happened. (#1202br)

        `str(error)` on a Playwright pageerror yields only a minified location. netflix-r33
        recorded exactly that as the evidence for its two blocking UI flows:

            Error at http://localhost:8053/assets/index--TCHSJCV.js:49:360
            page-level Error

        A lane handed that cannot act: the file is a production bundle, and 49:360 names
        no source it can open. Both flows — account_menu_sign_out and
        verify_profile_isolation — were "blocked by frontend runtime JavaScript Error on
        page navigation", and `validation_ui_evidence_failed` is the corpus's single most
        common delivery blocker (46 times across 40 run logs).

        Playwright's Error carries `.message`, `.name` and `.stack`; the message is the one
        a lane can search its own source for. Each is read defensively: a handler that
        raises here would lose the error entirely, which is worse than a vague one.
        """
        # #1203iu: the reading moved to `page_error_fields_1202br` above, unchanged, so the
        # auth-flow probe can use the same one. The record this appends is byte-identical.
        _f = page_error_fields_1202br(error)
        self.state.console_logs.append({
            "type": "error",
            "text": _f["text"],
            "message": _f["message"],
            "error_name": _f["error_name"],
            "stack": _f["stack"],
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

