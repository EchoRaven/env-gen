r"""#699: a function documented as "called by the verifier" is called by nobody, in every run.

Found by the sweep the previous finding suggested. #691, #694b, #696 and #698 were all the same
shape — a correct computation whose result nothing consumes — so the pattern itself became the
search: first every dict key written and never read (that returned exactly one action-bearing hit,
`better_state_available`, already fixed as #698), then every module-level function whose name
appears only at its own `def`. That second sweep returned 26, and one of them is
`promote_integration_to_main`.

Its docstring says: "Called by the verifier after a successful RunHub run so that `main` only ever
points at code that has passed the latest verification." A token scan of every identifier in the
framework finds the name exactly once — here. The verifier does not call it; nothing does.

The consequence is measurable across every generated repo that has both branches:

    diverged in BOTH directions   130 runs   integration ahead 20-73 commits, main holding
                                             1 commit integration lacks
    main purely behind              5
    main ahead                      3
    in sync                         0

`main` is frozen at the early bootstrap + first framework-delivery commit while integration
accumulates the whole run. They never reconverge, because the function designed to reconverge them
is dead. And that single orphaned commit on `main` is the one #691 is about: the MCP writer runs
once, lands there, and the release — cut from integration — never sees it.

Wiring the promotion into the verifier is a real behaviour change with delivery consequences and
is deliberately not done here. What is fixed is the docstring, which told the next reader that a
promotion happens.
"""
import inspect
import re
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.agents.runtime import auto_commit as ac


def _doc() -> str:
    return ac.promote_integration_to_main.__doc__ or ""


# --- the correction is stated -------------------------------------------------------------------

def test_the_docstring_records_that_it_was_untrue_and_is_now_wired():
    d = " ".join(_doc().split())
    assert "WAS NOT TRUE FOR THE WHOLE KEPT HISTORY, and #706 made it true" in d


def test_the_original_claim_is_preserved_verbatim():
    """The intent is worth keeping even though the statement is false."""
    d = " ".join(_doc().split())
    assert "Called by the verifier after a successful RunHub run" in d


def test_the_corpus_measurement_is_recorded():
    d = " ".join(_doc().split())
    assert "130 runs" in d
    assert "in sync 0" in d


def test_the_link_to_the_stranded_subtree_is_recorded():
    d = " ".join(_doc().split())
    assert "#691" in d
    assert "cut from integration" in d


def test_the_docstring_names_where_it_is_wired():
    d = " ".join(_doc().split())
    assert "orchestrator.py" in d
    assert "after the delivery gate goes fully clear" in d
    assert "best-effort" in d


# --- the claim itself, checked against the tree ---------------------------------------------------

def test_it_now_has_exactly_one_call_site():
    """This guard asserted ZERO and it FIRED when #706 wired the call — which is exactly what it
    was written for. Flipped to pin the new invariant: one caller, and it is the orchestrator."""
    # parents[3] IS llm_generator (runtime/agents/multi_agent/llm_generator); the first
    # draft used parents[4]/"env_generator"/"llm_generator" and both these tests SKIPPED,
    # which proves nothing at all.
    root = Path(ac.__file__).resolve().parents[3]
    assert root.name == "llm_generator", root
    # Count CALL syntax, not mentions: the #699 docstring names the function while explaining
    # that nothing calls it, and a bare-name probe counts that as a caller. (The first draft did,
    # and reported 2.)
    sites = []
    for p in root.rglob("*.py"):
        src = p.read_text(errors="ignore")
        for m in re.finditer(r"\bpromote_integration_to_main\s*\(", src):
            line_start = src.rfind("\n", 0, m.start()) + 1
            if src[line_start:m.start()].strip().startswith("def"):
                continue
            sites.append(p.name)
    # #706b added the second release path, so there are now two call sites — both in the
    # orchestrator. The invariant is the FILE, not the count.
    assert sites and set(sites) == {"orchestrator.py"}, sites


def test_the_probe_can_find_a_function_that_IS_called():
    """Negative control: the sweep must be capable of seeing a live caller."""
    root = Path(ac.__file__).resolve().parents[3]
    assert root.name == "llm_generator", root
    hits = 0
    for p in root.rglob("*.py"):
        src = p.read_text(errors="ignore")
        for m in re.finditer(r"\bmerge_agent_branch_to_main\s*\(", src):
            ls = src.rfind("\n", 0, m.start()) + 1
            if src[ls:m.start()].strip().startswith("def"):
                continue
            hits += 1
    assert hits > 0, "the control function must have real CALL sites, or this probe proves nothing"


# --- the function is not deleted, and still works -------------------------------------------------

def test_it_is_still_exported_and_callable():
    assert callable(ac.promote_integration_to_main)


def test_its_signature_is_unchanged():
    sig = inspect.signature(ac.promote_integration_to_main)
    assert sig.parameters["integration_branch"].default == "integration"
    assert sig.parameters["main_branch"].default == "main"
    assert sig.parameters["actor"].default == "verifier"


def test_it_still_refuses_a_non_repo(tmp_path: Path):
    ok, info = ac.promote_integration_to_main(repo_root=tmp_path)
    assert ok is False
    assert "not a git repo" in info


def test_the_return_contract_is_still_documented():
    d = _doc()
    assert "nothing to promote" in d


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
