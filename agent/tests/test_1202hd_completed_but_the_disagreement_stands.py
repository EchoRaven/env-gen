"""#1202hd — the task was completed and the contradiction it named is still there.

#1202gv files one task per changed finding (#1202bn's dedupe, which exists because
`create_task` has none and 55% of the corpus's cancelled tasks are duplicates). r102, live:
backend marked the task `completed` at the end of the run while `videos` and `comments` still
carried `owner_scoped_reads: true` — the exact disagreement the task named. The dedupe then
keeps the framework silent, because the finding has not CHANGED.

So a lane can close the one message that names a root cause without touching it, and nothing
notices. That is the reporting-discipline failure this corpus produces most: a completion
claimed without the fact behind it.

Re-filing is narrow on purpose: only when the finding still holds AND the previous task for it
is already `completed`. An open task is left alone (that is #1202bn working), and a finding
that changed files anyway under the existing rule.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.scaffolder import _refile_after_completion_1202hd  # noqa: E402

_TITLE = "Reconcile 2 table(s) the materials call public with the contract that owner-scopes them"


def _hub(tasks):
    """Shaped like the real consumer: `workhub.stores.tasks.value()` -> {id: task}."""
    class _Store:
        def value(self):
            return {str(i): t for i, t in enumerate(tasks)}
    class _Stores:
        tasks = _Store()
    class _W:
        stores = _Stores()
    class _H:
        workhub = _W()
    return _H()


def test_a_completed_task_with_the_finding_still_standing_refiles():
    hub = _hub([{"title": _TITLE, "status": "completed", "assignee": "backend"}])
    assert _refile_after_completion_1202hd(hub, _TITLE) is True


def test_an_open_task_is_left_alone():
    """#1202bn is working there — the lane already has it on the desk."""
    for st in ("pending", "in_progress", "claimed"):
        hub = _hub([{"title": _TITLE, "status": st, "assignee": "backend"}])
        assert _refile_after_completion_1202hd(hub, _TITLE) is False, st


def test_no_prior_task_is_not_a_refile():
    """First time through, the ordinary dedupe decides; this helper must not force it."""
    assert _refile_after_completion_1202hd(_hub([]), _TITLE) is False


def test_a_cancelled_task_does_not_count_as_a_completion():
    hub = _hub([{"title": _TITLE, "status": "cancelled", "assignee": "backend"}])
    assert _refile_after_completion_1202hd(hub, _TITLE) is False


def test_the_latest_task_decides():
    hub = _hub([{"title": _TITLE, "status": "completed"},
                {"title": _TITLE, "status": "in_progress"}])
    assert _refile_after_completion_1202hd(hub, _TITLE) is False, (
        "a newer OPEN task was ignored in favour of an older completed one")


def test_hostile_inputs_never_raise():
    class _Boom:
        @property
        def workhub(self):
            raise RuntimeError("no hub")
    for hub in (None, object(), _Boom()):
        assert _refile_after_completion_1202hd(hub, _TITLE) is False


def test_the_filer_consults_it():
    src = (LLM / "multi_agent" / "runtime" / "scaffolder.py").read_text(encoding="utf-8")
    at = src.index('_sc1202gv("task:public_content_scoped_away"')
    # #943: bound the window on a landmark, not a byte count.
    block = src[src.rindex("_gv = public_content_scoped_away_1202gv(", 0, at):
                src.index("create_task(", at)]
    assert "_refile_after_completion_1202hd(" in block, (
        "the dedupe still silences a finding whose task was closed without fixing it:\n%s"
        % block)


def test_the_dedupe_is_recorded_even_when_the_refile_wins():
    """#1202he: `_hd or _sc(...)` short-circuits, so a re-file left the finding UNRECORDED and
    the next pass filed it again as if new. r102's resume filed twice, five minutes apart."""
    src = (LLM / "multi_agent" / "runtime" / "scaffolder.py").read_text(encoding="utf-8")
    at = src.index('_sc1202gv("task:public_content_scoped_away"')
    stmt = src[src.rindex("\n", 0, at) + 1:src.index("\n", src.index(")))", at))]
    assert "=" in stmt.split("_sc1202gv")[0], (
        "the dedupe is still called inside the `or`, so a re-file does not record it:\n%s"
        % stmt)
    guard = src[src.index("if _gv and (", at):src.index("\n", src.index("if _gv and (", at))]
    assert "_sc1202gv(" not in guard, (
        "the guard still short-circuits past the dedupe:\n%s" % guard)


def test_the_refile_is_bounded():
    """#1202hg: unbounded re-filing is the flood #1202bn exists to prevent — I introduced it.

    r103, live: five tasks, four closed without touching the contract, inside thirty minutes.
    Re-filing once after a false completion is the correction; re-filing forever is noise that
    costs a lane tick each time and never changes the outcome. Bounded at two, after which the
    finding stands in the gate's own blockers rather than in a task nobody acts on.
    """
    hub = _hub([{"title": _TITLE, "status": "completed"}] * 2)
    assert _refile_after_completion_1202hd(hub, _TITLE) is False, (
        "still re-files after the bound — five tasks and four empty completions in r103")


def test_one_completion_still_refiles():
    hub = _hub([{"title": _TITLE, "status": "completed"}])
    assert _refile_after_completion_1202hd(hub, _TITLE) is True


def test_the_bound_counts_completions_not_tasks():
    """A cancelled task is not a claim of having fixed anything, so it does not spend the
    budget — but the TRIGGER is still "the latest one was completed", because only that is a
    false completion to correct."""
    hub = _hub([{"title": _TITLE, "status": "cancelled"},
                {"title": _TITLE, "status": "completed"}])
    assert _refile_after_completion_1202hd(hub, _TITLE) is True, (
        "a cancelled task was counted against the two-completion budget")
    hub2 = _hub([{"title": _TITLE, "status": "completed"},
                 {"title": _TITLE, "status": "cancelled"},
                 {"title": _TITLE, "status": "completed"}])
    assert _refile_after_completion_1202hd(hub2, _TITLE) is False, (
        "two completions should exhaust the budget even with a cancellation between them")
