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
import asyncio
import inspect
import pathlib
import types

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


# --- #1203pg: the sentence #712r restored, DRIVEN -----------------------------------------------
#
# This file adjudicated a claim and pinned the verdict as PROSE. The sentence it restored is
# #558's: "a single lucky pass never triggers a release; a round below the bar resets the count
# -- TRUE as written". Nothing verified the behaviour that sentence describes.
#
# Two mutations went through untouched: making the increment unreachable (so #558's fast release
# can never fire -- the exact cost #897 measured when the same path was disabled by a phantom
# key), and removing the reset (which makes the restored sentence FALSE). Only the quoted read
# statement had a driver, and it was the only mutation this file caught.
#
# Checked before writing these: `test_visual_avg_fast_release_558.py` (37 assertions, ratio
# 0.00), `test_visual_gate_resume_state_1202ce.py` and
# `test_fast_release_is_not_gated_on_a_phantom_key_897.py` all SET `avg_pass_rounds` directly.
# They own the CONSUMER -- the release decision and the resume round-trip. The producer, which
# is what #712 is about, was owned by nobody.


def _orch_712(box):
    _noop = lambda *a, **k: None  # noqa: E731

    class _Bus:
        async def send(self, *a, **k):
            return None

    return types.SimpleNamespace(
        _reference_images=[{"name": "inbox", "route": "/inbox", "auth": True, "path": "x.png"}],
        _compute_app_source_signature=lambda: box["sig"],
        output_dir=str(pathlib.Path(__file__).resolve().parents[1]),
        llm=None, message_bus=_Bus(),
        _logger=types.SimpleNamespace(warning=_noop, info=_noop, error=_noop, debug=_noop),
        hubs=types.SimpleNamespace(
            workhub=types.SimpleNamespace(create_task=lambda **k: {"id": "t1"})),
    )


def _round(gating, live=None):
    """One judged round whose GATING average is `gating`.

    `passed` stays False on purpose: `blocking_average` is #500's best-of-captures merge, so it
    can sit above the bar while the round itself did not pass -- which is the state #711/#712
    are entirely about.
    """
    async def _fake(*a, **k):
        out = {"passed": False, "capture_transient": False, "skipped": [],
               "summary": "merged above bar", "blocking_average": gating,
               "min_similarity": 0.65,
               "screens": [{"name": "inbox", "route": "/inbox", "similarity": gating,
                            "blank": False, "console_errors": [], "deviations": [], "fixes": []}]}
        if live is not None:
            out["blocking_average_live"] = live
        return out
    return _fake


def _run_rounds(monkeypatch, gatings):
    """Drive one round per entry and return `avg_pass_rounds` after each."""
    box = {"sig": "sig0"}
    gate = vf.VisualFidelityGate(_orch_712(box))
    gate.reset_for_milestone()
    seen = []
    for i, g in enumerate(gatings):
        monkeypatch.setattr(vf, "run_visual_fidelity", _round(g))
        box["sig"] = "round-%d" % i
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(gate.maybe_run())
        finally:
            loop.close()
        seen.append(gate.avg_pass_rounds)
    return seen


def test_a_round_at_or_above_the_bar_advances_the_count(monkeypatch):
    assert _run_rounds(monkeypatch, [0.80, 0.80]) == [1, 2]


def test_a_round_BELOW_the_bar_resets_the_count(monkeypatch):
    """#558's sentence, which #712r adjudicated as TRUE as written and this file pinned as prose.

    Without the reset a single lucky round would stand forever and the 'two consecutive rounds'
    precondition would stop being a precondition.
    """
    assert _run_rounds(monkeypatch, [0.80, 0.80, 0.50]) == [1, 2, 0]


def test_the_count_can_be_earned_again_after_a_reset(monkeypatch):
    assert _run_rounds(monkeypatch, [0.80, 0.50, 0.80]) == [1, 0, 1]


def test_exactly_at_the_bar_counts(monkeypatch):
    """`>=`, not `>`: the bar is the pass mark, so meeting it is passing it."""
    assert _run_rounds(monkeypatch, [0.65]) == [1]


def test_a_single_round_is_not_enough(monkeypatch):
    """"A single lucky pass never triggers a release" -- the count, not the flag, is the gate."""
    assert _run_rounds(monkeypatch, [0.80]) == [1]


def test_the_latched_average_warning_fires_when_this_capture_is_below_the_bar(monkeypatch):
    """#712's own evidence: the counter can advance on a merged average the capture did not earn,
    and that is exactly when the warning must speak."""
    msgs = []
    box = {"sig": "sig0"}
    orch = _orch_712(box)
    gate = vf.VisualFidelityGate(orch)
    gate.reset_for_milestone()
    monkeypatch.setattr(vf, "_LOG", types.SimpleNamespace(
        warning=lambda *a, **k: msgs.append((a[0] % a[1:]) if len(a) > 1 else str(a[0])),
        error=lambda *a, **k: None, info=lambda *a, **k: None, debug=lambda *a, **k: None))
    monkeypatch.setattr(vf, "run_visual_fidelity", _round(0.80, live=0.40))
    box["sig"] = "latched"
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(gate.maybe_run())
    finally:
        loop.close()
    assert gate.avg_pass_rounds == 1
    hit = [m for m in msgs if "avg_pass_rounds ->" in m]
    assert hit, "the counter advanced on a latched average and said nothing"
    assert "LATCHED average" in hit[0]
