"""DeliveryGate — delivery-gate logic extracted from Orchestrator (PROPOSAL #8 Tier-1a).

The gate is the read-only check that decides whether a generated env may be released
(contract alignment, build evidence, validation evidence, required files/dirs, hub
counts). It holds NO mutable orchestrator state — it reads output_dir + the hubs.

Slice 1 (this commit): the two PURE report formatters — `format_delivery_gate_report`
and `delivery_gate_suggestions` are pure functions of the gate dict (no `self`), so they
move verbatim as module-level functions. Orchestrator keeps thin shims so every caller
(run(), _maybe_framework_deliver, the coordination tick, tests) is unchanged.
Following slices move the validators (_validate_delivery_gate / _validate_contract_alignment
/ _incomplete_required_tasks / _extract_* / _validate_build_evidence) into a DeliveryGate
class constructed with (output_dir, hubs, logger) + the 3 cross-group callbacks
(get_validation_results / get_validation_summary / scaffold_design_readme).
"""
from __future__ import annotations

import os

import logging

_LOG_701 = logging.getLogger(__name__)

# --- #790: a delivery check that ERRORS must not read as a delivery check that PASSED ----------
# Seven helpers in this file swallow an exception and return the RELEASE-PERMITTING answer:
# `{}` (no unresolved bugs), `[]` (nothing incomplete / nothing uncovered / no blockers) and, in
# `_chain_touches_business`, `True` (this chain covers business). Each default is deliberate and
# is KEPT — a gate that hard-fails on a hub hiccup wedges every release, which is #789's trade.
# What was missing is that the operator, and `validate_delivery_gate`'s own record, could not tell
# "the check ran and found nothing" from "the check did not run". That is the #737/#769/#788/#789
# class: not wrong code, but code that stopped working while nothing said so — and #751/#752 were
# switched from REPORTING to BLOCKING this session on top of two of these very helpers.
_CHECK_ERRORS_790: List[str] = []


def _swallowed_790(where: str, exc: BaseException, defaulting_to: str) -> None:
    """Record + announce a delivery check that could not run. Never raises."""
    try:
        note = "%s: %s (%s) -> defaulted to %s" % (where, type(exc).__name__, exc, defaulting_to)
        if note not in _CHECK_ERRORS_790:
            _CHECK_ERRORS_790.append(note)
            _LOG_701.warning(
                "DELIVERY CHECK DID NOT RUN (#790): %s. The gate is treating this as the "
                "PERMISSIVE answer so a hub hiccup cannot wedge every release — but this is NOT "
                "evidence the check passed. Any release cut with this present is unverified on "
                "that axis.", note)
    except Exception:                                    # never let the reporter break the gate
        pass


def check_errors_790() -> List[str]:
    """Delivery checks that raised this process. Empty is the normal, healthy state."""
    return list(_CHECK_ERRORS_790)


def reset_check_errors_790() -> None:
    _CHECK_ERRORS_790.clear()

import re
from typing import Any, Dict, List, Optional


# FIX #287 (tiktok r70/r71, live): the check set that satisfies the ui_smoke gate. A passing
# ui_flow is STRICTLY STRONGER UI evidence than ui_smoke — walking a page's interaction flow
# proves the page rendered (a blank/fallback page has no controls to drive) — and
# deliverability._has_passing_ui_evidence already counts ui_flow as UI evidence. The gate used
# to accept only {ui_smoke, ui_page_reachable}: the verifier drove the browser and wrote 11
# PASSING ui_flow records but no ui_smoke record, so _has_passing_ui_evidence was True while
# ui_smoke_pass was False → validation_ui_smoke_missing blocked delivery on an app whose UI was
# demonstrably exercised, and r68/r70/r71 fail-fast aborted there. Accept ui_flow too, matching
# _has_passing_ui_evidence. (The ui_flow DIMENSION keeps its own ui_flow_missing/_failed gate,
# so a real flow defect is not let through.)
_UI_SMOKE_EVIDENCE_CHECKS = {"ui_smoke", "ui_page_reachable", "ui_flow"}


def _ui_smoke_pass(validation_results: Any) -> bool:
    """True iff any validation record is a passed UI-evidence check (see #287)."""
    return any(
        isinstance(r, dict)
        and r.get("status") == "passed"
        and (r.get("metadata", {}) or {}).get("check") in _UI_SMOKE_EVIDENCE_CHECKS
        for r in (validation_results or [])
    )


def _ts757(rec: Any) -> float:
    """#757: a validation record's recency, for superseding an answered failure by name."""
    for k in ("updated_at", "_updated_at", "created_at", "at"):
        v = (rec or {}).get(k) if isinstance(rec, dict) else None
        if isinstance(v, (int, float)):
            return float(v)
    return 0.0


_OWNER_COLUMNS_774 = ("profile_id", "user_id", "tenant_id", "owner_id", "account_id")


def _spec_owner_columns_lost_774(hubs: Any) -> List[Dict[str, str]]:
    """#774: a column the SPEC named that the contract does not carry — owner keys only.

    r150 shipped `my_list`, `ratings` and `continue_watching` keyed on `user_id` while its own
    description said `profile_id` and stated the one privacy rule in the task: *"Each profile
    sees only its own My List, ratings and Continue Watching."* Two profiles on an account shared
    all three. DDL, RegistryHub contract and handlers agreed with each other and disagreed with
    the spec, so every consistency check the framework runs passed — nothing compares the
    contract to the REQUIREMENT.

    Owner columns only, and that restriction is what makes it usable. Measured over the corpus
    with #773's extractor restored:

        runs comparable                                    111
        runs where a spec column is missing                 20   -- all RENAMES
        runs losing an OWNER column                          8   -- 7%, every one profile_id

    Re-measured 2026-08-16 SPLIT BY BUILD ERA, because three corpus figures this session turned
    out to be dominated by old builds and to describe already-fixed defects (#794). This one does
    NOT decay -- it is live, and if anything denser recently:

        ALL     112 comparable   8 hits   7%
        r100+    18 comparable   2 hits  11%
        r145+     7 comparable   1 hit   14%   <- that hit is r150, two runs before this writing

    All 8 are `profile_id` on my_list/ratings/continue_watching; no false positive in 112 runs.
    Blocking would have stopped r150, which shipped the cross-profile leak this check exists for.
    Still REPORTED, not enforced: the switch is the user's call, and the recent-slice denominator
    is 7 runs, which is too small to read a rate off on its own.

    A rename is the dominant shape and is benign: the spec says `poster`, the app ships
    `poster_url`. Token overlap separates them, EXCLUDING the token `id` — every table has an
    `id`, so a bare substring test reads `profile_id` as a rename of `id` and reports zero. That
    was the first version of this check, and it is the same over-loose matching #765 refuses one
    module over.

    Reported, not enforced. Returns [] on any fault.
    """
    out: List[Dict[str, str]] = []
    try:
        from .kickoff.run_kickoff import extract_contract_from_description as _ex
        _ms = getattr(hubs, "milestones", None) or getattr(hubs, "workhub", None)
        rows = []
        try:
            rows = [r for r in (hubs.milestones.list_milestones() or []) if isinstance(r, dict)]
        except Exception as _ms_exc:
            # #883: a failed roadmap read used to read as "the contract expects no tables".
            # `spec` is built from these rows, so `rows = []` makes every expectation vacuous and
            # the check downstream passes on nothing. #790's own rule, in #790's own file.
            _swallowed_790("contract_tables_from_milestones", _ms_exc,
                           "{} = the contract expects no tables")
            rows = []
        spec: Dict[str, set] = {}
        for r in rows:
            for t in (_ex(str(r.get("description_slice") or "")).get("tables") or []):
                spec.setdefault(str(t.get("name")), set()).update(
                    str(c.get("name")) for c in (t.get("columns") or []) if isinstance(c, dict))
        if not spec:
            return []
        have: Dict[str, set] = {}
        for t in (hubs.registryhub.get_tables() or {}).values():
            if not isinstance(t, dict):
                continue
            cols = (t.get("schema") or {}).get("columns") or []
            have[str(t.get("name"))] = {str(c.get("name")) for c in cols if isinstance(c, dict)}

        def _toks(c: str) -> set:
            return {x for x in str(c).split("_") if x and x != "id"}

        for name, cols in spec.items():
            present = have.get(name)
            if not present:
                continue
            for col in sorted(cols - present):
                if col not in _OWNER_COLUMNS_774:
                    continue
                if any(_toks(col) & _toks(x) for x in present):
                    continue                      # a rename, not a loss
                out.append({"table": name, "column": col,
                            "has": ", ".join(sorted(c for c in present if c.endswith("_id")))})
    except Exception:
        return []
    return out


