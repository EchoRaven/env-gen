r"""#738: #715 is route-shaped, so it calls r148's stale build CLEAN.

#715 asks whether the served bundle contains every route literal the source declares. That
catches r147's collapse, where a rename landed and nothing rebuilt. It cannot catch the other
half, which is what killed r148: the routes never changed, a frontend bug fix simply never
reached the container, and the SPA kept throwing `TypeError: (void 0) is not a function` on
every page. With `known_routes` unchanged, `_missing715` is empty and #722 prints "served build
matches the source" — a FALSE ALL-CLEAR over an app that renders nothing, which is worse than
the silence #722 was built to end.

The observation already existed, written by hand into the P0 nobody actioned:

    PRIOR FIX (task_17fc0b5257) DID NOT LAND. The deployed bundle hash + error signature are
    IDENTICAL to before.

Vite content-hashes its asset filenames (`index-C3zHFyCT.js`), so that is mechanical: if the
frontend source moved and the served asset names did not, the container serves a pre-edit build.

Keyed on the last commit that TOUCHED `app/frontend`, not on HEAD — most commits in a run are
backend or docs and legitimately leave the bundle alone, so a HEAD key would fire nearly every
round. Reports only, exactly like #715: a stale serve does not mean the app is broken, it means
the measurement is of the wrong build.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


_STALE = _fresh = None
_B1 = "index-C3zHFyCT.js index-a1b2c3.css"
_B2 = "index-9ZqWmP4x.js index-a1b2c3.css"
_C1 = "5f9973483aa11bb22cc33dd44ee55ff667788990"
_C2 = "a6c38260688011bb22cc33dd44ee55ff66778899"


def _stale(prev, commit, bundle):
    return vf._served_build_is_stale_738(prev, commit, bundle)


# --- the r148 case ----------------------------------------------------------------------------

def test_frontend_moved_and_the_bundle_did_not_is_stale():
    assert _stale({"frontend_commit": _C1, "bundle": _B1}, _C2, _B1) is True


def test_a_rebuilt_bundle_is_not_stale():
    assert _stale({"frontend_commit": _C1, "bundle": _B1}, _C2, _B2) is False


def test_an_untouched_frontend_is_not_stale():
    """The common round: backend commits land, the frontend and its bundle both stand still."""
    assert _stale({"frontend_commit": _C1, "bundle": _B1}, _C1, _B1) is False


def test_a_rebuild_with_no_frontend_commit_is_not_stale():
    """Cache-bust or dependency bump: the bundle moved, the source did not. Not this defect."""
    assert _stale({"frontend_commit": _C1, "bundle": _B1}, _C1, _B2) is False


# --- it cannot fire without a real prior --------------------------------------------------------

def test_the_first_round_is_never_stale():
    assert _stale({}, _C2, _B1) is False
    assert _stale(None, _C2, _B1) is False


@pytest.mark.parametrize("prev", [
    {"bundle": _B1},                       # no prior commit
    {"frontend_commit": _C1},              # no prior bundle
    {"frontend_commit": "", "bundle": _B1},
    {"frontend_commit": _C1, "bundle": ""},
])
def test_a_half_known_prior_is_never_stale(prev):
    assert _stale(prev, _C2, _B1) is False


@pytest.mark.parametrize("commit,bundle", [("", _B1), (_C2, ""), ("", "")])
def test_a_missing_reading_is_never_stale(commit, bundle):
    assert _stale({"frontend_commit": _C1, "bundle": _B1}, commit, bundle) is False


def test_a_non_mapping_prior_is_tolerated():
    for junk in ("", [], 0, "corrupt"):
        assert _stale(junk, _C2, _B1) is False


# --- the call site -------------------------------------------------------------------------------

def _block() -> str:
    src = inspect.getsource(vf.run_visual_fidelity)
    i = src.index("#738: A STALE BUNDLE WHOSE ROUTES DID NOT CHANGE")
    return src[i:src.index("except Exception:\n                pass", i)]


def test_it_reads_the_served_asset_names():
    b = _block()
    assert "ls -1 /usr/share/nginx/html/assets/" in b


def test_it_keys_on_the_frontend_subtree_not_head():
    b = _block()
    assert '"git", "log", "-1", "--format=%H", "--", "app/frontend"' in b
    assert "rev-parse" not in b, "HEAD would fire on every backend-only commit"


def test_the_state_survives_between_rounds():
    b = _block()
    assert 'design" / "visual_gate" / "served_build.json"' in b
    assert "_sf738.write_text(" in b


def test_a_fault_never_breaks_the_capture():
    b = _block()
    assert b.count("except Exception:") >= 2


def test_it_decides_nothing():
    """Same disposition as #715 — it must not gate, latch, or void a score by itself."""
    b = _block()
    stmts = [l.strip() for l in b.split("\n")
             if l.strip() and not l.strip().startswith("#")]
    assert not [l for l in stmts if l.startswith(("return", "raise "))]
    assert "passed" not in b and "plateau" not in b


# --- provenance ------------------------------------------------------------------------------------

def test_it_records_why_715_cannot_see_this():
    b = " ".join(_block().replace("#", " ").split())
    assert "715 compares ROUTE LITERALS" in b
    assert "would have called it CLEAN" in b
    assert "A false all-clear is worse than the silence 722 was built to end" in b


def test_the_hand_written_observation_is_quoted():
    b = " ".join(_block().replace("#", " ").split())
    assert "DID NOT LAND" in b
    assert "IDENTICAL to before" in b


def test_the_key_choice_is_justified():
    b = " ".join(_block().replace("#", " ").split())
    assert "keying on HEAD would fire on nearly every round" in b


def test_the_warning_tells_the_reader_what_to_do():
    b = _block()
    assert "Rebuild the frontend image" in b
    assert "a source edit alone does not" in b


def test_the_helper_states_the_first_round_rule():
    d = " ".join((vf._served_build_is_stale_738.__doc__ or "").split())
    assert "the first round of a run has no prior and can never be stale" in d


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
