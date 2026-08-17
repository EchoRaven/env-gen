"""#891: inter-stage contracts — a stage says so when its input never arrived.

This pipeline is ~10 stages where each stage's output is the next stage's only input, and until
now **no stage validated its input**. So one empty output propagates and only surfaces at the end,
far from the cause: the 7 runs of item 190 died 3-4 minutes in with `progress_events.jsonl` holding
two lines, and locating the break took an artifact-tree census plus a log dig.

Measured across the 151-run corpus, a later stage ran while an earlier one had produced nothing:

    backend  ran, DDL empty    12 runs   <- 8%; the app has no tables, so every query fails at
    seed     ran, DDL empty     5 runs      RUNTIME, five links from the cause
    frontend ran, DDL empty     4 runs
    capture  ran, DDL empty     2 runs
    capture  ran, frontend empty 1 run    <- r32; the blank-capture class (#75a/#737)

#864 added exactly this check at one boundary (the milestone roadmap) and it is the only reason
that failure is now legible. This generalises the shape rather than repeating it by hand.

★ **It reports; it does not abort.** Every prior version of this decision in this session
(#862/#864/#865/#876) landed on the same answer for the same reason: the run is usually already
lost, and aborting on a cause we cannot name trades a silent failure for a louder wrong one. What
was missing was never the abort — it was the sentence naming which stage did not deliver.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# say-once per (stage, needs): these fire on a broken run, and a broken run ticks many times.
# #845's rule — a line that repeats every tick stops being read.
_SAID_891: set = set()


def reset_said_891() -> None:
    """Test hook; also called per-run so a long session does not silence a later run."""
    _SAID_891.clear()


def require_stage_input_891(
    stage: str,
    needs: str,
    producer: str,
    present: Any,
    *,
    detail: str = "",
    progress: Any = None,
    event_type: Any = None,
) -> bool:
    """Announce (once) that ``stage`` is running without the input ``producer`` should have made.

    ``present`` may be a bool, a sized object, or a zero-arg callable — a callable that raises is
    treated as ABSENT and the raise is named, because "the check could not run" and "the input is
    missing" must not collapse into one (#873's rule; #877 is what happens when they do).

    Returns True iff the input is present. Never raises: an observability call that takes down the
    stage it observes would manufacture the failure it exists to report.
    """
    try:
        val = present() if callable(present) else present
        ok = bool(val) if not hasattr(val, "__len__") else len(val) > 0
        why = ""
    except Exception as exc:                       # noqa: BLE001 - reported below, never raised
        ok, why = False, f" (the check itself failed: {type(exc).__name__}: {exc})"

    if ok:
        return True

    key = f"{stage}<-{needs}"
    if key in _SAID_891:
        return False
    _SAID_891.add(key)

    msg = (
        "STAGE INPUT MISSING: %s is running without %s, which %s should have produced.%s%s "
        "Downstream failures from here are a CONSEQUENCE, not the cause (#891)."
    )
    try:
        logger.error(msg, stage, needs, producer, (" " + detail) if detail else "", why)
    except Exception:
        pass
    if progress is not None and event_type is not None:
        try:
            progress.emit(event_type, f"stage input missing: {stage} <- {needs}",
                          {"stage": stage, "needs": needs, "producer": producer,
                           "check_failed": bool(why), "ticket": 891})
        except Exception:
            pass
    return False


def require_stage_output_891(
    stage: str,
    produced: str,
    present: Any,
    *,
    detail: str = "",
    progress: Any = None,
    event_type: Any = None,
) -> bool:
    """The mirror: ``stage`` finished and its own output is not there.

    Cheaper to act on than the input check, because the producer is known — this is #864's
    read-back generalised. Same reporting discipline, same non-abort.
    """
    return require_stage_input_891(
        stage=f"(downstream of) {stage}", needs=produced, producer=stage,
        present=present, detail=detail, progress=progress, event_type=event_type)


def record_stage_894(
    stage: str,
    produced: str,
    count: Any = None,
    *,
    ok: bool = True,
    detail: str = "",
    progress: Any = None,
    event_type: Any = None,
) -> None:
    """#894: one line per stage boundary, in the log that survives the run.

    ★ Written from what this session actually cost. `progress_events.jsonl` is the only artifact
    every run leaves, and for the 7 runs of item 190 it held **two lines** — `generation_start`
    and `phase_start` — so "where did this run stop" was not answerable from it. I rebuilt an
    artifact-tree census by hand **four times** to answer that question, and the answer each time
    was one boundary.

    A stage timeline turns that into a read:

        generation_start
        phase_start   Agent Workflow
        stage         reference_compile  ok        3020 images
        stage         design_prep        ok        12 screens
        stage         milestone_plan     ok        1 milestone
        <nothing>                                  <- kickoff never started

    The absence of the next line IS the diagnosis, which is the property #863 added by hand for
    one boundary. Emitting on SUCCESS is the part that makes it work: a log that only speaks on
    failure cannot distinguish "this stage was fine" from "this stage never ran".

    Never raises; the run must not depend on its own narration.
    """
    try:
        n = None
        if count is not None:
            # a str/bytes is SIZED but is never a count — `count="12 screens"` recording 11 would
            # be a misleading number in the one log a reader trusts. Found by a test case whose
            # expectation was wrong and whose subject turned out to be worth fixing anyway.
            if isinstance(count, (str, bytes)):
                n = None
            else:
                n = len(count) if hasattr(count, "__len__") else int(count)
    except Exception:
        n = None
    try:
        logger.info("STAGE %s %s%s%s", stage, "ok" if ok else "EMPTY",
                    f" — {n} {produced}" if n is not None else f" — {produced}",
                    (" " + detail) if detail else "")
    except Exception:
        pass
    if progress is not None and event_type is not None:
        try:
            progress.emit(event_type, f"stage: {stage}",
                          {"stage": stage, "produced": produced, "count": n,
                           "ok": bool(ok), "ticket": 894})
        except Exception:
            pass


def stage_input_checker_891(progress: Any = None, event_type: Any = None) -> Callable:
    """Bind ``progress``/``event_type`` once so call sites stay one line."""
    def _check(stage: str, needs: str, producer: str, present: Any,
               detail: str = "") -> bool:
        return require_stage_input_891(stage, needs, producer, present, detail=detail,
                                       progress=progress, event_type=event_type)
    return _check


__all__ = ["require_stage_input_891", "require_stage_output_891",
           "stage_input_checker_891", "reset_said_891", "record_stage_894"]