def _imageless_spec_screens_unreachable_823(output_dir: Any) -> List[str]:
    """#823: a spec screen the visual gate CANNOT cover, and the app has no way to reach.

    #822 established that a screen declared in `reference_spec.json` with no reference image is
    absent from `design_system.json` and therefore never captured, scored or blocked on —
    `profiles` in 150 of 150 corpus runs. #788 established that nothing compares the spec's
    `screens` list to the built UI. So for exactly those screens there is no check at all.

    ★ The narrowing is what makes this sound. Two earlier attempts asked "does `route_hint` exist
    as a literal path" and "does any route share tokens with the screen" — both reported screens
    that ARE built, because the spec's names and the app's route vocabulary differ (`new_and_popular`
    is routed `/latest`; `landing` is `/`). Those screens do not need a structural check: the
    visual gate already covers them. Checking only the IMAGELESS ones removes the entire class of
    vocabulary noise. Measured over 142 checkable runs it reports `profiles` (22) and `search` (1)
    and nothing else. ★ The RELEASED gap is 2 runs, not 22: of the 22 reported, 21 built a
    frontend at all and only 2 also cut a tagged release. An earlier draft of this docstring
    said "15% of runs shipped" — that counted runs which never released, inflating it ~11x.
    The check is unchanged; the number beside it was wrong (#647's rule turned on itself).

    Reachability is judged over routes AND page component names, stemmed by the same
    `_route_tokens_728` the framework already uses, so `/profiles` and `ProfilesPage.jsx` both
    count. No App.jsx → `["<unknown: no App.jsx>"]`, never `[]`: a blind probe must not read as a
    clean one (8 corpus runs are in that state).

    REPORTED, not enforced — that switch is #774's class of decision.
    """
    try:
        import json as _json
        import re as _re
        from pathlib import Path as _P
        from .frontend_audit import _route_tokens_728 as _tok
        root = _P(output_dir)
        spec_f = root / "design" / "reference_spec.json"
        refs = root / "design" / "references"
        if not (spec_f.is_file() and refs.is_dir()):
            return []
        app_f = root / "app" / "frontend" / "src" / "App.jsx"
        if not app_f.is_file():
            return ["<unknown: no App.jsx to check reachability against>"]
        app = app_f.read_text(encoding="utf-8", errors="ignore")
        have: set = set()
        for _p in _re.findall(r"""path=["']([^"']+)["']""", app):
            have |= _tok(_p)
        pages = root / "app" / "frontend" / "src" / "pages"
        for _f in (pages.glob("*.jsx") if pages.is_dir() else []):
            have |= _tok(_f.stem)
        imgs = {f.stem for f in refs.iterdir()
                if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")}
        out: List[str] = []
        for sc in (_json.loads(spec_f.read_text(encoding="utf-8")).get("screens") or []):
            if not isinstance(sc, dict):
                continue
            name = str(sc.get("name") or "")
            if not name or name in imgs:
                continue                       # the visual gate covers this one
            want = _tok(name) | _tok(sc.get("route_hint"))
            if want and not (want & have):
                out.append(f"{name} (route_hint {sc.get('route_hint') or '-'})")
        return out[:8]
    except Exception:
        return []

# #830: `validation:<kind>:<flow>` — the kind as the record NAME carries it.
_re_830 = re.compile(r"(?:^|:)(" + "|".join(sorted(_UI_SMOKE_EVIDENCE_CHECKS)) + r")(?::|$)")


# #842: the asset CLASSES a screen's `must_have` asks for, against what design-prep actually staged.
# Each entry is (words that name the class in must_have prose, directory names that satisfy it).
# A closed vocabulary on both sides is what makes this sound -- #823 withdrew two versions that
# tried to match SCREEN names against ROUTE names, which are two open vocabularies. Asset classes
# are a short fixed list, and the staged side is a handful of directory names.
_ASSET_CLASSES_842 = {
    "avatar":   (("avatar", "avatars"), ("avatar", "profile")),
    "poster":   (("poster", "posters"), ("poster",)),
    "backdrop": (("backdrop", "backdrops", "hero image", "still"), ("backdrop", "still")),
    "logo":     (("logo", "logos", "wordmark"), ("brand", "logo")),
    "icon":     (("icon", "icons"), ("icon",)),
    "video":    (("clip", "trailer", "video", "playback"), ("video", "clip")),
}


def _unstaged_asset_classes_842(output_dir: Any) -> List[str]:
    """#842: an asset class the spec asks for and design-prep never stages.

    #841: `profiles` must_have says "profile avatars grid" and `account_menu` says "profile avatar
    dropdown", while the staged categories are backdrops | brand | fonts | icons | posters | video
    — no avatars, in 150 of 150 corpus runs. The lane, owning seed_data.json and having nothing to
    point at, filled `avatar_url` with a CROP OF A FLYOUT PANEL, and the judge correctly reports a
    blank square on my_list, new_and_popular and movies. The avatar sits in the shared top nav, so
    it costs `components` on every authenticated screen.

    Nothing compared the two lists before: #788 found `must_have` is never machine-checked, and
    this is the half of it that can be checked without semantics — a closed vocabulary on both
    sides. Measured over 150 runs it reports `avatar` and nothing else; an earlier cut also
    reported `logo`, which was a false positive (the wordmark is staged under `brand/`).

    REPORTED, not enforced. Returns ``["<class> (asked by <screen>)", ...]``; [] on any fault.
    """
    try:
        import json as _json
        from pathlib import Path as _P
        root = _P(output_dir)
        spec_f = root / "design" / "reference_spec.json"
        adir = root / "design" / "assets"
        if not (spec_f.is_file() and adir.is_dir()):
            return []
        staged = {d.name.lower() for d in adir.iterdir()}
        out: List[str] = []
        seen: set = set()
        for sc in (_json.loads(spec_f.read_text(encoding="utf-8")).get("screens") or []):
            if not isinstance(sc, dict):
                continue
            txt = " ".join(str(x) for x in (sc.get("must_have") or [])).lower()
            for cls, (words, dirs) in _ASSET_CLASSES_842.items():
                if cls in seen or not any(w in txt for w in words):
                    continue
                if any(any(dn in sd for sd in staged) for dn in dirs):
                    continue
                seen.add(cls)
                out.append(f"{cls} (asked by {sc.get('name')})")
        return out[:6]
    except Exception:
        return []

# #844: entity KINDS a screen is about, against the kinds the staged dataset actually contains.
# The sibling of #842 (asset classes), and narrowed the same way: matched on the SCREEN NAME, not
# on must_have prose. A first cut used the prose and reported `browse_home` 141/142, because its
# must_have lists the nav labels ("Home, Shows, Movies, Games, New & Popular") -- a nav label is
# not a content requirement, and it appears on every screen. The screen NAME is the closed,
# unambiguous signal: a screen called `games` is about games.
_ENTITY_KINDS_844 = {
    "game":  (("game", "games"), ("game",)),
    "show":  (("show", "shows", "series"), ("series", "show", "tv")),
    "movie": (("movie", "movies", "film"), ("movie", "film")),
}


def _unseeded_entity_kinds_844(output_dir: Any) -> List[str]:
    """#844: a screen whose subject does not exist in the staged data.

    #840: `games` blocks 71% of recent runs, floors on `components` in 10 of 10, and 9 of 10 carry
    the deviation *"implementation surfaces a film ... instead of a game"*. The judge is right --
    `GamesPage` fetches an unscoped `/api/titles`, the API supports `?kind=`, and the staged
    dataset holds `series` and `movie` and no games. 142 of 143 corpus runs declare a games screen;
    1 of 143 has a game row.

    ★ And it is unsatisfiable, not merely unfixed: the lane could author game rows in its own
    seed_data.json, but #807 established the framework dataset REPLACES `titles` wholesale, so
    they would be deleted before they shipped. No edit the lane can make clears the finding --
    #566z's class at the data layer.

    Measured over 142 runs this reports `game (screen games)` and nothing else; `show` and `movie`
    correctly stay silent because those kinds exist, which is what shows the probe discriminates
    rather than always firing.

    REPORTED, not enforced. [] on any fault.
    """
    try:
        import json as _json
        import re as _re
        from pathlib import Path as _P
        root = _P(output_dir)
        spec_f = root / "design" / "reference_spec.json"
        data_f = root / "app" / "backend" / "seed_dataset.json"
        if not (spec_f.is_file() and data_f.is_file()):
            return []
        data = _json.loads(data_f.read_text(encoding="utf-8"))
        have = {str(row.get("kind", "")).lower()
                 for tbl in (data.values() if isinstance(data, dict) else [])
                 if isinstance(tbl, list) for row in tbl if isinstance(row, dict)}
        if not have:
            return []                      # nothing staged at all is #807's story, not this one
        out: List[str] = []
        for sc in (_json.loads(spec_f.read_text(encoding="utf-8")).get("screens") or []):
            if not isinstance(sc, dict):
                continue
            name = str(sc.get("name") or "").lower()
            for cls, (words, kinds) in _ENTITY_KINDS_844.items():
                if any(_re.search(rf"(^|_){w}(_|$)", name) for w in words) \
                        and not (have & set(kinds)):
                    out.append(f"{cls} (screen {name})")
        return out[:6]
    except Exception:
        return []

# #845: say-once for STANDING facts. #842 fires on 150 of 150 corpus runs and #844 on 141 of 150 --
# because the gaps they name (no avatar staged, no game data) are properties of how this app is
# STAGED, not per-run defects. `validate_delivery_gate` runs at every tick, so each would log
# dozens of identical warnings per run. That is exactly the failure #793 was corrected for: a line
# that fires on healthy runs is a line the reader learns to skip, and I shipped two of them.
#
# The standing fact belongs in the record (EXPERIMENTS items 164/165) and in ONE warning per
# process. Reused shape, not a new mechanism (#792's lesson): a module-level set, cleared by the
# same reset the other reporters use.
_SAID_845: set = set()


def _say_once_845(key: str, logger: Any, msg: str, *args: Any) -> None:
    """Log once per process for a fact that does not change between ticks. Never raises."""
    try:
        if key in _SAID_845:
            return
        _SAID_845.add(key)
        logger.warning(msg, *args)
    except Exception:
        pass


def reset_said_845() -> None:
    """#762's rule: module state outlives a test, so whichever test ran first would silence every
    later one."""
    _SAID_845.clear()

def _ui_evidence_breadth_739(validation_results: Any) -> Dict[str, Any]:
    """#739: how BROAD is the UI evidence behind ``ui_smoke_pass``?

    `_ui_smoke_pass` is existential — ONE passing UI record satisfies it, and a FAILING UI
    record is not consulted at all. In r148 that reads `ui_smoke_pass=True` off `ui_smoke on
    landing + login PASS` while the SPA threw `TypeError: (void 0) is not a function` on 12 of
    14 pages, and the run released v1.0.0.

    This matters most for a decision that is already pending. #671 measured that the UI-smoke
    requirement has NEVER been evaluated — it sits behind `task_suite_exists`, and
    `tasks/tasks.yaml` exists in 0 of 144 runs — and recorded "enforcing it needs a live run".
    **r148 shows enforcement alone would not have caught it**: landing and login passed, so
    `ui_smoke_pass` is True either way. The predicate has to stop being existential too, and
    that is not a change to make blind — hence a measurement, reported beside the verdict.

    Returns counts only; changes no decision. `pages` is best-effort: UI records name their
    page inconsistently (`page`, `route`, `name`), so a missing name is counted as evidence
    without a page rather than dropped.
    """
    # #757: KEEP ONLY THE LATEST RECORD PER NAME. Validation records are a HISTORY, and #752
    # made a single `failed` entry block delivery — so a failure that a later run of the same
    # flow already fixed kept blocking forever, because nothing retires it. r149 is the proof
    # and it cost the whole run: the gate reported "18 passing UI record(s) while 1 FAILED",
    # `validation_ui_evidence_failed` was the ONLY failing check for 85 minutes, and the run
    # ended having delivered nothing. That is not a gate, it is a latch.
    #
    # Superseding by name is the same rule the store itself uses (`validation:<task_id>` is
    # last-write-wins), so this reads the history the way the store means it. A failure that is
    # still the newest word on its flow blocks, exactly as intended; one that a later pass has
    # answered does not.
    _latest757: Dict[str, Any] = {}
    for r in (validation_results or []):
        if not isinstance(r, dict):
            continue
        # #830: fall back to the record NAME when `metadata.check` is absent. #193/#236 recover
        # the kind from `evidence`, but a writer that puts it ONLY in the name
        # (`validation:ui_flow:landing`) leaves nothing to recover — and 645 UI records across
        # the corpus are in exactly that state, invisible to this detector. 36 runs it calls
        # "no UI evidence" have ui_flow records, up to 13 of them.
        #
        # This is a DETECTOR BUG, not a policy change: #752 blocks on "UI evidence that both
        # passes and fails", and the detector has not been seeing all the evidence that policy
        # refers to. Realised effect on #752's reach: r130+ 3 -> 4 runs (the name-only shape is
        # mostly an OLD writer behaviour); corpus-wide 10 -> 22. If that widening is unwanted,
        # revert this hunk alone — #752's own branch is untouched.
        _kind830 = (r.get("metadata", {}) or {}).get("check")
        if not _kind830:
            _m830 = _re_830.search(str(r.get("name") or ""))
            _kind830 = _m830.group(1) if _m830 else None
        if _kind830 not in _UI_SMOKE_EVIDENCE_CHECKS:
            continue
        _key = str(r.get("name") or r.get("task_id") or id(r))
        _prev = _latest757.get(_key)
        if _prev is None or _ts757(r) >= _ts757(_prev):
            _latest757[_key] = r
    passed: List[str] = []
    failed: List[str] = []
    for r in _latest757.values():
        meta = r.get("metadata", {}) or {}
        # #757: the record's own `name` is the reliable label — r149 printed "passed ? / failed
        # ?" for all 19 because none of page/route/name was set in metadata, and a gate that
        # cannot say WHICH page failed cannot be acted on. Names look like
        # `validation:ui_flow:browse_home`; the last segment is the page.
        page = str(meta.get("page") or meta.get("route") or meta.get("name")
                   or str(r.get("name") or "").split(":")[-1] or "?")
        # #752: canonicalise the spelling. Readers normally arrive through #193/#236's
        # normaliser, but the raw store carries THREE spellings — `success` 1198, `passed` 310,
        # `failure` 252 — and this function is now load-bearing (#752 blocks on `failed`), so a
        # record that skipped the normaliser must not silently read as neither.
        _st = str(r.get("status") or "").strip().lower()
        if _st in ("passed", "success", "pass"):
            passed.append(page)
        elif _st in ("failed", "failure", "error"):
            failed.append(page)
    return {
        "passed_records": len(passed),
        "failed_records": len(failed),
        "pages_passed": sorted(set(passed)),
        "pages_failed": sorted(set(failed)),
    }


def _norm_gate_path(p: Any) -> str:
    """Param-agnostic path key for milestone-scope matching: '/api/notes/{id}' ≡ '/api/notes/{}'."""
    s = str(p or "").split("?", 1)[0]
    s = re.sub(r"\{[^}]+\}|:[A-Za-z_][\w]*", "{}", s)
    return s.rstrip("/") or "/"


def unresolved_bug_tasks_743(hubs) -> Dict[str, Any]:
    """#743: bug tasks are excluded from the structural gate, delegated to a gate that isn't.

    `incomplete_required_tasks` deliberately counts only structural kickoff kinds, and says why:
    ad-hoc `task_*` "are governed by their own gates (visual deferral, deliverability) and are
    deliberately excluded here so this gate never double-blocks them". The exclusion is right in
    shape — a bug should not double-block — but the delegation goes nowhere for this kind:
    **neither `deliverability.py` nor this module references `kind='bug'` or a bug severity
    anywhere.** Nothing consumes them.

    Measured over the corpus, restricted to `metadata.kind == 'bug'` (1477 bug tasks in 129 runs):

        completed 818   pending 363   cancelled 140   in_progress 139   failed 17
        P0 only:  completed 443, genuinely open 317, cancelled 99
        runs ending with an unresolved P0 bug        86
        of those, runs that RELEASED                 15     (of 29 real releases in the corpus)

    #755 CORRECTION: this block first read "90 ... 90 — 100%". Both halves were wrong. The
    release test was `r.get("tag") or r.get("version")`, and every `codehub_releases.json`
    carries a bootstrap `{"version": 1, "last_modified_by": "ensure_codehub_document"}` document
    — so EVERY run scored as released. A real release record has a `tag`, and only 29 of 149
    runs have one.

    So a hard block on "any open P0 bug" would stop 86 of 129 runs — and 15 of the 29 runs that
    actually released — and is not a gate, it is a halt. **`failed` is the narrow one**: `fail_task` is authorised (creator/claimer/orchestrator
    only), requires a `reason`, and means an attempt was MADE and did not work — unlike `pending`,
    which can just mean nobody reached it. Only **20 of 148 runs (13%)** end with one, and all 20
    released, carrying things like "Frontend Dockerfile uses registry-blocked base images" and
    "Record the missing critical UI flow validations (blocks delivery)".

    Reports only — no verdict changes here. Whether `failed` should block is a gate-tightening
    of the same class as item 56 and is recorded for a decision rather than switched on.
    """
    wh = getattr(hubs, "workhub", None)
    if wh is None or not hasattr(wh, "list_tasks"):
        return {}
    try:
        tasks = wh.list_tasks() or []
    except Exception as exc:
        _swallowed_790("unresolved_bug_tasks_743", exc, "{} = no unresolved bugs")
        return {}
    failed: List[Dict[str, Any]] = []
    open_p0: List[Dict[str, Any]] = []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        meta = t.get("metadata") or {}
        status = str(t.get("status") or "")
        if status == "failed":
            failed.append({"id": t.get("id"), "title": str(t.get("title") or "")[:120],
                           "severity": meta.get("severity"),
                           "reason": str(t.get("fail_reason") or "")[:200],
                           "kind": meta.get("kind")})
        elif (meta.get("kind") == "bug" and meta.get("severity") == "P0"
                and status in {"pending", "in_progress"}):
            open_p0.append({"id": t.get("id"), "title": str(t.get("title") or "")[:120],
                            "status": status, "assignee": t.get("assignee")})
    return {"failed": failed[:10], "failed_count": len(failed),
            "open_p0_bugs": open_p0[:10], "open_p0_bug_count": len(open_p0)}


def scope_filter_incomplete(incomplete_tasks: List[Dict[str, Any]], scope_paths) -> List[Dict[str, Any]]:
    """§4 milestone-scoped gate: keep only incomplete structural tasks whose endpoint is in
    THIS milestone's slice; defer (drop) tasks for a clearly out-of-slice endpoint (a later
    milestone's surface). A task with NO identifiable endpoint is KEPT (never wrongly deferred).
    ``scope_paths`` empty/None ⇒ no filtering (full-app gate, byte-identical). PURE."""
    if not scope_paths:
        return incomplete_tasks
    keep_keys = {_norm_gate_path(p) for p in scope_paths}
    out: List[Dict[str, Any]] = []
    for t in incomplete_tasks:
        ep = (t.get("metadata") or {}).get("endpoint") or t.get("endpoint")
        path = ep.get("path") if isinstance(ep, dict) else (ep if isinstance(ep, str) else None)
        if path and _norm_gate_path(path) not in keep_keys:
            continue  # out-of-slice structural task → deferred to its own milestone
        out.append(t)
    return out

from .. import delivery as _contract


def delivery_gate_suggestions(gate: Dict[str, Any]) -> List[str]:
    """Map gate failures to concrete remediation suggestions."""
    suggestions: List[str] = []

    missing_files = set(gate.get("missing_files", []))
    missing_dirs = set(gate.get("missing_dirs", []))
    invalid_json = set(gate.get("invalid_json", []))
    failed_checks = set(gate.get("failed_checks", []))

    if "docker/docker-compose.yml" in missing_files:
        suggestions.append("Regenerate `docker/docker-compose.yml` and verify service ports/paths.")
    if "design/README.md" in missing_files:
        suggestions.append("Recreate `design/README.md` (kickoff-coordinator-authored).")

    if "app/backend" in missing_dirs or "backend_code_missing" in failed_checks:
        suggestions.append("Generate backend implementation files under `app/backend` before delivery.")
    if "app/frontend" in missing_dirs or "frontend_code_missing" in failed_checks:
        suggestions.append("Generate frontend implementation files under `app/frontend` before delivery.")
    if "app/database" in missing_dirs or "database_sql_missing" in failed_checks:
        suggestions.append("Create database SQL artifacts under `app/database` (e.g., schema/seed SQL).")

    if "no_endpoints_in_hub" in failed_checks:
        suggestions.append("Register API endpoints in hub using `registryhub_register_endpoint(...)`.")
    if "no_tables_in_hub" in failed_checks:
        suggestions.append("Register DB tables in hub using `registryhub_register_table(...)`.")
    if "no_pages_in_hub" in failed_checks:
        suggestions.append("Register UI pages via `registryhub_register_ui_page(...)`.")
    if "no_implemented_endpoints" in failed_checks:
        suggestions.append("Mark at least one endpoint as implemented via `registryhub_register_endpoint(..., status='implemented')`.")
    if "no_implemented_tables" in failed_checks:
        suggestions.append("Mark at least one table as implemented via `registryhub_register_table(name=..., status='implemented')`.")
    if "verification_checklist_not_ready" in failed_checks:
        suggestions.append("Run and record verification/build checks until checklist is ready for delivery.")
    if "business_chain_missing" in failed_checks:
        suggestions.append(
            "Verifier: register real business-flow verification chains via "
            "`registryhub_register_verification_chain` (auth round-trip + one chain "
            "per critical flow: create -> read-back -> cross-user). The synthesized "
            "default does NOT satisfy delivery.")
    if "business_chain_failing" in failed_checks:
        suggestions.append(
            "Verifier: a registered verification chain is not passing — run_validation "
            "must show business_chain green. Fix the broken step or the endpoint, then re-run.")
    if "business_chain_api_coverage" in failed_checks:
        suggestions.append(
            "Verifier: every registered API endpoint must be exercised by at least one "
            "verification chain step. Add steps (or a new chain) until the union of all "
            "chains covers the whole API surface.")
    if "business_chain_coverage" in failed_checks:
        suggestions.append(
            "Verifier: author one business-flow verification chain per declared critical "
            "flow so every critical flow is covered (not just a subset).")
    if "validation_retry_pending" in failed_checks:
        suggestions.append(
            "Automatic smoke retry is still pending. Wait for retry completion and rerun delivery gate."
        )
    if "validation_api_smoke_missing" in failed_checks:
        suggestions.append(
            "Record at least one passed API smoke check via `codehub_record_check(pr_id='main', "
            "name='validation:api_smoke', status='success', evidence={...})`."
        )
    if "validation_ui_smoke_missing" in failed_checks:
        suggestions.append(
            "Record at least one passed UI smoke check via `codehub_record_check(pr_id='main', "
            "name='validation:ui_smoke', status='success', evidence={...})`."
        )
    if "completeness_state_entity_no_write" in failed_checks:
        suggestions.append(
            "Contract-completeness (#557): a state-bearing table (mutable data column "
            "like progress_seconds/status/value) is READABLE but has NO POST/PUT/PATCH "
            "endpoint — declare + implement the missing write endpoint and register it "
            "in RegistryHub so the feature can actually be persisted (the "
            "Continue-Watching write-path class)."
        )
    if "completeness_flow_no_write" in failed_checks:
        suggestions.append(
            "Contract-completeness (#557): a declared feature_inventory flow whose verb "
            "implies a mutation has no write endpoint backing it — add + register the "
            "endpoint that performs that action."
        )
    if "completeness_entity_no_read" in failed_checks:
        suggestions.append(
            "Contract-completeness (#557): a declared entity has no GET endpoint — add + "
            "register a read endpoint so it is reachable from the frontend."
        )
    if "contract_alignment_failed" in failed_checks:
        suggestions.append(
            "Resolve hub/code drift: align RegistryHub-registered endpoints + SchemaHub-registered tables with SQL schema and backend route definitions before delivery."
        )
    if "semantic_projection_errors" in failed_checks:
        suggestions.append(
            "Fix semantic projection errors recorded in hub, usually invalid or unsupported design/task spec structure."
        )
    if "frontend_build_not_recorded" in failed_checks:
        suggestions.append(
            "Run frontend build (`npm install && npm run build` in `app/frontend`) and record a passed `frontend_build` validation result."
        )
    if "deliverability_ui_flow_missing" in failed_checks:
        suggestions.append(
            "Each critical UI flow in WorkHub (explicit `critical_flows[]` "
            "or `pages` with `critical: true`) needs a passing `validation:ui_flow` "
            "record. Spawn a UI-flow tester worker (config_profile='verifier'); have "
            "it drive `browser_navigate` + at least one mutating step "
            "(`browser_click`/`browser_fill`) + `browser_screenshot`, then call "
            "`codehub_record_check(pr_id='main', name='validation:ui_flow:<name>', "
            "status='success', evidence={...})`."
        )
    if "deliverability_ui_flow_failed" in failed_checks:
        suggestions.append(
            "One or more critical UI flow tests failed. Inspect the failure evidence "
            "(`browser_console`, `browser_network_errors`, screenshot), file a bug "
            "via `bug_create(...)`, route to the owning agent, and re-run the flow "
            "test once fixed."
        )
    if "deliverability_critical_flows_invalid" in failed_checks:
        suggestions.append(
            "WorkHub `critical_flows[]` is present but every entry is "
            "unparseable (each entry must be either a `{\"name\": \"<slug>\", ...}` "
            "dict or a bare slug string). Fix the entries via frontend's "
            "kickoff section re-emit."
        )

    # Deduplicate while preserving order
    deduped: List[str] = []
    seen = set()
    for s in suggestions:
        if s not in seen:
            deduped.append(s)
            seen.add(s)
    return deduped


def format_delivery_gate_report(gate: Dict[str, Any]) -> str:
    """Format delivery gate result as a readable report."""
    if gate.get("ok", False):
        counts = gate.get("hub_counts", {})
        return (
            "Delivery gate passed.\n"
            f"- Endpoints: {counts.get('endpoints', 0)} "
            f"(implemented/tested: {counts.get('implemented_endpoints', 0)})\n"
            f"- Tables: {counts.get('tables', 0)} "
            f"(implemented/tested: {counts.get('implemented_tables', 0)})\n"
            f"- Pages: {counts.get('pages', 0)}"
        )

    state = gate.get("state", "failed")
    if state == "waiting_for_retry":
        lines = ["Delivery gate waiting for automatic retries:"]
    else:
        lines = ["Delivery gate failed:"]

    missing_files = gate.get("missing_files", [])
    if missing_files:
        lines.append(f"- Missing files: {', '.join(missing_files)}")

    missing_dirs = gate.get("missing_dirs", [])
    if missing_dirs:
        lines.append(f"- Missing directories: {', '.join(missing_dirs)}")

    invalid_json = gate.get("invalid_json", [])
    if invalid_json:
        lines.append(f"- Invalid JSON specs: {', '.join(invalid_json)}")

    failed_checks = gate.get("failed_checks", [])
    if failed_checks:
        lines.append(f"- Failed checks: {', '.join(failed_checks)}")

    contract_alignment = gate.get("contract_alignment", {})
    if contract_alignment:
        lines.append(
            "- Contract alignment: "
            f"expected_tables={contract_alignment.get('expected_tables', 0)}, "
            f"sql_tables={contract_alignment.get('sql_tables', 0)}, "
            f"declared_endpoints={contract_alignment.get('declared_endpoints', 0)}, "
            f"implemented_endpoints={contract_alignment.get('implemented_endpoints', 0)}"
        )
        for item in contract_alignment.get("errors", [])[:5]:
            lines.append(f"  • ERROR: {item}")
        for item in contract_alignment.get("warnings", [])[:5]:
            lines.append(f"  • WARN: {item}")

    semantic_drift = gate.get("semantic_hub_drift", {})
    if semantic_drift:
        lines.append(
            "- Semantic hub drift: "
            f"spec_endpoints={semantic_drift.get('spec_endpoints', 0)}, "
            f"hub_endpoints={semantic_drift.get('hub_endpoints', 0)}, "
            f"spec_tables={semantic_drift.get('spec_tables', 0)}, "
            f"hub_tables={semantic_drift.get('hub_tables', 0)}, "
            f"spec_pages={semantic_drift.get('spec_pages', 0)}, "
            f"hub_pages={semantic_drift.get('hub_pages', 0)}"
        )
        for item in semantic_drift.get("errors", [])[:5]:
            lines.append(f"  • ERROR: {item}")
        for item in semantic_drift.get("warnings", [])[:5]:
            lines.append(f"  • WARN: {item}")

    projection_errors = gate.get("projection_errors", {})
    if projection_errors:
        lines.append(f"- Projection errors: {len(projection_errors)}")
        for path, item in list(projection_errors.items())[:5]:
            lines.append(f"  • {path}: {item.get('error') if isinstance(item, dict) else item}")

    build_evidence = gate.get("build_evidence", {})
    if build_evidence:
        lines.append(
            "- Build evidence: "
            f"frontend_package={build_evidence.get('frontend_package', False)}, "
            f"frontend_build_recorded={build_evidence.get('frontend_build_recorded', False)}"
        )

    counts = gate.get("hub_counts", {})
    lines.append(
        "- hub counts: "
        f"endpoints={counts.get('endpoints', 0)} "
        f"(implemented={counts.get('implemented_endpoints', 0)}), "
        f"tables={counts.get('tables', 0)} "
        f"(implemented={counts.get('implemented_tables', 0)}), "
        f"pages={counts.get('pages', 0)}"
    )

    verification = gate.get("verification", {})
    checklist = verification.get("checklist", {}) if isinstance(verification, dict) else {}
    if checklist:
        status_pairs = []
        for key, item in checklist.items():
            status = item.get("status", "pending") if isinstance(item, dict) else "pending"
            status_pairs.append(f"{key}={status}")
        lines.append(f"- Verification checklist: {', '.join(status_pairs)}")

    runtime_validation = gate.get("validation_runtime", {})
    if runtime_validation:
        lines.append(
            "- Runtime validation: "
            f"task_suite={runtime_validation.get('task_suite_exists', False)}, "
            f"total_results={runtime_validation.get('total_results', 0)}, "
            f"api_smoke_pass={runtime_validation.get('api_smoke_pass', False)}, "
            f"ui_smoke_pass={runtime_validation.get('ui_smoke_pass', False)}, "
            f"retries_used_total={runtime_validation.get('retries_used_total', 0)}, "
            f"retry_pending={runtime_validation.get('retry_pending_count', 0)}, "
            f"retry_exhausted={runtime_validation.get('retry_exhausted_count', 0)}"
        )
        failed_top = runtime_validation.get("failed_top", [])
        if failed_top:
            lines.append("- Failed validation tasks (top):")
            for item in failed_top:
                lines.append(
                    "  • "
                    f"{item.get('task_id')} [{item.get('status')}] "
                    f"(domain_hint={item.get('domain_hint')}, mode={item.get('execution_mode')}) "
                    f"- {item.get('summary') or 'no summary'}"
                )

    # #557: completeness oracle findings (reported even when the gate otherwise
    # passes — Stage 1 is advisory, not blocking).
    completeness = gate.get("completeness", [])
    if completeness:
        lines.append(
            f"- Completeness oracle (#557, reported): {len(completeness)} gap(s)")
        for item in completeness[:8]:
            if not isinstance(item, dict):
                continue
            target = item.get("entity") or item.get("flow") or "?"
            lines.append(
                f"  • [{item.get('severity')}] {item.get('check_id')}: "
                f"{target} — {item.get('detail')}")

    suggestions = delivery_gate_suggestions(gate)
    if suggestions:
        lines.append("- Suggested fixes:")
        for s in suggestions:
            lines.append(f"  • {s}")

    return "\n".join(lines)


def incomplete_required_tasks(hubs) -> List[Dict[str, Any]]:
    """GATE-C2/C3: kickoff-synthesized STRUCTURAL tasks that are still
    pending/in_progress AND not satisfied by registry evidence.

    The delivery gate is an "evidence exists" model — it never checked
    whether the assigned work is DONE, so dozens of per-endpoint
    ``validate_api_smoke`` tasks (and any ``implement_*`` task) could linger
    pending while a release cut anyway (the user's "task not finished, why
    release" root cause).

    This is COVERAGE-AWARE, not status-naive — verified on the released
    generated/instagram round47: 24 ``validate_api_smoke`` tasks sat pending
    only because the verifier ran one ``run_validation()`` covering every
    endpoint instead of closing each per-endpoint task. Blocking on raw
    pending status would falsely block that good release. So a pending task
    blocks ONLY when its registry evidence is missing:

      * ``implement_endpoint``  → endpoint not registered implemented/tested
      * ``implement_table``     → table not registered implemented/tested
      * ``validate_api_smoke``  → endpoint has no passing contract-test record

    Ad-hoc ``task_*`` (visual / breaking-change / merge-conflict / chain-
    authoring remediation) are NOT structural kickoff kinds — they are
    governed by their own gates (visual deferral, deliverability) and are
    deliberately excluded here so this gate never double-blocks them.
    """
    wh = getattr(hubs, "workhub", None)
    if wh is None or not hasattr(wh, "list_tasks"):
        return []
    rh = getattr(hubs, "registryhub", None)
    sh = getattr(hubs, "schema_hub", None)
    try:
        tasks = wh.list_tasks() or []
    except Exception as exc:
        _swallowed_790("incomplete_required_tasks", exc, "[] = nothing incomplete")
        return []

    def _norm(s: Any) -> str:
        return re.sub(r"[^a-z0-9]", "", str(s or "").lower())

    # Registry endpoint identity → (clean_id, implemented?) keyed by the
    # normalized form so a task's metadata.endpoint OR its munged id both map.
    endpoints: Dict[str, Any] = {}
    try:
        endpoints = (rh.get_endpoints() if rh is not None else {}) or {}
    except Exception:
        endpoints = {}
    reg_clean: Dict[str, str] = {}
    impl_ep: set = set()
    for k, v in endpoints.items():
        if k == "_meta" or not isinstance(v, dict):
            continue
        # Deprecated endpoints are retired from the contract — do NOT count them as
        # "required" here. lifecycle.business_endpoints (and validation_ready) already
        # filter them out, so counting them only here makes delivery block on an
        # endpoint validation considers done (the deprecated-asymmetry: ready-yet-blocked).
        if v.get("status") == "deprecated":
            continue
        clean = (
            f"{(v.get('method') or '').upper()} {v.get('path') or ''}".strip()
            if v.get("method") else str(k)
        )
        nk = _norm(clean)
        reg_clean[nk] = clean
        if v.get("status") in {"implemented", "tested"}:
            impl_ep.add(nk)

    tables: Dict[str, Any] = {}
    try:
        tables = (sh.list_tables() if sh is not None else {}) or {}
    except Exception:
        tables = {}
    impl_tbl: set = {
        _norm(v.get("name") or k)
        for k, v in tables.items()
        if k != "_meta" and isinstance(v, dict)
        and v.get("status") in {"implemented", "tested"}
    }

    _METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}

    def _endpoint_norm(t: Dict[str, Any]) -> str:
        ep = (t.get("metadata") or {}).get("endpoint") or t.get("endpoint")
        if isinstance(ep, dict) and ep.get("path"):
            return _norm(f"{(ep.get('method') or '').upper()} {ep['path']}")
        parts = str(t.get("id") or "").split(".")
        for i, p in enumerate(parts):
            if p.lower() in _METHODS and i + 1 < len(parts):
                return _norm(p + " " + ".".join(parts[i + 1:]))
        return _norm(t.get("id"))

    def _table_norm(t: Dict[str, Any]) -> str:
        name = (t.get("metadata") or {}).get("table") or t.get("table")
        if name:
            return _norm(name)
        tid = str(t.get("id") or "")
        return _norm(tid[len("impl.table."):] if tid.startswith("impl.table.") else tid)

    def _endpoint_validated(nk: str) -> bool:
        if rh is None:
            return False
        clean = reg_clean.get(nk)
        if not clean:  # endpoint not even registered → cannot be validated
            return False
        try:
            recs = rh.get_contract_test_results(clean) or []
            # PROPOSAL #44: contract-test records are stored under the
            # param-NAME-agnostic endpoint_id (``GET /api/notes/{}`` — the same
            # canonicalization as registryhub.endpoint_id / PROPOSAL #1/#29), but
            # ``clean`` carries the registry path form (``GET /api/notes/{id}``).
            # An exact-match lookup misses a PASSING test for an ``{id}`` endpoint,
            # so validate_api_smoke.*_{id} tasks are falsely "incomplete" and the
            # delivery gate (incomplete_required_tasks) blocks forever even though
            # the smoke test passed (smoke-notes run 2026-06-19). Fall back to the
            # canonical form so the passing record resolves.
            if not recs:
                canon = re.sub(r"\{[^}]+\}", "{}", clean)
                if canon != clean:
                    recs = rh.get_contract_test_results(canon) or []
        except Exception:
            return False
        return any(
            isinstance(r, dict)
            and ((r.get("result") or {}).get("passed") is True
                 or (r.get("result") or {}).get("verdict") == "pass")
            for r in recs
        )

    incomplete: List[Dict[str, Any]] = []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        if t.get("status") not in {"pending", "in_progress"}:
            continue
        kind = (t.get("metadata") or {}).get("kind") or t.get("kind")
        if kind == "implement_endpoint":
            _nk = _endpoint_norm(t)
            # Covered if the lane flipped the registry status, OR if api_smoke
            # PROVED the endpoint works — a passing contract-test record from
            # run_validation's live HTTP probe (the same evidence the
            # validate_api_smoke branch below trusts). The framework PROJECTS a
            # working handler for every registered endpoint and api_smoke probes
            # all of them, but the lane often never calls
            # register_endpoint(status='implemented'); without this, those
            # api_smoke-validated endpoints' impl tasks block delivery FOREVER
            # while the idle lanes can't self-heal (youtube run #19 deadlock:
            # 32 'defined' endpoints all passed api_smoke, gate wedged anyway).
            if _nk in impl_ep or _endpoint_validated(_nk):
                continue
            reason = "endpoint not implemented in registry and no passing contract-test record"
        elif kind == "implement_table":
            if _table_norm(t) in impl_tbl:
                continue
            reason = "table not implemented in registry"
        elif kind == "validate_api_smoke":
            if _endpoint_validated(_endpoint_norm(t)):
                continue
            reason = "endpoint has no passing contract-test record"
        else:
            continue  # not a structural kickoff task — governed elsewhere
        incomplete.append({
            "id": t.get("id"),
            "kind": kind,
            "status": t.get("status"),
            "assignee": t.get("assignee"),
            "reason": reason,
        })
    return incomplete


