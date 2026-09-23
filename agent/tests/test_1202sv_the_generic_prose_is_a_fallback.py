r"""#1202sv: `#983`'s generic blocker-prose replay must be a FALLBACK, not an override.

`#983` exists because most gate checks reached the lane as a bare check name: it replays the
prose the gate classified into the check token, so an unhandled check still says WHICH page or
flow. Its own comment states the contract — *"Set first so a bespoke branch overrides"* — and
delivers it by POSITION, which is not something position can deliver: the block sits BELOW two
branches that already set `_extra` (`#154`'s bare_authed_fetch call sites, `#799`'s uncovered
endpoints), so it overrides exactly what it promises to defer to.

That it has been harmless is luck, not design, and the luck is checkable: the one check where
both paths fire (`deliverability_bare_authed_fetch`) has the dispatcher and the gate reading
the SAME producer — `frontend_audit.bare_authed_fetch_blockers` — so the two strings are one
function's output either way. The next bespoke branch added above that line would have been
silently replaced, and the failure mode is invisible (a lane receives a plausible generic
message instead of the specific one someone wrote for it).

Guarding on emptiness makes the stated contract true wherever the block sits.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime import remediation_dispatcher as rd  # noqa: E402

_ANCHOR = '_prose = (getattr(orch, "_gate_blocker_prose_983", None) or {}).get(name) or []'


def _prose_block():
    """The #983 replay, located by its own statement rather than a source window (#943)."""
    src = inspect.getsource(rd)
    i = src.index(_ANCHOR)
    return src[i:src.index("except Exception:", i)]


def test_the_replay_defers_to_a_branch_that_already_said_something():
    assert "if _prose and not _extra:" in _prose_block(), (
        "#983 promises a bespoke branch overrides it; only an emptiness guard delivers that")


def test_it_still_fires_when_nothing_else_has():
    """The whole point of #983 — 37 ui_page_unwired firings reached the lane as a bare check
    name. Deferring must not become never speaking."""
    blk = _prose_block()
    assert "WHAT THE GATE ACTUALLY REPORTED" in blk
    assert "_prose[:8]" in blk


def test_the_branches_above_it_are_the_reason_position_cannot_work():
    """If #983 ever moves to the top of the loop the guard is still correct — but while it sits
    below them, these two assignments are what it was silently replacing."""
    src = inspect.getsource(rd)
    start = src.index("owner, title, how = spec")
    prose_at = src.index(_ANCHOR, start)
    above = src[start:prose_at]
    assert "_off = bare_authed_fetch_blockers(" in above, (
        "#154's exact call sites are set before the replay")
    assert "_unc799 = _uncovered_endpoints_799(orch)" in above


def test_both_paths_read_one_producer_so_today_nothing_changes():
    """The claim that makes this safe to land without a behaviour argument: for the only check
    where both fire, the dispatcher and the gate call the same function."""
    disp = inspect.getsource(rd)
    from multi_agent.runtime import deliverability
    assert "from .frontend_audit import bare_authed_fetch_blockers" in disp
    assert "bare_authed_fetch_blockers" in inspect.getsource(deliverability)


def test_the_guard_is_a_real_condition_not_a_comment():
    """Parse it: the `if` must test `_extra`, not merely mention it nearby."""
    src = inspect.getsource(rd)
    i = src.index(_ANCHOR)
    stmt = ast.parse("if " + src[src.index("if _prose and not _extra:", i) + 3:
                                 src.index(":", src.index("if _prose and not _extra:", i))]
                     + ": pass").body[0]
    names = {n.id for n in ast.walk(stmt.test) if isinstance(n, ast.Name)}
    assert names == {"_prose", "_extra"}
