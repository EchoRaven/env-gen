r"""#1203ja: the release the user actually boots was the one release nobody walked.

``create_release`` has exactly TWO call sites. ``_maybe_framework_deliver`` surrounds its
cut with the #1202nm blocking pre-release test-user gate, #155's
``ensure_fresh_smoke_before_cut``, and the post-release test-user safety net. The other
site — the post-loop FINAL cut in ``run`` — cuts the run's HIGHEST tag and had none of
them.

Measured over every run on this machine with a stdout log and at least one release (60):
8 took the final path ("FINAL DELIVERY: gate clear") and all 8 ship a final tag with no
``test_user_reports/<tag>.json``; of the 50 that did not, all 50 have one. The 8 include
tiktok-web r173, r177, r184 and r185 — the four best runs here, each recorded as a full
delivery. r185: 3 of 3 milestones delivered, gate clear, 1.0.0 and 1.1.0 walked, and
1.2.0 — what ships — never walked.

★ THIRD TIME AT THIS PAIR OF SITES. #706 hooked main-promotion at the other site only
(#706b fixed it here); #1203hy's status refusal had the same asymmetry (#1203ig). #706b
records WHY unit tests missed it: "the unit tests asserted the hook is present and
correct, and it was, at the site the run did not use." So the load-bearing test in this
module is not the one that checks #1203ja's own block — it is
`test_both_release_sites_run_the_test_user_walk`, which asks the question PER SITE so a
fourth miss reddens a test instead of waiting for a live run to expose it.
"""
import ast
import os

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ORCH = os.path.join(_AGENT, "env_generator", "llm_generator", "multi_agent",
                     "orchestrator.py")


def _tree():
    with open(_ORCH, encoding="utf-8") as fh:
        return ast.parse(fh.read())


