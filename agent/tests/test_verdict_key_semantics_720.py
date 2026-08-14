r"""#720: six key names span two dicts and at least three mean different things.

`run_visual_fidelity` RETURNS one dict and `_persist_verdict` writes another, and they share key
names while carrying different values. That collision cost two fixes: #712 claimed the
fast-release counter reads a monotonic high-water mark, having verified monotonicity on
`rounds.jsonl` — the PERSISTED number — while the counter reads the RETURNED one, which is the
current capture and can fall. #711's release consequence went the same way. Every measurement was
correct; the object measured was not the one in the causal path.

The shared names:

    blocking_average   coverage   min_similarity   passed   screens   summary

and the ones known to differ:

    returned blocking_average   _blocking_similarity_average(results)   CURRENT
    persisted blocking_average  over #500's merged                      HIGH-WATER
    returned passed             passed                                  un-merged
    persisted passed            bool(passed) or _merged_passed          merged-optimistic
    persisted screens           merged                                  BEST-EVER per screen

This test does not try to prove what each one means — that is what the table in
EXPERIMENTS_PENDING item 42 is for. It fails when a NEW shared name appears without being
declared, so the next collision is noticed when it is introduced rather than after it has misled
someone.
"""
import inspect
import re

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


# Names known to appear in both dicts. Each must say whether the two agree, because an
# undocumented collision is exactly what #712 tripped over.
KNOWN_SHARED = {
    "blocking_average": "DIFFER — returned is the current capture, persisted is #500's merge",
    "passed":           "DIFFER — persisted is `or _merged_passed`, returned is not",
    "screens":          "DIFFER — persisted is `merged`, returned is `results`",
    "coverage":         "same object passed straight through",
    "min_similarity":   "same scalar passed straight through",
    "summary":          "same string passed straight through",
}


def _returned_keys():
    src = inspect.getsource(vf)
    i = src.index('return {"passed": passed, "summary": summary, "screens": results')
    j = src.index("def _persist_verdict", i)
    return set(re.findall(r'"(\w+)":', src[i:j]))


def _persisted_keys():
    src = inspect.getsource(vf)
    i = src.index('"passed": bool(passed) or _merged_passed')
    start = src.rindex("_verdict = {", 0, i) if "_verdict = {" in src[:i] else i - 400
    j = src.index("}", i)
    return set(re.findall(r'"(\w+)":', src[start:j]))


# --- the sweep still finds both dicts -----------------------------------------------------------

def test_both_dicts_are_locatable():
    assert len(_returned_keys()) >= 5
    assert len(_persisted_keys()) >= 5


def test_the_known_collisions_are_still_collisions():
    shared = _returned_keys() & _persisted_keys()
    gone = [k for k in KNOWN_SHARED if k not in shared]
    assert not gone, f"declared as shared but no longer in both dicts — update the table: {gone}"


# --- the guard ------------------------------------------------------------------------------------

def test_no_undeclared_key_is_shared_between_the_dicts():
    shared = _returned_keys() & _persisted_keys()
    undeclared = sorted(shared - set(KNOWN_SHARED))
    assert not undeclared, (
        "these key names now appear in BOTH the returned and the persisted verdict without being "
        "declared. Decide whether they agree and add them to KNOWN_SHARED and to "
        "EXPERIMENTS_PENDING item 42's table — an undocumented collision is what #712 tripped "
        f"over: {undeclared}")


@pytest.mark.parametrize("key,note", sorted(KNOWN_SHARED.items()))
def test_every_declaration_says_whether_they_agree(key, note):
    assert note.startswith("DIFFER") or "same" in note, (
        f"{key}'s note must state agreement or difference, not just exist")


def test_the_guard_is_not_vacuous(monkeypatch):
    """Planted violation, because "no undeclared shared key" is exactly the assertion that reads
    green when the sweep sees nothing at all.

    Audited every guard built this session for this: #716 and #719 are proven by having FIRED on
    real changes, #717 tests both directions (marker present and absent), and this one had only a
    one-way assertion. Two guards this session shipped able to report a clean pass while blind —
    #716 let #727's dead pattern through, #734's sweep skipped tool names with digits — so an
    unproven guard is the thing to fix rather than to trust."""
    import test_verdict_key_semantics_720 as me
    monkeypatch.setattr(me, "KNOWN_SHARED", {}, raising=False)
    shared = _returned_keys() & _persisted_keys()
    assert shared, "the two dicts share no keys at all — the sweep itself is broken"
    undeclared = sorted(shared - set(me.KNOWN_SHARED))
    assert undeclared, "with an empty registry every shared key must be reported"
    assert "blocking_average" in undeclared


# --- the three that actually differ, pinned ---------------------------------------------------------

def test_the_returned_average_is_computed_from_results():
    assert "_blk_avg = _blocking_similarity_average(results)" in inspect.getsource(vf)


def test_the_persisted_average_is_computed_from_merged():
    src = inspect.getsource(vf)
    assert "sum(_sim(s) for s in _blocking_merged)" in src


def test_the_persisted_screens_are_the_merged_list():
    assert '"screens": merged,' in inspect.getsource(vf)


def test_the_persisted_passed_is_the_optimistic_one():
    assert '"passed": bool(passed) or _merged_passed' in inspect.getsource(vf)


def test_the_live_field_is_built_from_results_not_merged():
    """rounds.jsonl's `live` is the one per-screen field that IS current."""
    src = inspect.getsource(vf)
    i = src.index('"live": {str(s.get("name"))')
    assert "for s in (results or [])" in src[i:src.index("}", i) + 200]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
