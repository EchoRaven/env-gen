"""Flow-coverage gate.

Closes the gap that ``validation:ui_smoke`` accepted ``browser_navigate +
browser_screenshot`` alone as "UI tested". For each critical flow the
verifier (or a spawned UI-flow tester worker) must drive
``browser_navigate`` + at least one mutating step (``browser_click`` /
``browser_fill`` / ``browser_press_key``) and then write a passing
``validation:ui_flow:<name>`` record via ``record_validation_result``
with ``metadata={"check": "ui_flow", "flow": "<name>"}``.

Two flow sources, in priority order:
  1. Explicit ``critical=True`` user_flows in the frontend section of
     the kickoff meeting decisions (WorkHub).
  2. Fallback: registered UI pages with ``critical=True``.

If neither source yields anything (small/scratch apps, or kickoffs
that didn't opt in), the gate stays silent — strictly-tighter,
never looser.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class FlowCoverageReport:
    required: List[str] = field(default_factory=list)
    passed: List[str] = field(default_factory=list)
    failed: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    source: str = "none"  # "critical_flows" | "critical_pages" | "none"

    @property
    def is_clean(self) -> bool:
        return not self.failed and not self.missing

    def to_dict(self) -> dict:
        return {
            "required": list(self.required),
            "passed": list(self.passed),
            "failed": list(self.failed),
            "missing": list(self.missing),
            "source": self.source,
            "is_clean": self.is_clean,
        }


def _derive_ui_spec_from_hub(hub_registry) -> Optional[dict]:
    """Build a {critical_flows, pages} dict from WorkHub state.

    Priority sources:
      1. Frontend's kickoff section ``user_flows[]`` with ``critical=True``.
      2. Frontend's kickoff section ``ui_pages[]`` (carries the
         ``critical`` flag for the page-derived fallback).
      3. WorkHub-registered UI pages from ``get_ui_pages()`` as a final
         fallback for runs that registered pages directly without a
         kickoff section.
    """
    if hub_registry is None:
        return None
    workhub = getattr(hub_registry, "workhub", None)
    if workhub is None:
        return None

    critical_flows: List[dict] = []
    pages: List[dict] = []

    try:
        kickoff_pages = workhub.list_pages(kind="kickoff") or []
    except Exception:
        kickoff_pages = []

    for kp in kickoff_pages:
        meta = kp.get("metadata") or {}
        decisions = meta.get("decisions") or []
        frontend_decisions = [
            d for d in decisions
            if isinstance(d, dict) and d.get("section") == "frontend"
        ]
        if not frontend_decisions:
            continue
        # Latest round wins (revision overrides initial draft).
        frontend_decisions.sort(key=lambda d: d.get("round", 0) or 0)
        content = (frontend_decisions[-1].get("content") or {})
        # Preserve raw critical-flow entries (with name OR malformed)
        # so ``_extract_required_flows`` can surface the
        # ``critical_flows_invalid`` source when every entry is
        # unparseable.
        for flow in (content.get("user_flows") or []):
            if isinstance(flow, dict) and flow.get("critical"):
                critical_flows.append(flow)
            elif isinstance(flow, str):
                critical_flows.append(flow)
        for page in (content.get("ui_pages") or []):
            if isinstance(page, dict):
                pages.append(page)

    if not pages:
        try:
            registered = workhub.get_ui_pages() or {}
        except Exception:
            registered = {}
        for name, page in registered.items():
            if isinstance(page, dict):
                pages.append({**page, "name": page.get("name") or name})

    return {"critical_flows": critical_flows, "pages": pages}


_TRUTHY_STRS = {"true", "yes", "1", "y", "t"}
_FALSY_STRS = {"false", "no", "0", "n", "f", "", "null", "none"}


def _is_truthy_critical(value: Any) -> bool:
    """Coerce a ``critical`` flag value to bool.

    Python's bare ``if value:`` makes any non-empty string truthy —
    so a designer (or LLM emitting loose JSON) writing
    ``"critical": "false"`` would silently flip the page INTO the
    critical set. Recognize the obvious stringly-typed forms; treat
    unknown strings as truthy (the safe direction is "more flows
    required" — a missing-flow blocker is easier to triage than a
    silently-skipped one).
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in _FALSY_STRS:
            return False
        if lowered in _TRUTHY_STRS:
            return True
        # Unknown string: bias toward "critical" so the gate doesn't
        # silently drop a page the designer probably meant to require.
        return bool(lowered)
    return bool(value)


