r"""#799: #798's defect swept across the rest of the dispatch table.

#798 fixed one entry. The rule it established — *the task text asks the lane to look up something
the framework already knows* — was then run as a query over every entry in the gate-level dispatch
table. Four flagged, two real:

    business_chain_missing          "NO chain is registered"  -- complete as written. FALSE POSITIVE
                                    of my filter; there is no instance to name.
    business_chain_failing          fixed by #798
    business_chain_api_coverage     "Add steps ... for the uncovered endpoints"  -- names none,
                                    and `delivery_gate._uncovered_business_endpoints` computes
                                    exactly that set, with the same `${var}`->`{x}` collapse
                                    `register_verification_chain` validates steps with.
    verification_checklist_not_ready  lists all four build checks and leaves the lane to work out
                                    which is red -- the store holds each one's status.

Both fixes reuse the framework's own computation rather than re-deriving it (#772: mirrored logic
drifts), and both fall back to the generic text on any fault — a P0 must still be filed if the
lookup fails.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime import remediation_dispatcher as rd


class _CH:
    def __init__(self, rows):
        self._r = rows

    def list_checks(self):
        return self._r


def _orch(checks=None, chains=None):
    hubs = type("H", (), {})()
    if checks is not None:
        hubs.codehub = _CH(checks)
    if chains is not None:
        hubs.registryhub = type("R", (), {
            "get_verification_chains": lambda self: chains})()
    return type("O", (), {"hubs": hubs})()


# --- the red build checks -----------------------------------------------------------------------

_ROWS = [
    {"name": "build:database", "status": "success"},
    {"name": "build:docker", "status": "failure",
     "evidence": {"summary": "compose up exited 1: port 5432 in use"}},
    {"name": "build:frontend", "status": "pending"},
    {"name": "validation:ui_smoke:login", "status": "failure"},
]


def test_only_the_red_build_checks_are_named():
    out = rd._red_checklist_checks_799(_orch(checks=_ROWS))
    assert any("build:docker = failure" in l for l in out)
    assert any("build:frontend = pending" in l for l in out)


def test_a_green_check_is_not_named():
    """Non-vacuity: the fixture has a passing check and it must not appear."""
    out = rd._red_checklist_checks_799(_orch(checks=_ROWS))
    assert not any("build:database" in l for l in out)


def test_non_build_checks_are_not_dragged_in():
    """`validation:ui_smoke:login` is failing too, and belongs to a different gate entirely."""
    out = rd._red_checklist_checks_799(_orch(checks=_ROWS))
    assert not any("ui_smoke" in l for l in out)


def test_the_reason_travels_when_the_store_has_one():
    out = rd._red_checklist_checks_799(_orch(checks=_ROWS))
    assert any("port 5432 in use" in l for l in out)


def test_a_never_recorded_check_says_so():
    """'missing' and 'failed' need different fixes, so they must not both read as blank."""
    out = rd._red_checklist_checks_799(_orch(checks=[{"name": "build:backend"}]))
    assert out and "never recorded" in out[0]


def test_an_all_green_checklist_yields_nothing():
    out = rd._red_checklist_checks_799(_orch(checks=[{"name": "build:docker", "status": "success"}]))
    assert out == []


# --- the uncovered endpoints ----------------------------------------------------------------------

def test_the_meta_document_is_not_treated_as_a_chain():
    """#755/#798's shape: `_meta` is a bootstrap record. Passing it as an authored chain is how
    the probe behind #798 reported 0 failing chains across 140 runs."""
    import inspect
    src = inspect.getsource(rd._uncovered_endpoints_799)
    assert 'name != "_meta"' in src


def test_it_reuses_the_gates_own_computation():
    """#772: a hand-written re-derivation drifts from the check that actually blocks."""
    import inspect
    src = inspect.getsource(rd._uncovered_endpoints_799)
    assert "from .delivery_gate import _uncovered_business_endpoints" in src


@pytest.mark.parametrize("fn", ["_uncovered_endpoints_799", "_red_checklist_checks_799"])
@pytest.mark.parametrize("bad", [object(), None])
def test_any_fault_leaves_the_generic_text_standing(fn, bad):
    assert getattr(rd, fn)(bad) == []


@pytest.mark.parametrize("fn,cap", [("_uncovered_endpoints_799", 12),
                                    ("_red_checklist_checks_799", 6)])
def test_both_are_capped(fn, cap):
    """#680: the task description is already the largest object the system produces."""
    import inspect
    assert f"[:{cap}]" in inspect.getsource(getattr(rd, fn))


# --- wiring ----------------------------------------------------------------------------------------

def test_both_are_attached_to_their_entries():
    import inspect
    src = inspect.getsource(rd)
    assert 'if name == "business_chain_api_coverage":' in src
    assert 'elif name == "verification_checklist_not_ready":' in src
    assert "THE UNCOVERED ENDPOINTS" in src and "THE CHECK(S) THAT ARE NOT GREEN" in src


def test_the_false_positive_was_left_alone():
    """`business_chain_missing` says NO chain is registered — a complete statement with no
    instance to name. Wrapping it would be cargo-culting the pattern (the #790
    `_endpoint_validated` lesson)."""
    import inspect
    src = inspect.getsource(rd)
    assert 'if name == "business_chain_missing":' not in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