def _declared_critical_flows(hubs) -> List[str]:
    """Names of the DECLARED critical flows (the authoritative set the verifier
    must cover). Reuses ``compute_flow_coverage``'s inventory. Returns [] on any
    error so the coverage check degrades to a no-op rather than wedging the gate."""
    try:
        from .flow_coverage import compute_flow_coverage
        rep = compute_flow_coverage(hubs, None)
        return list(getattr(rep, "required", []) or [])
    except Exception as exc:
        _swallowed_790("_declared_critical_flows", exc, "[] = no declared critical flows")
        return []


def _uncovered_business_endpoints(rh, authored_chains: List[Dict[str, Any]]) -> List[str]:
    """Business endpoints (``METHOD /path``) NOT exercised by ANY authored chain
    step. Reuses ``registryhub.endpoint_id`` + the ``${var}``->``{x}`` collapse
    that ``register_verification_chain`` validates steps with, so a chain step
    ``/api/posts/${id}`` matches the registered ``/api/posts/{post_id}``
    (param-name-agnostic). Returns [] on any error so the check degrades to a
    no-op rather than wedging the gate."""
    try:
        from .lifecycle import business_endpoints
        required: Dict[str, str] = {}  # endpoint_id -> readable "METHOD /path"
        for ep in business_endpoints(rh.get_endpoints() or {}):
            m = str(ep.get("method") or "").upper()
            p = str(ep.get("path") or "")
            if m and p:
                required[rh.endpoint_id(m, p)] = f"{m} {p}"
        if not required:
            return []
        covered = set()
        for ch in authored_chains:
            for st in (ch.get("steps") or []):
                p = str(st.get("path") or "")
                if not p:
                    continue
                p = re.sub(r"\$\{[^}]+\}", "{x}", p)
                covered.add(rh.endpoint_id(str(st.get("method") or "GET"), p))
        return sorted(lbl for eid, lbl in required.items() if eid not in covered)
    except Exception as exc:
        _swallowed_790("_uncovered_business_endpoints", exc, "[] = every business endpoint covered")
        return []


