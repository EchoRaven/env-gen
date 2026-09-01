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

from typing import Any, Iterable, Optional

__all__ = ["join_capped"]


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
