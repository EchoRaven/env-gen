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
