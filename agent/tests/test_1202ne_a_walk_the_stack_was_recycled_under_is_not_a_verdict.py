"""#1202ne: a browser test-user walk that a stack recycle overlapped is discarded, not judged.

tiktok-r125 v1.1.0: the framework's pre-release browser walk started at 06:45:36; at 06:45:58 the
verifier's `docker_up(build, force_recreate, fresh=True)` ran `down -v`. `login.png` carries that
second as its mtime, and every one of the next 12 pages came back blank. The gate dispatched a P0
"12 blank pages" to the frontend and deferred the release, though the walk eight minutes earlier
had rendered real data from the same code.

Across the run logs, 6 of the 22 browser reports where every page (or all but one) came back
blank had a compose `up`/`down` in the five minutes before them.

The containers are the one place every writer leaves a mark (the lane's docker tool takes neither
the compose lock nor #1202kz's record), so the walk compares the stack's container ids and start
times before and after, and on a change walks once more when the stack serves again.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime import compose_mutex as CM  # noqa: E402
from multi_agent.runtime import heal_pipeline as HP  # noqa: E402
from multi_agent.runtime import test_user_runner as TUR  # noqa: E402
from multi_agent.runtime import validation_runner as VR  # noqa: E402
from multi_agent.runtime import visual_fidelity as VF  # noqa: E402

BLANK = {"ran": True, "auth_ok": False, "blank_pages": [f"p{i}" for i in range(12)],
         "summary": "blank"}
CLEAN = {"ran": True, "auth_ok": True, "blank_pages": [], "summary": "clean"}


class _Log:
    def __init__(self):
        self.lines = []

    def warning(self, msg, *a):
        self.lines.append(msg % a if a else msg)

    info = debug = error = warning


def _setup(monkeypatch, tmp_path, identities, walks, serving=True):
    (tmp_path / "docker").mkdir()
    compose = tmp_path / "docker" / "docker-compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")
    tasks = []
    orch = SimpleNamespace(
        output_dir=str(tmp_path), llm=None, _reference_images=[], _logger=_Log(),
        hubs=SimpleNamespace(workhub=SimpleNamespace(create_task=lambda **kw: tasks.append(kw)),
                             record_validation_result=lambda **kw: None))
    registry = SimpleNamespace(list_ui_pages=lambda: {})
    ids = iter(identities)
    walk_iter = iter(walks)
    calls = {"walks": 0}

    async def _run(*a, **kw):
        calls["walks"] += 1
        return dict(next(walk_iter))

    monkeypatch.setattr(CM, "stack_identity_1202ne", lambda cf, **kw: next(ids))
    monkeypatch.setattr(HP, "_stack_serving_1202ne", lambda base, api: serving)
    monkeypatch.setattr(TUR, "run_browser_test_user", _run)
    monkeypatch.setattr(TUR, "extract_seed_display_values", lambda proj: [])
    monkeypatch.setattr(TUR, "format_feedback", lambda r: "feedback")
    monkeypatch.setattr(TUR, "clean_ui_flow_passes", lambda r: [])
    monkeypatch.setattr(VF, "_service_host_port", lambda *a: 8006)
    monkeypatch.setattr(VF, "_seed_demo_login", lambda proj: None)
    monkeypatch.setattr(VR, "_backend_host_port", lambda *a: 8082)
    # #1202qt gates the walk on a serving backend; these cases are about a stack that IS
    # serving when the walk starts, so the readiness wait passes.
    monkeypatch.setattr(VR, "wait_backend_ready", lambda *a, **kw: True)
    pipe = HP.HealPipeline(orch)
    run = lambda: pipe._run_browser_test_user(tmp_path, compose, registry, "1.1.0")  # noqa: E731
    return run, tasks, calls, orch


A = frozenset({"fe 06:40", "be 06:40", "db 06:40"})
B = frozenset({"fe 06:46", "be 06:46", "db 06:46"})
C = frozenset({"fe 06:50", "be 06:50", "db 06:50"})


def test_r125_a_recycle_during_the_walk_dispatches_nothing_and_re_walks(monkeypatch, tmp_path):
    run, tasks, calls, orch = _setup(monkeypatch, tmp_path, [A, B, B, B], [BLANK, CLEAN])
    report = run()
    assert calls["walks"] == 2
    assert report["summary"] == "clean"
    assert tasks == []
    assert any("#1202ne" in ln for ln in orch._logger.lines)


def test_a_second_overlap_gives_no_verdict_rather_than_a_false_one(monkeypatch, tmp_path):
    run, tasks, calls, _ = _setup(monkeypatch, tmp_path, [A, B, B, C], [BLANK, BLANK])
    assert run() is None
    assert calls["walks"] == 2
    assert tasks == []


def test_a_stack_that_does_not_come_back_gives_no_verdict(monkeypatch, tmp_path):
    run, tasks, calls, _ = _setup(monkeypatch, tmp_path, [A, frozenset()], [BLANK],
                                  serving=False)
    assert run() is None
    assert calls["walks"] == 1
    assert tasks == []


def test_a_stable_stack_keeps_the_verdict_and_the_p0(monkeypatch, tmp_path):
    run, tasks, calls, _ = _setup(monkeypatch, tmp_path, [A, A], [BLANK])
    report = run()
    assert calls["walks"] == 1
    assert report["blank_pages"] == BLANK["blank_pages"]
    assert len(tasks) == 1 and tasks[0]["priority"] == "P0"


def test_an_unreadable_identity_changes_nothing(monkeypatch, tmp_path):
    run, tasks, calls, _ = _setup(monkeypatch, tmp_path, [None, None], [BLANK])
    assert run()["blank_pages"]
    assert calls["walks"] == 1 and len(tasks) == 1


def test_a_stack_that_was_already_down_is_judged_as_before(monkeypatch, tmp_path):
    """Nothing running before the walk is not a recycle: the empty snapshot is not compared."""
    run, tasks, calls, _ = _setup(monkeypatch, tmp_path, [frozenset(), B], [BLANK])
    assert run()["blank_pages"]
    assert calls["walks"] == 1 and len(tasks) == 1


def test_the_identity_names_id_and_start_time(monkeypatch, tmp_path):
    """A restart keeps the id and changes the start time; both must be in the snapshot."""
    import subprocess

    outs = {"ps": "abc\ndef\n", "inspect": "abc 2026-09-15T11:49:00Z\ndef 2026-09-15T11:49:01Z\n"}

    def _fake(cmd, **kw):
        key = "ps" if "ps" in cmd else "inspect"
        return SimpleNamespace(returncode=0, stdout=outs[key], stderr="")

    monkeypatch.setattr(subprocess, "run", _fake)
    got = CM.stack_identity_1202ne(tmp_path / "docker-compose.yml")
    assert got == frozenset({"abc 2026-09-15T11:49:00Z", "def 2026-09-15T11:49:01Z"})
    outs["ps"] = ""
    assert CM.stack_identity_1202ne(tmp_path / "docker-compose.yml") == frozenset()