def _business_endpoint_ids(rh) -> set:
    """The endpoint_id set for the app's BUSINESS endpoints (excludes auth/oauth/
    control-surface/infra via ``is_business``). Reuses ``registryhub.endpoint_id`` so
    the ids match chain steps param-name-agnostically (same basis as
    ``_uncovered_business_endpoints``). Empty on any error → callers degrade to a no-op."""
    try:
        from .lifecycle import business_endpoints
        ids = set()
        for ep in business_endpoints(rh.get_endpoints() or {}):
            m = str(ep.get("method") or "").upper()
            p = str(ep.get("path") or "")
            if m and p:
                ids.add(rh.endpoint_id(m, p))
        return ids
    except Exception:
        return set()


def _chain_touches_business(rh, rec: Dict[str, Any], biz_ids: set) -> bool:
    """True iff ANY step of the chain targets one of the app's business endpoints
    (the ``${var}`` -> ``{x}`` collapse mirrors ``_uncovered_business_endpoints`` so a
    step ``/api/titles/${id}`` matches the registered ``/api/titles/{title_id}``). On
    any error returns True — be conservative and let the chain keep its blocking power."""
    try:
        for st in (rec.get("steps") or []):
            p = str(st.get("path") or "")
            if not p:
                continue
            p = re.sub(r"\$\{[^}]+\}", "{x}", p)
            if rh.endpoint_id(str(st.get("method") or "GET"), p) in biz_ids:
                return True
    except Exception as exc:
        _swallowed_790("_chain_touches_business", exc, "True = this chain covers business")
        return True
    return False


def complete_coverage_chain(hubs) -> Dict[str, Any]:
    """COVERAGE-BY-CONSTRUCTION (2026-07-01) — the verifier LLM authors the REAL business-flow
    + isolation chains, but reliably COVERING every registered business endpoint is a mechanical,
    high-variance chore that repeatedly wedged delivery (run-12 + run-19 stuck 78min on
    ``business_chain_api_coverage``; the backend was fully green). Once the verifier has authored
    >=1 real chain, the framework COMPLETES the api-coverage requirement by registering a single
    ``_framework_coverage`` chain (``kind="coverage"``) whose steps reference exactly the endpoints
    no verifier chain touches — satisfying the user's full-coverage HARD RULE BY CONSTRUCTION
    without weakening it:
      * it counts ONLY toward ``business_chain_api_coverage`` (union of chains hits every endpoint);
      * it is NEVER executed (carries no request bodies — load_verifier_chains skips kind=coverage,
        so it can't fail api_smoke's business_chain probe);
      * it never satisfies ``business_chain_missing`` / ``_failing`` / ``_isolation`` — those stay
        the verifier's REAL-chain job (the framework only fills the mechanical coverage gap).
    Idempotent (recomputed from the CURRENT uncovered set each call). Returns ``{"covered": N,
    "endpoints": [...]}`` when it (re)wrote the chain, else ``{}``. Best-effort; never raises."""
    rh = getattr(hubs, "registryhub", None)
    if rh is None or not hasattr(rh, "get_verification_chains"):
        return {}
    try:
        chains = rh.get_verification_chains() or {}
    except Exception:
        return {}
    verifier_authored = [
        rec for name, rec in chains.items()
        if name != "_meta" and isinstance(rec, dict) and rec.get("steps")
        and str(rec.get("kind") or "").lower() != "coverage"
    ]
    if not verifier_authored:
        return {}  # the verifier must author >=1 REAL chain first — missing stays its job
    uncovered = _uncovered_business_endpoints(rh, verifier_authored)
    if not uncovered:
        return {}  # already fully covered by the verifier's own chains
    steps: List[Dict[str, Any]] = []
    for lbl in uncovered:
        parts = str(lbl).split(None, 1)          # "METHOD /path" -> {method, path}
        if len(parts) == 2 and parts[1].strip().startswith("/"):
            steps.append({"method": parts[0].strip().upper(), "path": parts[1].strip()})
    if not steps:
        return {}
    import time as _time
    rec = {
        "id": "_framework_coverage", "name": "_framework_coverage", "kind": "coverage",
        "description": ("framework coverage-completion: references the business endpoints no "
                        "verifier chain touches so the api-coverage gate is satisfied by "
                        "construction. NOT executed (no bodies); the verifier's real chains "
                        "carry the flow/isolation verification."),
        "steps": steps, "status": "coverage", "last_result": None, "last_run_at": None,
        "registered_by": "framework", "_updated_at": _time.time(),
    }
    try:
        vc = getattr(rh, "_verification_chains", None)
        if vc is None:
            return {}
        vc.update(lambda m: m.set("_framework_coverage", rec, "framework"),
                  change_info={"agent": "framework"})
    except Exception:
        return {}
    return {"covered": len(steps), "endpoints": [s["path"] for s in steps]}


