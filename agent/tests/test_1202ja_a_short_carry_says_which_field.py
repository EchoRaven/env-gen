"""#1202ja: one unreadable carry field must not abandon the others, and must not be silent.

Every carried field was assigned inside one `try` whose `except` was a bare `pass`. A single
unreadable value abandoned the rest: with `alive_before_this_run` set to a non-numeric string,
the carry kept `usd_before_this_run` and dropped `alive_before_this_run` to 0.0 and `runs` to
1 — silently. `alive_before_this_run` is what bounds lane time (#1202fk) and what
`_snapshot_budget_1202ia` reads, so the run believed it had runway it had already spent.

Per-field, NOT all-or-nothing. The first draft of the fix adopted the carry only when every
field read, which threw away a `usd_before_this_run` that WAS correct and left the spend cap
looser than before — worse, on the path that governs money. These are independent
accumulators; one being unreadable does not make another wrong.

Latent, not observed: the seven corpus ledgers with `usd_before>0, alive=0` that look like
this fingerprint are version skew, written 09-05..09-07 before #1202fk added the field, with
`runs` intact.
"""
import sys
import json
import pathlib
import logging

_AGENT = pathlib.Path(__file__).resolve().parents[1]
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

from env_generator.llm_generator.multi_agent.runtime.run_budget import RunBudget  # noqa: E402


_LEDGER = {
    "usage": {"started_at": 100.0, "elapsed_sec": 600},
    "llm": {"usd": 120.0, "calls": 50},
    "cumulative_1202cg": {"usd_before_this_run": 300.0,
                          "alive_before_this_run": 3600.0,
                          "calls_before_this_run": 200,
                          "runs": 3, "first_started_at": 1.0},
}


def _carry(tmp_path, ledger, caplog=None):
    rb = RunBudget(tmp_path, logging.getLogger("t1202ja"))
    p = rb.path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(ledger if isinstance(ledger, str) else json.dumps(ledger))
    rb._carry_1202cg = None
    return rb._carry_1202cg_for(999.0,
                                {"llm": {"usd": 5.0, "calls": 2},
                                 "usage": {"elapsed_sec": 60}})


def test_an_intact_ledger_is_unchanged(tmp_path):
    c = _carry(tmp_path, _LEDGER)
    assert c["usd_before_this_run"] == 420.0      # 300 carried + 120 from the prior process
    assert c["alive_before_this_run"] == 4200.0   # 3600 + that process's 600
    assert c["runs"] == 4


def test_one_bad_field_does_not_take_the_others_with_it(tmp_path, caplog):
    bad = json.loads(json.dumps(_LEDGER))
    bad["cumulative_1202cg"]["alive_before_this_run"] = "n/a"
    with caplog.at_level(logging.WARNING):
        c = _carry(tmp_path, bad)
    # the money carry is INTACT — the first draft of this fix zeroed it
    assert c["usd_before_this_run"] == 420.0, c
    assert c["runs"] == 4, c
    # and only the unreadable one is short
    assert c["alive_before_this_run"] == 600.0, c


def test_it_names_the_field_that_did_not_read(tmp_path, caplog):
    bad = json.loads(json.dumps(_LEDGER))
    bad["cumulative_1202cg"]["alive_before_this_run"] = "n/a"
    with caplog.at_level(logging.WARNING):
        _carry(tmp_path, bad)
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "#1202ja" in msg, msg
    assert "alive_before_this_run" in msg, msg
    # and does NOT claim the other fields failed
    assert "usd_before_this_run" not in msg, msg


def test_an_unreadable_ledger_is_audible(tmp_path, caplog):
    """A carry that reads as zero is indistinguishable from a first run, and the difference
    is whether the caps have anything to enforce."""
    with caplog.at_level(logging.WARNING):
        c = _carry(tmp_path, "{not json")
    assert c["usd_before_this_run"] == 0.0
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "#1202ja" in msg and "ledger" in msg, msg


def test_a_healthy_read_stays_quiet(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        _carry(tmp_path, _LEDGER)
    assert not [r for r in caplog.records if "#1202ja" in r.getMessage()]


def test_a_missing_field_is_not_a_failure(tmp_path, caplog):
    """An ABSENT key is a first run or an older ledger, not a fault — #1202fk added
    `alive_before_this_run` on 09-07 and every ledger written before it lacks the key.
    Warning on those would cry wolf on every resume of an older run."""
    old = json.loads(json.dumps(_LEDGER))
    del old["cumulative_1202cg"]["alive_before_this_run"]
    with caplog.at_level(logging.WARNING):
        c = _carry(tmp_path, old)
    assert c["usd_before_this_run"] == 420.0
    assert not [r for r in caplog.records if "#1202ja" in r.getMessage()], caplog.records
