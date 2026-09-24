"""#1202ce — the visual gate's milestone progress must survive a --resume.

A resumed run constructs a NEW VisualFidelityGate, so every counter started at zero. That
is not a cosmetic difference: `_visual_release_decision` escapes on
`(now - deferred_since) > escape_s`, so a run 50 minutes into its deferral lost all of it
and had to earn the escape again; `plateau_rounds` / `avg_pass_rounds` are the other two
escape preconditions; `released` is #521's sticky latch, so a milestone that already
escaped would re-defer; `attempts` is the per-source judging budget, so a resume silently
granted three more PAID judgments on source that had already spent them; and
`_verdict_cache` is pixel-keyed (#142), so losing it means paying to re-judge an identical
screenshot.

LOCAL-ONLY (agent/tests/ gitignored).
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.visual_fidelity import VisualFidelityGate  # noqa: E402


class _Orch:
    def __init__(self, d):
        self.output_dir = d


def _gate(tmp_path):
    return VisualFidelityGate(_Orch(tmp_path))


def _state_file(tmp_path):
    return tmp_path / "design" / "visual_gate" / "gate_state.json"


def _populate(g, key="milestone:1:core@0.1.0"):
    g._milestone_key_1202ce = key
    g.sig = "src-abc"
    g.attempts = 2
    g.passed = False
    g.deferred_since = 1000.0
    g.total_judgments = 7
    g.transient_refunds = 1
    g.unreachable_refunds = 2
    g.plateau_rounds = 3
    g.avg_pass_rounds = 2
    g.released = True
    g._passed_screens = {"login", "browse_home"}
    g._best_by_screen = {"login": 0.81, "browse_home": 0.62}
    g._verdict_cache = {"login|md5abc": {"similarity": 0.81}}
    return g


def test_a_fresh_gate_with_no_state_file_keeps_its_defaults(tmp_path):
    g = _gate(tmp_path)
    assert g.attempts == 0 and g.deferred_since is None and g.released is False


def test_the_counters_survive_a_new_gate(tmp_path):
    _populate(_gate(tmp_path))._save_state_1202ce()
    g2 = _gate(tmp_path)
    g2.reset_for_milestone("milestone:1:core@0.1.0")   # a resume re-entering it
    assert g2.deferred_since == 1000.0
    assert g2.attempts == 2
    assert g2.total_judgments == 7
    assert g2.plateau_rounds == 3
    assert g2.avg_pass_rounds == 2
    assert g2.released is True
    assert g2.unreachable_refunds == 2


def test_the_deferral_clock_specifically(tmp_path):
    """The one that decides the wall-clock escape."""
    g = _gate(tmp_path)
    g._milestone_key_1202ce = "m1"
    g.deferred_since = 12345.0
    g._save_state_1202ce()
    g2 = _gate(tmp_path)
    g2.reset_for_milestone("m1")
    assert g2.deferred_since == 12345.0


def test_the_pass_latch_and_best_scores_survive(tmp_path):
    _populate(_gate(tmp_path))._save_state_1202ce()
    g2 = _gate(tmp_path)
    g2.reset_for_milestone("milestone:1:core@0.1.0")
    assert g2._passed_screens == {"login", "browse_home"}
    assert g2._best_by_screen == {"login": 0.81, "browse_home": 0.62}


def test_the_verdict_cache_survives_so_identical_pixels_are_not_re_judged(tmp_path):
    _populate(_gate(tmp_path))._save_state_1202ce()
    g2 = _gate(tmp_path)
    g2.reset_for_milestone("milestone:1:core@0.1.0")
    assert g2._verdict_cache == {"login|md5abc": {"similarity": 0.81}}


def test_re_entering_the_same_milestone_keeps_the_progress(tmp_path):
    """THE property. reset_for_milestone fires on every pass through the milestone loop,
    so without this a resume wiped the state it had just restored."""
    _populate(_gate(tmp_path))._save_state_1202ce()
    g2 = _gate(tmp_path)
    g2.reset_for_milestone("milestone:1:core@0.1.0")
    assert g2.deferred_since == 1000.0 and g2.total_judgments == 7
    assert g2.released is True and g2._passed_screens == {"login", "browse_home"}


def test_advancing_to_the_next_milestone_still_resets(tmp_path):
    """The behaviour this must not break: a NEW milestone anchors fresh counters."""
    _populate(_gate(tmp_path))._save_state_1202ce()
    g2 = _gate(tmp_path)
    g2.reset_for_milestone("milestone:2:social@0.2.0")
    assert g2.deferred_since is None and g2.total_judgments == 0
    assert g2.released is False and g2._passed_screens == set()
    assert g2.plateau_rounds == 0 and g2.avg_pass_rounds == 0


def test_a_caller_that_names_no_milestone_resets_unconditionally(tmp_path):
    """Backward compatibility for any call site not updated."""
    _populate(_gate(tmp_path))._save_state_1202ce()
    g2 = _gate(tmp_path)
    g2.reset_for_milestone()
    assert g2.deferred_since is None and g2.released is False


def test_a_reset_lands_on_disk(tmp_path):
    """Otherwise a crash right after a milestone advance would resume into the PREVIOUS
    milestone's counters."""
    _populate(_gate(tmp_path))._save_state_1202ce()
    g2 = _gate(tmp_path)
    g2.reset_for_milestone("milestone:2:social@0.2.0")
    g3 = _gate(tmp_path)
    g3.reset_for_milestone("milestone:2:social@0.2.0")
    assert g3.deferred_since is None
    assert json.loads(_state_file(tmp_path).read_text())["_milestone_key_1202ce"] == \
        "milestone:2:social@0.2.0"


