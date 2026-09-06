"""Browser control-exercise audit tool (design §3.2).

Exposes the enumerate→click→assert-effect pass as a BrowserManager-based agent tool the
browser test-user can call. It drives the SHARED browser page (it does NOT open its own
Playwright) and reuses the pure logic + async driver in
``multi_agent.runtime.control_exercise``: it enumerates every interactive control on a page,
clicks each from a freshly-reset state, captures the observed effect (navigation, the /api
calls fired + statuses, DOM change, console errors), cross-checks the fired calls against the
declared contract, and returns a per-control verdict (dead / error / off-contract / sound).
"""
from typing import Any, Dict, Optional

from utils.tool import BaseTool, ToolResult, ToolCategory
from ._manager import BrowserManager, PLAYWRIGHT_AVAILABLE


class BrowserExerciseControlsTool(BaseTool):
    NAME = "browser_exercise_controls"

    def __init__(self, browser_manager: BrowserManager, **kwargs):
        super().__init__(name=self.NAME, category=ToolCategory.RUNTIME, **kwargs)
        self.browser = browser_manager

    @property
    def tool_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.NAME,
                "description": (
                    "Exercise EVERY interactive control on a page: click each from a fresh "
                    "state and report the observed effect (navigation / API call + status / "
                    "DOM change / console error), flagging DEAD controls (a write-looking "
                    "button that does nothing), ERROR controls (5xx on click), and OFF-CONTRACT "
                    "calls (an API call matching no declared endpoint). Drives the shared "
                    "browser; call browser_navigate first or pass the full url. Pass the "
                    "declared api_endpoints so off-contract calls can be detected."),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string",
                                "description": "Full URL of the page to exercise, e.g. http://localhost:8080/inbox"},
                        "api_endpoints": {
                            "type": "array", "items": {"type": "string"},
                            "description": "Declared endpoints as 'METHOD /path' (from registryhub_list_endpoints) "
                                           "so a control's API call can be checked against the contract. Optional."},
                        "max_controls": {"type": "integer",
                                         "description": "Max controls to exercise (default 25)."},
                    },
                    "required": ["url"],
                },
            },
        }

    async def execute(self, url: str, api_endpoints: Optional[list] = None,
                      max_controls: int = 25, **kwargs) -> ToolResult:
        if not PLAYWRIGHT_AVAILABLE:
            return ToolResult.fail(
                "Playwright not installed. Run: pip install playwright && playwright install chromium")
        if not await self.browser.ensure_browser():
            return ToolResult.fail("Failed to start browser")
        page = getattr(self.browser.state, "page", None)
        if page is None:
            return ToolResult.fail("No page open. Use browser_navigate first.")
        # Lazy import (tools is imported BY multi_agent — avoid an import cycle at load time).
        try:
            from multi_agent.runtime.control_exercise import (
                exercise_controls, build_contract_index, evaluate_control,
                aggregate_control_report, path_from_url)
        except Exception as exc:  # pragma: no cover
            return ToolResult.fail(f"control_exercise unavailable: {exc}")

        eps = []
        for e in (api_endpoints or []):
            if isinstance(e, str) and " " in e.strip():
                m, p = e.strip().split(None, 1)
                eps.append({"method": m, "path": p})
            elif isinstance(e, dict) and e.get("path"):
                eps.append(e)
        contract_index = build_contract_index(eps)

        try:
            records = await exercise_controls(
                page, url, contract_index, max_controls=int(max_controls or 25))
        except Exception as exc:
            return ToolResult.fail(f"control exercise failed: {exc}")

        evals = []
        for r in records:
            v = evaluate_control(r)
            v["label"] = r.get("label")
            evals.append(v)
        report = aggregate_control_report(path_from_url(url) or url, path_from_url(url), evals)
        # Surface the raw per-control records too so the agent can judge sound-but-ambiguous ones.
        #
        # #1202ei: `console_errors` belongs in that list. `evaluate_control` can classify a
        # control's effect as "console_error" -- the agent is told clicking it broke
        # something and not WHAT, though `exercise_controls` captured the message and
        # carries it on the same record this projection is built from. The text was
        # dropped HERE, at the boundary, so it reached nothing: inside control_exercise it
        # is read once, as a boolean, to pick that very effect label.
        #
        # Reporting the category and withholding the instance is the shape of #973, #978,
        # #1202df, #1202ea and #1202ee. Bounded like every other list in this report.
        report["records"] = [
            {"label": r.get("label"), "effect": ev["effect"], "navigated_to": r.get("navigated_to"),
             "network": r.get("network"), "off_contract": r.get("off_contract"),
             "dom_changed": r.get("dom_changed"),
             "console_errors": r.get("console_errors") or []}
            for r, ev in zip(records, evals)]
        return ToolResult.ok(report)
