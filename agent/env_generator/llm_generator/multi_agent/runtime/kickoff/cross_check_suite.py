"""Cross-check suite — pure-Python contract/slice consistency checker.

Charter §4 names contract-first as the single biggest bug-reducer for
generated code, and charter §8 lists "contract drift / field-name
mismatch across agents" as the dominant generated-code bug class. This
module is the cross-cutting predicate that exists to catch that class
of drift at kickoff time, BEFORE any implementation task is dispatched.

Four checks are wired in (plan §Step-2):

1. ``api_vs_frontend`` — every endpoint in the API contract is
   referenced by at least one frontend screen, and no UI call targets
   an undefined endpoint. (Catches frontend calling an endpoint backend
   didn't build, or backend shipping dead endpoints.)
2. ``api_vs_data_model`` — every endpoint's response shape references
   only declared tables. (Catches field/table-name drift between
   backend and data layer.)
3. ``test_strategy_coverage`` — verifier ships at least one predicate
   per *critical* flow. (Catches acceptance-gate gaps — the discipline
   from charter §4.)

Round 8e.1 dropped the legacy ``ui_pages_vs_user_flows`` check (was
between design's ui_pages and design's user_flows). After the
design→frontend merge both fields live in frontend's kickoff section,
so cross-section consistency is implicit; intra-section coherence is
the LLM's job, not the suite's.

Each check is a pure function that takes already-loaded data (NEVER a
hub handle) and returns one of ``'pass' | 'fail' | 'evidence_pending'``
PLUS a ``CheckResult`` payload (severity + offending_field) so the
dispatcher can render an actionable blocker string. Per the story_hub
convention, individual check functions MUST NOT raise — the
``run_cross_checks`` dispatcher coerces any unexpected exception to
``status='evidence_pending'``.

Contract for input shapes (documented here because there is no hub
schema yet — kickoff is greenfield):

- ``api_endpoints`` — ``Iterable[Mapping]`` with keys
  ``{method: str, path: str, response: Mapping | None}``. The
  ``response`` mapping carries a top-level ``tables`` list naming the
  data-model tables the response touches (e.g.
  ``{"tables": ["posts", "users"]}``). Absent ``tables`` = no
  table dependency.
- ``frontend_screens`` — ``Iterable[Mapping]`` with keys
  ``{id: str, api_calls: List[{method: str, path: str}]}``. ``id``
  doubles as the screen's UI page identifier for check (3).
- ``data_model`` — ``Mapping`` with ``{"tables": List[{name: str, ...}]}``.
- ``ui_pages`` — ``Iterable[Mapping]`` with ``{id: str}``.
- ``user_flows`` — ``Iterable[Mapping]`` with
  ``{id: str, critical: bool, pages: List[str], predicates: List[str]}``.
  ``pages`` lists page-ids referenced by the flow; ``predicates`` is
  the list of predicate-ids tied to this flow (used by check 4).
- ``predicates`` — ``Iterable[Mapping]`` with
  ``{id: str, flow: str}``. ``flow`` names the user_flow this
  predicate covers.

This contract is the FIRST formalization of these kickoff payload
shapes; downstream modules (orchestrator synthesis, kickoff agent
prompts) MUST match it. Update the docstring here first if the shape
shifts.
"""
from __future__ import annotations

import inspect
import re
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Literal,
    Mapping,
    Optional,
    Tuple,
)

# Status vocabulary mirrors story_hub.evaluate_story_gate so the
# dispatcher's aggregate semantics line up across the two gates.
CheckStatus = Literal["pass", "fail", "evidence_pending"]


# ---------------------------------------------------------------------------
# CheckResult — uniform per-check payload
# ---------------------------------------------------------------------------

