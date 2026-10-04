r"""#1203f0: the pre-cut latch demanded a BACKEND change to clear a FRONTEND build failure.

`ensure_fresh_smoke_before_cut` stamped `_fresh_smoke_fail_sig = backend_source_signature(...)`,
and `fresh_smoke_decision` then returns "hold" for that exact signature until the BACKEND source
changes. But the check it gates is `docker_up`, which builds BOTH services — so a FRONTEND build
failure stamps a BACKEND hash, and the frontend lane's fix cannot re-arm it. The hold prints
"waiting for a lane fix" while the only lane that can fix it is the one whose edits are invisible
to the latch.

★ LIVE in r154: `docker_up` failed on a rollup build error, the frontend lane committed at
04:11:16, a fresh validation PASSED at 04:11:58 with `fail_count=0` — and the latch message
printed again at 04:12:28. Measured over the run logs on disk, that message appears 30 times
across 6 runs, 19 of them in r59 alone.

★ #501 already fixed this exact class in the checklist self-heal, with the reasoning this patch
needs verbatim: "a stale `build:frontend` re-invalidated by a FRONTEND-only fix must also grant a
refresh — r70 wedged on `verification_checklist_not_ready` because #492 keyed on the backend
signature alone". The pre-cut smoke was the third site and still keyed on the backend alone.

Both writers had to change together: `_smoke_backend_sig` is written from `cur` (the cut-time
decision) AND from `_pre_smoke_sig` (the pre-smoke stamp), and those two values are COMPARED.
Changing one alone would make them never match and re-boot docker every tick. #501's own site now
delegates too, so three consumers share one definition of "the tree changed".
"""
import inspect
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime import framework_validation as FV  # noqa: E402
from multi_agent.runtime.framework_validation import (  # noqa: E402
    fresh_smoke_decision, tree_signature_1203f0)


def _tree(tmp, backend="print(1)", frontend="export default 1"):
    app = tmp / "app"
    (app / "backend").mkdir(parents=True, exist_ok=True)
    (app / "frontend" / "src").mkdir(parents=True, exist_ok=True)
    (app / "backend" / "main.py").write_text(backend)
    (app / "frontend" / "src" / "App.jsx").write_text(frontend)
    return app


# ---------------------------------------------------------------- the signature

def test_a_frontend_only_change_moves_the_signature(tmp_path):
    """★ The defect in one assertion: this is what the latch could not see."""
    app = _tree(tmp_path)
    before = tree_signature_1203f0(app)
    (app / "frontend" / "src" / "App.jsx").write_text("export default 2")
    assert tree_signature_1203f0(app) != before


def test_a_backend_only_change_still_moves_it(tmp_path):
    """★ The invariant: the behaviour the latch already had must not be lost."""
    app = _tree(tmp_path)
    before = tree_signature_1203f0(app)
    (app / "backend" / "main.py").write_text("print(2)")
    assert tree_signature_1203f0(app) != before


def test_an_untouched_tree_is_stable(tmp_path):
    """The latch's whole purpose: do not re-boot docker on an unchanged tree."""
    app = _tree(tmp_path)
    assert tree_signature_1203f0(app) == tree_signature_1203f0(app)


def test_it_is_none_only_when_both_halves_are_unavailable(tmp_path):
    """#501's rule: `None` preserves every caller's "cannot compute -> do not block" path, and a
    half-present tree must still yield a usable signature."""
    assert tree_signature_1203f0(tmp_path / "nope") is None
    app = tmp_path / "app"
    (app / "backend").mkdir(parents=True)
    (app / "backend" / "main.py").write_text("x=1")
    assert tree_signature_1203f0(app) is not None


def test_a_fault_does_not_raise():
    for bad in (None, 12345, ""):
        tree_signature_1203f0(bad)


# ---------------------------------------------------------------- the latch clears now

def test_the_latch_releases_after_a_frontend_fix(tmp_path):
    """★ End to end on the shipped decision function: stamp a failure, change ONLY the frontend,
    and the decision must move off "hold"."""
    app = _tree(tmp_path)
    failed = tree_signature_1203f0(app)
    assert fresh_smoke_decision(failed, None, None, failed) == "hold"
    (app / "frontend" / "src" / "App.jsx").write_text("export default 2  // the lane's fix")
    assert fresh_smoke_decision(tree_signature_1203f0(app), None, None, failed) == "smoke"


def test_the_latch_still_holds_on_a_genuinely_unchanged_tree(tmp_path):
    """★ Not a loosening: with nothing edited, it must still refuse to re-boot."""
    app = _tree(tmp_path)
    sig = tree_signature_1203f0(app)
    assert fresh_smoke_decision(sig, None, None, sig) == "hold"


# ---------------------------------------------------------------- both writers moved together

def test_the_cut_time_decision_uses_the_tree_signature():
    src = inspect.getsource(FV.ensure_fresh_smoke_before_cut)
    assert "tree_signature_1203f0(app_root)" in src, src[:400]
    assert "backend_source_signature(app_root)" not in src, src[:400]


def test_the_pre_smoke_stamp_uses_the_same_one():
    """★ The trap: `_smoke_backend_sig` is written from BOTH, and the two are compared. Changing
    one alone would make them never match and re-boot docker every tick."""
    src = inspect.getsource(FV)
    i = src.index("_pre_smoke_sig = ")
    j = src.index("\n", i)
    assert "tree_signature_1203f0" in src[i:j], src[i:j]


def test_no_site_still_keys_on_the_backend_alone():
    """Pinned over the whole module: the three consumers of "the tree changed" must agree."""
    src = inspect.getsource(FV)
    lines = [ln for ln in src.split("\n")
             if "backend_source_signature(" in ln
             and "def backend_source_signature" not in ln
             and not ln.lstrip().startswith("#")]
    # the only remaining call is the one INSIDE tree_signature_1203f0
    assert len(lines) == 1, lines


def test_501s_own_site_delegates_too():
    """One implementation, three uses — so a later edit cannot make them disagree (#1032)."""
    src = inspect.getsource(FV)
    assert src.count("tree_signature_1203f0(") >= 4, src.count("tree_signature_1203f0(")
