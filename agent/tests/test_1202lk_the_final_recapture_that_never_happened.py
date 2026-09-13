"""#1202lk — the final pre-release re-judge produced NO verdict, and the run shipped anyway.

GROUND TRUTH (tiktok-web-r120, 2026-09-12, from the run's own orchestrator log):

    18:59:51  verdict.json written — blocking_average 0.5487, 2 total judgments
    19:16:59  Visual fidelity: capture unavailable — 0 of 8 screen(s) photographed; not judged
              — the capture raised explore_grid: Error: Page.g…
    19:16:59  Visual fidelity deferral RELEASED (escape after 2734s deferred / 0 attempts /
              2 total judged) — delivering anyway
    19:17:59  FINAL DELIVERY 1.2.0
    19:18     app/frontend/src/App.jsx last modified — the lane was STILL editing

#102's comment promises the opposite of what happened: *"the recorded score then reflects the
DELIVERED source"*. It does not, whenever that final capture photographs nothing — the
`capture_unavailable` channel returns WITHOUT touching `last_result`/`last_judged_sig`, so the
release reads a verdict from earlier code and no artifact records that it did.

Both halves are asserted here: RETRY (bounded, with the per-source attempt budget re-armed so
the retry can actually photograph) and STAMP (provenance on verdict.json when the budget is
spent). Each structural assertion carries a counter-proof: the same locator run against source
with the mechanism removed must FAIL.
"""
import ast
import json
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf

# Read the orchestrator as TEXT rather than importing it: the module pulls `utils.*` from the
# runtime's own sys.path, which a bare pytest process does not have, and every assertion below
# is about its source structure anyway.
_ORCH_PATH = (Path(__file__).resolve().parent.parent
              / "env_generator" / "llm_generator" / "multi_agent" / "orchestrator.py")


class _FakeLogger:
    def __init__(self):
        self.lines = []

    def warning(self, msg, *a):
        self.lines.append(msg % a if a else msg)

    info = debug = error = warning


class _FakeOrch:
    def __init__(self, tmp, sig):
        self.output_dir = str(tmp)
        self._sig = sig
        self._logger = _FakeLogger()

    def _compute_app_source_signature(self):
        if isinstance(self._sig, Exception):
            raise self._sig
        return self._sig


def _gate(tmp, sig):
    return vf.VisualFidelityGate(_FakeOrch(tmp, sig))


# ---------------------------------------------------------------- coverage predicate

def test_a_stale_verdict_is_not_coverage(tmp_path):
    """r120's exact shape: a last_result exists, judged from a DIFFERENT source."""
    g = _gate(tmp_path, "delivered-sig")
    g.last_result = {"passed": False, "blocking_average": 0.5487}   # r120 had one
    g.last_judged_sig = "eighteen-minutes-ago"
    assert g.verdict_covers_delivered_source_1202lk() is False


def test_a_judgment_of_the_delivered_source_is_coverage(tmp_path):
    g = _gate(tmp_path, "same-sig")
    g.last_judged_sig = "same-sig"
    assert g.verdict_covers_delivered_source_1202lk() is True


@pytest.mark.parametrize("sig,judged", [
    (None, "x"),                 # signature uncomputable
    ("x", None),                 # nothing judged yet this milestone
    (RuntimeError("boom"), "x"),  # signature raised
])
def test_unknown_provenance_is_never_claimed_as_coverage(tmp_path, sig, judged):
    g = _gate(tmp_path, sig)
    g.last_judged_sig = judged
    assert g.verdict_covers_delivered_source_1202lk() is False


# ---------------------------------------------------------------- the retry budget

