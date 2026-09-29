r"""#1202z4: a route the lane defined twice never runs, and only the log said so.

`backend_audit` computes it and `sync_endpoint_statuses` returns it in `out["duplicated"]`.
Everything that then happens to the finding is one `_logger.warning` — and a lane reads
WorkHub, not the orchestrator's log.

MEASURED over the 158 run logs: it reports in 4 of them (3%) and reaches a hub in NONE. A
grep of every file under `shared/hubs/` in every run for `DUPLICATE/shadowed` returns
nothing. Rare, and severe when it fires: r136 reported TWENTY-THREE shadowed endpoints,
47 times across the run, and nothing was ever dispatched.

★ THERE IS NO JUDGEMENT CALL HERE. `duplicated_routes` finds only INTRA-module collisions —
the same (method, path) decorated twice inside one file — which its own docstring calls
"always a lane bug". A cross-module override (main.py's projected handler plus a
custom_routes.py override) is deliberately NOT flagged, because that one is legitimate. My
first reading of this had it backwards (framework stub shadowing the lane's real handler),
and the guidance would have been wrong; the docstring settled it.

★ A TASK, NOT A BLOCKER, on #1202z0's reasoning: nothing establishes that the shadowed copy
was the one that mattered, and blocking a run over a duplicate that happens to be identical
would stop it for nothing. The audience changes, not the verdict.
"""
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.heal_pipeline import (  # noqa: E402
    _file_shadowed_route_task_1202z4 as file_task)


class _WH:
    def __init__(self, existing=None):
        self.tasks = list(existing or [])
        self.created = []

    def list_tasks(self):
        return self.tasks

    def create_task(self, **kw):
        self.created.append(kw)
        return {"id": "t1", **kw}


class _Orch:
    def __init__(self, wh):
        class _H:
            workhub = wh
        self.hubs = _H()


_DUPS = ["GET /api/videos/feed", "POST /api/videos/{video_id}/like"]


def test_a_task_is_filed_for_the_backend():
    wh = _WH()
    file_task(_Orch(wh), _DUPS)
    assert len(wh.created) == 1, wh.created
    assert wh.created[0]["assignee"] == "backend"


def test_the_task_names_every_route_it_can():
    wh = _WH()
    file_task(_Orch(wh), _DUPS)
    d = wh.created[0]["description"]
    for r in _DUPS:
        assert r in d, d


def test_the_task_says_which_definition_wins():
    """The whole harm is invisible from behaviour — the route answers, just from the other
    function. A lane told only "duplicate" would not know which body is dead."""
    d = _filed(_DUPS)["description"].lower()
    assert "first" in d and "never" in d, d
    assert "dead code" in d or "never runs" in d or "never reaches" in d, d


def test_the_task_does_not_misname_a_legitimate_override():
    """★ Cross-module overrides are NOT what this reports, and saying so keeps a lane from
    deleting a custom_routes.py handler that is meant to win."""
    d = _filed(_DUPS)["description"]
    assert "custom_routes.py" in d and "not reported here" in d, d
    assert "WITHIN ONE FILE" in d, d


def _filed(dups):
    wh = _WH()
    file_task(_Orch(wh), dups)
    assert wh.created, "nothing was filed"
    return wh.created[0]


def test_it_does_not_block():
    assert _filed(_DUPS).get("priority") == "P1", _filed(_DUPS).get("priority")


def test_nothing_duplicated_files_nothing():
    wh = _WH()
    file_task(_Orch(wh), [])
    assert wh.created == []


def test_an_open_task_is_not_cloned():
    """#794: r136 reported this 47 times in one run."""
    wh = _WH([{"title": "Route defined twice in one file — the second never runs (2)",
               "status": "in_progress"}])
    file_task(_Orch(wh), _DUPS)
    assert wh.created == [], wh.created


def test_a_completed_task_does_not_suppress_a_new_one():
    wh = _WH([{"title": "Route defined twice in one file — the second never runs (2)",
               "status": "completed"}])
    file_task(_Orch(wh), _DUPS)
    assert len(wh.created) == 1


def test_a_missing_workhub_is_not_a_crash():
    class _NoHub:
        hubs = None
    file_task(_NoHub(), _DUPS)          # must not raise


def test_a_listing_fault_still_files():
    class _Bad(_WH):
        def list_tasks(self):
            raise RuntimeError("hub down")
    wh = _Bad()
    file_task(_Orch(wh), _DUPS)
    assert len(wh.created) == 1, "a dedupe fault must not swallow the task"


def test_a_long_list_is_capped_but_says_so():
    """r136 had 23. A description that silently shows 20 of them understates the work."""
    many = ["GET /api/x%d" % i for i in range(23)]
    d = _filed(many)["description"]
    assert "and 3 more" in d, d


def test_the_caller_passes_the_duplicated_key():
    """★ I have tested a helper and not its caller repeatedly. Three properties: the call
    exists, it is fed `duplicated` (not `regressed`, which is the neighbouring key), and it
    is not behind the `implemented or regressed` branch — a run whose only finding is a
    duplicate would otherwise never reach it."""
    import ast
    import inspect
    import multi_agent.runtime.heal_pipeline as H

    src = inspect.getsource(H.HealPipeline)
    tree = ast.parse(src.lstrip())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", "") == "_file_shadowed_route_task_1202z4"]
    assert len(calls) == 1, "called %d times" % len(calls)
    arg_src = ast.dump(calls[0])
    assert "duplicated" in arg_src, arg_src[:200]

    for node in ast.walk(tree):
        if isinstance(node, ast.If) and any(c is calls[0] for c in ast.walk(node)):
            raise AssertionError("the call sits behind a branch: %s"
                                 % ast.dump(node.test)[:120])