def business_chain_blockers(hubs) -> Dict[str, Any]:
    """DELIVERY-QUALITY GATE (user 2026-06-24): what ships must be verified by a
    REAL business-flow verification chain, not just per-endpoint api_smoke. The
    verifier MUST author chains (``registryhub_register_verification_chain``) that
    exercise the business flows end-to-end. The framework's synthesized DEFAULT
    chain is a ``run_validation`` deadlock-breaker only — it is NEVER stored in the
    chain registry, so an empty ``get_verification_chains()`` proves the verifier
    authored none, and the default can never satisfy this gate.

    Returns ``{}`` when satisfied, else ``{"reason": <check>, "detail": <msg>, ...}``.
    Strictest tier (user choice): three blocking conditions —
      * ``business_chain_missing``  — verifier authored NO chain (registry empty)
      * ``business_chain_failing``  — an authored chain has not PASSED (never run,
                                      or last run left steps broken)
      * ``business_chain_coverage`` — fewer authored chains than declared critical
                                      flows (must cover every critical flow)
    """
    rh = getattr(hubs, "registryhub", None)
    if rh is None or not hasattr(rh, "get_verification_chains"):
        return {}
    # COVERAGE-BY-CONSTRUCTION (2026-07-01): once the verifier authored real chains, let the
    # framework complete the mechanical api-coverage gap (the #1 recurring stuck-blocker —
    # run-12/run-19 wedged 78min here). Best-effort; registers a kind="coverage" chain that
    # counts ONLY for the coverage check below.
    try:
        complete_coverage_chain(hubs)
    except Exception as _e:
        # #701: SAY SO. This call is the fix for what the comment above calls "the #1 recurring
        # stuck-blocker — run-12/run-19 wedged 78min here", and it was swallowed whole. When it
        # raises, no kind="coverage" chain is registered, the api-coverage check below finds the
        # gap it was written to close, and the run wedges on exactly the blocker this prevents —
        # with nothing anywhere saying the prevention failed.
        #
        # The swallow itself is right: a coverage-completion hiccup must never crash the gate,
        # and the check below still runs. What was wrong is that the two outcomes — "completed"
        # and "crashed, so the next 78 minutes are for nothing" — were indistinguishable.
        # Same disposition as #691, #696, #698 and #700: keep the behaviour, end the silence.
        try:
            _LOG_701.warning(
                "coverage-chain completion FAILED (%s: %s) — no kind=\"coverage\" chain was "
                "registered, so the api-coverage check below will report the mechanical gap "
                "this call exists to close. A coverage stuck-blocker after this line is a "
                "SYMPTOM of it, not a verifier failure.", type(_e).__name__, _e)
        except Exception:
            pass
    try:
        chains = rh.get_verification_chains() or {}
    except Exception as exc:
        _swallowed_790("business_chain_blockers", exc, "{} = no chain blockers")
        return {}
    _all_with_steps = [
        rec for name, rec in chains.items()
        if name != "_meta" and isinstance(rec, dict) and rec.get("steps")
    ]
    # A framework COVERAGE-completion chain (kind="coverage") counts ONLY toward the api-
    # coverage check — it is never executed and must NOT satisfy missing / failing / isolation,
    # which remain the VERIFIER's real-chain responsibility.
    authored = [rec for rec in _all_with_steps
                if str(rec.get("kind") or "").lower() != "coverage"]
    # #486: a chain that exercises NO business endpoint — only auth/control-surface/infra
    # paths (a verifier-authored tenant-admin / reset / init-tenant sweep) — is not a
    # business-FLOW chain: it verifies nothing about the APP, so its pass/fail must not gate
    # business delivery (netflix r58, live: `tenant_admin_coverage` POSTs the framework
    # /api/v1/tenants which 400s on a missing client-supplied id, wedging an app that is
    # otherwise 27/27 business-green — the task#47 whack-a-mole). Mirrors the kind="coverage"
    # exclusion and reuses the SAME is_business() classification the coverage check already
    # trusts. SAFE: excluding an infra-only chain can NEVER hide a business bug (it touches
    # zero business endpoints), and the full business surface stays enforced by
    # _uncovered_business_endpoints below. Degrades to a no-op when the endpoint registry is
    # unavailable (business ids empty → keep every chain). If the filter leaves NO chain, the
    # verifier authored no business-flow chain → business_chain_missing correctly fires.
    _biz_ids = _business_endpoint_ids(rh)
    if _biz_ids:
        authored = [rec for rec in authored
                    if _chain_touches_business(rh, rec, _biz_ids)]
    if not authored:
        return {
            "reason": "business_chain_missing", "authored": 0,
            "detail": ("no verifier-authored verification chain is registered — the "
                       "synthesized default does NOT satisfy delivery. The verifier "
                       "must register business-flow chains via "
                       "registryhub_register_verification_chain."),
        }
    # #272: a chain blocked ONLY by a framework-projected defect (a _projected_ handler
    # 5xx — route_projector's bug, not the lane's) is separated out. It still blocks
    # delivery (a broken endpoint must not ship), but under its OWN reason so remediation
    # routes to the FRAMEWORK, not to a lane dispatched to fix code it never wrote — the
    # exact trap #263/#270/#271 sprang (Hatch design principle #5: infra-vs-app failures
    # must be structurally distinct).
    # #510 (netflix r84, 2026-08-05): a NEVER-RUN chain (status 'registered', no last_result)
    # has NO failure evidence — it must NOT block delivery like a chain that RAN and broke.
    # r84 died here: the verifier RE-AUTHORED 5 comprehensive business chains at the deliver
    # tail that never ran → business_chain_failing FOREVER → the milestone gate never cleared →
    # the #139 final-gate DRIFT WAIVER (which needs a cleared milestone) never fired → main()=1,
    # no release — though 11 authored chains PASSED and covered the surface. A never-run chain
    # is INDETERMINATE, not a failure; only a chain that RAN and left broken steps (or status
    # 'failing') blocks. The ≥1-passing guard below + the api-coverage check (+ the framework
    # coverage-completion chain) still enforce that SOMETHING real verified the surface, so this
    # can never ship a wholly-unverified app. Mirrors the framework's OWN model (the kind=
    # 'coverage' chain is intentionally never-run yet counts). GENERALIZES: the verifier's unrun
    # re-authoring / churn can no longer wedge a fully-verified app at the deliver tail.
    def _never_ran(_rec):
        return (not _rec.get("last_result")
                and str(_rec.get("status") or "").lower()
                not in ("passing", "framework_blocked", "failing", "broken"))
    not_passing = [
        str(rec.get("name") or rec.get("id"))
        for rec in authored
        if not _never_ran(rec) and (
            (rec.get("status") not in ("passing", "framework_blocked"))
            or (rec.get("last_result") or {}).get("broken"))
    ]
    framework_blocked = [
        str(rec.get("name") or rec.get("id"))
        for rec in authored
        if rec.get("status") == "framework_blocked"
        and not (rec.get("last_result") or {}).get("broken")
    ]
    if framework_blocked and not not_passing:
        _defs = [d for rec in authored
                 for d in ((rec.get("last_result") or {}).get("framework_defects") or [])]
        return {
            "reason": "business_chain_framework_defect", "authored": len(authored),
            "chains": framework_blocked, "defects": _defs[:8],
            "detail": (f"{len(framework_blocked)} chain(s) are blocked ONLY by a "
                       "framework-PROJECTED handler crashing (5xx from a _projected_ "
                       "function — emitted by route_projector, which the lane cannot edit): "
                       + "; ".join(_defs[:4])
                       + ". This is a FRAMEWORK defect, not an app bug — do not dispatch a "
                       "lane. Fix the projector/skeleton generator."),
        }
    if not_passing:
        return {
            "reason": "business_chain_failing", "authored": len(authored),
            "chains": not_passing,
            "detail": (f"{len(not_passing)} verification chain(s) have NOT passed: "
                       + ", ".join(not_passing[:8]) + ". run_validation must show "
                       "business_chain green (re-author the broken step or fix the "
                       "endpoint) before delivery."),
        }
    # #510 GUARD: not_passing excludes never-run chains, so an authored set that is ALL
    # never-run would otherwise fall through to GREEN with nothing actually verified. Require
    # at least ONE authored chain to have PASSED — else the business surface is unverified.
    if not any(rec.get("status") in ("passing", "framework_blocked")
               and not (rec.get("last_result") or {}).get("broken")
               for rec in authored):
        return {
            "reason": "business_chain_failing", "authored": len(authored),
            "chains": [str(rec.get("name") or rec.get("id")) for rec in authored][:8],
            "detail": ("verifier authored chain(s) but NONE has PASSED (all never-run/"
                       "indeterminate) — run_validation must show at least one passing "
                       "business chain before delivery."),
        }
    # HARD RULE (user 2026-06-24): the UNION of all authored chains must exercise
    # EVERY business API endpoint at least once — the chains collectively cover the
    # whole API surface, not just happy-path flows. A registered endpoint that no
    # chain step touches is unverified and blocks delivery.
    uncovered = _uncovered_business_endpoints(rh, _all_with_steps)
    if uncovered:
        return {
            "reason": "business_chain_api_coverage", "authored": len(authored),
            "uncovered": uncovered,
            "detail": (f"{len(uncovered)} registered API endpoint(s) are NOT exercised by "
                       "ANY verification chain — every business endpoint must appear in at "
                       "least one chain step: " + ", ".join(uncovered[:12])
                       + ("" if len(uncovered) <= 12 else f" (+{len(uncovered) - 12} more)")
                       + ". Add steps to existing chains or author a new chain to cover them."),
        }
    # ISOLATION/INVARIANT requirement (#2, user 2026-06-25): coverage above proves every
    # endpoint is HIT, but a pure 2xx happy-path sweep proves nothing about tenancy/ownership
    # — a backend returning dummy 2xx for every route would clear it (V29: 11 dummy no-op
    # routes shipped). Require >=1 NEGATIVE assertion: a step expecting a denial (401/403),
    # i.e. an unauth or cross-user/cross-tenant access that MUST be refused. Routed to the
    # verifier via _GATE_OWNER["business_chain_isolation"]. Env-gated (default-off) until the
    # drive fix is validated end-to-end, then enable by default.
    import os as _os
    if _os.environ.get("ENVGEN_ISOLATION_GATE", "0").lower() in ("1", "true", "yes", "on"):
        _denial = {401, 403}
        _has_isolation = False
        for _rec in authored:
            for _st in (_rec.get("steps") or []):
                _exp = _st.get("expect")
                if isinstance(_exp, (list, tuple)):
                    _codes = {int(x) for x in _exp if str(x).isdigit()}
                elif str(_exp).strip().isdigit():
                    _codes = {int(str(_exp).strip())}
                else:
                    _codes = set()
                if _codes & _denial:
                    _has_isolation = True
                    break
            if _has_isolation:
                break
        if not _has_isolation:
            return {
                "reason": "business_chain_isolation", "authored": len(authored),
                "detail": ("verification chains are a pure 2xx happy-path sweep with NO "
                           "negative/isolation assertion — that cannot distinguish a real, "
                           "tenancy-enforcing backend from one returning dummy 2xx. Add at "
                           "least one step proving ownership/tenant isolation is ENFORCED: a "
                           "second user (or an unauthenticated request) attempting to read or "
                           "modify another user's resource MUST be refused (expect 401/403). "
                           "Author the cross-user isolation step, register it, re-run "
                           "run_validation."),
            }
    # NOTE: the per-flow chain-COUNT check was retired alongside the user_flow
    # migration (2026-06-22) — critical flows are now page-derived, so a count proxy
    # (chains >= flows) is no longer meaningful. The per-API coverage above is the
    # robust, concrete coverage guarantee (every endpoint exercised); authored+passing
    # + full API coverage is what delivery requires.
    return {}


def noncanonical_business_response_keys(hubs) -> List[Dict[str, Any]]:
    """PROMPT-C1 (response_key by-construction): a route_projector-projected
    business endpoint MUST declare a response_key inside the canonical envelope
    the projector actually emits — ``items`` (collection) or ``item`` (single).
    The projector hardcodes that envelope and IGNORES any other key, so a
    registered ``response_key='games'`` leaves the frontend reading
    ``data.games`` against a ``{"items": [...]}`` body → the single biggest
    blank-page source. Flag the non-canonical key at build time instead.

    Only the KEY VOCABULARY is enforced ({items, item}); WHICH of the two an
    endpoint should use (single vs collection) is the runtime
    ``business_endpoints_correct_shape`` gate's job — and is deliberately NOT
    re-derived here, because the method/path heuristic mis-classifies legit
    single-object GETs that don't end in ``/me`` or ``/{id}`` (round47's
    ``GET /api/.../insights`` / ``/limit`` / ``/business_discovery`` correctly
    return ``item``; demanding ``items`` for them would be a false positive).

    Scope = projector-owned BUSINESS endpoints only. Control-plane / infra /
    auth / oauth / spine endpoints carry a ``metadata.kind`` and ship their own
    handlers (e.g. ``{"message": ...}``) — NOT projected, frontend already skips
    them, exempt (round47's 3 ``message`` keys are all ``kind=infra``).
    custom_routes are hand-authored, exempt. An ABSENT response_key is a
    separate "lane forgot to set it" concern, not a wrong-key blank page, so it
    is not flagged here."""
    rh = getattr(hubs, "registryhub", None)
    if rh is None:
        return []
    try:
        endpoints = rh.get_endpoints() or {}
    except Exception as exc:
        _swallowed_790("noncanonical_business_response_keys", exc, "[] = every response key canonical")
        return []
    _CANONICAL = {"items", "item"}
    # #853: this one is a deliberate VARIANT (it adds "custom"), so it is composed rather than
    # replaced. But it listed `control_plane` and NOT `control` — and `control` is the tag
    # `control_surface_kind_for_path` actually emits, so the variant exempted the spelling that
    # never occurs and missed the one that does. Composing from the canonical set makes that
    # class of omission impossible while keeping the intent.
    from .kickoff.contract import FIXED_ENDPOINT_KINDS as _FIXED_KINDS_853
    _EXEMPT_KINDS = set(_FIXED_KINDS_853) | {"custom"}
    bad: List[Dict[str, Any]] = []
    for k, v in endpoints.items():
        if k == "_meta" or not isinstance(v, dict):
            continue
        md = v.get("metadata") or {}
        if str(md.get("kind") or "").strip().lower() in _EXEMPT_KINDS:
            continue  # not projector-owned (orchestrator/spine/custom handlers)
        # #251 (r50, live): exemption must not depend on a metadata field the LANE has to
        # remember. r50 was green except for this check, burned both graces and aborted on
        # POST /auth/signup (response_key='signup') and POST /auth/logout — framework-owned
        # AS-router endpoints the projector never touches, which the docstring already says
        # are exempt. Their kind was simply unset, so the metadata-only test flagged them
        # and NO lane could fix it (the handlers are ours). Exempt the control surface BY
        # PATH too — an unwinnable hard gate is the opt-5 lesson we keep re-learning.
        _p = str(v.get("path") or (k.split(" ", 1)[-1] if " " in k else k)).lower()
        if (_p.startswith("/auth/") or _p.startswith("/api/auth/")
                or _p.startswith("/oauth") or _p.startswith("/api/oauth")
                or _p.startswith("/.well-known")):
            continue
        if md.get("custom") or md.get("custom_route"):
            continue  # custom_routes are hand-authored, not projected
        rk = md.get("response_key") or (v.get("schema") or {}).get("response_key")
        if rk is None or rk in _CANONICAL:
            continue
        bad.append({
            "endpoint": k,
            "response_key": rk,
            "reason": (
                f"projected business endpoint declares non-canonical "
                f"response_key={rk!r} — the projector emits {{items/item}}, so the "
                f"frontend reading data.{rk} renders blank. Use 'items' or 'item'."
            ),
        })
    return bad


def extract_spec_tables(spec: Dict[str, Any]) -> Dict[str, set]:
    tables = spec.get("tables", {})
    out: Dict[str, set] = {}
    if isinstance(tables, dict):
        iterable = tables.items()
    elif isinstance(tables, list):
        iterable = ((t.get("name"), t) for t in tables if isinstance(t, dict))
    else:
        iterable = []
    for raw_name, table in iterable:
        name = str(raw_name or "").strip()
        if not name or not isinstance(table, dict):
            continue
        columns = table.get("columns", {})
        if isinstance(columns, dict):
            out[name] = {str(c) for c in columns.keys()}
        elif isinstance(columns, list):
            out[name] = {
                str(c.get("name"))
                for c in columns
                if isinstance(c, dict) and c.get("name")
            }
    return out

# Contract extraction lives in multi_agent/delivery/contract_extract.py. It is
# now STACK-PLUGGABLE (FastAPI + Express auto-detected) — see that module.