def _extract_required_flows(spec: dict) -> Tuple[List[str], str]:
    """Return (flow_names, source_label).

    Priority: explicit ``critical_flows`` overrides ``critical: true``
    page derivation. Names are stripped, deduped, ordered.

    Sources: ``"critical_flows"`` | ``"critical_pages"`` |
    ``"critical_flows_invalid"`` (explicit list present but every
    entry was unparseable — see below) | ``"none"``.
    """
    if not isinstance(spec, dict):
        return [], "none"

    raw_flows = spec.get("critical_flows")
    explicit_flows_present = (
        isinstance(raw_flows, list) and len(raw_flows) > 0
    )
    if explicit_flows_present:
        names: List[str] = []
        seen = set()
        for entry in raw_flows:
            if isinstance(entry, dict):
                name = entry.get("name") or entry.get("id")
            elif isinstance(entry, str):
                name = entry
            else:
                name = None
            if not name:
                continue
            name = str(name).strip()
            if name and name not in seen:
                seen.add(name)
                names.append(name)
        if names:
            return names, "critical_flows"
        # Explicit list present but every entry was unparseable. Do
        # NOT silently fall through to page derivation — the designer
        # asked for explicit flows and got them all wrong. Surface
        # this so the gate can emit a blocker instead of masking it.
        return [], "critical_flows_invalid"

    raw_pages = spec.get("pages")
    page_entries: List[Tuple[Optional[str], dict]] = []  # (fallback_name, page_dict)
    if isinstance(raw_pages, list):
        for page in raw_pages:
            if isinstance(page, dict):
                page_entries.append((None, page))
    elif isinstance(raw_pages, dict):
        # dict form: {name: page_obj}; fall back to the dict key if
        # the page entry doesn't carry its own ``name``.
        for k, v in raw_pages.items():
            if isinstance(v, dict):
                page_entries.append((str(k), v))

    critical_names: List[str] = []
    seen = set()
    for fallback_name, page in page_entries:
        if not _is_truthy_critical(page.get("critical")):
            continue
        name = (
            page.get("name")
            or page.get("id")
            or fallback_name
            or page.get("path")
        )
        if not name:
            continue
        name = str(name).strip()
        if name and name not in seen:
            seen.add(name)
            critical_names.append(name)
    if critical_names:
        return critical_names, "critical_pages"

    return [], "none"


def _index_ui_flow_records(hub_registry) -> Dict[str, str]:
    """Return ``{flow_name: best_status}`` over validation:ui_flow records.

    ``best_status`` is ``"passed"`` if any record for that flow passed,
    else ``"failed"`` if any failed, else the latest status. We collapse
    duplicates by name so a later passing run can clear an earlier
    failure (matches how the auto-retry loop works for smoke checks).
    """
    try:
        results = hub_registry.get_validation_results(limit=1000) or []
    except Exception:
        results = []

    by_flow: Dict[str, str] = {}
    for r in results:
        if not isinstance(r, dict):
            continue
        meta = r.get("metadata") or {}
        if meta.get("check") != "ui_flow":
            continue
        flow = meta.get("flow")
        if not flow:
            continue
        flow = str(flow).strip()
        if not flow:
            continue
        status = r.get("status", "error")
        prev = by_flow.get(flow)
        if prev == "passed":
            continue
        if status == "passed":
            by_flow[flow] = "passed"
        elif status in {"failed", "error"} and prev != "failed":
            by_flow[flow] = "failed"
        elif prev is None:
            by_flow[flow] = status
    return by_flow


def compute_flow_coverage(hub_registry, workspace=None) -> FlowCoverageReport:
    """Compare required user-journey flows against ``validation:ui_flow``
    records. See module docstring for the contract.

    ``workspace`` is accepted for legacy callers but no longer read —
    WorkHub is the source of truth.

    Defense in depth: never raise — the gate must keep working even
    when the hub lookup hiccups. Worst case is an empty report which
    the delivery gate reads as "nothing to enforce".
    """
    spec = _derive_ui_spec_from_hub(hub_registry)
    if spec is None:
        return FlowCoverageReport(source="none")

    required, source = _extract_required_flows(spec)
    if not required:
        return FlowCoverageReport(source=source)

    by_flow = _index_ui_flow_records(hub_registry)
    passed: List[str] = []
    failed: List[str] = []
    missing: List[str] = []
    for name in required:
        status = by_flow.get(name)
        if status == "passed":
            passed.append(name)
        elif status in {"failed", "error"}:
            failed.append(name)
        else:
            missing.append(name)

    return FlowCoverageReport(
        required=required,
        passed=passed,
        failed=failed,
        missing=missing,
        source=source,
    )


__all__ = ["FlowCoverageReport", "compute_flow_coverage"]