def test_an_unreadable_state_file_leaves_defaults(tmp_path):
    """Best-effort in the safe direction: worst case is today's behaviour."""
    f = _state_file(tmp_path)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("{ not json", encoding="utf-8")
    g = _gate(tmp_path)
    g.reset_for_milestone("m1")
    assert g.attempts == 0 and g.deferred_since is None


def test_a_state_file_of_the_wrong_shape_leaves_defaults(tmp_path):
    f = _state_file(tmp_path)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("[1, 2, 3]", encoding="utf-8")
    g = _gate(tmp_path); g.reset_for_milestone("m1")
    assert g.attempts == 0


def test_the_write_is_atomic_and_leaves_no_temp(tmp_path):
    """JsonStore's lesson (#1202ap): a half-written temp left behind fills a disk that is
    already full."""
    _populate(_gate(tmp_path))._save_state_1202ce()
    leftovers = [p.name for p in _state_file(tmp_path).parent.iterdir()
                 if p.name.endswith(".tmp")]
    assert leftovers == []


def test_maybe_run_persists_on_every_exit_path():
    """The body has eight returns; a counter that reached disk on only some of them would be
    worse than one that never did. The finally lives at the CALL SITE — wrapping maybe_run
    meant renaming its body, and seven tests read it with inspect.getsource to assert the
    mechanisms recorded inside it. #943: landmark anchors."""
    src = (LLM / "multi_agent" / "orchestrator.py").read_text(encoding="utf-8")
    i = src.index("async def _maybe_run_visual_fidelity")
    body = src[i:src.index("async def ", i + 40)]
    assert "try:" in body and "finally:" in body and "_save_state_1202ce()" in body


def test_the_gate_method_tests_read_still_carries_its_mechanisms():
    """The regression this replaced: seven tests assert on inspect.getsource(maybe_run).
    A wrapper would hand them eight lines and every assertion would silently pass nothing."""
    import inspect
    from multi_agent.runtime.visual_fidelity import VisualFidelityGate
    body = inspect.getsource(VisualFidelityGate.maybe_run)
    assert "#737: A BLACKOUT CANNOT IMPROVE" in body
    assert len(body.splitlines()) > 100


def test_the_orchestrator_names_the_milestone():
    src = (LLM / "multi_agent" / "orchestrator.py").read_text(encoding="utf-8")
    assert "self._vf_gate.reset_for_milestone(_mkey)" in src


# --- the other two milestone-scoped deferral gates -------------------------------------

from multi_agent.runtime.milestone_resume import (  # noqa: E402
    save_gate_counters_1202ce, restore_gate_counters_1202ce)

GATE_FIELDS = ("_pages_gate_deferred_since", "_pages_gate_attempts",
               "_tu_squad_passed", "_tu_squad_deferred_since", "_tu_squad_attempts")
RUN_SCOPED = ("_rc_deferred_since", "_rc_attempts",
              "_tu_browser_deferred_since", "_tu_browser_attempts")


class _OrchGates:
    def __init__(self, d):
        self.output_dir = d
        self._pages_gate_deferred_since = None
        self._pages_gate_attempts = 0
        self._tu_squad_passed = False
        self._tu_squad_deferred_since = None
        self._tu_squad_attempts = 0


def _loaded(tmp_path):
    o = _OrchGates(tmp_path)
    o._pages_gate_deferred_since = 500.0
    o._pages_gate_attempts = 2
    o._tu_squad_passed = True
    o._tu_squad_deferred_since = 700.0
    o._tu_squad_attempts = 3
    return o


def test_the_page_and_squad_clocks_survive_the_same_milestone(tmp_path):
    """pages_release_decision escapes on (now - deferred_since) > escape_s, exactly like
    the visual gate, so losing this restarts that clock too."""
    save_gate_counters_1202ce(_loaded(tmp_path), "milestone:1:core@0.1.0")
    fresh = _OrchGates(tmp_path)
    assert restore_gate_counters_1202ce(fresh, "milestone:1:core@0.1.0") is True
    assert fresh._pages_gate_deferred_since == 500.0
    assert fresh._pages_gate_attempts == 2
    assert fresh._tu_squad_passed is True
    assert fresh._tu_squad_deferred_since == 700.0
    assert fresh._tu_squad_attempts == 3


def test_a_different_milestone_restores_nothing(tmp_path):
    save_gate_counters_1202ce(_loaded(tmp_path), "milestone:1:core@0.1.0")
    fresh = _OrchGates(tmp_path)
    assert restore_gate_counters_1202ce(fresh, "milestone:2:social@0.2.0") is False
    assert fresh._pages_gate_deferred_since is None and fresh._tu_squad_attempts == 0


