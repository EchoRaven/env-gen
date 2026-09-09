r"""#1202ii: an explicit env var is an instruction, not a default.

`load_caps` prefers the caps persisted in run_budget.json. That is right for the case its
docstring names — a UI raising a cap mid-run, which the process then re-reads. It is wrong
for the case an operator actually hits: `--resume` inherits the ORIGINAL run's caps
forever, so

    ENVGEN_MAX_WALLCLOCK_SEC=18000 NAME=... RESUME=1 bash run_validation.sh

was obeyed by nothing and reported by nobody. tiktok-r107 was launched that way twice and
stopped both times on "wall-clock 10876s exceeded cap 10800s" — the number from its first
process, hours earlier, while its ledger and its log both stated the cap it was actually
enforcing and neither mentioned the one that had been asked for.
"""
from __future__ import annotations

import json
import logging

import pytest

from env_generator.llm_generator.multi_agent.runtime.run_budget import RunBudget

STORED = {"max_wall_sec": 10800.0, "max_ticks": 200, "unlimited": False}
ENV = {"max_wall_sec": 18000.0, "max_ticks": 200, "unlimited": False}


@pytest.fixture
def ledger(tmp_path):
    (tmp_path / "run_budget.json").write_text(json.dumps({"caps": dict(STORED)}))
    return RunBudget(tmp_path, logging.getLogger("test_1202ii"))


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for v in ("ENVGEN_MAX_WALLCLOCK_SEC", "ENVGEN_MAX_TICKS"):
        monkeypatch.delenv(v, raising=False)


def test_without_the_env_var_the_stored_cap_wins(ledger):
    """The UI-raise case the docstring names must keep working."""
    assert ledger.load_caps(ENV)["max_wall_sec"] == 10800.0


def test_an_explicitly_set_env_var_wins(ledger, monkeypatch):
    """The r107 case: the operator raised it and was ignored twice."""
    monkeypatch.setenv("ENVGEN_MAX_WALLCLOCK_SEC", "18000")
    assert ledger.load_caps(ENV)["max_wall_sec"] == 18000.0


def test_lowering_is_honoured_too(ledger, monkeypatch):
    """An instruction is an instruction; a smoke run may want a shorter clock."""
    monkeypatch.setenv("ENVGEN_MAX_WALLCLOCK_SEC", "600")
    assert ledger.load_caps({**ENV, "max_wall_sec": 600.0})["max_wall_sec"] == 600.0


def test_ticks_are_overridable_the_same_way(ledger, monkeypatch):
    monkeypatch.setenv("ENVGEN_MAX_TICKS", "500")
    assert ledger.load_caps({**ENV, "max_ticks": 500})["max_ticks"] == 500


def test_the_override_keeps_the_stored_type(ledger, monkeypatch):
    monkeypatch.setenv("ENVGEN_MAX_TICKS", "500")
    out = ledger.load_caps({**ENV, "max_ticks": 500})
    assert isinstance(out["max_ticks"], int)
    monkeypatch.setenv("ENVGEN_MAX_WALLCLOCK_SEC", "18000")
    assert isinstance(ledger.load_caps(ENV)["max_wall_sec"], float)


def test_an_equal_value_is_not_announced(ledger, monkeypatch, caplog):
    """Nothing was overridden, so nothing should be claimed."""
    monkeypatch.setenv("ENVGEN_MAX_WALLCLOCK_SEC", "10800")
    with caplog.at_level(logging.WARNING):
        ledger.load_caps({**ENV, "max_wall_sec": 10800.0})
    assert not [r for r in caplog.records if "#1202ii" in r.getMessage()]


def test_the_override_is_announced(ledger, monkeypatch, caplog):
    """Silently obeying is only half a fix — the previous behaviour was silent too."""
    monkeypatch.setenv("ENVGEN_MAX_WALLCLOCK_SEC", "18000")
    with caplog.at_level(logging.WARNING):
        ledger.load_caps(ENV)
    msgs = [r.getMessage() for r in caplog.records if "#1202ii" in r.getMessage()]
    assert msgs and "10800" in msgs[0] and "18000" in msgs[0]


def test_a_missing_ledger_still_returns_the_env(tmp_path):
    b = RunBudget(tmp_path, logging.getLogger("test_1202ii"))
    assert b.load_caps(ENV)["max_wall_sec"] == 18000.0


def test_a_corrupt_ledger_still_returns_the_env(tmp_path):
    (tmp_path / "run_budget.json").write_text("{broken")
    b = RunBudget(tmp_path, logging.getLogger("test_1202ii"))
    assert b.load_caps(ENV)["max_wall_sec"] == 18000.0


def test_the_env_names_match_what_the_launcher_exports():
    """A rename on either side would make this silently inert again."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    sh = (root / "run_validation.sh").read_text()
    for var in RunBudget._CAP_ENV_1202II.values():
        assert var in sh, f"{var} is not the name the launcher sets"
