r"""#1034: a printed COUNT beside a silently truncated list, twelve times over.

#1022b fixed two gate lines that said "5 P0 BUG task(s) ... <four titles>" with no marker.
Scanning `runtime/` for the same shape — a `logger.warning` that prints a count AND joins a
`[:N]`-truncated list, with no "+N more" anywhere near it — finds **12**:

    delivery_gate.py:1952       completeness oracle, %d gap(s), [:8]
    delivery_gate.py:2544       #1009 incomplete_required_tasks, %d x %s, [:6]   <- fixed here
    design_prep.py:887          %d section(s) nobody reads, [:8]
    frontend_audit.py:1225      declares %d API(s), [:4]
    frontend_audit.py:1242      declares %d component(s), [:6]
    frontend_scaffold.py:11584  #707 staged %d placeholder asset(s), [:8]
    heal_pipeline.py:2012       #1014 committing %d LANE-OWNED path(s), [:10]    <- fixed here
    remediation_dispatcher.py:889   %s unwired page(s), [:200]
    visual_fidelity.py:2590     #715 %d route(s) the served frontend lacks, [:6]
    visual_fidelity.py:3138     #740 %d console error(s), [:160]
    visual_fidelity.py:3660     %d screen(s) with a different verdict, [:8]
    visual_fidelity.py:3993     #713 %d screens with the SAME image, [:12]

Bounding the list is right; an unbounded dump is worse. Saying nothing about the cut is the
defect: reading these across ticks means DIFFING the lists, and an item merely pushed past
position N reads as resolved. It misled me twice in one session.

★ SCOPE, stated honestly. `join_capped` now exists in `runtime/message_format.py` and the two
gate-adjacent sites use it. The other ten are NOT converted: each needs its own import, and
threading a new import into six more modules already produced one real breakage here (the
insert landed above `from __future__ import annotations` in heal_pipeline and the module
stopped importing). #995 is the precedent — a multi-site edit is where this repo's rollbacks
come from. The helper and the list are in place so the rest is mechanical when someone wants
it; a correct partial fix beats a broad one that breaks imports.
"""
import ast
import glob
import inspect
import os
import re

import pytest

from env_generator.llm_generator.multi_agent.runtime.message_format import join_capped

_RUNTIME = os.path.dirname(inspect.getfile(
    __import__("env_generator.llm_generator.multi_agent.runtime.message_format",
               fromlist=["x"])))


# --- the helper --------------------------------------------------------------------------

def test_a_truncated_list_declares_the_remainder():
    assert join_capped(list("abcdefgh"), 20) == "a; b; c; d; e; f (+14 more not shown)"


def test_an_untruncated_list_gains_no_noise():
    assert join_capped(["a", "b", "c"], 3) == "a; b; c"


def test_total_defaults_to_the_list_length():
    assert join_capped(["a", "b"]) == "a; b"


def test_the_cap_is_adjustable():
    assert join_capped(list("abcdef"), 6, cap=2) == "a; b (+4 more not shown)"


def test_the_separator_is_adjustable():
    assert join_capped(["a", "b"], 2, sep=", ") == "a, b"


@pytest.mark.parametrize("items,total", [
    (None, None), ([], 0), (["a"], "junk"), (["a"], None), (None, 5),
])
def test_it_never_raises(items, total):
    """Every caller is a logging path — a formatting slip must not break a gate or a run."""
    assert isinstance(join_capped(items, total), str)


def test_a_count_larger_than_the_list_still_reports_honestly():
    """The caller's count is authoritative: it is what the reader is being shown."""
    assert join_capped(["a"], 9) == "a (+8 more not shown)"


def test_a_count_smaller_than_the_list_does_not_invent_a_negative():
    assert join_capped(list("abc"), 1) == "a; b; c"


# --- the two converted sites -----------------------------------------------------------------

def test_the_1009_line_uses_it():
    from env_generator.llm_generator.multi_agent.runtime import delivery_gate as dg
    src = inspect.getsource(dg)
    assert "join_capped(_names, len(_names))" in src
    assert '"; ".join(_names[:6])' not in src


def test_the_1014_line_uses_it():
    from env_generator.llm_generator.multi_agent.runtime import heal_pipeline as hp
    src = inspect.getsource(hp)
    assert "join_capped(_hits, len(_hits), cap=10)" in src
    assert '"; ".join(_hits[:10])' not in src


def test_both_modules_still_import():
    """★ The seam that actually broke: the import insert landed above
    `from __future__ import annotations` and heal_pipeline stopped importing."""
    import importlib
    for m in ("delivery_gate", "heal_pipeline", "message_format"):
        importlib.import_module(
            f"env_generator.llm_generator.multi_agent.runtime.{m}")


def test_future_imports_stay_first_everywhere_in_runtime():
    """Generalised from that breakage: a `__future__` import must be the first statement."""
    bad = []
    for f in sorted(glob.glob(os.path.join(_RUNTIME, "*.py"))):
        try:
            tree = ast.parse(open(f, encoding="utf-8", errors="ignore").read())
        except SyntaxError:
            bad.append(f"{os.path.basename(f)}: does not parse")
            continue
        body = [n for n in tree.body if not isinstance(n, ast.Expr)]
        for i, n in enumerate(body):
            if isinstance(n, ast.ImportFrom) and n.module == "__future__" and i != 0:
                bad.append(f"{os.path.basename(f)}: __future__ import is statement {i}")
    assert bad == [], bad


# --- the class is recorded so the remaining ten are findable ------------------------------------

def test_the_unconverted_sites_are_listed():
    d = " ".join((__doc__ or "").split())
    for f in ("design_prep.py", "frontend_audit.py", "visual_fidelity.py",
              "remediation_dispatcher.py", "frontend_scaffold.py"):
        assert f in d, f"{f} must stay named so the remaining work is findable"
    assert "NOT converted" in d, "the partial scope must be stated, not implied"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
