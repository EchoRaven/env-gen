r"""#712r: WITHDRAWN — the counter reads the current average, not the high-water mark.

#712 claimed that #558's "a single lucky pass never triggers a release; a round below the bar
resets the count" was false, on the grounds that `avg_pass_rounds` counts a monotonically
non-decreasing number. That is wrong and the original sentence stands.

The counter reads `result["blocking_average"]`, and `result` is what `run_visual_fidelity`
RETURNS: `_blocking_similarity_average(results)`, the CURRENT capture's blocking-only mean, with
no merging. The merged high-water value exists only in the PERSISTED record — verdict.json and
rounds.jsonl — written by `_persist_verdict`, which receives `results` and writes to disk without
touching the returned dict. Two numbers with the same name in two dicts; I verified monotonicity
on the persisted one and assumed the counter read it.

**r148 caught it.** Round 6 recorded gating 0.656 against live 0.61 with the bar at 0.65 — the
exact latch condition #712 described — and #712's warning fired ZERO times. It cannot fire at
all: `result` carries no `blocking_average_live` key, since `run_visual_fidelity`'s body never
mentions one, so the guard is always None. A dead branch protecting a false claim.

What survives, and is tested elsewhere: the PERSISTED record is a high-water mark that diverges
from the live capture (#711's warning, which is real and worth keeping). What does not survive is
the consequence — the record is not what authorises a release.

This file no longer tests a mechanism. It pins the retraction, so the false version cannot
quietly return.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf
from env_generator.llm_generator.multi_agent import orchestrator as orch


def _src() -> str:
    return inspect.getsource(vf)


def _r_block() -> str:
    """The #712r retraction, anchored on its own end rather than a character count."""
    s = _src()
    i = s.index("#712r")
    return s[i:s.index("~~#712: THE STRUCK-OUT SENTENCE IS FALSE", i)]


# --- the retraction is recorded, not silently reverted ---------------------------------------

def test_the_withdrawal_is_explicit():
    s = _src()
    assert "#712r — THIS WHOLE BLOCK IS WITHDRAWN" in s


def test_558s_original_sentence_is_restored_unstruck():
    s = _src()
    assert "a single lucky pass never triggers a release; a round below the" in s
    assert "bar resets the count — TRUE as written" in s


def test_the_strike_through_is_gone_from_558():
    s = _src()
    i = s.index("FIX #558: track consecutive REAL judgments")
    head = s[i:s.index("#712r", i)]
    assert "~~a single lucky pass" not in head


def test_the_reason_names_the_two_dicts():
    block = _r_block()
    assert "run_visual_fidelity RETURNS" in block
    assert "persisted record" in block


def test_r148s_disconfirming_evidence_is_recorded():
    s = _src()
    block = " ".join(_r_block().replace("#", " ").split())
    assert "0.656 against live 0.61" in block
    assert "fired ZERO times" in block


def test_the_dead_branch_is_named_as_such():
    s = _src()
    block = " ".join(_r_block().replace("#", " ").split())
    assert "dead branch" in block
    assert "written by me" in block


# --- the mechanism the retraction restores -------------------------------------------------------

def test_the_counter_still_reads_blocking_average():
    s = _src()
    assert '_ba = result.get("blocking_average")' in s


def test_the_reset_branch_still_exists():
    """It is reachable again, which is the whole point of the retraction."""
    s = _src()
    i = s.index('_ba = result.get("blocking_average")')
    assert "self.avg_pass_rounds = 0" in s[i:s.index("FIX #129", i)]


def test_the_returned_average_is_the_current_capture():
    """No merging in the value the decision path reads."""
    s = _src()
    assert "_blk_avg = _blocking_similarity_average(results)" in s
    body = inspect.getsource(vf._blocking_similarity_average)
    assert "prior" not in body and "merged" not in body.split('"""')[2]


def test_the_release_path_reads_the_returned_dict_not_the_record():
    s = inspect.getsource(orch._visual_fast_release_args)
    assert 'getattr(gate, "last_result", None)' in s
    assert 'res.get("blocking_average")' in s


def test_the_default_n_is_unchanged():
    assert orch.VISUAL_AVG_RELEASE_ROUNDS == 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