def _functions():
    return {n.name: n for n in ast.walk(_tree())
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _release_sites():
    """Every function containing a `create_release(...)` call, by name."""
    out = {}
    for name, fn in _functions().items():
        for sub in ast.walk(fn):
            if isinstance(sub, ast.Call) and getattr(sub.func, "attr", "") == "create_release":
                out[name] = fn
                break
    return out


def _referenced(fn):
    """Every attribute/name/imported symbol reachable inside `fn`.

    ★ Collects BOTH halves of `import x as y`: #706b reaches its hook through
    `promote_integration_to_main as _promote_706b`, so a predicate that kept only the
    alias reported the hook MISSING at a site that has it — a ratchet that reddens for a
    hook which is present is worse than no ratchet.
    """
    seen = set()
    for sub in ast.walk(fn):
        if isinstance(sub, ast.Attribute):
            seen.add(sub.attr)
        elif isinstance(sub, ast.Name):
            seen.add(sub.id)
        elif isinstance(sub, (ast.Import, ast.ImportFrom)):
            for a in sub.names:
                seen.add(a.name)
                if a.asname:
                    seen.add(a.asname)
    return seen


def test_there_are_still_exactly_two_release_sites():
    """The ratchet below asks its question per site; a third site would slip past it."""
    sites = _release_sites()
    assert set(sites) == {"_maybe_framework_deliver", "run"}, (
        "the set of functions that cut a release changed to %s — re-read this module: "
        "every new site needs the post-cut hooks checked below" % sorted(sites))


def test_both_release_sites_run_the_test_user_walk():
    """★ THE TICKET. Asked per site, which is the only form that catches a #706-shaped
    miss: the walk must be reachable from EVERY function that cuts a release."""
    missing = [name for name, fn in _release_sites().items()
               if "_run_test_user_validation" not in _referenced(fn)]
    assert not missing, (
        "%s cuts a release without ever running the test-user walk — the tag it ships is "
        "unwalked, which is #1203ja (r173/r177/r184/r185 all shipped that way)" % missing)


def test_both_release_sites_promote_integration_to_main():
    """#706/#706b, the first instance of this asymmetry, asked the same way. Guards the
    predicate as much as the code: if this ever reads False, `_referenced` dropped the
    aliased import again."""
    missing = [name for name, fn in _release_sites().items()
               if "promote_integration_to_main" not in _referenced(fn)]
    assert not missing, "%s cuts a release without promoting integration -> main" % missing


def _class_methods():
    """Every method of the orchestrator class, by name."""
    out = {}
    for n in ast.walk(_tree()):
        if isinstance(n, ast.ClassDef):
            for st in n.body:
                if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out[st.name] = st
    return out


def _reachable(fn, depth=1):
    """`_referenced`, following `self.<method>` calls `depth` levels — but never into
    another release site.

    #1203jd put the pre-cut fresh smoke behind `self._final_fresh_smoke_ok_1203jd` rather
    than inline, so a direct-reference check would read the guard as ABSENT at a site that
    reaches it. One level of expansion asks the property instead of asking where the call
    happens to be written.

    ★ THE EXCLUSION IS THE WHOLE TEST. `run` calls `_maybe_framework_deliver`, so a plain
    one-level expansion pulled in that site's symbols and the check passed for `run` no
    matter what `run` itself did — the mutation that deletes the final cut's guard call
    stayed GREEN until this exclusion went in. "Site A has a guard because it calls site
    B" is not what is being asked: each site must reach it on its own.
    """
    seen = set(_referenced(fn))
    if depth <= 0:
        return seen
    methods = _class_methods()
    others = {name for name, f in _release_sites().items() if f is not fn}
    for sub in ast.walk(fn):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
            if sub.func.attr in others:
                continue
            tgt = methods.get(sub.func.attr)
            if tgt is not None and tgt is not fn:
                seen |= _reachable(tgt, depth - 1)
    return seen


def test_both_release_sites_reach_the_pre_cut_fresh_smoke():
    """#155/#1203jd, the third concern asked per site. gmrun3's broken middleware landed
    2min before a cut and shipped unvalidated; the final cut had no such guard, and for
    r185/r184/r177/r173 real lane work merged inside the 1-6 minute window between the
    last clean smoke and the cut."""
    missing = [name for name, fn in _release_sites().items()
               if "ensure_fresh_smoke_before_cut" not in _reachable(fn)]
    assert not missing, (
        "%s cuts a release without any pre-cut fresh api_smoke — the tag can ship lane "
        "code no smoke ever validated (#1203jd)" % missing)


def _final_walk_dispatch():
    """The `to_thread(self._run_test_user_validation, ...)` call inside `run`."""
    run = _functions()["run"]
    for sub in ast.walk(run):
        if not isinstance(sub, ast.Call):
            continue
        if getattr(sub.func, "attr", "") != "to_thread":
            continue
        if any(isinstance(a, ast.Attribute) and a.attr == "_run_test_user_validation"
               for a in sub.args):
            return run, sub
    raise AssertionError("the final-release walk dispatch is gone from `run`")


def test_the_final_walk_is_skipped_when_a_report_already_exists():
    """★ WITHOUT THIS THE PATCH IS A REGRESSION: tiktok-web-r108 took the final path and
    HAS its final report, because the deferring pass's #1202nm PRE-RELEASE walk wrote it.
    Re-walking would overwrite a gate-relevant record with a post-shutdown one, so the
    dispatch must sit under a condition, and that condition must be the report check."""
    run, call = _final_walk_dispatch()
    guards = []
    for node in ast.walk(run):
        if not isinstance(node, ast.If):
            continue
        if any(c is call for c in ast.walk(node)) and not any(
                c is call for c in ast.walk(node.test)):
            guards.append(node)
    assert guards, "the final-release walk is dispatched unconditionally"
    tests = [ast.dump(g.test) for g in guards]
    assert any("_walked_1203ja" in t for t in tests), (
        "the walk is guarded, but not by the #1203ja report check: %s" % tests)
    # and the guard must be a NEGATIVE one — `if _walked_1203ja:` would invert the rule
    assert any("_walked_1203ja" in t and "Not" in t for t in tests), (
        "the guard runs the walk when the report ALREADY exists: %s" % tests)


def test_an_unreadable_report_path_does_not_rewalk():
    """Fail CLOSED. If the report path cannot be read we do not know whether the
    pre-release walk already produced one, and overwriting it is the harm — so the
    handler must assume walked, not unwalked."""
    run = _functions()["run"]
    handlers = [h for h in ast.walk(run) if isinstance(h, ast.ExceptHandler)
                and any(isinstance(s, ast.Assign)
                        and getattr(s.targets[0], "id", "") == "_walked_1203ja"
                        for s in ast.walk(h))]
    assert handlers, "nothing sets `_walked_1203ja` on the failure path"
    vals = []
    for h in handlers:
        for s in ast.walk(h):
            if isinstance(s, ast.Assign) and getattr(s.targets[0], "id", "") == "_walked_1203ja":
                vals.append(getattr(s.value, "value", None))
    assert vals and all(v is True for v in vals), (
        "the unreadable case assumes NOT walked (%s) and would overwrite an existing "
        "report" % vals)


def test_the_final_walk_is_not_a_gate():
    """DELIBERATE, and the test says so rather than a comment alone: the final cut has no
    retry (its loop has ended), so holding the release to report a defect would delete the
    run's last milestone from the ledger — r184 would read 3-of-4. The walk may not raise,
    and its verdict may not decide anything here."""
    run, call = _final_walk_dispatch()
    owner = None
    for node in ast.walk(run):
        if isinstance(node, ast.Try) and any(c is call for c in ast.walk(node)):
            if owner is None or node.lineno > owner.lineno:
                owner = node          # innermost: the latest-starting Try containing it
    assert owner is not None, "the walk dispatch is not wrapped — it can raise into delivery"
    assert not any(isinstance(s, ast.Raise) for s in ast.walk(owner)), \
        "the final-release walk can raise, which would cost the release it just cut"
    # the report is recorded, not consulted: nothing here binds the result to a name
    assert not any(isinstance(p, (ast.Assign, ast.AnnAssign)) and
                   any(c is call for c in ast.walk(p))
                   for p in ast.walk(owner)), \
        "the final walk's result is bound to a name — if it gates anything, re-read the " \
        "reason above before changing this test"