def _result(
    status: CheckStatus,
    *,
    severity: str,
    offending_field: Optional[str] = None,
    detail: str = "",
) -> Dict[str, Any]:
    """Build a CheckResult dict.

    ``severity`` is one of ``'info' | 'warning' | 'error'`` — used by
    the dispatcher to gate ``ok`` (only ``'error'`` flips ``ok=False``).
    ``offending_field`` names the input element that triggered the
    fail (e.g. ``"api_endpoints[2].path"`` or ``"flow:checkout"``);
    ``None`` means the result is summary-only.
    """
    return {
        "status": status,
        "severity": severity,
        "offending_field": offending_field,
        "detail": detail,
    }


# ---------------------------------------------------------------------------
# Check 1 — api_vs_frontend
# ---------------------------------------------------------------------------

# Round 8h refactor: endpoint/api_call canonicalization lives in
# runtime.kickoff.schema_tolerance — see that module for the full
# rationale per helper. The aliases below preserve the private
# names this module's call sites have always used.
from .schema_tolerance import (  # noqa: E402
    api_call_key as _api_call_key,
    endpoint_key as _endpoint_key,
    is_critical_flow as _is_critical_flow,
)


# Endpoint kinds that are the runtime-owned FIXED surface (registered before the
# meeting by orchestrator._register_contract_surface). They are valid reference
# targets for a UI call, but are NOT business endpoints, so the "every endpoint
# needs a UI consumer" rule does not apply to them. This is read from the
# REGISTERED `kind` attribute (set at construction) — never a hardcoded path list.
_FIXED_KINDS = frozenset({"auth", "oauth", "infra", "spine"})


def _param_agnostic(method_path: str) -> str:
    """Normalize ``"METHOD /path"`` so a path param's NAME and form
    ({note_id} / :noteId / ${id}) don't matter for matching — every param
    segment becomes ``:p``. ``GET /api/notes/:noteId`` and
    ``GET /api/notes/{note_id}`` are the SAME endpoint at runtime (the param
    notation is not contract drift), so the cross-check must treat them as equal.
    Mirrors ``delivery.contract_extract.param_agnostic``."""
    parts = method_path.split(" ", 1)
    if len(parts) != 2:
        return method_path
    method, path = parts[0].upper().strip(), parts[1].strip()
    path = re.sub(r"\$\{[^}/]+\}", ":p", path)    # ${id}  -> :p
    path = re.sub(r"\{[^}/]+\}", ":p", path)       # {id}   -> :p
    path = re.sub(r":[A-Za-z_]\w*", ":p", path)    # :noteId -> :p
    if len(path) > 1:
        path = path.rstrip("/")
    return f"{method} {path}"


def _registered_kind(rec: Mapping[str, Any]) -> str:
    """The endpoint's `kind`, wherever it landed (top-level or under metadata)."""
    if not isinstance(rec, Mapping):
        return ""
    if rec.get("kind"):
        return str(rec["kind"]).lower()
    md = rec.get("metadata")
    if isinstance(md, Mapping) and md.get("kind"):
        return str(md["kind"]).lower()
    return ""


