r"""#724: the docstring told the next caller to cut releases from the worst available tree.

`create_branch_at`'s docstring said release branches "must capture a snapshot of `main`". Three
runs say otherwise, and so does the content of `main`:

    every release-v1.0.0 in r146, r147, r148 is an ancestor of `integration`
    and an ancestor of NEITHER `main`

Releases are cut with `source="integration"`. And `main` is not a lagging copy of the same work —
reproducing r148's promotion merge at the commits that existed when it ran gives SIXTEEN
conflicting files, the whole app, because the framework's delivery commit writes the entire
skeleton onto `main` while the lane's work goes to `integration`. A branch cut from `main` would
be framework projections with no lane work in it.

Nothing relies on the `start_point="main"` default today — both call sites pass the point
explicitly — so this is a documentation defect rather than a live one. It is worth fixing anyway
because the sentence actively recommended the wrong branch to whoever added the third caller.
"""
import inspect
import re
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime.hubs.codehub import git_ops


def _doc() -> str:
    return inspect.getdoc(git_ops.GitOps.create_branch_at) or ""


def _flat() -> str:
    """Whitespace-folded, because every phrase worth asserting wraps across lines."""
    return " ".join(_doc().split())


# --- the wrong advice is gone ---------------------------------------------------------------------

def test_the_old_advice_survives_only_as_an_attributed_quotation():
    """It is quoted while being corrected — a bare `not in` matches my own quotation marks,
    the same trap #718's test hit."""
    f = _flat()
    i = f.find("must capture a snapshot")
    assert i > 0, "the corrected sentence should still be quoted so the intent survives"
    assert "the previous sentence said" in f[:i]
    assert f.count("must capture a snapshot") == 1, "it must not read as current advice"


def test_it_says_where_releases_actually_come_from():
    d = _doc()
    assert 'source="integration"' in _flat()


def test_it_explains_what_main_actually_holds():
    assert "framework projections with no lane work" in _flat()


# --- the default is documented as misleading rather than silently kept -------------------------------

def test_the_default_is_still_main_and_is_called_out():
    sig = inspect.signature(git_ops.GitOps.create_branch_at)
    assert sig.parameters["start_point"].default == "main"
    assert "misleading" in _flat()


def test_it_names_the_call_sites_that_make_it_safe_today():
    d = _doc()
    f = _flat()
    assert "service.py:806" in f and ":1104" in f


def test_both_call_sites_really_do_pass_a_start_point():
    """If a third caller ever omits it, this fails and the docstring's premise must be revisited."""
    root = Path(git_ops.__file__).resolve().parents[3]
    bare = []
    for p in root.rglob("*.py"):
        src = p.read_text(errors="ignore")
        for m in re.finditer(r"create_branch_at\(([^)]*)\)", src):
            args = m.group(1)
            if "def " in src[max(0, m.start() - 40):m.start()]:
                continue
            if "start_point" not in args:
                bare.append(f"{p.name}: {args[:60]}")
    assert not bare, f"a caller now relies on the main default: {bare}"


# --- provenance -----------------------------------------------------------------------------------

def test_the_three_run_measurement_is_recorded():
    f = _flat()
    assert "r146, r147 and r148" in f
    assert "and of NEITHER" in f


def test_the_sixteen_file_conflict_is_recorded():
    d = _doc()
    assert "16 conflicting files" in _flat()


def test_it_links_the_mechanism_to_691():
    assert "691" in _flat()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
