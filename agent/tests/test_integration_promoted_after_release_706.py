r"""#706: wire promote_integration_to_main — after the cut, so the release still comes from integration.

Approved after #699 measured the cost of leaving it unwired: across every generated repo with both
branches, **130 of 146 runs diverged in BOTH directions** — integration ahead by 20-73 commits
while `main` held one commit integration lacked — and **0 runs in sync**. That one orphaned commit
on `main` is #691's: the MCP writer runs once, lands there before the fork, and the release never
sees it.

The hook is the point the function's own docstring describes and the only point where the claim is
true: `orchestrator.py`, immediately after the delivery gate goes fully clear and
`create_release(source="integration")` has cut the release. Two properties follow from placing it
AFTER the cut rather than in the verifier:

  * the RELEASE is unchanged — still cut from `integration`, and `main` follows it rather than
    feeding it, so nothing that ships is affected by the promotion succeeding or failing;
  * nothing is rolled back. This is the opposite of the bounded-escape question, which was
    declined precisely because shipping an earlier round means reverting later work.

Best-effort by construction: the run has already delivered when this executes, so a promotion
failure is logged and swallowed and can never block a delivery.
"""
import inspect
import re
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent import orchestrator as orch
from env_generator.llm_generator.multi_agent.agents.runtime import auto_commit as ac


def _block() -> str:
    src = inspect.getsource(orch)
    i = src.index("#706: PROMOTE INTEGRATION TO MAIN")
    return src[i:src.index("_write_preview_config", i)]


# --- it is called, once, in the right place ------------------------------------------------------

def test_the_promotion_is_called():
    assert "promote_integration_to_main(" in _block()


def test_EVERY_release_path_promotes():
    """#706b. The original assertion checked that A hook exists, and it did — at the site r147
    did not use. There are two create_release() calls in the orchestrator and the run took the
    other one, finishing with rev-list --count main..integration = 40. The invariant is not
    'a hook exists', it is 'every path that cuts a release then promotes'."""
    src = inspect.getsource(orch)
    # Skip occurrences inside comments: orchestrator.py:3506 mentions create_release() in prose
    # ("guarantees create_release() snapshots every commit") and a bare regex counts it as a
    # third call site whose window then has no promotion.
    cuts = []
    for m in re.finditer(r"create_release\(", src):
        line_start = src.rfind("\n", 0, m.start()) + 1
        if src[line_start:m.start()].lstrip().startswith("#"):
            continue
        cuts.append(m.start())
    assert len(cuts) >= 2, "expected both release paths to still exist"
    for i, c in enumerate(cuts):
        nxt = cuts[i + 1] if i + 1 < len(cuts) else len(src)
        window = src[c:nxt]
        assert "promote_integration_to_main" in window, (
            f"the create_release at offset {c} is not followed by a promotion")


def test_it_runs_after_the_release_is_cut():
    src = inspect.getsource(orch)
    cut = src.index('ch.create_release(')
    promo = src.index("#706: PROMOTE INTEGRATION TO MAIN")
    assert cut < promo, "the promotion must follow the cut, not precede it"


def test_the_release_still_comes_from_integration():
    """The invariant the whole design rests on."""
    src = inspect.getsource(orch)
    i = src.index('ch.create_release(')
    # Anchored on the call's own closing line rather than a character count.
    assert 'source="integration"' in src[i:src.index('agent="orchestrator",', i)]


def test_the_import_is_local_to_the_block():
    """The orchestrator must not gain a module-level dependency on auto_commit for this."""
    b = _block()
    assert "from .agents.runtime.auto_commit import promote_integration_to_main" in b
    src = inspect.getsource(orch)
    head = src[:src.index("#706: PROMOTE INTEGRATION TO MAIN")]
    assert "import promote_integration_to_main" not in head


# --- it can never block a delivery -----------------------------------------------------------------

def test_the_whole_block_is_guarded():
    b = _block()
    assert "try:" in b and "except Exception as _promo_err:" in b


def test_a_failure_only_warns():
    b = _block()
    assert "_logger.warning(" in b
    # STATEMENT level, not substring: the warning text itself contains "raised", and a
    # bare `"raise" not in code` matches that. Same trap as the keyword-argument one in #702.
    stmts = [l.strip() for l in b.split("\n")
             if l.strip() and not l.strip().startswith("#")]
    assert not [l for l in stmts if l == "raise" or l.startswith(("raise ", "return"))]


def test_a_refused_promotion_is_distinguished_from_a_raised_one():
    """(False, info) and an exception are different failures and read differently."""
    b = _block()
    assert "if _ok:" in b
    assert "did not happen" in b
    assert "promotion raised" in b


def test_the_warning_says_the_release_is_unaffected():
    b = " ".join(_block().split())
    assert "The release is unaffected" in b
    assert "cut from integration" in b


# --- the callee is unchanged -------------------------------------------------------------------------

def test_the_callee_still_refuses_a_non_repo(tmp_path: Path):
    ok, info = ac.promote_integration_to_main(repo_root=tmp_path)
    assert ok is False and "not a git repo" in info


def test_the_callee_signature_is_unchanged():
    sig = inspect.signature(ac.promote_integration_to_main)
    assert sig.parameters["integration_branch"].default == "integration"
    assert sig.parameters["main_branch"].default == "main"


def test_the_call_passes_the_release_tag_as_the_blessed_run():
    assert "blessed_run_id=str(release_tag)" in _block()


# --- provenance -----------------------------------------------------------------------------------

def test_the_measurement_that_justified_it_is_recorded():
    b = " ".join(_block().replace("#", " ").split())
    assert "130 of 146 runs diverged in BOTH directions" in b
    assert "0 runs in sync" in b


def test_the_link_to_the_stranded_subtree_is_recorded():
    b = " ".join(_block().replace("#", " ").split())
    assert "691" in b and "MCP writer runs once" in b


def test_why_after_the_cut_is_recorded():
    b = " ".join(_block().replace("#", " ").split())
    assert "Promoting after the cut, not before" in b
    assert "`main` follows it rather than feeding it" in b


def test_the_callee_docstring_no_longer_claims_nobody_calls_it():
    d = " ".join((ac.promote_integration_to_main.__doc__ or "").split())
    assert "#706 made it true" in d
    assert "orchestrator.py" in d


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