def api_vs_frontend(
    api_endpoints: Iterable[Mapping[str, Any]],
    frontend_screens: Iterable[Mapping[str, Any]],
    registered_endpoints: Optional[Iterable[Mapping[str, Any]]] = None,
    *,
    dead_endpoint_severity: str = "info",
) -> Dict[str, Any]:
    """Verify every API endpoint has a UI consumer and vice versa.

    Returns a CheckResult. Fails (severity='error') on EITHER:
      * an endpoint declared in ``api_endpoints`` that no screen calls
        (dead endpoint), OR
      * a screen ``api_calls`` entry that does not match any endpoint
        (frontend calling something backend didn't build — the dominant
        contract-drift bug per charter §8).

    Empty inputs on both sides → ``'pass'`` (vacuously consistent;
    nothing to misalign). Empty endpoints + nonempty screen api_calls
    → ``'fail'`` (UI calls into the void).
    """
    # ALL comparisons are param-agnostic (see _param_agnostic): {note_id} ≡
    # :noteId ≡ ${id}. The fixed surface (registered BEFORE the meeting) is keyed
    # by its normalized form -> kind, used to (a) resolve a UI call that targets
    # e.g. /auth/login and (b) exempt it from the "needs a UI consumer" rule BY KIND.
    reg_kind: Dict[str, str] = {}
    for rec in (registered_endpoints or []):
        if isinstance(rec, Mapping) and rec.get("method") and rec.get("path"):
            nk = _param_agnostic(_endpoint_key(rec.get("method"), rec.get("path")))
            reg_kind[nk] = _registered_kind(rec)

    endpoints_seen: Dict[str, str] = {}   # normalized key -> display key (for errors)
    seen_idx: Dict[str, int] = {}
    for i, ep in enumerate(api_endpoints or []):
        if not isinstance(ep, Mapping):
            return _result(
                "fail",
                severity="error",
                offending_field=f"api_endpoints[{i}]",
                detail="endpoint entry is not a mapping",
            )
        disp = _endpoint_key(ep.get("method"), ep.get("path"))
        nk = _param_agnostic(disp)
        endpoints_seen[nk] = disp
        seen_idx[nk] = i

    # A UI call resolves against the meeting endpoints OR the registered contract.
    known = set(endpoints_seen) | set(reg_kind)

    referenced: set = set()
    for j, screen in enumerate(frontend_screens or []):
        if not isinstance(screen, Mapping):
            return _result(
                "fail",
                severity="error",
                offending_field=f"frontend_screens[{j}]",
                detail="screen entry is not a mapping",
            )
        for k, call in enumerate(screen.get("api_calls") or []):
            if not isinstance(call, Mapping):
                continue
            disp = _api_call_key(call)
            nk = _param_agnostic(disp)
            if nk not in known:
                return _result(
                    "fail",
                    severity="error",
                    offending_field=f"frontend_screens[{j}].api_calls[{k}]",
                    detail=f"UI call to undefined endpoint: {disp}",
                )
            referenced.add(nk)

    # The dead-endpoint direction (a backend endpoint NO screen calls) is a
    # contract-TIGHTNESS rule, not a runtime-fatal one: an unused-by-UI endpoint
    # still works at runtime. The last-resort kickoff reconcile passes
    # ``dead_endpoint_severity="ignore"`` so it can finalize a slightly-loose-
    # but-shippable contract instead of aborting the whole run (0 files) — e.g.
    # an Instagram backend that declares DELETE /api/posts/{id} which no screen
    # wires up. The undefined-endpoint direction above stays fatal (a UI call to
    # a missing endpoint 404s); reconcile fixes THAT by pruning the call.
    # DEFAULT DOWNGRADED error→info (2026-06-10): reference-driven contracts
    # legitimately include endpoints with NO UI consumer — the MCP tool surface
    # (insights/business_discovery/...) is served by the MCP server, not a
    # screen. An unconsumed endpoint is never runtime-fatal; implementation is
    # enforced by api_smoke per-endpoint probes + the spec/predicate gates. The
    # UI-call-to-missing-endpoint direction above remains fatal.
    if dead_endpoint_severity == "error":
        for nk, disp in endpoints_seen.items():
            if nk in referenced:
                continue
            # Exempt the fixed surface BY ITS REGISTERED KIND (never by path): a
            # lane that declared e.g. GET /health in its section isn't a dead
            # business endpoint — it's runtime-owned surface, registered kind=infra.
            if reg_kind.get(nk) in _FIXED_KINDS:
                continue
            return _result(
                "fail",
                severity="error",
                offending_field=f"api_endpoints[{seen_idx[nk]}]",
                detail=f"endpoint has no UI consumer: {disp}",
            )

    return _result("pass", severity="info", detail="api↔frontend aligned")


# ---------------------------------------------------------------------------
# Check 2 — api_vs_data_model
# ---------------------------------------------------------------------------

