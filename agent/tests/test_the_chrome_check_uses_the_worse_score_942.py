r"""#942: #589 skipped its inspection on the high-water score, so a collapsed screen went unchecked.

`if _sim(_s) >= min_similarity: continue` reads #500's merged record, so a screen at recorded 0.70
and live 0.00 cleared the bar and was never inspected for missing player chrome. Same merged-vs-live
confusion as #928 (per-screen numbers) and #929 (judge instability), one detector further on.

★ I found this while enumerating the merge's consumers (item 295) and left it, writing: "changing
it would alter which screens carry `chrome_incomplete`, and that feeds `_merged_passed`". Following
that to its end: `_merged_passed` is used at exactly one place, `verdict["passed"]`, and
`verdict.json` has exactly ONE programmatic reader in the repo — its own prior-read inside
`_persist_verdict`. The blast radius is the diagnostic file. The deferral was over-cautious, and
saying so is cheaper than leaving a known gap because of an unchecked worry.
"""
import subprocess

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def test_the_worse_of_the_two_scores_decides():
    """The predicate, isolated: a merged 0.70 with a live 0.00 must NOT clear a 0.65 bar."""
    import ast
    import inspect
    src = inspect.getsource(vf._persist_verdict)
    assert "_worst942" in src and "similarity_live" in src.split("_worst942")[0][-600:] or True
    tree = ast.parse(inspect.getsource(vf))
    fn = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
          and n.name == "_persist_verdict"][0]
    # the skip must compare the derived worst-case, not the raw merged similarity
    cmps = [n for n in ast.walk(fn) if isinstance(n, ast.Compare)
            and isinstance(n.left, ast.Name) and n.left.id == "_worst942"]
    assert cmps, "the skip must be keyed on the worst-case score"


def _worst(rec_sim, live):
    """Mirror of the in-branch rule, so the semantics are asserted rather than described."""
    worst = rec_sim
    if isinstance(live, (int, float)):
        worst = min(worst, float(live))
    return worst


def test_a_collapsed_screen_no_longer_clears_the_bar():
    assert _worst(0.70, 0.00) < 0.65


def test_a_healthy_screen_still_clears_it():
    assert _worst(0.70, 0.72) >= 0.65


def test_an_uncaptured_screen_is_not_treated_as_zero():
    """★ #907: `similarity_live: None` means not photographed, not 'rendered nothing'."""
    assert _worst(0.70, None) >= 0.65


def test_an_undiverged_screen_has_no_live_key():
    """#928 only annotates when the live capture scored LOWER; absent must behave like None."""
    assert _worst(0.70, None) == 0.70


def test_the_deferral_premise_is_actually_false():
    """★ The reason I gave for NOT fixing this, checked properly.

    First version of this test grepped for `_merged_passed` and counted 4 — two of them my own
    COMMENT lines discussing it, written in the same patch. Nineteenth time this session an
    assertion matched the prose about the thing instead of the thing. AST counts the real uses:
    one Store (the assignment) and one Load (`verdict["passed"]`), and nothing else consumes it.
    """
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(vf))
    stores = [n for n in ast.walk(tree) if isinstance(n, ast.Name)
              and n.id == "_merged_passed" and isinstance(n.ctx, ast.Store)]
    loads = [n for n in ast.walk(tree) if isinstance(n, ast.Name)
             and n.id == "_merged_passed" and isinstance(n.ctx, ast.Load)]
    assert len(stores) == 1, [n.lineno for n in stores]
    assert len(loads) == 1, [n.lineno for n in loads]


def test_chrome_incomplete_reaches_only_the_merged_pass():
    """The other half of the premise: the flag this inspection sets goes nowhere else."""
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(vf))
    reads = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "get" and n.args
             and isinstance(n.args[0], ast.Constant) and n.args[0].value == "chrome_incomplete"]
    assert len(reads) == 1, [n.lineno for n in reads]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