def validate_contract_alignment(output_dir, hubs) -> Dict[str, Any]:
    """Run lightweight static checks for design/DB/backend/API drift."""
    errors: List[str] = []
    warnings: List[str] = []

    # Sources of truth: RegistryHub for endpoints, SchemaHub for tables.
    hub_endpoints = hubs.registryhub.get_endpoints() or {}
    hub_tables = hubs.schema_hub.list_tables() or {}
    api_spec = {
        "endpoints": [
            {"method": ep.get("method"), "path": ep.get("path")}
            for ep in hub_endpoints.values()
            if isinstance(ep, dict) and ep.get("status") != "deprecated"
        ],
    }
    db_spec = {"tables": list(hub_tables.values())}

    expected_tables = extract_spec_tables(db_spec)
    sql_tables = _contract.extract_sql_tables(output_dir / "app/database")
    backend_sql_refs = _contract.extract_backend_sql_refs(output_dir / "app/backend")

    from .database_scaffold import _SPINE_OWNED_TABLES
    for table, expected_columns in sorted(expected_tables.items()):
        if str(table).lower() in _SPINE_OWNED_TABLES:
            # tenants/users/oauth_* are owned deterministically by the
            # tenancy spine (database_scaffold), not the contract — skip
            # column alignment so a contract-declared users table (which
            # the spine intentionally replaces) doesn't false-error.
            continue
        if not expected_columns:
            # Hub knows of the table but hasn't registered columns
            # yet (early/minimal state). Skip column-level alignment.
            continue
        actual_columns = sql_tables.get(table)
        if actual_columns is None:
            errors.append(f"SQL schema missing registered table: {table}")
            continue
        missing_columns = sorted(expected_columns - actual_columns)
        if missing_columns:
            errors.append(f"SQL table `{table}` missing registered columns: {', '.join(missing_columns[:8])}")

    for table, referenced_columns in sorted(backend_sql_refs.items()):
        actual_columns = sql_tables.get(table)
        if not actual_columns:
            warnings.append(f"Backend references table `{table}` but SQL schema did not define it.")
            continue
        missing_columns = sorted(referenced_columns - actual_columns)
        if missing_columns:
            errors.append(f"Backend references missing SQL columns on `{table}`: {', '.join(missing_columns[:8])}")

    declared_endpoints = _contract.extract_api_endpoints(api_spec)
    implemented_endpoints = _contract.extract_backend_routes(output_dir / "app/backend")
    # Param-agnostic match so {id}/:id/${id} + stack differences don't false-flag.
    declared_keys = {_contract.param_agnostic(e): e for e in declared_endpoints}
    impl_keys = {_contract.param_agnostic(r) for r in implemented_endpoints}
    if declared_endpoints and implemented_endpoints:
        missing_endpoints = sorted(e for k, e in declared_keys.items() if k not in impl_keys)
        if missing_endpoints:
            warnings.append(
                "Backend route coverage missing declared endpoints: "
                + ", ".join(missing_endpoints[:10])
            )

    # Code-derived consumer gate (P0, contract_enforcement_and_lifecycle_design §A2):
    # every BUSINESS API call in the generated frontend MUST hit a registered
    # endpoint. Phase 3b.6: the auth/oauth surface (oauth_scaffold), the spine
    # tables (database_scaffold) and the tenant/health control plane
    # (control_plane) are now REGISTERED in RegistryHub by _register_contract_surface
    # — so a frontend call to /auth/login or /api/v1/reset matches a real
    # declared endpoint and needs no hardcoded path exemption (consistency-by-
    # construction replaces the old _INFRA prefix list). The only residual
    # exemption is the EXTERNAL central IdP (/idp) used by the google-idp env
    # variant — it is a foreign service, never an endpoint of THIS env.
    frontend_calls = _contract.extract_frontend_calls(output_dir / "app/frontend")
    _EXTERNAL = ("/idp",)
    # Match on PATH (param-agnostic), METHOD-tolerant. A static scan can't
    # reliably tell a fetch's method from a React-Router route path (a `/auth/
    # login` *page* route looks like `GET /auth/login`), so requiring a
    # method-exact match false-flags registered endpoints as "unregistered".
    # The api_smoke gate (authoritative — it boots the app and probes every
    # registered endpoint with its real method) already validated the surface,
    # so here flag only a call whose PATH has NO registered endpoint at all —
    # that is the genuine frontend↔contract drift this gate exists to catch.
    def _pa_path(mp: str) -> str:
        # #494 (netflix r65): STRIP any ?query first. A query param does NOT define a
        # new endpoint — GET /api/titles?kind=movie is the SAME endpoint as GET
        # /api/titles. Without stripping, param_agnostic mangles "titles?kind=movie"
        # into a :p param segment (GET /api/:p), which matches no declared path key →
        # a FALSE "Frontend calls unregistered endpoint" error that hard-blocked r65's
        # delivery (incomplete_required_tasks) even though /api/titles IS registered.
        pa = _contract.param_agnostic(str(mp or "").split("?", 1)[0])
        return pa.split(" ", 1)[1] if " " in pa else pa
    declared_path_keys = {_pa_path(e) for e in declared_endpoints}
    unregistered_calls = []
    for call in sorted(frontend_calls):
        path = call.split(" ", 1)[1] if " " in call else call
        if any(path == pre or path.startswith(pre + "/") for pre in _EXTERNAL):
            continue
        if declared_path_keys and _pa_path(call) not in declared_path_keys:
            unregistered_calls.append(call)
    if unregistered_calls:
        errors.append(
            "Frontend calls unregistered endpoint(s) (register in RegistryHub): "
            + ", ".join(unregistered_calls[:10])
        )

    return {
        "errors": errors[:20],
        "warnings": warnings[:20],
        "expected_tables": len(expected_tables),
        "sql_tables": len(sql_tables),
        "declared_endpoints": len(declared_endpoints),
        "implemented_endpoints": len(implemented_endpoints),
        "frontend_calls": len(frontend_calls),
        "frontend_call_unregistered": len(unregistered_calls),
    }


def validate_build_evidence(output_dir, get_validation_results) -> Dict[str, Any]:
    """Check whether generated projects have recorded build validation."""
    frontend_package = output_dir / "app/frontend/package.json"
    validation_results = get_validation_results(limit=200) or []
    frontend_build_recorded = any(
        isinstance(r, dict)
        and r.get("status") == "passed"
        and (
            r.get("metadata", {}).get("check") == "frontend_build"
            or "npm run build" in str(r.get("summary", "")).lower()
        )
        for r in validation_results
    )
    return {
        "frontend_package": frontend_package.exists(),
        "frontend_build_recorded": frontend_build_recorded,
    }


def convergence_grace(*, failed_count: int, last_shrink_age_s: float,
                      grace_used: int,
                      max_failed: int = 2,
                      recent_s: float = 1800.0,
                      grace_s: float = 900.0,
                      max_grace: int = 2) -> float:
    """#228 — seconds of extra time the no-convergence fail-fast should grant.

    r20 (live): the run converged to ONE failing gate
    (deliverability_ui_flow_missing) and the verifier recorded the flows 36s
    AFTER the 75-min fail-fast fired — a substantively complete app (api_smoke
    green, business_chain green, 15/15 flows green) was aborted on wall-clock.
    When the failing set is SMALL and recently SHRANK (the lanes are visibly
    converging, not livelocking), grant a bounded extension: up to
    ``max_grace`` × ``grace_s``. Returns 0 when not converging — the fail-fast
    keeps its teeth for genuine livelocks (many gates, or no recent shrink)."""
    if grace_used >= max_grace:
        return 0.0
    if failed_count <= 0 or failed_count > max_failed:
        return 0.0
    if last_shrink_age_s > recent_s:
        return 0.0
    return float(grace_s)


def _deliverability_check_token(blocker: str) -> str:
    """Map ONE deliverability blocker (human prose) onto its stable check token.

    Extracted from the validate_delivery_gate fold loop (verbatim mapping) so the
    canonicalization is unit-testable; each token names the failed dimension, the
    full prose stays in ``deliverability_report`` for the operator-facing log."""
    low = str(blocker).lower()
    if "no successful runhub run" in low:
        return "deliverability_no_successful_run"
    if "failed endpoint probe" in low:
        return "deliverability_failed_endpoint_probes"
    if "failed mcp probe" in low:
        return "deliverability_failed_mcp_probes"
    if "dead artifact" in low:
        return "deliverability_dead_artifacts"
    if "authored seed missing" in low:
        # #41: the lane never authored seed_data.json — the app would ship the
        # bland framework fallback (run-33 shipped SUCCESS this way).
        return "deliverability_missing_authored_seed"
    if "authored seed quality" in low:
        # #54: the lane authored seed_data.json but it is a token/placeholder
        # seed (thin rows, marker words, sequential names) — the populated-
        # screen bar needs realistic density. Anchored on the exact prefix
        # deliverability emits; must precede the generic seed branches.
        return "deliverability_authored_seed_quality"
    if "missing seed" in low:
        return "deliverability_missing_seed"
    if "low row count" in low or "placeholder seed" in low:
        return "deliverability_seed_quality"
    if "critical visual review" in low and "pending" in low:
        return "deliverability_critical_visuals_pending"
    if "critical visual review" in low and "need revision" in low:
        return "deliverability_critical_visuals_needs_revision"
    if "critical_flows" in low and "unparseable" in low:
        return "deliverability_critical_flows_invalid"
    if "ui flow(s) failed" in low:
        # Anchor on the FULL prefix emitted by ``_flow_coverage_summary``
        # (``"N critical UI flow(s) failed:"``) so a flow whose NAME contains
        # the substring "missing" (e.g. ``recover_missing_password``) doesn't
        # collide with the missing-branch check. failed FIRST: ``ui flow(s)
        # failed`` doesn't appear in the missing-branch prose; ``missing`` can
        # appear in the failed-branch prose if a flow name has it.
        return "deliverability_ui_flow_failed"
    if "ui flow(s) missing" in low:
        return "deliverability_ui_flow_missing"
    if "declared but unusable" in low:
        # B1: a declared ui_page whose route isn't wired in App.jsx
        # or whose component file is absent (round 44 blank-screen
        # class). Deterministic, NOT relaxed on functionally_validated.
        return "deliverability_ui_page_unwired"
    if "framework fallback page" in low:
        # #223: a route-wired generic fallback the REGISTRY can't see (the
        # code-truth sweep). The registered-page variant carries "declared
        # but unusable" and keeps ui_page_unwired above.
        return "deliverability_frontend_fallback_page"
    if "bare unauthenticated fetch" in low:
        # #154 (§6-1, gmrun4): frontend calls an authed /api/ endpoint with a
        # bare fetch() that never attaches the Authorization token → runtime
        # 401 → empty pages/login wall while api_smoke (framework-minted
        # token) stays green. Deterministic, NOT relaxed on
        # functionally_validated — functional validation is exactly the
        # blind spot.
        return "deliverability_bare_authed_fetch"
    if "placeholder stub" in low:
        # #173 (gmrun9): a GET route handler that does NO DB read and returns a
        # hardcoded empty collection → a permanently-empty page (the departures
        # `return {"items": []}` the lane shipped). Deterministic AST; NOT relaxed
        # on functionally_validated — api_smoke never asserts a non-empty body.
        return "deliverability_placeholder_stub_handler"
    if "fabricated fallback" in low:
        # #175 (gmrun9): the frontend renders `place.rating || '4.5'` /
        # `? place.name : 'HI Point Montara Lighthouse'` → invented data whenever
        # the field is absent (often always, on a field-name drift). Static JSX
        # scan; the no-placeholder/mock bar #170's prompt rule failed to hold.
        return "deliverability_fabricated_field_fallback"
    if "dead control" in low or "resolves to no app.jsx route" in low:
        # #238 (tiktok r27 M1): a nav <Link>/navigate target resolves to no
        # App.jsx route → 404 on click. Owner = frontend (routes + nav both
        # lane-owned). Anchored on the exact prose dead_nav_link_blockers emits.
        return "deliverability_dead_nav_link"
    # Unmapped blocker — surface verbatim under a catch-all so the operator
    # sees it instead of silently dropping; future canonicalization work can
    # move it into a named token.
    return f"deliverability_other:{str(blocker)[:80]}"


def enforce_completeness(output_dir, hubs, tables: Dict[str, Any],
                         failed_checks: List[str], logger) -> List[Dict[str, Any]]:
    """#557 R4-core (user-approved) — CONTRACT-COMPLETENESS: HEAL-THEN-ENFORCE.

    Reconcile the app's DECLARED feature-set (feature_inventory ∪ state-bearing
    tables) against its WORKING surface (declared endpoints) and — when enforcing —
    HARD-BLOCK delivery on a genuinely-incomplete feature, after auto-healing every
    HEALABLE gap FIRST so enforcement can never false-block.

    Every other gate derives from the declared contract, so a MISSING endpoint is
    invisible: business_chain_api_coverage reports "100%" of declared endpoints while
    a needed write-path (the Continue-Watching progress POST) simply doesn't exist and
    the functional gate stays green with the feature broken. This oracle catches that
    class — the readable-but-not-writable STATE entity (severity ``error``).

    ENFORCE is ON by DEFAULT (``ENVGEN_COMPLETENESS_ENFORCE``; set to ``0``/``false``
    for the old reported-only behavior — BYTE-IDENTICAL: no heal runs, the oracle is
    computed + logged but NEVER contributes a failed check). When enforcing:

    1. HEAL-THEN-ENFORCE — the #556 state-write heal (reused verbatim via
       ``heal_pipeline.heal_state_write_endpoints`` → ``route_projector.
       project_state_write_endpoints``; NO duplication) runs BEFORE the oracle is
       consulted. A HEALABLE gap — a state entity whose write the projector CAN back
       from its ORM model — is projected + REGISTERED first, so ``compute_completeness``
       then sees the healed write and does NOT flag it. This fixes the timing bug: the
       #556 heal otherwise runs LATER (orchestrator final-flush / release-snapshot,
       AFTER this gate), so naive enforcement would false-block a gap the heal WOULD
       have closed. Idempotent: the later heal then no-ops (already projected/registered).
    2. ENFORCE — only the error-severity ``completeness_state_entity_no_write`` is
       promoted to ``failed_checks`` (hard-block). A GENUINELY unhealable gap (a state
       entity with a GET but no ORM model the projector can back) survives step 1 and
       correctly blocks — a real functional incompleteness must not ship. Warn-severity
       findings (``completeness_flow_no_write`` / ``completeness_entity_no_read``) are
       ALWAYS advisory and never block.

    Mutates ``failed_checks`` in place (de-duped) and returns the reported results list
    for the gate dict. Best-effort; never raises (a malformed hub degrades to reported-
    only rather than wedging the gate)."""
    completeness_results: List[Dict[str, Any]] = []
    try:
        from .completeness_audit import compute_completeness
        _enforce = os.environ.get(
            "ENVGEN_COMPLETENESS_ENFORCE", "1").lower() in ("1", "true", "yes", "on")
        # (1) HEAL-THEN-ENFORCE: project + register any HEALABLE state-write BEFORE the
        # oracle checks. Guarded on _enforce so ENFORCE=off stays byte-identical (the
        # heal — which writes main.py + registers endpoints — never runs when off).
        if _enforce:
            try:
                from .heal_pipeline import heal_state_write_endpoints
                heal_state_write_endpoints(
                    output_dir / "app" / "backend",
                    getattr(hubs, "registryhub", None),
                    tables=tables, logger=logger)
            except Exception as _heal_err:
                if logger is not None:
                    try:
                        logger.warning(
                            "heal-then-enforce state-write heal raised inside delivery "
                            "gate (enforcement proceeds on current state): %s", _heal_err)
                    except Exception:
                        pass
        completeness_report = compute_completeness(hubs)
        completeness_results = completeness_report.to_dict().get("results", [])
        if completeness_results and logger:
            try:
                logger.warning(
                    "completeness oracle (#557, %s) flagged %d gap(s): %s",
                    "ENFORCED" if _enforce else "reported/not-blocking",
                    len(completeness_results),
                    ", ".join(
                        f"{r.get('check_id')}[{r.get('severity')}]:"
                        f"{r.get('entity') or r.get('flow')}"
                        for r in completeness_results[:8]
                    ),
                )
            except Exception:
                pass
        # (2) ENFORCE — only error-severity results block (state_entity_no_write). Warn
        # findings (flow_no_write / entity_no_read) stay advisory: blocking_check_ids
        # is queried with severity="error" so a warn can never enter failed_checks.
        if _enforce:
            for cid in completeness_report.blocking_check_ids("error"):
                if cid not in failed_checks:
                    failed_checks.append(cid)
    except Exception as _completeness_err:
        if logger is not None:
            try:
                logger.warning(
                    "completeness_audit raised inside delivery gate: %s",
                    _completeness_err)
            except Exception:
                pass
    return completeness_results