def api_vs_data_model(
    api_endpoints: Iterable[Mapping[str, Any]],
    data_model: Mapping[str, Any],
) -> Dict[str, Any]:
    """Verify every endpoint response references only declared tables.

    Returns a CheckResult. Fails on any endpoint whose
    ``response['tables']`` mentions a table name not in
    ``data_model['tables'][*]['name']``. Endpoints with no
    ``response.tables`` are skipped (vacuously aligned — no table dep).
    """
    if not isinstance(data_model, Mapping):
        return _result(
            "fail",
            severity="error",
            offending_field="data_model",
            detail="data_model is not a mapping",
        )
    declared: set = set()
    for t in data_model.get("tables") or []:
        if isinstance(t, Mapping) and t.get("name"):
            declared.add(str(t["name"]).strip())

    for i, ep in enumerate(api_endpoints or []):
        if not isinstance(ep, Mapping):
            return _result(
                "fail",
                severity="error",
                offending_field=f"api_endpoints[{i}]",
                detail="endpoint entry is not a mapping",
            )
        response = ep.get("response")
        if not isinstance(response, Mapping):
            continue
        for tbl in response.get("tables") or []:
            tname = str(tbl).strip()
            if tname not in declared:
                return _result(
                    "fail",
                    severity="error",
                    offending_field=(
                        f"api_endpoints[{i}].response.tables"
                    ),
                    detail=(
                        f"endpoint references undeclared table "
                        f"'{tname}' (endpoint="
                        f"{_endpoint_key(ep.get('method'), ep.get('path'))})"
                    ),
                )
    return _result("pass", severity="info", detail="api↔data_model aligned")


# ---------------------------------------------------------------------------
# Check 3 — test_strategy_coverage
# (Round 8e.1 dropped the legacy "ui_pages_vs_user_flows" check —
#  both fields now live in frontend's section, intra-section.)
# ---------------------------------------------------------------------------

def test_strategy_coverage(
    predicates: Iterable[Mapping[str, Any]],
    user_flows: Iterable[Mapping[str, Any]],
    missing_predicate_severity: str = "error",
) -> Dict[str, Any]:
    # Defuse pytest's name-based collection: this is a check function,
    # not a test function. Without this marker pytest auto-collects it
    # and chokes on the (predicates, user_flows) positional signature
    # treating them as fixtures.
    """Verify the verifier ships ≥1 predicate per CRITICAL flow.

    Charter §4: acceptance predicates are the milestone gate, written
    DURING kickoff before any build. A critical flow with zero
    predicates is the precise failure mode this check exists to catch.

    Non-critical flows are skipped. If no flows are marked critical,
    the check passes vacuously (M0 / discovery slices may have no
    critical path yet).
    """
    by_flow: Dict[str, int] = {}
    for k, pred in enumerate(predicates or []):
        if not isinstance(pred, Mapping):
            return _result(
                "fail",
                severity="error",
                offending_field=f"predicates[{k}]",
                detail="predicate entry is not a mapping",
            )
        flow_id = str(pred.get("flow", "")).strip()
        if flow_id:
            by_flow[flow_id] = by_flow.get(flow_id, 0) + 1

    for j, flow in enumerate(user_flows or []):
        if not isinstance(flow, Mapping):
            return _result(
                "fail",
                severity="error",
                offending_field=f"user_flows[{j}]",
                detail="flow entry is not a mapping",
            )
        if not _is_critical_flow(flow):
            continue
        fid = str(flow.get("id", "")).strip()
        if not fid:
            return _result(
                "fail",
                severity="error",
                offending_field=f"user_flows[{j}].id",
                detail="critical flow is missing an id",
            )
        if by_flow.get(fid, 0) < 1:
            # Reconcile mode downgrades a missing predicate to non-blocking: it is
            # not runtime-fatal (gate C validates each flow's endpoints behaviorally
            # at delivery), so a flow without an authored predicate must not abort the
            # whole run (instagram M2 died on exactly this: residual user_flows[0]).
            if missing_predicate_severity == "ignore":
                continue
            return _result(
                "fail",
                severity="error",
                offending_field=f"user_flows[{j}].id",
                detail=(
                    f"critical flow '{fid}' has no acceptance predicate "
                    "(charter §4: predicates must be authored at kickoff)"
                ),
            )
    return _result(
        "pass",
        severity="info",
        detail="every critical flow has ≥1 predicate",
    )


