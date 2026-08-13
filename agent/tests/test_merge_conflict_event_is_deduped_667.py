r"""#667: the merge-conflict EVENT republished every step while its task was deduped.

`step_runner`'s step-start pull does three things on conflict: log, publish an urgent
`merge_conflict` event to the orchestrator, and create a remediation task. The TASK is created
once per unresolved conflict — there is an explicit `_dup` guard. The EVENT had no such guard,
so an unresolved conflict re-sent identical urgent traffic on every step.

Measured over the 249 run logs:

    4320 conflicts across 31 runs, median 50 per run, 796 in r124 alone
    runs WITH pull conflicts: median 396 "dispatch queue FULL" warnings
    runs WITHOUT:             median 202
    r = 0.78 over 128 runs; the three worst conflict runs (796/612/454) are the three worst
    saturation runs (2498/2814/2176)

#150 drops the ordinary-dispatch copy when that bounded queue fills, so the repeat was buying
nothing and crowding the channel everything else shares. The conflicting files are the frontend
pages several lanes touch at once (BrowseHomePage.jsx x1896, GenreCategoryPage.jsx x804), so
this is the normal multi-lane case, not an exotic one.

The first event still fires, and fires again after each resolution — the task auto-completes
when a later pull succeeds, so the next conflict sees no open task. The task stays the durable
record, which is the split the surrounding code already chose.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.agents.runtime import step_runner as sr


def _block():
    """The conflict branch, bounded by the construct that follows it."""
    src = inspect.getsource(sr)
    i = src.index("#667: DEDUPE THE EVENT")
    return src[i:src.index("May 29 audit fix", i)]


# --- the gate exists and reuses the task's own signal ----------------------------------------

def test_the_event_is_gated_on_an_open_conflict_task():
    body = _block()
    assert "_open_conflict_task" in body
    assert "if (not _open_conflict_task" in body


def test_it_keys_on_exactly_what_the_task_dedup_keys_on():
    """Two different predicates would drift; the point is that they agree."""
    body = _block()
    for token in ('"step_runner_merge_conflict"', '"pending", "in_progress"',
                  '_t.get("assignee") == self.agent_id'):
        assert token in body, token


def test_the_probe_is_best_effort():
    """A workhub fault must not suppress the event — it must fall through to publishing."""
    body = _block()
    assert "_open_conflict_task = False" in body
    i = body.index("except Exception:")
    assert "_open_conflict_task = False" in body[i:]


def test_a_hub_fault_defaults_to_publishing_not_silence():
    body = _block()
    tail = body[body.index("except Exception:"):]
    assert "= False" in tail.split("\n")[1], "the except must reset to False (publish), not True"


# --- the task path is untouched -------------------------------------------------------------

def test_the_task_is_still_created_and_still_deduped():
    src = inspect.getsource(sr)
    i = src.index("May 29 audit fix")
    tail = src[i:src.index("assignee=", i)]
    assert "_dup = any(" in tail
    assert "if not _dup:" in tail
    assert "create_task(" in tail


def test_the_warning_still_logs_every_occurrence():
    """Log volume is cheap and per-step visibility is the diagnostic; only the EVENT is deduped."""
    src = inspect.getsource(sr)
    i = src.index("step-start pull conflict: {pulled_info}")
    assert src.index("#667: DEDUPE THE EVENT") > i, "the log must precede the gate"


def test_the_event_still_carries_the_routing_payload():
    body = _block()
    src = inspect.getsource(sr)
    i = src.index("#667: DEDUPE THE EVENT")
    tail = src[i:src.index("May 29 audit fix", i)]
    assert 'event_type="merge_conflict"' in tail
    assert '"phase": "step_start_pull"' in tail


def test_the_auto_complete_on_success_is_still_there():
    """What makes the gate self-clearing: the task closes when a later pull succeeds."""
    src = inspect.getsource(sr)
    assert "step-start pull succeeded — conflict gone" in src


# --- provenance -------------------------------------------------------------------------------

def test_the_measurement_is_recorded():
    flat = " ".join(_block().replace("#", " ").split())
    assert "4320 conflicts across 31 runs" in flat
    assert "r = 0.78 over 128 runs" in flat


def test_the_reason_the_repeat_was_harmful_is_recorded():
    # strip the comment markers: a wrapped line puts a "#" mid-sentence
    flat = " ".join(_block().replace("#", " ").split())
    assert "150 drops the ordinary-dispatch copy" in flat


def test_what_still_fires_is_recorded():
    """A reader must be able to see this does not silence the first report."""
    flat = " ".join(_block().replace("#", " ").split())
    assert "The first event still fires" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
