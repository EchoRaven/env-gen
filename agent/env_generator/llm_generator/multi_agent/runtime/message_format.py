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

from typing import Any, Dict, Iterable, Mapping, Optional

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
    ``items`` is used. Never raises: a formatting slip must not be able to break a gate or
    a run.

    #1202xi: THAT USED TO SAY "every caller is a logging path", AND 52 OF THE 87 CALL SITES
    ARE NOT. The four biggest are exactly the lane-facing ones -- delivery_gate 12,
    deliverability 10, remediation_dispatcher 10, scaffolder 8 -- where the joined text is
    BLOCKER PROSE, not a log line: `deliverability.py:868` builds "Register the endpoints each
    page actually calls." and `delivery_gate.py:1945` the contract/chain contradiction message.

    Swallowing is still right, but the consequence is not "a log line is short". The only way
    this returns "" is a non-iterable `items`, and a blocker built from "" READS AS AN EMPTY
    LIST -- the #983 shape, a check that fires while naming nothing. A caller assembling
    blocker prose should treat "" as "the instances could not be rendered", never as "there
    are none".
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
    """Say, once, that a best-effort mechanism did not run. (#1201)

    #1203os: the CAUSE clause now says what it means when there is no exception. A caller
    that checked a precondition and found it absent passes `exc=None`, and the tail then read
    `NoneType: None`, which looks like a bug in the reporter rather than a mechanism that
    declined for a reason it already stated.
    """
    try:
        if site in _WARNED_1201:
            return
        _WARNED_1201.add(site)
        import logging
        _cause = ("its precondition was not met (no exception was raised)" if exc is None
                  else "%s: %s" % (type(exc).__name__, str(exc)[:160]))
        logging.getLogger(__name__).warning(
            "#1201 %s did NOT run this process: %s. It is guarded so it cannot break the "
            "run, which also means nothing else will report it — treat this as the mechanism "
            "being OFF, not as a transient.",
            what, _cause)
    except Exception:
        pass


# --- #1203os: a FINDING is not a mechanism that turned off --------------------------
# #1201's population is supposed to answer one question -- "which guarded mechanisms were off
# in this run?" -- and three call sites were using it to report something else entirely: a
# fact about the GENERATED APP, or an event that happened on purpose. The template then
# appended `did NOT run this process ... treat this as the mechanism being OFF` to a sentence
# about which nothing was off.
#
# MEASURED over the 294 corpus run logs: of 602 `#1201` lines, **599 in 66 logs** are those
# three sites --
#
#     registryhub: "ui_page 'X' registered with no `apis_used`"              565 / 66 logs
#     registryhub: "ui_page 'X' claimed IMPLEMENTED with no route/component"  32 / 10 logs
#     compose_mutex: "waited Ns for the stack lease ... tearing it down"       2 /  2 logs
#
# -- and only 3 lines in 3 logs are a mechanism actually declining. So 99.5% of the answer to
# "which mechanisms turned off" was wrong, and the cost is not hypothetical: an audit of that
# very question returned 608 rows of which 3 were real, which is how this was found.
#
# It also buries the findings. Two of the three are the UI contract -- a page registered
# without naming the endpoints it reads, which is what turns the decoy-twin / consumer-wiring
# / implemented-flip checks OFF for that page -- and the third is the lease-wait announcement
# that the 13.2h `lease_wait` measurement is built on. A reader who meets them inside #1201's
# template is told to read them as a framework mechanism being broken.
#
# Same dedupe contract as #1201 (once per process per site, never raises); separate store, so
# moving a site between the two cannot silence it.
_ANNOUNCED_1203OS = set()


def announce_once_1203os(site: str, message: str, *args: Any) -> None:
    """Say, once per process per `site`, a thing that IS the case. (#1203os)

    For a finding about the generated app or an event the framework chose -- never for a
    mechanism that failed, which is `warn_once_1201`'s job and whose population has to stay
    answerable.
    """
    try:
        if site in _ANNOUNCED_1203OS:
            return
        _ANNOUNCED_1203OS.add(site)
        import logging
        logging.getLogger(__name__).warning("#1203os " + str(message), *args)
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


def ui_page_pending_detail_1203n1(pending: Any, cap: int = 6, reasons_cap: int = 2) -> str:
    """``"login_modal (component Foo not rendered), profile_own (…)"`` — the pending ui_pages
    WITH the reason each one is pending.

    `sync_ui_page_statuses` records `out["pending"][name] = missing`, the same `missing` list
    that decided the page did not flip to `implemented`. Its only consumer printed
    `list(pending.keys())`, so the reason was computed and dropped.

    MEASURED over every run log on disk: `UI-PAGE LIFECYCLE` has been written **2021 times**,
    and `is NOT in the registered contract` -- one of the misses that puts a page in that list
    -- appears **0 times**, ever. The line that reports page lifecycle has never once said
    what a page was waiting for.

    A page whose list is empty reads "no reason recorded" rather than looking fine: #883 --
    having no reason is a state to state, not a pass. Both levels are capped through
    `join_capped`, which declares its own cut (#1034).

    The `isinstance(pending, Mapping)` guard carries no weight and is kept for intent:
    without it a list argument raises inside `.items()`, the `except` catches it, `.keys()`
    raises too and the function still returns "". Mutation N15 removes it and nothing
    changes (#1203jr).
    """
    try:
        if not isinstance(pending, Mapping) or not pending:
            return ""
        return join_capped(
            ["%s (%s)" % (name, join_capped([str(x) for x in (why or [])],
                                            total=len(why or []),
                                            cap=reasons_cap, sep="; ") or "no reason recorded")
             for name, why in list(pending.items())],
            total=len(pending), cap=cap, sep=", ")
    except Exception:
        try:
            return str(list(pending.keys()))
        except Exception:
            return ""
