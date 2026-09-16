"""Deliverability LLM tools (Cutover 24)."""

from __future__ import annotations

from typing import Any, Optional

from utils.tool import BaseTool, ToolCategory, ToolResult, create_tool_param

from multi_agent.runtime.deliverability import compute_deliverability


class _DeliverabilityToolBase(BaseTool):
    def __init__(self, *, hub_registry=None, app_root: Optional[str] = None,
                 session_start_ts: float = 0.0):
        super().__init__(name=self.NAME, category=ToolCategory.KNOWLEDGE)
        self.hub_registry = hub_registry
        self.app_root = app_root
        self.session_start_ts = session_start_ts


def _framework_gate_verdict_1202pn(app_root, max_age_s: float = 1200.0) -> Optional[dict]:
    """#1202pn: the delivery gate's latest verdict, from `<run>/logs/delivery_gate.jsonl`.

    This report and the gate are computed separately, and the orchestrator read "deliverable"
    here while the gate kept refusing on `business_chain_failing` — so it treated the gate's own
    repair tasks as stale and cancelled them (r125 20/73, r126 10/30). None when there is no
    fresh ledger line: absence is not a verdict.
    """
    if not app_root:
        return None
    import json as _json
    import time as _time
    from pathlib import Path as _P
    _base = _P(str(app_root))
    ledger = next((d / "logs" / "delivery_gate.jsonl"
                   for d in [_base] + list(_base.parents)[:3]
                   if (d / "logs" / "delivery_gate.jsonl").is_file()), None)
    if ledger is None:
        return None
    try:
        with open(ledger, "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - 65536))
            lines = fh.read().decode("utf-8", "replace").strip().splitlines()
        last = _json.loads(lines[-1]) if lines else {}
    except Exception as exc:
        from multi_agent.runtime.message_format import warn_once_1201
        warn_once_1201("deliverability-gate-verdict-1202pn",
                       "#1202pn: reading the delivery gate ledger", exc)
        return None
    age = _time.time() - float(last.get("at") or 0)
    if not last or age > max_age_s:
        return None
    return {"ok": bool(last.get("ok")), "failed_checks": list(last.get("failed_checks") or []),
            "age_s": int(age)}


class DeliverabilityCheckTool(_DeliverabilityToolBase):
    NAME = "deliverability_check"
    DESCRIPTION = ("Evidence-based unified deliverability report: latest RunHub "
                    "run + endpoint/MCP probe counts + coverage + seed + visual "
                    "reviews. Replaces LLM-judged checklist. Verdict = "
                    "'deliverable' iff blockers list is empty.")

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={"type": "object", "properties": {}}, required=[])

    async def execute(self, **_kw) -> ToolResult:
        report = compute_deliverability(
            self.hub_registry, self.app_root, self.session_start_ts)
        data = report.to_dict()
        gate = _framework_gate_verdict_1202pn(self.app_root)
        if gate is not None:
            data["delivery_gate_latest"] = gate
            if not gate["ok"] and gate["failed_checks"]:
                data["delivery_gate_note"] = (
                    "The delivery gate evaluated %ds ago and still refuses delivery on: %s. "
                    "Tasks titled '(blocks delivery)' for these checks are live, not stale — "
                    "do not cancel them; deliver_project will be refused until they pass."
                    % (gate["age_s"], ", ".join(map(str, gate["failed_checks"][:6]))))
        return ToolResult.ok(data=data)


class DeliverabilitySummaryTool(_DeliverabilityToolBase):
    NAME = "deliverability_summary"
    DESCRIPTION = ("One-line summary of deliverability: verdict + blocker count "
                    "+ first blocker. Use this for quick checks; use "
                    "deliverability_check for the full report.")

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={"type": "object", "properties": {}}, required=[])

    async def execute(self, **_kw) -> ToolResult:
        report = compute_deliverability(
            self.hub_registry, self.app_root, self.session_start_ts)
        return ToolResult.ok(data={
            "verdict": report.verdict,
            "blocker_count": len(report.blockers),
            "first_blocker": report.blockers[0] if report.blockers else None,
            "run_within_session": report.run_within_session,
        })


_DELIVERABILITY_TOOLS = [DeliverabilityCheckTool, DeliverabilitySummaryTool]


def create_deliverability_tools(hub_registry=None,
                                 app_root: Optional[str] = None,
                                 session_start_ts: float = 0.0) -> list:
    return [cls(hub_registry=hub_registry, app_root=app_root,
                session_start_ts=session_start_ts)
            for cls in _DELIVERABILITY_TOOLS]


__all__ = [
    "DeliverabilityCheckTool", "DeliverabilitySummaryTool",
    "create_deliverability_tools",
]
