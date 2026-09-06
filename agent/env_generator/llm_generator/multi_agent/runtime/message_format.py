"""Formatting helpers for AGENT-FACING and operator-facing diagnostic text.

#1034: one function, because one defect showed up twelve times.

A warning that prints a COUNT beside a list truncated with a bare ``[:N]`` tells the reader
there are N items and shows them fewer, with nothing marking the gap. r172's gate line
16:03:16 read *"#743 5 P0 BUG task(s) are still open at the delivery cut: <four titles>"* —
five claimed, four listed, no marker. Reading these across ticks means diffing the lists, and
a silent cap makes the diff wrong: an item merely pushed past position N reads as resolved. It
misled me twice in one session before #1022b fixed the two gate lines.

Bounding the list is right — an unbounded dump is worse. The fix is to SAY the list was cut.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

__all__ = ["join_capped"]


# #1202ee: how much of ONE browser console error survives being written down.
#
# Measured on the same payload this bounds -- 135 console errors across 33 run logs:
# p50 330, p90 450, p99 630, max 710. The capture site in visual_fidelity.py bounded
# each message at 300, i.e. BELOW THE MEDIAN, and that cut happened at CAPTURE, so no
# downstream reporter could restore what it removed. #1202ea measured this for the
# test-user walk; the visual gate reads the same console of the same browser, so there
# is one number and both use it.
#
# It buys the frames, not prose: "TypeError: (void 0) is not a function" is 37 chars and
# each stack frame with a full bundle URL is ~60-90 more. 300 held the message and one
# frame; 480 holds the message and roughly four.
CONSOLE_ERROR_CAP_1202EE = 480


def join_capped(items: Iterable[Any], total: Optional[Any] = None, cap: int = 6,
                sep: str = "; ") -> str:
    """Join at most ``cap`` items and declare the remainder.

    ``total`` is what the caller is PRINTING as the count; when omitted the length of
    ``items`` is used. Never raises — every caller is a logging path, and a formatting slip
    must not be able to break a gate or a run.
    """
    try:
        seq = list(items or [])
    except Exception:
        return ""
    try:
        n = int(total) if total is not None else len(seq)
    except (TypeError, ValueError):
        n = len(seq)
    try:
        k = max(0, int(cap))
    except (TypeError, ValueError):
        k = 6
    shown = [str(x) for x in seq[:k]]
    text = sep.join(shown)
    hidden = n - len(shown)
    return f"{text} (+{hidden} more not shown)" if hidden > 0 else text

# --- #1201: a safety mechanism that fails must not fail SILENTLY ---------------------
# Three times in one session a mechanism was wired and never reached — an api-module scan
# hidden behind its own bound, a helper reported as landed while it sat outside the directory
# every commit staged, and #1200's leak signal sharing a try with an import that is wrapped
# precisely because it can fail. Each was invisible because the guard around it ends in
# `except Exception: pass`.
#
# Those guards are right: a repair must never break the run it repairs. What is wrong is that
# they say nothing, so a mechanism can be off for an entire run — a cross-user leak reopened,
# a declaration never reconciled — with a clean log. #1102 already named this exactly: "a
# notice nobody sees is the silence this fix exists to end."
#
# Once per process per site, so a per-tick pass cannot flood the log. Never raises: a
# reporter that can break its caller is worse than the silence it replaces.
_WARNED_1201 = set()


def warn_once_1201(site: str, what: str, exc: Any) -> None:
    """Say, once, that a best-effort mechanism did not run. (#1201)"""
    try:
        if site in _WARNED_1201:
            return
        _WARNED_1201.add(site)
        import logging
        logging.getLogger(__name__).warning(
            "#1201 %s did NOT run this process: %s: %s. It is guarded so it cannot break the "
            "run, which also means nothing else will report it — treat this as the mechanism "
            "being OFF, not as a transient.",
            what, type(exc).__name__, str(exc)[:160])
    except Exception:
        pass


# --- #1202ad: one place for "report a state, not a heartbeat" ----------------------------
# This rule has now been implemented five separate times, once per site, and I introduced one
# of the offenders myself two days after removing the same noise elsewhere:
#
#     #1202n  heal declines             r26 134 lines,  2 distinct states
#     #1202p  declaration drift         r30 416 lines,  4 pages
#     #1202v  seed audit "0 of N"       r30 213 lines,  1 state
#     #1202ab lane-page verdict         r32 280 lines,  9 pages
#     #1202ac unstaged assets (mine)    r32 117 lines,  1 set
#
# Each fix was a private dict and a hand-written comparison. A rule that lives in five copies
# drifts on the first edit to any of them — the same reasoning `_imports_own_components`
# records for #905/#906. So: one helper, and the remaining sites call it.
#
# It is deliberately NOT "log once". A state that MOVES is news and must be said again,
# including a move back to a state already seen — that is the difference between silence and
# a heartbeat, and #1202n's tests pin it.
_STATE_SAID_1202AD: Dict[str, Any] = {}


def state_changed_1202ad(site: str, state: Any) -> bool:
    """True when `state` differs from what `site` last reported. Never raises.

    `site` is the caller's own key — include the page/lane/table when the same code reports
    per-item, so two items cannot silence each other. `state` should carry everything whose
    change is worth a line: a verdict flip is a change, a count that moves is a change.
    """
    try:
        key = str(site)
        try:
            token = repr(state)
        except Exception:
            return True                     # unrepresentable state -> always report
        if _STATE_SAID_1202AD.get(key) == token:
            return False
        _STATE_SAID_1202AD[key] = token
        return True
    except Exception:
        return True                         # a memo failure must never silence a report


def reset_state_memo_1202ad(prefix: str = "") -> None:
    """Forget what has been said, for a site prefix or entirely. For tests and new runs."""
    try:
        if not prefix:
            _STATE_SAID_1202AD.clear()
            return
        for k in [k for k in _STATE_SAID_1202AD if k.startswith(prefix)]:
            _STATE_SAID_1202AD.pop(k, None)
    except Exception:
        pass