# Defuse pytest's name-based collection: pytest treats any top-level
# callable whose name starts with ``test_`` as a test function. This
# is a CHECK function, not a test — without ``__test__ = False`` pytest
# tries to collect it and fails on the (predicates, user_flows)
# positional signature (it tries to resolve them as fixtures).
test_strategy_coverage.__test__ = False  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

# Registry keyed by check id. Each entry is
#   (extractor, check_fn)
# where extractor pulls the (positional) args out of the ``drafts``
# mapping that the orchestrator hands the dispatcher. Tests inject a
# replacement registry via the ``checks=`` kwarg.
_CheckEntry = Tuple[
    Callable[[Mapping[str, Mapping[str, Any]]], Tuple[Any, ...]],
    Callable[..., Dict[str, Any]],
]


# Round 8h refactor: extractors moved to schema_tolerance — see that
# module for the smoke #9-octavus rationale + Fix #J narrative.
from .schema_tolerance import (  # noqa: E402
    extract_backend_endpoints as _extract_backend_endpoints,
    extract_frontend_screens as _extract_frontend_screens,
)


def _extract_api_vs_frontend(
    drafts: Mapping[str, Mapping[str, Any]],
    registered_endpoints: Optional[Iterable[Mapping[str, Any]]] = None,
) -> Tuple[Any, ...]:
    api = _extract_backend_endpoints(drafts.get("backend") or {})
    fe = _extract_frontend_screens(drafts.get("frontend") or {})
    # Thread the registered fixed surface so the check resolves /auth/login etc.
    # against the registered contract + exempts it by `kind` (§4 D4.2).
    return api, fe, registered_endpoints


def _extract_api_vs_data_model(
    drafts: Mapping[str, Mapping[str, Any]],
    registered_endpoints: Optional[Iterable[Mapping[str, Any]]] = None,
) -> Tuple[Any, ...]:
    api = _extract_backend_endpoints(drafts.get("backend") or {})
    dm = (drafts.get("backend") or {}).get("data_model") or {}
    return api, dm


def _extract_test_strategy_coverage(
    drafts: Mapping[str, Mapping[str, Any]],
    registered_endpoints: Optional[Iterable[Mapping[str, Any]]] = None,
) -> Tuple[Any, ...]:
    preds = (drafts.get("verifier") or {}).get("predicates") or []
    # Round 8e.1: user_flows owned by frontend (was design's).
    flows = (drafts.get("frontend") or {}).get("user_flows") or []
    return preds, flows


_DEFAULT_CHECKS: Dict[str, _CheckEntry] = {
    "api_vs_frontend": (_extract_api_vs_frontend, api_vs_frontend),
    "api_vs_data_model": (_extract_api_vs_data_model, api_vs_data_model),
    # Round 8e.1: ui_pages_vs_user_flows dropped — both fields live
    # in frontend's section, intra-section consistency is the LLM's
    # job not a cross-check.
    "test_strategy_coverage": (
        _extract_test_strategy_coverage,
        test_strategy_coverage,
    ),
}