def validate_delivery_gate(output_dir, hubs, session_start_ts, logger, *,
                           scaffold_design_readme, get_validation_results,
                           get_validation_summary,
                           milestone_scope: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Validate objective delivery readiness.

    Gate design:
    1) Required artifacts must exist (compose + README).
    2) Generated code footprint must exist for backend/frontend/database.
    3) RegistryHub / SchemaHub / WorkHub must contain registered contract entries.
    4) Contract alignment: registered endpoints/tables match implemented code.
    5) If build checklist has recorded results, it must be ready_for_delivery.
    """
    # Guarantee the required design doc exists before checking (also scaffolded
    # each heal tick; this covers the resumed-complete checkpoint path).
    scaffold_design_readme()
    required_files = [
        "docker/docker-compose.yml",
        "design/README.md",
    ]
    required_dirs = [
        "app/backend",
        "app/frontend",
        "app/database",
    ]

    missing_files: List[str] = []
    invalid_json: List[str] = []
    missing_dirs: List[str] = []
    failed_checks: List[str] = []

    for rel in required_files:
        p = output_dir / rel
        if not p.exists():
            missing_files.append(rel)

    for rel in required_dirs:
        p = output_dir / rel
        if not p.exists() or not p.is_dir():
            missing_dirs.append(rel)

    # Basic code footprint checks
    backend_has_code = any((output_dir / "app/backend").glob("**/*.*"))
    frontend_has_code = any((output_dir / "app/frontend").glob("**/*.*"))
    database_has_sql = any((output_dir / "app/database").glob("**/*.sql"))
    if not backend_has_code:
        failed_checks.append("backend_code_missing")
    if not frontend_has_code:
        failed_checks.append("frontend_code_missing")
    if not database_has_sql:
        failed_checks.append("database_sql_missing")

    # A deterministically functionally-validated app — a successful in-session
    # RunHub run (the framework's api_smoke: clean docker boot that BUILT the
    # frontend+backend, then probed every endpoint) — has already PROVEN both
    # contract alignment and the frontend build at runtime. So the static
    # contract-alignment check and the frontend_build RECORD (verifier
    # bookkeeping the LLM drifts on) become warnings, not hard delivery
    # blockers. They still block when the app is NOT functionally validated.
    _session_ts = session_start_ts or 0.0
    _runhub = getattr(hubs, "runhub", None)
    functionally_validated = bool(
        _runhub is not None
        and hasattr(_runhub, "last_successful_run_since")
        and _runhub.last_successful_run_since(_session_ts)
    )

    contract_report = validate_contract_alignment(output_dir, hubs)
    if contract_report.get("errors") and not functionally_validated:
        failed_checks.append("contract_alignment_failed")

    build_report = validate_build_evidence(output_dir, get_validation_results)
    if (build_report.get("frontend_package")
            and not build_report.get("frontend_build_recorded")
            and not functionally_validated):
        failed_checks.append("frontend_build_not_recorded")

    # hub topology checks
    endpoints = hubs.registryhub.get_endpoints() or {}
    tables = hubs.schema_hub.list_tables() or {}
    pages = hubs.registryhub.list_ui_pages() or {}
    projection_errors = {}  # file-coordination CRDT removed in Cutover 4 (replaced by git worktree)
    semantic_drift = {"errors": [], "warnings": []}  # vestigial — specs no longer exist as independent source.

    if not endpoints:
        failed_checks.append("no_endpoints_in_hub")
    if not tables:
        failed_checks.append("no_tables_in_hub")
    if not pages:
        failed_checks.append("no_pages_in_hub")
    if semantic_drift.get("errors"):
        failed_checks.append("semantic_hub_drift")
    if projection_errors:
        failed_checks.append("semantic_projection_errors")

    implemented_endpoints = sum(
        1 for v in endpoints.values()
        if isinstance(v, dict) and v.get("status") in {"implemented", "tested"}
    )
    implemented_tables = sum(
        1 for v in tables.values()
        if isinstance(v, dict) and v.get("status") in {"implemented", "tested"}
    )
    if implemented_endpoints == 0:
        failed_checks.append("no_implemented_endpoints")
    if implemented_tables == 0:
        failed_checks.append("no_implemented_tables")

    # Build verification checklist from CodeHub.checks directly (hubs.get_verification_checklist removed)
    by_component: dict = {}   # #585: bound BEFORE the try so the diagnostic below survives a fault
    try:
        build_checks = [
            c for c in hubs.codehub.list_checks()
            if c.get("name", "").startswith("build:")
        ]
        by_component: dict = {}
        # #566q (netflix r124/r126 verification_checklist wedge): keep the latest check DICT per
        # component, NOT the status string. list_checks() (no pr_id) returns build:* across ALL PRs
        # (one per milestone), so a component gets >1 record; the old code stored the STATUS STRING
        # then called prev.get("updated_at") on it → AttributeError on the 2nd record → swallowed by
        # the outer except → ready_for_delivery=False FOREVER → verification_checklist_not_ready
        # wedged M1 despite every build:* being success (stuck 35-55min).
        for c in build_checks:
            comp = c.get("name", "").removeprefix("build:")
            prev = by_component.get(comp)
            if prev is None or c.get("updated_at", 0) > prev.get("updated_at", 0):
                by_component[comp] = c

        def _st(_comp):
            return (by_component.get(_comp) or {}).get("status", "pending")
        checklist_statuses_map = {
            "sql_syntax": _st("database"),
            "docker_build": _st("docker"),
            "npm_install": _st("frontend"),
            "backend_start": _st("backend"),
        }
        all_passing = all(s == "success" for s in checklist_statuses_map.values())
        checklist = {
            "checklist": {k: {"status": v} for k, v in checklist_statuses_map.items()},
            "all_required_passing": all_passing,
            "ready_for_delivery": all_passing,
        }
    except Exception as _cl_exc:
        # #585: never swallow this silently. The computation above has been patched four
        # times (#120, #492, #511, #566q) for the same symptom — the checklist blocking a
        # run whose build:* checks are all success — and each investigation had to start
        # from zero because the gate never said what it saw.
        checklist = {"checklist": {}, "all_required_passing": False, "ready_for_delivery": False}
        try:
            logger.warning("verification checklist computation FAILED (%s: %s) — treating as "
                           "not-ready; this is the swallow that hid #566q",
                           type(_cl_exc).__name__, str(_cl_exc)[:160])
        except Exception:
            pass
    checklist_items = checklist.get("checklist", {})
    statuses = [
        item.get("status", "pending")
        for item in checklist_items.values()
        if isinstance(item, dict)
    ]
    any_recorded = any(s != "pending" for s in statuses)
    if any_recorded and not checklist.get("ready_for_delivery", False):
        failed_checks.append("verification_checklist_not_ready")
        # #585: say WHICH component is not success, and when it was last written. Measured
        # across the arc: of the runs whose last decline carried this blocker, r107 and r130
        # were blocked at a moment when all four build:* records on disk were `success` with
        # timestamps ~1 min EARLIER — so the gate saw something the artifacts do not explain.
        # Without this line the next investigation starts from zero again, exactly as the
        # previous four did.
        try:
            _seen = {k: (v or {}).get("status") for k, v in checklist_items.items()
                     if isinstance(v, dict)}
            _when = {c: (r or {}).get("updated_at")
                     for c, r in (by_component or {}).items()}
            logger.warning("verification_checklist_not_ready — observed %s | build:* "
                           "updated_at %s", _seen, _when)
        except Exception:
            pass

    # Runtime validation matrix (if task suite exists):
    # require at least one API smoke pass and one UI smoke pass.
    task_suite_exists = (output_dir / "tasks" / "tasks.yaml").exists()
    validation_summary = get_validation_summary() or {}
    validation_results = get_validation_results(limit=200) or []
    retry_pending_count = int(validation_summary.get("retry_pending_count", 0) or 0)
    api_smoke_pass = any(
        isinstance(r, dict)
        and r.get("status") == "passed"
        and r.get("metadata", {}).get("check") in {"api_smoke", "api_health"}
        for r in validation_results
    )
    ui_smoke_pass = _ui_smoke_pass(validation_results)
    # #739: make the thinness audible. The verdict is unchanged — this only says what it rests
    # on, because "ui_smoke_pass=True" alongside failing UI records reads as app-wide UI health
    # and in r148 meant two unauthenticated pages out of fourteen.
    _breadth739 = _ui_evidence_breadth_739(validation_results)
    # #752 (user-approved) — CONTRADICTED UI EVIDENCE BLOCKS; MISSING UI EVIDENCE DOES NOT.
    #
    # #739 showed `ui_smoke_pass` is existential: one passing record satisfies the whole UI
    # requirement and a FAILING one is never consulted. r148 read True off "ui_smoke on landing
    # + login PASS" while the SPA crashed on 12 of 14 pages, and item 58 concluded that merely
    # switching #671's matrix on would not have caught it — landing and login passed either way.
    #
    # Item 58 asked for both halves. Measuring them separately is what makes this safe to turn
    # on, and they are nothing alike:
    #     passing AND failing UI records (contradicted)    6 of 148 runs   -> 4%, a gate
    #     no UI evidence at all (missing)                 67 of 148 runs   -> 45%, a halt
    # So the contradiction blocks, unconditionally and regardless of `task_suite_exists`,
    # because it needs no matrix to interpret: the app itself said both things. The MISSING
    # case stays exactly where #671 left it, behind `tasks/tasks.yaml` — blocking 45% of runs
    # for absent evidence is a stop, not a quality bar, and #671 already recorded that
    # enforcing it needs a live run.
    if _breadth739["failed_records"]:
        failed_checks.append("validation_ui_evidence_failed")
    if ui_smoke_pass and _breadth739["failed_records"]:
        logger.warning(
            "#739 ui_smoke_pass=True rests on %d passing UI record(s) while %d FAILED: passed "
            "%s / failed %s. The check is existential (#287) and never consults a failing "
            "record, so one working page certifies the whole UI. r148 read True off landing + "
            "login while the SPA crashed on 12 of 14 pages and released v1.0.0. Reported, not "
            "enforced — the matrix that would consume it is itself skipped (#671).",
            _breadth739["passed_records"], _breadth739["failed_records"],
            ", ".join(_breadth739["pages_passed"][:6]) or "-",
            ", ".join(_breadth739["pages_failed"][:6]) or "-")
    failed_validation_top = [
        {
            "task_id": r.get("task_id"),
            "status": r.get("status"),
            "summary": r.get("summary", ""),
            "domain_hint": (
                (r.get("metadata", {}) or {}).get("domain")
                or (r.get("evidence", {}) or {}).get("domain")
                or "any"
            ),
            "execution_mode": r.get("execution_mode", "auto"),
        }
        for r in validation_results
        if isinstance(r, dict) and r.get("status") in {"failed", "error"}
    ][:5]
    # #671: SAY SO WHEN THE MATRIX IS SKIPPED. `tasks/tasks.yaml` has NEVER existed —
    # 0 of 144 runs have it, `tasks.yaml` appears nowhere in any run tree, and the gate logged
    # `task_suite=False` 41 times and `task_suite=True` never. So the runtime validation matrix
    # below (require at least one API smoke pass and one UI smoke pass before delivery) has not
    # run once, and the report gave no sign of it: `task_suite_exists: False` sits in the
    # payload as a fact, not as a caveat on the verdict.
    #
    # The evidence those checks want IS present in most runs — read through
    # `get_validation_results`' normalisation (#193/#236: 'success' -> 'passed', evidence.check
    # lifted into metadata.check), api_smoke passes in 90 of 144 and ui_smoke in 116 of 144.
    # So 54 runs delivered with no API smoke pass and 28 with no UI smoke pass, and the gate
    # never asked. (Measuring the raw codehub_checks store instead of going through that
    # normalisation says 0 of 144 for both — an artifact of skipping the normaliser, not a
    # finding.)
    #
    # ENFORCING them is a real gate-tightening that needs a live run to validate, so it is
    # recorded in EXPERIMENTS_PENDING rather than switched on blind. What is safe now is to
    # stop the skip being silent: an unchecked matrix must not read like a passed one.
    matrix_skipped_reason = "" if task_suite_exists else (
        "no tasks/tasks.yaml — the API-smoke and UI-smoke requirements were NOT evaluated; "
        "api_smoke_pass/ui_smoke_pass below are REPORTED, not enforced")
    if task_suite_exists:
        if retry_pending_count > 0:
            # Soft-fail: auto-retry loop is still in progress.
            failed_checks.append("validation_retry_pending")
        else:
            if not api_smoke_pass:
                failed_checks.append("validation_api_smoke_missing")
            if not ui_smoke_pass:
                failed_checks.append("validation_ui_smoke_missing")

    # PR 6 review (2026-05-30) follow-up: fold the
    # deliverability aggregator into the autonomous hard gate.
    # ``compute_deliverability`` was previously only consumed by
    # the UI-driven deliver path (``deliver_project_call`` in
    # live_monitor_server). The autonomous / LLM-driven deliver
    # path enforced retro (via ``RetroBeforeDeliverPolicy``) and
    # the topology/build checks above, but NOT visual-critical
    # approval, seed data, RunHub-successful-run-since-session,
    # or coverage dead-artifact detection. The original in-tool
    # gates in ``DeliverProjectTool.execute`` intended to enforce
    # those four — but were dead-wired (``self.agent.hub_registry``
    # vs the real ``self.agent._hubs``); the 2026-05-30 cleanup
    # commit deleted them. Folding here closes the
    # autonomous-vs-UI enforcement asymmetry by reusing the SAME
    # aggregator both paths now share. Single enforcement point,
    # consistent with the architectural pattern from the
    # two-pass dispatcher and GateRegistry extraction.
    deliverability_failed_checks: List[str] = []
    try:
        from .deliverability import compute_deliverability
        session_start_ts = session_start_ts or 0.0
        app_root = output_dir / "app"
        if not app_root.exists():
            app_root = output_dir
        deliverability_report = compute_deliverability(
            hubs, app_root, session_start_ts=session_start_ts,
        )
        for blocker in (deliverability_report.blockers or []):
            # Canonicalize: blocker strings are human prose; map
            # them onto stable check tokens the test surface
            # can assert against (extracted to
            # ``_deliverability_check_token`` — unit-testable).
            deliverability_failed_checks.append(_deliverability_check_token(blocker))
    except Exception as deliv_err:
        # Defense in depth: a malformed aggregator call must
        # never crash the gate. Surface the exception as its
        # own failure so the gap stays visible.
        try:
            logger.warning(
                f"compute_deliverability raised inside delivery gate: {deliv_err}"
            )
        except Exception:
            pass
        deliverability_failed_checks.append("deliverability_compute_failed")
        deliverability_report = None

    failed_checks.extend(deliverability_failed_checks)

    # GATE-C2/C3 (2026-06-12): task-completeness HARD check. The gate above
    # proves "evidence exists"; this proves "the assigned structural work is
    # DONE". Coverage-aware (see _incomplete_required_tasks) so it never
    # blocks a run_validation-covered endpoint whose per-endpoint task was
    # left open. NOT relaxed by functionally_validated — an un-evidenced
    # implement_*/validate task is genuine incomplete work, not bookkeeping.
    # #743: the structural gate excludes bug tasks as "governed by their own gates"; no gate
    # consumes them. Say what is open at the cut. Reports, decides nothing.
    # #774: the spec named an owner column the contract does not carry. Reported, not enforced —
    # 8 of 111 corpus runs, every one `profile_id` on the per-profile private tables, which is
    # the single privacy rule those specs state. Whether it should BLOCK is a decision of the
    # same class as #750/#751/#752 and is recorded rather than taken here.
    try:
        _lost774 = _spec_owner_columns_lost_774(hubs)
        if _lost774:
            logger.warning(
                "#774 the SPEC names an owner column this contract does not carry: %s. The DDL, "
                "the contract and the handlers can all agree with each other and still not "
                "implement the requirement — r150 shipped my_list/ratings/continue_watching on "
                "user_id while its spec said profile_id, so every profile on an account shared "
                "them. Reported, not enforced.",
                "; ".join(f"{x['table']}.{x['column']} (has: {x['has'] or 'no *_id'})"
                          for x in _lost774[:6]))
    except Exception:
        pass
    try:
        _unreach823 = _imageless_spec_screens_unreachable_823(output_dir)
        if _unreach823:
            _say_once_845("823", logger,
                "#823 the SPEC declares %d screen(s) with no reference image AND no way to reach "
                "them in the app: %s. The visual gate cannot cover an imageless screen (#822: "
                "`profiles` in 150 of 150 runs) and nothing else compares the spec to the built "
                "UI (#788), so a missing one ships unnoticed — 22 of 142 corpus runs (15%%) had "
                "no reachable profiles screen. Reported, not enforced.",
                len(_unreach823), "; ".join(_unreach823))
    except Exception:
        pass
    try:
        _noasset842 = _unstaged_asset_classes_842(output_dir)
        if _noasset842:
            _say_once_845("842", logger,
                "#842 the SPEC asks for asset class(es) design-prep never staged: %s. The lane has "
                "nothing to point at, so it substitutes whatever is nearest (#841: a crop of a "
                "flyout panel used as an avatar_url) and the judge correctly reports a blank "
                "square — on every authenticated screen when the asset is in the shared nav. "
                "Reported, not enforced.", "; ".join(_noasset842))
    except Exception:
        pass
    try:
        _nokind844 = _unseeded_entity_kinds_844(output_dir)
        if _nokind844:
            _say_once_845("844", logger,
                "#844 a screen's SUBJECT is not in the staged data: %s. The page can only render "
                "the wrong entity (#840: the games hero shows a film), and the lane cannot fix it "
                "-- rows it authors in seed_data.json are replaced wholesale by the dataset "
                "(#807). Reported, not enforced.", "; ".join(_nokind844))
    except Exception:
        pass
    _bugs743 = unresolved_bug_tasks_743(hubs)
    if logger and _bugs743.get("failed_count"):
        logger.warning(
            "#743 %d task(s) are in status FAILED at the delivery cut and nothing reads them: "
            "%s. `fail_task` is authorised and requires a reason, so this is a deliberate "
            "'attempted and did not work' — unlike pending. 20 of 148 corpus runs end with one "
            "and 4 of those 20 released (#755: my first count said all 20, inflated by a "
            "bootstrap doc read as a release tag). Reported, not enforced.",
            _bugs743["failed_count"],
            "; ".join(f"[{f.get('severity') or '-'}] {f.get('title')}"
                      f"{' — ' + f['reason'] if f.get('reason') else ''}"
                      for f in _bugs743.get("failed", [])[:4]))
    if logger and _bugs743.get("open_p0_bug_count"):
        logger.warning(
            "#743 %d P0 BUG task(s) are still open at the delivery cut: %s. Corpus: 90 of 129 "
            "runs end this way and 15 of them released (#755-corrected; 86 runs, not 90), so "
            "this is reported rather than blocking — 15 of the 29 real releases is a halt.",
            _bugs743["open_p0_bug_count"],
            "; ".join(str(b.get("title")) for b in _bugs743.get("open_p0_bugs", [])[:4]))
    # #751 (user-approved) — A TASK EXPLICITLY MARKED FAILED BLOCKS THE CUT.
    #
    # #743 measured both candidates and only this one is a gate rather than a halt:
    #     any open P0 BUG      90 of 129 runs would block   -> a halt
    #     any FAILED task      20 of 148 runs would block   -> 13%
    # and all 20 of those released. `failed` is not "nobody got to it" — `fail_task` is
    # authorised (creator, claimer or orchestrator only) and REQUIRES a reason, so the status
    # is a deliberate "this was attempted and did not work", carrying things like "Frontend
    # Dockerfile uses registry-blocked base images" and "Record the missing critical UI flow
    # validations (blocks delivery)".
    #
    # The open-P0 half stays REPORTED, exactly as #743 left it: blocking 70% of runs is not a
    # quality bar, it is a stop, and task hygiene is why (r148's open P0s included eleven stale
    # `Fix breaking change in GET /api/...` left in_progress).
    #
    # Clearing it is cheap and in the lane's hands: complete the task, or cancel it if it was
    # wrong. That is the same escape any structural blocker already has.
    if _bugs743.get("failed_count"):
        failed_checks.append("unresolved_failed_tasks")
    # #795 (2026-08-16): BOTH figures above are corpus-wide and BOTH understate recent builds.
    # Re-measured by build era with the SHIPPED normaliser (#193/#236 flatten) rather than a
    # hand-written re-implementation (#772), with a non-vacuity check (89 of 151 runs carry any
    # UI record at all):
    #
    #     slice     runs   #751 failed-task   #752 contradicted UI
    #     ALL        151        13%                  6%
    #     r130+       22        18%                 13%
    #     r145+        7        28%                 28%
    #
    # #752 was approved on "4%, a gate"; on the r130+ slice it is 13%. Neither reaches the
    # rates that disqualified the rejected candidates (#743's 70%, #671's 45%), so the calls
    # stand -- but the margin is smaller than the numbers they were made on. The r145+
    # denominator is 7, too small to read a rate off alone. #794 is why this was re-run: a
    # corpus-wide figure can describe a defect that no longer occurs -- and here the opposite
    # was true, which is exactly why it has to be measured rather than assumed either way.

    incomplete_tasks = incomplete_required_tasks(hubs)
    # §4: when a milestone slice is provided (intermediate milestone), defer structural tasks
    # for a clearly out-of-slice endpoint — an intermediate milestone is gated on ITS OWN
    # surface, not the whole app. Empty/None scope ⇒ no filtering (full-app, byte-identical).
    if milestone_scope:
        _before = len(incomplete_tasks)
        incomplete_tasks = scope_filter_incomplete(
            incomplete_tasks, (milestone_scope or {}).get("endpoint_paths"))
        if logger and len(incomplete_tasks) != _before:
            logger.warning("milestone-scoped delivery gate: deferred %d out-of-slice structural task(s)",
                           _before - len(incomplete_tasks))
    if incomplete_tasks:
        failed_checks.append("incomplete_required_tasks")

    # PROMPT-C1 (2026-06-12): response_key by-construction. A projected
    # business endpoint whose declared response_key isn't the canonical
    # items/item envelope the projector emits is a latent blank page —
    # catch it at the gate instead of at the user's screen.
    noncanonical_response_keys = noncanonical_business_response_keys(hubs)
    if noncanonical_response_keys:
        failed_checks.append("business_response_key_noncanonical")

    # DELIVERY-QUALITY (user 2026-06-24): what ships must be verified by a REAL,
    # PASSING, verifier-authored business-flow chain covering every critical flow
    # — not just shallow api_smoke, and never the synthesized default. The verifier
    # MUST author it; a miss blocks delivery and routes back (dispatch_gate_level_checks).
    business_chain_block = business_chain_blockers(hubs)
    if business_chain_block:
        failed_checks.append(business_chain_block["reason"])

    # #557 R4-core (user-approved) CONTRACT-COMPLETENESS — HEAL-THEN-ENFORCE.
    # Reconcile the app's DECLARED feature-set (feature_inventory ∪ state-bearing
    # tables) against its WORKING surface (declared endpoints). Every other gate
    # derives from the declared contract, so a MISSING endpoint is invisible:
    # business_chain_api_coverage reports "100%" of declared endpoints while a needed
    # write-path (the Continue-Watching progress POST) simply doesn't exist and the
    # functional gate stays green with the feature broken. This oracle catches that
    # class and, with ENFORCE on (now the DEFAULT), HARD-BLOCKS delivery on a
    # genuinely-incomplete feature — after auto-HEALING every healable gap FIRST (the
    # #556 state-write projection) so enforcement can never false-block. Set
    # ENVGEN_COMPLETENESS_ENFORCE=0/false for the old reported-only behavior
    # (byte-identical). See enforce_completeness for the full contract.
    completeness_results = enforce_completeness(
        output_dir, hubs, tables, failed_checks, logger)

    ok = not (missing_files or missing_dirs or invalid_json or failed_checks)
    soft_fail_only = (
        bool(failed_checks)
        and set(failed_checks).issubset({"validation_retry_pending"})
        and not (missing_files or missing_dirs or invalid_json)
    )
    gate_state = "ok" if ok else ("waiting_for_retry" if soft_fail_only else "failed")
    return {
        "ok": ok,
        "state": gate_state,
        "soft_fail_only": soft_fail_only,
        "missing_files": missing_files,
        "missing_dirs": missing_dirs,
        "invalid_json": invalid_json,
        "failed_checks": failed_checks,
        # #790: checks that could not RUN. Not a failure (the permissive default stands so a
        # hub hiccup cannot wedge every release) and NOT evidence of a pass either — a
        # release cut with this non-empty is unverified on those axes. Travels with the
        # verdict rather than living only in a log line nobody reads at the cut.
        "checks_errored_790": check_errors_790(),
        "incomplete_required_tasks": incomplete_tasks,
        "unresolved_bugs": _bugs743,     # #743: reported, never enforced
        "noncanonical_response_keys": noncanonical_response_keys,
        "business_chain": business_chain_block,
        "completeness": completeness_results,  # #557 reported (not-yet-blocking)
        "hub_counts": {
            "endpoints": len(endpoints),
            "tables": len(tables),
            "pages": len(pages),
            "implemented_endpoints": implemented_endpoints,
            "implemented_tables": implemented_tables,
        },
        "verification": checklist,
        "contract_alignment": contract_report,
        "semantic_hub_drift": semantic_drift,
        "projection_errors": projection_errors,
        "build_evidence": build_report,
        "deliverability": (
            deliverability_report.to_dict()
            if deliverability_report is not None else None
        ),
        "validation_runtime": {
            "task_suite_exists": task_suite_exists,
            "matrix_skipped_reason": matrix_skipped_reason,     # #671
            "total_results": validation_summary.get("total", 0),
            "all_passed": validation_summary.get("all_passed", False),
            "api_smoke_pass": api_smoke_pass,
            "ui_smoke_pass": ui_smoke_pass,
            # #739: ui_smoke_pass is EXISTENTIAL and never consults a failing record. r148 read
            # True off landing+login while 12 of 14 pages crashed. Reported, not enforced.
            "ui_evidence_breadth": _ui_evidence_breadth_739(validation_results),
            "retries_used_total": validation_summary.get("retries_used_total", 0),
            "retry_pending_count": validation_summary.get("retry_pending_count", 0),
            "retry_exhausted_count": validation_summary.get("retry_exhausted_count", 0),
            "failed_top": failed_validation_top,
        },
    }


__all__ = ["format_delivery_gate_report", "delivery_gate_suggestions",
           "incomplete_required_tasks", "noncanonical_business_response_keys",
           "business_chain_blockers", "enforce_completeness",
           "extract_spec_tables", "validate_contract_alignment", "validate_build_evidence",
           "validate_delivery_gate"]
