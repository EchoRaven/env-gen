r"""#866: the forensic log for this exact bug was written outside the run directory.

`json_store` carries instrumentation built for **smoke #21 (2026-06-03)** — *"the kickoff meeting
page vanished from `workhub_pages.json` between create_meeting (write 1) and the orchestrator's
'Meeting not found' diagnosis (write 3)"* — whose header still records that *"multi-thread /
multi-process / asyncio reproduction tests all PASS — the bug needs a production-only condition
the tests can't capture."*

★ **Ten weeks later the same shape is still recurring.** 7 corpus runs have
`shared/hubs/milestones.json` **absent while the `.lock` beside it exists** — the store was taken
and never written — and that is a total loss, because `start_kickoff` runs inside the loop over
the roadmap (#864). Two of them, r136 and r140, are 2026-08-11.

**The instrument could never have closed it.** It is off by default, which is a defensible choice
for a per-write JSONL trace. But it also wrote to a fixed `/tmp/envgen_jsonstore_debug-<pid>.log`
— *outside the run directory*. So even switched on, its evidence does not travel with the
artifacts that would explain it: whoever opens a dead run three days later has the store, the
logs, the captures and the agent traces, and not the one file built to answer the question.

A store's path is `<run>/shared/hubs/<name>.json`, so the run root is derivable with no new
argument and no caller change. `/tmp` stays as the fallback for a store outside a run tree.

**Still not enabled by default** — a line per write across every hub is a real cost, and the
decision to pay it belongs to whoever is chasing the bug. What changes is that paying it now
produces evidence in the place everything else about that run already lives.
"""
import inspect
import pathlib
import tempfile

import pytest

from env_generator.llm_generator.multi_agent.runtime import json_store as js


def _run_tree():
    d = pathlib.Path(tempfile.mkdtemp()) / "netflix-web-rX" / "shared" / "hubs"
    d.mkdir(parents=True)
    return d


def test_a_store_inside_a_run_logs_beside_the_run():
    hubs = _run_tree()
    p = js._debug_log_path_866(hubs / "milestones.json")
    assert p.parent.name == "logs"
    assert p.parent.parent.name == "netflix-web-rX"
    assert p.name == "jsonstore_debug.jsonl"


def test_the_logs_dir_is_created():
    """The run's `logs/` exists by the time hubs are written, but the instrument must not depend
    on that — it is most useful on runs that died early."""
    hubs = _run_tree()
    js._debug_log_path_866(hubs / "milestones.json")
    assert (hubs.parent.parent / "logs").is_dir()


def test_a_store_outside_a_run_still_has_somewhere_to_go():
    """Non-vacuity for the fallback: a loose store must not lose its trace or raise."""
    loose = pathlib.Path(tempfile.mkdtemp()) / "loose.json"
    p = js._debug_log_path_866(loose)
    assert p == js._DEBUG_LOG_PATH


def test_no_path_at_all_falls_back():
    assert js._debug_log_path_866(None) == js._DEBUG_LOG_PATH


def test_only_the_shared_hubs_shape_is_treated_as_a_run():
    """★ It must not guess. A file two levels under anything would otherwise scatter logs into
    unrelated directories — the shape has to be `<run>/shared/hubs/<name>.json` exactly."""
    for bad in ("a/b/hubs/x.json", "a/shared/other/x.json", "a/hubs/shared/x.json"):
        p = pathlib.Path(tempfile.mkdtemp()) / bad
        p.parent.mkdir(parents=True, exist_ok=True)
        assert js._debug_log_path_866(p) == js._DEBUG_LOG_PATH, bad


def test_the_shape_check_is_relative_not_absolute():
    """★ My first version of the case above listed `shared/hubs/x.json` as a NON-run shape. Placed
    under a tmpdir that is `/tmp/tmpXXX/shared/hubs/x.json` — a perfectly valid run rooted at
    `/tmp/tmpXXX` — so the test was wrong and the code was right. The rule is positional relative
    to the file, not anchored to any absolute prefix, and that is deliberate: runs live wherever
    the caller put them."""
    d = pathlib.Path(tempfile.mkdtemp()) / "shared" / "hubs"
    d.mkdir(parents=True)
    assert js._debug_log_path_866(d / "x.json").parent.name == "logs"


def test_every_emit_site_passes_its_store_path():
    """Otherwise the helper exists and the traces still go to /tmp — a fix with no reader."""
    src = inspect.getsource(js)
    body = src[src.index("class JsonStore"):] if "class JsonStore" in src else src
    calls = body.count("_debug_emit({")
    assert calls >= 3, calls
    assert body.count("}, self.file_path)") == calls, (
        "an emit site still drops its path and will log to /tmp")


def test_the_emitter_cannot_break_production():
    """Unchanged property, re-pinned because #866 added a `mkdir` to the path it runs on: a
    diagnostic that raises here would take out the write it was observing."""
    src = inspect.getsource(js._debug_emit)
    assert "except Exception" in src and "pass" in src
    helper = inspect.getsource(js._debug_log_path_866)
    assert "except Exception" in helper


def test_it_is_still_off_by_default():
    """Deliberate: a line per write across every hub is a real cost. #866 changes where the
    evidence lands, not whether it is collected."""
    import os
    assert not os.environ.get(js._DEBUG_ENV, "")
    assert js._debug_active(pathlib.Path("/x/shared/hubs/y.json")) is False


def test_the_bug_it_serves_is_still_described_in_the_module():
    """Non-vacuity for the premise. If smoke #21's note is ever removed, this ticket's rationale
    should be re-read rather than assumed."""
    src = inspect.getsource(js)
    assert "smoke #21" in src.lower()
    assert "production-only condition" in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