def reconcile_check_registry() -> Dict[str, "_CheckEntry"]:
    """Lenient cross-check registry for the LAST-RESORT kickoff reconcile.

    Same as ``_DEFAULT_CHECKS`` but two tightness directions are downgraded to
    non-blocking: the ``api_vs_frontend`` dead-endpoint direction
    (``dead_endpoint_severity="ignore"``) and ``test_strategy_coverage``'s
    missing-predicate direction (``missing_predicate_severity="ignore"`` — a
    critical flow without an authored predicate is validated behaviorally by gate C
    at delivery, so it must not abort the run; instagram M2 died on exactly this,
    residual ``user_flows[0]``). The runtime-fatal checks stay enforced: the
    undefined-endpoint direction of ``api_vs_frontend`` (now auto-registered, not a
    404) and ``api_vs_data_model`` (an endpoint referencing a missing table). Used
    only when the orchestrator is about to abort a kickoff — shipping a
    slightly-loose contract beats 0 files.
    """
    import functools

    lenient = functools.partial(api_vs_frontend, dead_endpoint_severity="ignore")
    lenient_strategy = functools.partial(
        test_strategy_coverage, missing_predicate_severity="ignore")
    reg = dict(_DEFAULT_CHECKS)
    reg["api_vs_frontend"] = (_extract_api_vs_frontend, lenient)
    reg["test_strategy_coverage"] = (_extract_test_strategy_coverage, lenient_strategy)
    return reg


def run_cross_checks(
    drafts: Mapping[str, Mapping[str, Any]],
    checks: Optional[Dict[str, _CheckEntry]] = None,
    registered_endpoints: Optional[Iterable[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Run every registered cross-check predicate against agent drafts.

    ``drafts`` is the per-agent payload mapping (``agent_id -> draft``)
    collected by the kickoff broadcast. ``checks`` defaults to
    ``_DEFAULT_CHECKS``; tests inject stubs via this kwarg.

    Each check function MUST NOT raise. The dispatcher catches any
    unexpected exception and coerces it to a
    ``status='evidence_pending'`` blocker, mirroring
    ``story_hub.evaluate_story_gate`` discipline.

    Returns the story_hub-style aggregate::

        {
          "ok": bool,
          "items": [
            {"id": <check_id>, "status": ..., "blockers": [...],
             "severity": ..., "offending_field": ...},
            ...
          ],
        }

    ``ok`` is ``True`` iff every check returned ``status='pass'``.
    """
    if not isinstance(drafts, Mapping):
        raise ValueError(
            "run_cross_checks requires drafts to be a Mapping "
            "(agent_id -> draft payload); got "
            f"{type(drafts).__name__}"
        )
    registry = checks if checks is not None else _DEFAULT_CHECKS
    items: List[Dict[str, Any]] = []
    aggregate_ok = True
    for check_id, entry in registry.items():
        extractor, fn = entry
        blockers: List[str] = []
        try:
            # Arity-aware: the default extractors accept (drafts,
            # registered_endpoints); custom/legacy extractors may accept only
            # (drafts). Don't break the 1-arg contract.
            try:
                _arity = len(inspect.signature(extractor).parameters)
            except (TypeError, ValueError):
                _arity = 1
            args = extractor(drafts, registered_endpoints) if _arity >= 2 else extractor(drafts)
            result = fn(*args)
        except Exception as exc:  # noqa: BLE001 — coerce per charter
            result = _result(
                "evidence_pending",
                severity="warning",
                offending_field=check_id,
                detail=f"check raised: {type(exc).__name__}: {exc}",
            )
        status = result.get("status", "evidence_pending")
        if status == "fail":
            blockers.append(
                f"failed:{check_id}:{result.get('detail', '')}"
            )
        elif status == "evidence_pending":
            blockers.append(
                f"evidence_pending:{check_id}:"
                f"{result.get('detail', '')}"
            )
        if status != "pass":
            aggregate_ok = False
        items.append({
            "id": check_id,
            "status": status,
            "blockers": blockers,
            "severity": result.get("severity"),
            "offending_field": result.get("offending_field"),
        })
    return {"ok": aggregate_ok, "items": items}


__all__ = [
    "CheckStatus",
    "api_vs_frontend",
    "api_vs_data_model",
    # Round 8e.1: ui_pages_vs_user_flows removed — merged into frontend.
    "test_strategy_coverage",
    "run_cross_checks",
]
