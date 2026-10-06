"""#1203g8 — run_validation recorded 26 verdicts and not one duration.

`run_validation` is the biggest single consumer of a run's wall clock: one sampled call took
376.8 SECONDS (5.2% of all recorded tool time in a single call), and it is the per-milestone wall
cap — 7200s — that killed r159 with zero delivery and $268.88 spent.

It records 26 checks through `_add`, which stored `{name, status, detail}`. `perf_counter`
appeared NOWHERE in the module. So a run could say which check failed and never which one spent
the time. What reaches disk is thinner still: the persisted evidence for `validation:api_smoke`
is `{check, source, summary}` — one line — so even the 26 verdicts are not durable.

The artifact follows the convention of its neighbours (`tool_timings_1202wl.json`,
`list_total_unreachable_1202w0.jsonl`): one JSON object per call, appended, under `logs/`. It is
written from `_finalize`, which all eight return paths already pass through for #1202qe's reason
("every return path after the snapshot") — so a validation that bails at `docker_up` is measured
exactly like one that runs to the end. That is the case that matters most: an early failure is
cheap and a timeout is not.
"""
import json
import sys
import time
from pathlib import Path

import pytest

_AGENT = Path(__file__).resolve().parents[1]
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

from env_generator.llm_generator.multi_agent.runtime import validation_runner as V  # noqa: E402

_ART = Path("logs") / "validation_phase_timings_1203g8.jsonl"


def _read(root):
    f = Path(root) / _ART
    if not f.exists():
        return []
    return [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_the_writer_lands_one_record_per_call(tmp_path):
    assert V.record_phase_timings_1203g8(
        tmp_path, [("docker_up", 12.5), ("backend_health", 3.0)], 15.5) is True
    recs = _read(tmp_path)
    assert len(recs) == 1
    assert recs[0]["total_sec"] == 15.5
    assert recs[0]["phases"] == [{"name": "docker_up", "sec": 12.5},
                                 {"name": "backend_health", "sec": 3.0}]


def test_it_appends_rather_than_overwrites(tmp_path):
    V.record_phase_timings_1203g8(tmp_path, [("a", 1.0)], 1.0)
    V.record_phase_timings_1203g8(tmp_path, [("b", 2.0)], 2.0)
    assert [r["phases"][0]["name"] for r in _read(tmp_path)] == ["a", "b"]


@pytest.mark.parametrize("root,phases", [
    (None, [("a", 1.0)]), ("", [("a", 1.0)]),
])
def test_it_declines_without_a_destination(root, phases):
    assert V.record_phase_timings_1203g8(root, phases, 1.0) is False


def test_no_phases_writes_nothing(tmp_path):
    """An empty list is not a measurement — a file of empty records would make the artifact
    useless for exactly the question it exists to answer."""
    assert V.record_phase_timings_1203g8(tmp_path, [], 5.0) is False
    assert _read(tmp_path) == []


def test_it_never_raises(tmp_path):
    class _Bad:
        def __float__(self):
            raise ValueError("nope")
    assert V.record_phase_timings_1203g8(tmp_path, [("x", _Bad())], 1.0) in (True, False)
    assert V.record_phase_timings_1203g8(object(), [("x", 1.0)], 1.0) is False


# ------------------------------------------------- end to end, through the real validation

@pytest.fixture
def unrunnable(tmp_path):
    """A compose file whose image cannot be pulled: `docker_up` fails and the run takes the
    EARLY return path — the one an investigation of a wall-clock death actually needs."""
    (tmp_path / "docker").mkdir()
    (tmp_path / "docker" / "docker-compose.yml").write_text(
        "services:\n  backend:\n    image: no_such_image_1203g8\n", encoding="utf-8")
    return tmp_path


def test_an_early_return_is_still_measured(unrunnable):
    r = V.run_smoke_validation(unrunnable, [], up_timeout=1, health_timeout=1, teardown=False)
    assert r["passed"] is False
    recs = _read(unrunnable)
    assert len(recs) == 1, "the early docker_up exit wrote no timing record"
    names = [p["name"] for p in recs[0]["phases"]]
    assert "docker_up" in names, names


def test_the_expensive_phase_is_the_one_charged(unrunnable):
    """docker_up is where the time goes on this path, so it must carry it — not the cheap
    frontend scans that ran before it."""
    V.run_smoke_validation(unrunnable, [], up_timeout=1, health_timeout=1, teardown=False)
    rec = _read(unrunnable)[-1]
    by = {p["name"]: p["sec"] for p in rec["phases"]}
    assert by["docker_up"] == max(by.values())
    assert by["docker_up"] > 0, by


def test_the_phases_sum_to_the_total(unrunnable):
    """A breakdown that does not add up to the total answers 'which phase' with a number
    nobody can trust — the same property #1203g4 pinned for retries."""
    V.run_smoke_validation(unrunnable, [], up_timeout=1, health_timeout=1, teardown=False)
    rec = _read(unrunnable)[-1]
    s = sum(p["sec"] for p in rec["phases"])
    assert abs(s - rec["total_sec"]) <= 0.1, (s, rec["total_sec"])


def test_every_check_record_carries_its_own_seconds(unrunnable):
    """On the record too, so a caller already reading `checks` needs no second artifact."""
    r = V.run_smoke_validation(unrunnable, [], up_timeout=1, health_timeout=1, teardown=False)
    assert r["checks"], "no checks recorded"
    for c in r["checks"]:
        assert "sec" in c, c
        assert isinstance(c["sec"], (int, float))


def test_two_calls_append_two_records(unrunnable):
    for _ in range(2):
        V.run_smoke_validation(unrunnable, [], up_timeout=1, health_timeout=1, teardown=False)
    assert len(_read(unrunnable)) == 2


# ------------------------------------------------------------- structure, over the AST

def test_every_return_path_goes_through_the_writer():
    """#1178's lesson: an artifact only one exit writes is blind exactly where a run died.
    All eight `_finalize` calls must pass the timings."""
    import inspect
    src = inspect.getsource(V)
    total = src.count("return _finalize(")
    wired = src.count("phases_1203g8=_phase_timings_1203g8")
    assert total >= 8, total
    assert wired == total, "%d of %d return paths pass the timings" % (wired, total)


def test_the_writer_is_called_from_finalize_only():
    import inspect
    src = inspect.getsource(V._finalize)
    assert "record_phase_timings_1203g8(" in src


def test_the_clock_is_monotonic_not_wall():
    """`perf_counter`, not `time.time()`: a wall clock that steps during a 6-minute validation
    would charge a phase for the step."""
    import inspect
    src = inspect.getsource(V.run_smoke_validation)
    assert "perf_counter" in src
    i = src.index("_phase_t0_1203g8")
    j = src.index("perf_counter", i)
    assert j - i < 200, "the phase clock is not perf_counter"
