r"""#798: the most re-filed task in the corpus told the verifier to go and look up something the
framework had already written down.

`business_chain_failing`'s body: *"read the broken step, fix the chain (or bug_create for the
endpoint it exposed), then re-run run_validation."* It named no step. Meanwhile
`registryhub_verification_chains.json` records, per chain, `last_result.broken` plus a per-step
row carrying `action` / `method` / `path` / `status` / `ok` / `kind` / `note` / `expect`.

Measured: **30 of 140 corpus runs carry at least one failing chain, and all 30 have that
payload.** And `"Make business_chain pass (blocks delivery)"` is the most re-filed title in the
corpus — 13 copies in r130 alone (#794). So the single most-repeated instruction in the system was
a lookup request for data already on disk.

Same `_extra` mechanism #284 uses for ui_flow names and #148 for the action-404 list; the
action-404 branch keeps precedence because it re-routes the task to a different lane entirely.

★ Two measurement errors on the way here, both mine, both the same class:
  * `list(d.values())` over the chains file includes the `_meta` bootstrap document, so the first
    "chain" inspected had keys `['last_modified_at','last_modified_by','version']` and the probe
    reported **0 failing chains in 140 runs**. Identical shape to #755, where a bootstrap
    `{"version": 1}` was counted as a release.
  * that zero was the seventh instrument-zero of the session, caught by the rule (*a zero is a
    claim about the instrument*) rather than by noticing the key names.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime import remediation_dispatcher as rd


class _RH:
    def __init__(self, chains):
        self._c = chains

    def get_verification_chains(self):
        return self._c


class _Orch:
    def __init__(self, chains):
        self.hubs = type("H", (), {"registryhub": _RH(chains)})()


_STEPS = {
    "_meta": {"version": 1},
    "auth_round_trip": {"last_result": {"broken": [], "steps": [
        {"action": "register user", "method": "POST", "path": "/auth/register",
         "status": 201, "ok": True, "expect": [200, 201, 409]},
        {"action": "protected read", "method": "GET", "path": "/api/profiles",
         "status": 500, "ok": False, "expect": [200],
         "note": "AttributeError: 'Profile' has no attribute user_id"}]}},
}


def test_the_failing_step_is_named():
    out = rd._chain_broken_detail_798(_Orch(_STEPS))
    assert len(out) == 1, out
    line = out[0]
    assert "auth_round_trip" in line and "protected read" in line
    assert "GET /api/profiles" in line


def test_it_carries_got_versus_expected():
    """'It returned 500' is a lookup; 'it returned 500 where [200] was expected' is a diagnosis."""
    line = rd._chain_broken_detail_798(_Orch(_STEPS))[0]
    assert "returned 500" in line and "expected [200]" in line


def test_the_note_travels():
    line = rd._chain_broken_detail_798(_Orch(_STEPS))[0]
    assert "AttributeError" in line


def test_passing_steps_are_not_reported():
    """Non-vacuity: the chain above has a passing step too, and it must not be listed."""
    out = rd._chain_broken_detail_798(_Orch(_STEPS))
    assert not any("register user" in l for l in out)


def test_the_meta_document_is_skipped():
    """`_meta` is a bootstrap record, not a chain — treating it as one is what made the probe
    behind this fix report 0 failing chains across 140 runs (#755's shape)."""
    out = rd._chain_broken_detail_798(_Orch(_STEPS))
    assert not any("_meta" in l or "last_modified_at" in l for l in out)


def test_a_chain_with_no_step_rows_falls_back_to_broken():
    """Older records carry `broken` strings and no per-step rows; they must not be lost."""
    out = rd._chain_broken_detail_798(_Orch(
        {"catalog": {"last_result": {"broken": ["POST /api/titles/1/unlike -> 404"],
                                     "steps": []}}}))
    assert out and "unlike" in out[0]


def test_a_green_registry_yields_nothing():
    out = rd._chain_broken_detail_798(_Orch(
        {"c": {"last_result": {"broken": [], "steps": [
            {"action": "a", "method": "GET", "path": "/x", "status": 200, "ok": True}]}}}))
    assert out == []


@pytest.mark.parametrize("bad", [object(), None])
def test_any_fault_leaves_the_generic_text_standing(bad):
    """This runs on the release path; a P0 must still be filed if the lookup fails."""
    assert rd._chain_broken_detail_798(bad) == []


def _many(n):
    return {f"c{i}": {"last_result": {"steps": [
        {"action": f"a{i}", "method": "GET", "path": f"/x{i}", "status": 500,
         "ok": False, "expect": [200]}]}} for i in range(n)}


def test_it_is_capped():
    """The task body is already the largest object the system produces (#680)."""
    out = rd._chain_broken_detail_798(_Orch(_many(30)))
    assert len([l for l in out if "-> step" in l]) == 8


def test_the_cap_says_what_it_dropped():
    """#811. A silent cap re-creates #798's own defect in miniature: the verifier fixes the 8 it
    was shown, re-runs, and the chain is still red for reasons the task never mentioned. #680's
    'no silent caps' rule, applied to my own fix from two items earlier."""
    out = rd._chain_broken_detail_798(_Orch(_many(20)))
    assert out[-1].startswith("… and 12 more broken step(s)")


def test_under_the_cap_there_is_no_note():
    """Non-vacuity: the note must not appear when nothing was dropped, or it is noise on every
    task and gets skipped — the failure mode #793's line was corrected for."""
    out = rd._chain_broken_detail_798(_Orch(_many(3)))
    assert len(out) == 3
    assert not any("and" in l and "more" in l for l in out)


def test_exactly_at_the_cap_there_is_no_note():
    out = rd._chain_broken_detail_798(_Orch(_many(8)))
    assert len(out) == 8 and not any(l.startswith("…") for l in out)


# --- wiring -----------------------------------------------------------------------------------

def test_it_is_attached_to_the_task_body():
    import inspect
    src = inspect.getsource(rd)
    assert "_chain_broken_detail_798(orch)" in src
    assert "THE BROKEN STEP(S), from the chain registry's own" in src


def test_the_action_404_branch_keeps_precedence():
    """#148 re-routes the task to the BACKEND lane for a missing action endpoint; that is a
    different owner, not just different text, so it must win."""
    import inspect
    src = inspect.getsource(rd)
    i404 = src.index('_act = _chain_action_404s(orch)')
    i798 = src.index("_brk798 = _chain_broken_detail_798(orch)")
    assert i404 < i798
    assert "else:" in src[i404:i798]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
