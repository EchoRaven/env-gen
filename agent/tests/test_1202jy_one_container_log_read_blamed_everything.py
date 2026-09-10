"""#1202jy: #1202gs's cache had no expiry, so one log read spoke for a whole run.

`_backend_traceback_1202gs` reads the container log's tail when a step 5xxes, and cached the
result per project "so a chain of failing steps costs one read, not one per step". A chain is
a burst of seconds; a run is hours. Both directions of that cache were wrong:

  * a "" cached from the first 5xx blinded every later one — 46 of the 57 recent 5xx steps
    carry no traceback at all;
  * a HIT cached from the first 5xx was ATTRIBUTED to every later one. tiktok-r103's eleven
    5xx steps all carry the SAME traceback: `GET /api/messages` and
    `POST /api/videos/{uuid}/comments` are both blamed on `_public_video_direct_middleware`,
    the cause of a different failure minutes earlier. Ten false attributions from one read.

The second is the worse half and the class this session keeps finding — #1202jk's note named
the wrong table, and this names the wrong exception.

A short TTL serves the stated purpose exactly. The negative window is shorter still: a ""
is not a fact about the app, only about when we looked.
"""
import sys
import pathlib

_AGENT = pathlib.Path(__file__).resolve().parents[1]
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

import ast                                                             # noqa: E402
import inspect                                                        # noqa: E402

from env_generator.llm_generator.multi_agent.runtime import chain_executor as CE  # noqa: E402


def _fresh_cache():
    """The default-arg cache is shared across calls — every test must start clean."""
    CE._backend_traceback_1202gs.__defaults__[0].clear()


def test_a_hit_expires_so_a_later_failure_is_not_blamed_on_it(monkeypatch, tmp_path):
    """★ r103's shape: one read attributed to eleven unrelated 5xx."""
    _fresh_cache()
    (tmp_path / "docker").mkdir()
    (tmp_path / "docker" / "docker-compose.yml").write_text("services: {}\n")

    calls = []

    class _R:
        stdout, stderr = "boom", ""

    def _run(*a, **k):
        calls.append(1)
        return _R()

    import subprocess as _sp
    import time as _t
    monkeypatch.setattr(_sp, "run", _run)
    monkeypatch.setattr(CE, "_last_exception_1202gs", lambda t: "trace")
    clock = {"t": 1000.0}
    monkeypatch.setattr(_t, "monotonic", lambda: clock["t"])

    first = CE._backend_traceback_1202gs(str(tmp_path), 500)
    assert first == "trace" and len(calls) == 1, (calls, first)

    same = CE._backend_traceback_1202gs(str(tmp_path), 500)
    assert same == "trace" and len(calls) == 1, "a burst must still cost one read"

    clock["t"] += CE._TTL_1202JY + 1
    CE._backend_traceback_1202gs(str(tmp_path), 500)
    assert len(calls) == 2, (
        "past the window this must read again — otherwise a minutes-later 5xx inherits the "
        "cause of an earlier, different one")


def test_an_empty_read_does_not_blind_the_rest_of_the_run(monkeypatch, tmp_path):
    """★ The other direction: 46 of 57 recent 5xx carry nothing, which is what a cached ""
    looks like from outside."""
    _fresh_cache()
    (tmp_path / "docker").mkdir()
    (tmp_path / "docker" / "docker-compose.yml").write_text("services: {}\n")
    calls = []

    class _R:
        stdout, stderr = "", ""

    import subprocess as _sp
    import time as _t
    monkeypatch.setattr(_sp, "run", lambda *a, **k: (calls.append(1), _R())[1])
    monkeypatch.setattr(CE, "_last_exception_1202gs", lambda t: "")
    clock = {"t": 500.0}
    monkeypatch.setattr(_t, "monotonic", lambda: clock["t"])

    assert CE._backend_traceback_1202gs(str(tmp_path), 500) == ""
    clock["t"] += CE._NEG_TTL_1202JY + 0.5
    CE._backend_traceback_1202gs(str(tmp_path), 500)
    assert len(calls) == 2, "an empty read must expire quickly, not decide the run"


def test_a_negative_expires_faster_than_a_hit():
    """A "" says only when we looked. It must not decide the rest of the run."""
    assert CE._NEG_TTL_1202JY < CE._TTL_1202JY


def test_the_window_is_seconds_not_a_run():
    """The stated purpose is 'a chain of failing steps costs one read' — that is a burst."""
    assert 0 < CE._TTL_1202JY <= 60, CE._TTL_1202JY


def test_a_sub_500_status_still_costs_nothing():
    """#647's bound: a 404 is the server ANSWERING; reading a log for it buys nothing."""
    _fresh_cache()
    assert CE._backend_traceback_1202gs("/proj", 404) == ""
    assert CE._backend_traceback_1202gs("/proj", "not-a-number") == ""


def test_the_record_says_what_the_trace_actually_is():
    """★ Naming it `server_traceback` beside a path invites reading it as THIS request's."""
    src = inspect.getsource(CE.execute_chain)
    i = src.index('entry["server_traceback"] = _tb1202gs')
    # #943: a landmark, not a byte count — the block below grew while this was being written.
    tail = src[i:src.index("if autofilled:", i)]
    assert 'entry["server_traceback_is"]' in tail
    assert "NOT a" in tail and "most recent logged exception" in tail, (
        "the label must say it is the log tail shared by nearby 5xx, not a per-request trace")


def test_the_cache_stores_a_timestamp_not_a_bare_string():
    """Non-vacuity: the TTL is inert unless the entry carries when it was taken."""
    tree = ast.parse(inspect.getsource(CE._backend_traceback_1202gs))
    stores = [n for n in ast.walk(tree)
              if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Subscript)]
    assert stores, "expected a cache write"
    assert any(isinstance(a.value, ast.Tuple) for a in stores), (
        "the cached value must be (taken_at, text)")
