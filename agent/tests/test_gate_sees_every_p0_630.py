r"""#630: the delivery gate could only see a minority of the P0 bugs.

`collect_test_user_bugs` skips any bug whose source is not one of the three test-user profiles,
and it is the ONLY bug reader in the delivery path — no other gate calls `list_open_bugs`. Across
40 runs:

    314 P0 bugs filed
    207 of them by the VERIFIER — the largest source, entirely invisible to the gate
     32 of the 73 P0s still open at run end are non-test-user

So a run could release while carrying "Landing page (/) crashes with 'Cn is not a function' —
blank render blocks entire landing". Several did.

I deferred this twice as "a release-path behaviour change no artifact can validate". That was
wrong: the counterfactual is cheap. Replaying each released run and counting the open
non-test-user P0s at the moment of its FIRST release:

    21 runs released
    17 carried ZERO            -> the change is invisible to them
     4 would have deferred     -> 1-4 open P0s
       r127 (1 of 1) and r128 (3 of 4) had them RESOLVED later in the same run
       r109 (2) and r133 (1) never did -> they ride the existing escape budget

~~Blast radius 4 of 21~~ — **that figure does NOT reproduce, and it is the number this whole
paragraph rests on.** Re-derived over the current corpus, counting bug tasks with
`metadata.kind == "bug"`, `metadata.severity == "P0"` and `metadata.source` outside
`TEST_USER_SOURCES`:

    claimed                          21 released, 17 zero,  4 would defer
    at run END                       27 released,  5 zero, 22 would defer
    at FIRST RELEASE (reconstructed) 27 released,  7 zero, 20 would defer

r109 matches its named figure exactly; r127, r128 and r133 come out higher. The reconstruction is
NOT sound on its own — only 15% (84 of 552) of these bugs carry `metadata.triage_history`, so the
rest default to "open" in the probe — but the ORDER OF MAGNITUDE is off by roughly five, and the
claim is what justifies deferring a release. EXPERIMENTS_PENDING records it as the one claim in
that sweep which fails. Struck through rather than deleted, per item 48: the reasoning stays
visible, and the number no longer reads as measured.

The deferral may still be exactly what "bug-free" asks for, and it still cannot wedge:
`squad_gate_outcome`'s `defect` branch burns an escape attempt and `squad_release_decision`'s
wall clock is still the backstop.

The gate reads `bugs["p0"]` and nothing else, so widening it in one place is the whole change —
`orchestrator.py` is untouched.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime import test_user_squad as sq


class _WorkHub:
    def __init__(self, bugs):
        self._bugs = bugs

    def list_open_bugs(self):
        return self._bugs


class _Orch:
    def __init__(self, bugs):
        self.hubs = type("H", (), {"workhub": _WorkHub(bugs)})()


def _bug(source, severity="P0", title="x"):
    return {"title": title, "metadata": {"kind": "bug", "source": source, "severity": severity}}


# --- the count -----------------------------------------------------------------------------------

def test_a_verifier_p0_is_counted(sample=None):
    orch = _Orch([_bug("verifier")])
    assert sq.collect_open_p0_by_source(orch) == {"verifier": 1}


def test_the_verifier_was_invisible_to_the_old_reader():
    """The defect, pinned: the test-user reader skips the largest source."""
    orch = _Orch([_bug("verifier"), _bug("verifier")])
    assert sq.collect_test_user_bugs(orch)["p0"] == 0
    assert sum(sq.collect_open_p0_by_source(orch).values()) == 2


def test_every_source_is_broken_out():
    orch = _Orch([_bug("verifier"), _bug("browser_test_user"), _bug("debugger")])
    assert sq.collect_open_p0_by_source(orch) == {
        "verifier": 1, "browser_test_user": 1, "debugger": 1}


def test_test_user_bugs_are_still_included_not_replaced():
    orch = _Orch([_bug("api_test_user"), _bug("verifier")])
    assert sum(sq.collect_open_p0_by_source(orch).values()) == 2


def test_lower_severities_are_not_counted():
    orch = _Orch([_bug("verifier", "P1"), _bug("verifier", "P2"), _bug("verifier", "P0")])
    assert sq.collect_open_p0_by_source(orch) == {"verifier": 1}


def test_a_bug_with_no_source_is_still_counted():
    """An unattributed P0 must not vanish from the gate."""
    orch = _Orch([{"title": "x", "metadata": {"severity": "P0"}}])
    assert sq.collect_open_p0_by_source(orch) == {"unknown": 1}


def test_severity_case_does_not_matter():
    orch = _Orch([_bug("verifier", "p0")])
    assert sq.collect_open_p0_by_source(orch) == {"verifier": 1}


# --- it must never break delivery ------------------------------------------------------------------

def test_a_hub_error_returns_empty_rather_than_raising():
    class _Boom:
        def list_open_bugs(self):
            raise RuntimeError("hub down")

    orch = type("O", (), {"hubs": type("H", (), {"workhub": _Boom()})()})()
    assert sq.collect_open_p0_by_source(orch) == {}


def test_a_missing_workhub_returns_empty():
    assert sq.collect_open_p0_by_source(type("O", (), {"hubs": None})()) == {}


# --- how the gate consumes it -----------------------------------------------------------------------

def test_the_gate_still_blocks_on_a_defect_and_can_still_escape():
    """The widened count feeds the SAME outcome function, so the escape budget still applies."""
    assert sq.squad_gate_outcome(ran=True, p0=3) == "defect"
    assert sq.squad_gate_outcome(ran=True, p0=0) == "pass"
    assert sq.squad_gate_outcome(ran=False, p0=3) == "retry"


def test_the_widening_happens_where_the_gate_reads(sample=None):
    """`orchestrator.py` reads bugs["p0"] and nothing else — the change lives in one file."""
    import inspect
    src = inspect.getsource(sq._run_squad_for_delivery_impl)  # #1202nx: body behind the lease
    i = src.index("#630: the gate reads")
    block = src[i:src.index("verdict = ", i)]
    assert 'bugs["p0"] = sum(by_source.values())' in block
    assert 'bugs["p0_test_user"]' in block, "the narrower figure must survive for reporting"


def test_a_genuine_zero_is_not_confused_with_a_failed_reading():
    """`sum(...) or old` would treat a real 0 as 'no reading' and fall back. Explicit branch."""
    import inspect
    src = inspect.getsource(sq._run_squad_for_delivery_impl)  # #1202nx: body behind the lease
    i = src.index("#630: the gate reads")
    block = src[i:src.index("verdict = ", i)]
    assert "if by_source else" in block
    assert "sum(by_source.values()) or" not in block


def test_the_counterfactual_is_recorded():
    import inspect
    flat = " ".join(inspect.getsource(sq.collect_open_p0_by_source).replace("#", " ").split())
    assert "21 runs released" in flat and "17 carried ZERO" in flat
    assert "verifier files 207 of the 314" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_the_blast_radius_figure_is_marked_as_not_reproducing():
    """Fourth instance of item 48's mode three, and the highest-stakes one: '4 of 21' justifies
    DEFERRING a release, and it does not reproduce — re-derivation gives 20-22 of 27, five times
    higher. The paragraph that rests on it now says so."""
    import test_gate_sees_every_p0_630 as me
    d = " ".join((me.__doc__ or "").split())
    i = d.find("Blast radius 4 of 21")
    assert i > 0, "the original figure should stay visible"
    assert "~~" in d[max(0, i - 4):i], "it must be struck through where it appears"
    assert "does NOT reproduce" in d
    assert "22 would defer" in d
    assert "NOT sound on its own" in d, "the re-derivation's own limits must travel with it"
