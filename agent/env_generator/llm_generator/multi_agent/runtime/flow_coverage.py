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
from typing import Any, Dict, List, Mapping, Optional, Tuple


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
      3. RegistryHub-registered UI pages from ``list_ui_pages()`` as a
         final fallback for runs that registered pages directly without a
         kickoff section.
    """
    if hub_registry is None:
        return None
    workhub = getattr(hub_registry, "workhub", None)
    if workhub is None:
        return None
    registryhub = getattr(hub_registry, "registryhub", None)

    critical_flows: List[dict] = []
    pages: List[dict] = []

    try:
        kickoff_pages = workhub.list_documents(kind="kickoff") or []
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
            registered = registryhub.list_ui_pages() or {} if registryhub is not None else {}
        except Exception:
            registered = {}
        for name, page in registered.items():
            if isinstance(page, dict):
                pages.append({**page, "name": page.get("name") or name})

    return {"critical_flows": critical_flows, "pages": pages}


def _is_navigable_page(page: Any) -> bool:
    """#243 — is this ui_page entry something a browser can actually NAVIGATE to?

    A registered ``ui_page`` whose ``route`` is EMPTY is a component that got
    mis-registered as a page (r33 M2: video_grid, explore_grid, explore_card,
    suggested_creator_card, top_action_bar, content_tabs, more_menu_panel — all
    ``route=''``). The deterministic walk only visits routed pages, so no
    ``validation:ui_flow`` record can ever exist for them and the coverage gate
    is unwinnable. Conservative: only reject when a route/path key is PRESENT
    and is not a ``/``-rooted path — an entry with NO route key at all is an
    older spec shape and stays required (we can't prove it is a component).

    ★ #905: that premise is FALSE for most of what this actually exempts. Blank routes are not
    rare and they are not mostly components — `register_ui_page(route: str = "")` defaults to
    empty, and **673 of the 2390 page records carry one** — 28%, in 78% of the 144 runs that
    registered any page at all. Split by where their file lives:

        exempted, path under /pages/       643     REAL pages whose route was never recorded
        exempted, path under /components/   26     #243's actual class
        ★ of those 643, records EXIST for  403     the walk visits App.jsx's real routes and
                                                   keys records by NAME, so "can NEVER exist"
                                                   is wrong for 63% of them
        ★ ...and are FAILING, but ignored   24     r116 alone hid 7: landing, login, profiles,
                                                   browse_home, shows, movies, title_detail

    So the exemption removed real, *validatable* pages from the required set and swallowed 24
    recorded failures. It is also load-bearing in the other direction now: `_extract_required_flows`
    falls back to "every declared ui_page is a flow", and this filter runs BEFORE that — in r153
    it cut the required set from 12 pages to 4.

    Keep #243's exemption for its real class and use the discriminator that is already in the
    record: a `path` under ``src/pages/`` is the framework's own page convention (the scaffolder
    writes there; `_project_page_component` tests ``"/pages/" in rel``). A component file is not a
    page; a page file with no route is a page whose route nobody wrote down.

    Safe in both directions: a newly-required flow with no record reads as MISSING, which
    `deliverability` already suppresses on a functionally-validated app (and #489/#240 author the
    records from a real browser walk pre-gate); a FAILED record always blocked and now actually
    reaches the gate."""
    if not isinstance(page, Mapping):
        return True
    _src = str(page.get("path") or "").replace("\\", "/")
    _is_page_file = "/pages/" in _src
    for key in ("route", "path"):
        if key in page:
            val = str(page.get(key) or "").strip()
            if val.startswith("/"):
                return True
            # no usable route on this entry — a real page file still has to be walked.
            # (``path`` is overloaded: a route in the kickoff spec shape, a SOURCE FILE in the
            # registry shape. `app/frontend/src/pages/X.jsx` never starts with '/', so before
            # #905 every registry record that reached this branch was exempted outright.)
            return _is_page_file
    return True


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
    # #243 (tiktok r33 M2, live): a ui_page with NO navigable route is a
    # COMPONENT mis-registered as a page (M2 registered video_grid /
    # explore_card / top_action_bar / … all with route=''). The browser walk
    # only visits routed pages, so a ui_flow record for a routeless entry can
    # NEVER be produced — requiring one is an UNWINNABLE gate (the opt-5
    # false-block class): r33 M2 sat on 8 permanently-missing flows. Drop them
    # from the REQUIRED set (they are still audited as components elsewhere).
    page_entries = [(fb, p) for fb, p in page_entries if _is_navigable_page(p)]

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

    # CONTRACT-DERIVED FALLBACK (user directive 2026-06-22 — flows come from the
    # registered CONTRACT, not authored user_flows): with no explicit critical_flows
    # and no critical:true pages, treat EVERY declared ui_page as a flow to validate.
    # Keeps the ui_flow gate non-empty after user_flows retirement (matches
    # test_user_squad's per-page coverage). ui_flow MISSING stays a warning on a
    # functionally-validated app, so this widens coverage without hard-blocking.
    all_names: List[str] = []
    seen_all = set()
    for fallback_name, page in page_entries:
        name = (page.get("name") or page.get("id")
                or fallback_name or page.get("path"))
        if not name:
            continue
        name = str(name).strip()
        # #237 (tiktok r26, live): the page set carries suffix TWINS of the same
        # surface (kickoff `explore` + #225-synthesized `explore_page`) → the
        # derived required set doubled to 31 flows, inflating the verifier's
        # endgame serial burden for zero extra coverage. Dedupe on the
        # suffix-normalized key; the first-seen spelling stays the required name.
        if name and _flow_key(name) not in seen_all:
            seen_all.add(_flow_key(name))
            all_names.append(name)
    if all_names:
        return all_names, "pages"

    return [], "none"


def _flow_key(name: str) -> str:
    """#237: suffix-normalized flow identity — ``explore`` / ``explore_page`` /
    ``explore_screen`` are the SAME user journey. Used to dedupe the derived
    required set and to match records to requirements, so a verifier record
    under either spelling satisfies the flow.

    #285 (tiktok r70, live): the verifier ALSO writes ``_ui`` and COMPOUND
    ``_page_ui`` variants. Folding only ONE trailing ``_page``/``_screen`` left
    ``following_suggested_creators_page`` (required, key ``..._creators``) and its
    passing record ``following_suggested_creators_page_ui`` (key unchanged — trailing
    ``_ui``) under DIFFERENT keys, so the passing record could never clear the failing
    ``_page`` twin → 6 flows falsely FAILED though every one passed, and the run
    idled through both converging-grace windows. Fold ``_ui`` too, and loop until
    stable so compound suffixes (``_page_ui``, ``_screen_ui``, ``_ui_page``) all
    collapse to the same bare journey key."""
    n = str(name or "").strip().lower()
    changed = True
    while changed:
        changed = False
        for suf in ("_page", "_screen", "_ui"):
            if n.endswith(suf) and len(n) > len(suf):
                n = n[: -len(suf)]
                changed = True
                break
    return n


_UI_FLOW_NAME_PREFIX = "validation:ui_flow:"


def _index_ui_flow_records(hub_registry, stale_before: float = 0.0) -> Dict[str, str]:
    """Return ``{flow_name: best_status}`` over validation:ui_flow records.

    LATEST-WINS by ``recorded_at`` (#357).

    ``stale_before`` (#401): if > 0, a FAILED/ERROR record whose newest ``recorded_at`` is
    older than this timestamp is DROPPED (the flow then reads as MISSING → re-verify). A
    ui_flow verdict is verifier-driven and lags the build: a flow the frontend has since
    FIXED keeps its old FAILURE record for the rest of the run, false-failing the delivery
    gate to a STUCK/FAIL-FAST abort (netflix r3: browse_home/player recorded fail at 23:31,
    fixed minutes later, never re-checked, aborted at 00:49). The caller passes the latest
    build-validation time so a failure recorded against an EARLIER build is treated as needing
    re-verification, not as a live regression. A PASSING record is NEVER dropped (a green flow
    stays green — the regression-gate direction #357 protects is untouched); ``stale_before``
    <= 0 (the default) preserves the old behaviour exactly.

    This used to be "passed if ANY record passed", which is right in one
    direction -- a later passing run should clear an earlier failure, matching
    the auto-retry loop -- and blind in the other: a later FAILING record could
    never clear an earlier pass. Once a flow had been green once the gate could
    never see it regress, which is the entire purpose of a regression gate.
    r91's store holds 18 records for 4 flows including success -> failure ->
    success -> failure sequences, all of which read green forever after the
    first success.

    `get_validation_results` already maps `updated_at` onto `recorded_at` for
    every row, so ordering is available. Records with NO usable timestamp keep
    the old passed-wins collapse, so an old store cannot start reporting
    differently just because it lacks the field; a timestamped record always
    outranks an untimed one.
    """
    try:
        results = hub_registry.get_validation_results(limit=1000) or []
    except Exception:
        results = []

    by_flow: Dict[str, str] = {}
    seen_at: Dict[str, float] = {}   # #357: newest recorded_at seen per flow
    for r in results:
        if not isinstance(r, dict):
            continue
        meta = r.get("metadata") or {}
        flow = None
        if meta.get("check") == "ui_flow":
            flow = meta.get("flow")
        else:
            # #340: accept the record an agent can actually WRITE. This indexer
            # was shaped for `record_validation_result(..., metadata=...)`, a
            # HubRegistry method that is not a registered tool; the agent-facing
            # recorder `codehub_record_check` has no metadata parameter at all
            # (its schema is {pr_id, name, status, evidence}). So the ui_flow
            # blocker was unsatisfiable by construction -- 18 dispatches across
            # r91/r92/r93, all to the verifier, none clearable. The colon-
            # prefixed NAME is the form codehub_record_check documents and can
            # produce; treat it as equivalent. The metadata form above is
            # untouched, so every framework-written record still indexes.
            _n = str(r.get("name") or "")
            if _n.startswith(_UI_FLOW_NAME_PREFIX):
                flow = _n[len(_UI_FLOW_NAME_PREFIX):]
        if not flow:
            continue
        flow = str(flow).strip()
        if not flow:
            continue
        status = r.get("status", "error")
        prev = by_flow.get(flow)
        # #357: the ratchet ITSELF lived here — `if prev == "passed": continue`
        # short-circuited every record after the first success, so no later
        # failure could ever be seen. Ordering is decided below instead.
        _at = r.get("recorded_at")
        try:
            _at = float(_at) if _at not in (None, "") else None
        except Exception:
            _at = None
        _prev_at = seen_at.get(flow)
        if _at is not None:
            # A timestamped record outranks any untimed one, and later wins.
            if _prev_at is None or _at >= _prev_at:
                by_flow[flow] = status
                seen_at[flow] = _at
        elif _prev_at is None and prev != "passed":
            # Untimed: preserve the historical passed-wins collapse exactly.
            if status == "passed":
                by_flow[flow] = "passed"
            elif status in {"failed", "error"} and prev != "failed":
                by_flow[flow] = "failed"
            elif prev is None:
                by_flow[flow] = status
    # #401: drop stale FAILURE records (older than the latest build validation) so a flow the
    # frontend has since fixed re-reads as MISSING (re-verify) instead of a permanent hard-fail.
    if stale_before and stale_before > 0:
        for _f in [f for f, s in by_flow.items() if s in ("failed", "error")]:
            _at = seen_at.get(_f)
            if _at is not None and _at < stale_before:
                del by_flow[_f]
    return by_flow


# #401: grace so a genuine SAME-PASS failure (its ui_flow record is written seconds apart from
# that pass's api_smoke record) is NOT mistaken for stale — only a failure predating the latest
# build validation by more than this margin (i.e. a later full validation pass ran without
# re-checking the flow) is dropped.
_UI_FLOW_STALE_GRACE_S = 300.0


def _latest_build_validation_time(hub_registry) -> float:
    """#401: newest ``recorded_at`` across api_smoke validation records — the moment the CURRENT
    build was last validated end-to-end. Returned minus a grace margin so a same-pass ui_flow
    failure is preserved and only genuinely-older (stale) failures are dropped by
    ``_index_ui_flow_records``. Best-effort: 0.0 (staleness disabled) on any hiccup."""
    try:
        results = hub_registry.get_validation_results(limit=1000) or []
    except Exception:
        return 0.0
    latest = 0.0
    for r in results:
        if not isinstance(r, dict):
            continue
        meta = r.get("metadata") or {}
        if meta.get("check") == "api_smoke" or "api_smoke" in str(r.get("name") or ""):
            try:
                _at = float(r.get("recorded_at") or 0)
            except (TypeError, ValueError):
                _at = 0.0
            if _at > latest:
                latest = _at
    return (latest - _UI_FLOW_STALE_GRACE_S) if latest > 0 else 0.0


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

    by_flow = _index_ui_flow_records(
        hub_registry, stale_before=_latest_build_validation_time(hub_registry))
    # #237: also index by suffix-normalized key so a record under `explore_page`
    # satisfies a required `explore` (and vice versa). A passing record under
    # EITHER spelling wins over a failing one under the other — same collapse
    # rule as _index_ui_flow_records.
    by_key: Dict[str, str] = {}
    for rec_name, rec_status in by_flow.items():
        key = _flow_key(rec_name)
        prev = by_key.get(key)
        if prev == "passed":
            continue
        if rec_status == "passed" or prev is None:
            by_key[key] = rec_status
    passed: List[str] = []
    failed: List[str] = []
    missing: List[str] = []
    for name in required:
        # by_key is the sole lookup (it contains every exact spelling too):
        # a PASSED record under either spelling must win over a failed twin
        # (r26: `for_you_feed` failed at 00:41 post-abort while its
        # `for_you_feed_page` twin passed at 00:32 — same journey, green).
        status = by_key.get(_flow_key(name))
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