def test_the_retry_is_bounded_and_rearms_the_attempt_budget(tmp_path):
    g = _gate(tmp_path, "s")
    cap = vf._FINAL_RECAPTURE_TRIES_1202LK
    assert cap >= 1
    for i in range(cap):
        g.attempts = 3                    # the cap that made the retry a no-op
        assert g.arm_final_recapture_1202lk() is True
        assert g.attempts == 0, "a retry that cannot photograph is not a retry"
        assert g.final_recaptures_1202lk == i + 1
    g.attempts = 3
    assert g.arm_final_recapture_1202lk() is False, "the budget must be spendable"
    assert g.attempts == 3, "a refused arm must not hand out a fresh judging budget"


def test_the_retry_budget_survives_a_resume(tmp_path):
    """Milestone-anchored + persisted (#1202ce), so a resume cannot mint a second budget."""
    assert "final_recaptures_1202lk" in vf.VisualFidelityGate._STATE_FIELDS_1202CE
    g = _gate(tmp_path, "s")
    g._milestone_key_1202ce = "milestone:0:core"
    g.final_recaptures_1202lk = 2
    g._save_state_1202ce()
    g2 = _gate(tmp_path, "s")
    assert g2._load_state_1202ce("milestone:0:core") is True
    assert g2.final_recaptures_1202lk == 2


def test_a_new_milestone_gets_its_own_budget(tmp_path):
    g = _gate(tmp_path, "s")
    g.final_recaptures_1202lk = 3
    g.reset_for_milestone("milestone:1:next")
    assert g.final_recaptures_1202lk == 0


# ---------------------------------------------------------------- the provenance stamp

def _write_verdict(tmp_path, **extra):
    vdir = tmp_path / "design" / "visual_gate"
    vdir.mkdir(parents=True)
    blob = {"passed": False, "blocking_average": 0.5487,
            "screens": [{"name": "explore_grid", "similarity": 0.42}]}
    blob.update(extra)
    (vdir / "verdict.json").write_text(json.dumps(blob), encoding="utf-8")
    return vdir / "verdict.json"


def test_an_uncovered_verdict_is_stamped_and_says_why(tmp_path):
    vp = _write_verdict(tmp_path)
    assert vf.stamp_delivery_coverage_1202lk(tmp_path, "old", "new", False) is True
    blob = json.loads(vp.read_text(encoding="utf-8"))
    assert blob["reflects_delivered_source_1202lk"] is False
    assert blob["judged_source_sig_1202lk"] == "old"
    assert blob["delivered_source_sig_1202lk"] == "new"
    assert "NOT judged from the source that shipped" in blob["delivery_coverage_note_1202lk"]
    # additive only: it must not touch a single score or the pass/fail
    assert blob["passed"] is False and blob["blocking_average"] == 0.5487
    assert blob["screens"] == [{"name": "explore_grid", "similarity": 0.42}]


def test_a_covered_verdict_is_stamped_true_without_the_warning_note(tmp_path):
    vp = _write_verdict(tmp_path)
    assert vf.stamp_delivery_coverage_1202lk(tmp_path, "same", "same", True) is True
    blob = json.loads(vp.read_text(encoding="utf-8"))
    assert blob["reflects_delivered_source_1202lk"] is True
    assert "delivery_coverage_note_1202lk" not in blob


def test_the_stamp_never_raises_and_never_invents_a_verdict(tmp_path):
    # no verdict.json at all — the gate may never have run
    assert vf.stamp_delivery_coverage_1202lk(tmp_path, "a", "b", False) is False
    assert not (tmp_path / "design").exists()
    # unparseable verdict: report failure, do not clobber what is there
    vdir = tmp_path / "design" / "visual_gate"
    vdir.mkdir(parents=True)
    (vdir / "verdict.json").write_text("{not json", encoding="utf-8")
    assert vf.stamp_delivery_coverage_1202lk(tmp_path, "a", "b", False) is False
    assert (vdir / "verdict.json").read_text(encoding="utf-8") == "{not json"


# ---------------------------------------------------------------- the release wiring

