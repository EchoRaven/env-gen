"""#1202cg — project spend across resumes.

run_budget.json's payload is rebuilt from scratch on every write, so a --resume starts the
ledger at zero. r35: the fresh run died having spent $163 by tick 24, the resume's ledger
then read $0.20, and nothing on disk said the project had cost $163 more than the number an
operator was reading. LOCAL-ONLY (agent/tests/ gitignored).
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.run_budget import RunBudget  # noqa: E402


class _Log:
    def debug(self, *a, **k):
        pass


CAPS = {"max_wall_sec": 3600.0, "max_ticks": 100, "unlimited": False}


def _write(tmp_path, started_at, usd, calls, monkeypatch):
    """Drive a write with a known llm_usage, the way a process would."""
    import utils.llm as _u
    monkeypatch.setattr(_u, "llm_usage", lambda: {"usd": usd, "calls": calls}, raising=False)
    monkeypatch.setattr(_u, "tool_result_bytes", lambda: {}, raising=False)
    rb = RunBudget(tmp_path, _Log())
    rb.write(CAPS, started_at, 10.0, 1, "running")
    return rb


def _read(tmp_path):
    return json.loads((tmp_path / "run_budget.json").read_text(encoding="utf-8"))


def test_a_first_run_reports_only_its_own_spend(tmp_path, monkeypatch):
    _write(tmp_path, 1000.0, 50.0, 400, monkeypatch)
    c = _read(tmp_path)["cumulative_1202cg"]
    assert c["usd_before_this_run"] == 0.0
    assert c["usd_total"] == 50.0
    assert c["runs"] == 1


def test_a_resume_carries_the_previous_process_forward(tmp_path, monkeypatch):
    """The r35 shape: $163 then a resume that reads $0.20."""
    _write(tmp_path, 1000.0, 163.35, 2104, monkeypatch)
    _write(tmp_path, 2000.0, 0.20, 4, monkeypatch)      # new process = new started_at
    c = _read(tmp_path)["cumulative_1202cg"]
    assert c["usd_before_this_run"] == 163.35
    assert c["usd_total"] == 163.55
    assert c["calls_total"] == 2108
    assert c["runs"] == 2


def test_three_processes_accumulate(tmp_path, monkeypatch):
    _write(tmp_path, 1000.0, 100.0, 100, monkeypatch)
    _write(tmp_path, 2000.0, 50.0, 50, monkeypatch)
    _write(tmp_path, 3000.0, 25.0, 25, monkeypatch)
    c = _read(tmp_path)["cumulative_1202cg"]
    assert c["usd_total"] == 175.0 and c["runs"] == 3


def test_repeated_writes_in_one_process_do_not_double_count(tmp_path, monkeypatch):
    """THE trap. The ledger is written several times a minute; re-deriving the carry on
    every write would add this run's own spend to itself over and over."""
    _write(tmp_path, 1000.0, 100.0, 100, monkeypatch)
    rb = _write(tmp_path, 2000.0, 10.0, 10, monkeypatch)
    for usd in (20.0, 30.0, 40.0):
        import utils.llm as _u
        monkeypatch.setattr(_u, "llm_usage", lambda usd=usd: {"usd": usd, "calls": 1},
                            raising=False)
        rb.write(CAPS, 2000.0, 10.0, 1, "running")
    c = _read(tmp_path)["cumulative_1202cg"]
    assert c["usd_before_this_run"] == 100.0, "the carry moved during the run"
    assert c["usd_total"] == 140.0


def test_the_first_start_is_kept(tmp_path, monkeypatch):
    """So a project's wall-clock can be measured across resumes, not just the last leg."""
    _write(tmp_path, 1000.0, 10.0, 10, monkeypatch)
    _write(tmp_path, 9000.0, 5.0, 5, monkeypatch)
    assert _read(tmp_path)["cumulative_1202cg"]["first_started_at"] == 1000.0


def test_an_unreadable_prior_ledger_starts_clean(tmp_path, monkeypatch):
    """Best-effort in the safe direction: accounting must never break the run record."""
    (tmp_path / "run_budget.json").write_text("{ not json", encoding="utf-8")
    _write(tmp_path, 1000.0, 7.0, 7, monkeypatch)
    c = _read(tmp_path)["cumulative_1202cg"]
    assert c["usd_before_this_run"] == 0.0 and c["usd_total"] == 7.0


def test_the_live_fields_are_untouched(tmp_path, monkeypatch):
    """The monitor and the abort path read `llm.usd` and `usage`; the carry rides beside
    them and must not change what either sees."""
    _write(tmp_path, 1000.0, 163.35, 2104, monkeypatch)
    _write(tmp_path, 2000.0, 0.20, 4, monkeypatch)
    d = _read(tmp_path)
    assert d["llm"]["usd"] == 0.20, "the per-process spend must stay the cap's basis"
    assert d["usage"]["started_at"] == 2000.0
