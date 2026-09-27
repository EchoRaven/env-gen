"""#1202vy: a helper that nothing references is not dormant, it is a trap.

Two were found by sweeping the runtime for ticket-tagged functions with no references:

    _dumps_value_1202so    json_store.py   — #1202sz replaced it with the BYTES encoder
                                             (`_dumps_value_bytes_1202sz`) and left it behind.
                                             Zero references anywhere in the repo.
    _git_dir_1202kw        git_ops.py      — #1202mg unified the stale-lock logic and copied
                                             this resolver into `_resolve_gitdir_1202mg`
                                             VERBATIM, down to the docstring sentence about a
                                             linked worktree's `.git` being a file. Only its
                                             own test still reached it.

Neither was a live defect: both supersessions carried the logic forward correctly. The cost is
the next person's, and it is the shape this repo has paid for before — #272's `framework_defect`
was proved present by a test that hand-built the record, while the real writer could not
produce one, and it stayed dead across the whole corpus. A twin nobody calls is where a future
fix goes to have no effect.

The guard below is deliberately narrow: ZERO references anywhere, production or test. That is
not a judgement call — there is no argument for keeping a function no line of code names. A
helper called only from tests (the `reset_said_*` memo-clearers, eight of them) is left alone,
and a name listed in `__all__` is a re-export rather than a reference — `stage_input_checker_891`
sat there, a convenience wrapper "so call sites stay one line" that no call site ever adopted.
A helper that really is public surface has a test, and a test counts.
"""
import ast
import collections
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _ticket_tagged(name: str) -> bool:
    """This repo tags framework functions with the ticket that introduced them."""
    return "_1202" in name or name.rsplit("_", 1)[-1].isdigit()


def _scan():
    defs = {}
    uses = collections.Counter()
    files = sorted(LLM.rglob("*.py")) + sorted((ROOT / "tests").glob("*.py"))
    for p in files:
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            continue
        prod = "tests" not in p.parts
        for n in ast.walk(tree):
            if prod and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and _ticket_tagged(n.name):
                defs.setdefault(n.name, f"{p.relative_to(ROOT)}:{n.lineno}")
            if isinstance(n, ast.Name):
                uses[n.id] += 1
            elif isinstance(n, ast.Attribute):
                uses[n.attr] += 1
            elif isinstance(n, ast.alias):
                uses[(n.name or "").rsplit(".", 1)[-1]] += 1
                if n.asname:
                    uses[n.asname] += 1
    return defs, uses


def test_the_scan_sees_functions_that_are_called():
    """Validate the detector on known answers before trusting it — a sweep that cannot see a
    live call would report the whole module as dead. The first draft of this scan did exactly
    that: it counted the `def` as zero and flagged 460 of 678.
    """
    defs, uses = _scan()
    assert len(defs) > 300, f"the scan found only {len(defs)} tagged functions"
    for live in ("_structurally_private_resource_633", "_transition_payload_679",
                 "_apply_spec_visibility_1202hh", "_resolve_gitdir_1202mg"):
        assert uses[live] >= 2, (
            f"{live} is called in production but the scan counted {uses[live]} references — "
            f"the detector is broken, not the code")


def test_no_ticket_tagged_helper_is_referenced_nowhere():
    defs, uses = _scan()
    orphans = sorted(f"{n} ({defs[n]})" for n in defs if uses[n] == 0)
    assert not orphans, (
        "these functions are named by no line of code in the runtime or the tests. A "
        "supersession that leaves its twin behind is where the next fix goes to have no "
        "effect (#272's framework_defect is the precedent):\n  " + "\n  ".join(orphans))