def test_no_saved_state_restores_nothing(tmp_path):
    assert restore_gate_counters_1202ce(_OrchGates(tmp_path), "milestone:1:core@0.1.0") is False


def test_an_unnamed_milestone_restores_nothing(tmp_path):
    """`_mkey` is None when the #1202bz block failed; that must not match a saved key."""
    save_gate_counters_1202ce(_loaded(tmp_path), "milestone:1:core@0.1.0")
    assert restore_gate_counters_1202ce(_OrchGates(tmp_path), None) is False


def test_a_corrupt_file_restores_nothing(tmp_path):
    f = tmp_path / "design" / "milestone_gates.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("{ not json", encoding="utf-8")
    assert restore_gate_counters_1202ce(_OrchGates(tmp_path), "milestone:1:core@0.1.0") is False


def test_the_save_leaves_no_temp_behind(tmp_path):
    save_gate_counters_1202ce(_loaded(tmp_path), "m1")
    assert [p.name for p in (tmp_path / "design").iterdir() if p.name.endswith(".tmp")] == []


def test_the_orchestrator_only_zeroes_the_counters_it_did_not_restore():
    """Both gates' resets must sit behind the restore check — one left outside would zero
    half the progress and leave the run in a state neither a fresh nor a continuous run
    would ever be in. #943: landmark anchors."""
    src = (LLM / "multi_agent" / "orchestrator.py").read_text(encoding="utf-8")
    i = src.index("_restored_1202ce = restore_gate_counters_1202ce(self, _mkey)")
    # #943: landmark, never a byte window — the reset block ends at #532's squad-task
    # cancellation, which is the next thing the milestone entry does.
    region = src[i:src.index("#532", i)]
    for f in GATE_FIELDS:
        j = region.index(f"self.{f} = ")
        # every assignment must be indented deeper than the `if not _restored_1202ce:`
        line_start = region.rindex("\n", 0, j) + 1
        assert region[line_start:j].startswith(" " * 24), f
    assert region.count("if not _restored_1202ce:") == 2


def test_the_counters_are_saved_every_coordination_tick():
    src = (LLM / "multi_agent" / "orchestrator.py").read_text(encoding="utf-8")
    i = src.index("save_gate_counters_1202ce(self, _mkey)")
    assert "tick_count" in src[max(0, i - 1200):i]


def test_state_from_a_different_milestone_is_never_inherited(tmp_path):
    """The reason the load moved out of __init__: a gate must not pick up whatever ran last
    in this output directory. Caught by the pre-existing blank-refund tests, which share
    `output_dir` and never call reset_for_milestone."""
    _populate(_gate(tmp_path), key="milestone:1:core@0.1.0")._save_state_1202ce()
    g = _gate(tmp_path)
    g.reset_for_milestone("milestone:9:other@9.9.9")
    assert g.deferred_since is None and g.total_judgments == 0


def test_constructing_a_gate_never_reads_the_state_file(tmp_path):
    """Construction alone must stay inert — the counters arrive only via a milestone that
    claims them."""
    _populate(_gate(tmp_path))._save_state_1202ce()
    g = _gate(tmp_path)
    assert g.deferred_since is None and g.attempts == 0 and g.released is False


def test_the_run_scoped_deferral_clocks_survive_too(tmp_path):
    """Found by scanning for the pattern rather than waiting for each to surface: both feed
    squad_release_decision(deferred_since, attempts, now), the same bounded escape."""
    o = _OrchGates(tmp_path)
    o._rc_deferred_since, o._rc_attempts = 900.0, 4
    o._tu_browser_deferred_since, o._tu_browser_attempts = 950.0, 5
    save_gate_counters_1202ce(o, "m1")
    fresh = _OrchGates(tmp_path)
    assert restore_gate_counters_1202ce(fresh, "m1") is True
    assert fresh._rc_deferred_since == 900.0 and fresh._rc_attempts == 4
    assert fresh._tu_browser_deferred_since == 950.0 and fresh._tu_browser_attempts == 5


def test_a_restored_clock_survives_the_lazy_initialiser(tmp_path):
    """These are initialised with `if getattr(self, X, None) is None`, so a restored value
    must be non-None or the next tick would overwrite it with `now`."""
    o = _OrchGates(tmp_path)
    o._rc_deferred_since = 900.0
    save_gate_counters_1202ce(o, "m1")
    fresh = _OrchGates(tmp_path)
    restore_gate_counters_1202ce(fresh, "m1")
    assert getattr(fresh, "_rc_deferred_since", None) is not None


def test_persisting_can_never_abort_a_judged_round():
    """A gate double (or any future refactor) that lacks the persistence method must not
    take the run down with it — the same rule every other #1202b*/#1202c* hook follows."""
    src = (LLM / "multi_agent" / "orchestrator.py").read_text(encoding="utf-8")
    i = src.index("async def _maybe_run_visual_fidelity")
    body = src[i:src.index("async def ", i + 40)]
    save = body.index("_save_state_1202ce()")
    assert body.rindex("try:", 0, save) < save < body.index("except Exception:", save)