def _deliver_src():
    """The orchestrator method holding the visual release branch, by landmark (#943: no
    byte windows — locate the enclosing function from the log string itself)."""
    src = _ORCH_PATH.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        seg = ast.get_source_segment(src, node) or ""
        if "Visual fidelity deferral RELEASED" in seg:
            return seg
    raise AssertionError("the visual release branch moved — relocate this test's landmark")


def _retry_branch(seg):
    """The `elif _retry_1202lk:` body, located structurally."""
    for node in ast.walk(ast.parse(seg)):
        if (isinstance(node, ast.If)
                and isinstance(node.test, ast.Name)
                and node.test.id == "_retry_1202lk"):
            return node
    return None


def test_the_retry_defers_the_tick_instead_of_releasing():
    node = _retry_branch(_deliver_src())
    assert node is not None, "the #1202lk retry branch is gone"
    assert isinstance(node.body[-1], ast.Return), (
        "the retry branch must RETURN — falling through would release on the very "
        "stale verdict the retry exists to replace")


def test_the_retry_branch_is_not_dead_code():
    """`_retry_1202lk` must be ASSIGNED from the gate call, not pinned to a constant."""
    seg = _deliver_src()
    tree = ast.parse(seg)
    arms = [n for n in ast.walk(tree)
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "_retry_1202lk" for t in n.targets)]
    assert arms, "_retry_1202lk is never assigned"
    assert any("arm_final_recapture_1202lk" in (ast.get_source_segment(seg, a) or "")
               for a in arms), "the retry gate never asks the budget whether it may retry"


def test_both_release_paths_stamp_provenance():
    seg = _deliver_src()
    assert seg.count("_stamp_visual_delivery_coverage_1202lk") >= 3, (
        "every path that ships — passed, escaped, fast-released — must record whether its "
        "verdict covers the delivered source")


def test_the_release_branch_stamps_before_it_announces():
    """The escape path must not announce a release it has not yet given provenance to."""
    seg = _deliver_src()
    i_stamp = seg.index("self._stamp_visual_delivery_coverage_1202lk(_covered_1202lk)\n"
                        "                        _plat")
    i_rel = seg.index("Visual fidelity deferral RELEASED")
    assert i_stamp < i_rel


# ---------------------------------------------------------------- counter-proofs

def test_counterproof_removing_the_return_goes_red():
    """Delete the retry's `return` and the ordering assertion above must fail."""
    seg = _deliver_src()
    mutated = seg.replace(
        "                            self._final_recapture_cap_1202lk())\n"
        "                        return\n",
        "                            self._final_recapture_cap_1202lk())\n", 1)
    assert mutated != seg, "the mutation landmark moved — this counter-proof is vacuous"
    node = _retry_branch(mutated)
    assert node is not None
    assert not isinstance(node.body[-1], ast.Return)


def test_counterproof_a_constant_gate_is_caught():
    """Pin `_retry_1202lk` to a literal and the dead-code assertion must fail."""
    seg = _deliver_src()
    mutated = seg.replace("_retry_1202lk = bool(self._vf_gate.arm_final_recapture_1202lk())",
                          "_retry_1202lk = False", 1)
    assert mutated != seg, "the mutation landmark moved — this counter-proof is vacuous"
    tree = ast.parse(mutated)
    arms = [n for n in ast.walk(tree)
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "_retry_1202lk" for t in n.targets)]
    assert arms
    assert not any("arm_final_recapture_1202lk" in (ast.get_source_segment(mutated, a) or "")
                   for a in arms)


def test_counterproof_the_coverage_predicate_is_not_vacuously_true(tmp_path):
    """If it answered from `last_result` (as a naive fix would), r120 would pass as covered."""
    g = _gate(tmp_path, "delivered")
    g.last_result = {"passed": False}
    g.last_judged_sig = "stale"
    assert g.verdict_covers_delivered_source_1202lk() is False
    g.last_judged_sig = "delivered"
    assert g.verdict_covers_delivered_source_1202lk() is True
