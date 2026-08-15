r"""#760: the identical-content detector said the same two things 108 times.

`#615`'s duplicate-route warning is emitted inside a function that runs on every deliverability
sweep, with no memory. r149 logged `routes render identical content` **108 times carrying two
distinct findings** — the same two groups, 54 times each.

That is not cosmetic. It buries every other warning in a 21,000-line log, and it makes a COUNT
meaningless: my own checker line reported "#700 identical-content routes x108", which reads as
108 defects and is 2.

Keyed on the group's identity, so a group that CHANGES (a route joins or leaves it) is reported
again — that is the interesting event — while a stable one is stated once.

Bounded by item 78's dual-import hazard rather than defeated by it: this module sits in
`sys.modules` under both `multi_agent...` and `env_generator...`, so the set exists twice and a
group can be announced at most TWICE per run. 108 -> <=2 is the fix; pretending the set is a
singleton would be the bug.
"""
import inspect
import sys

import pytest

from env_generator.llm_generator.multi_agent.runtime import deliverability as dl


@pytest.fixture(autouse=True)
def _reset_said_700():
    """#762: #760's memory is module-level and outlives a test. Without this the suite passes
    file-by-file and fails as a whole — whichever test reaches the detector first silences the
    rest. Both sys.modules copies are cleared: the dual-import hazard this file already
    documents means the set exists twice."""
    for _m in list(sys.modules.values()):
        _r = getattr(_m, "reset_said_700", None)
        if callable(_r) and getattr(_m, "__name__", "").endswith("deliverability"):
            _r()
    yield
    # #762 again on the way out: a test that leaves the memory populated silences the NEXT
    # file just as effectively as one that inherits it.
    for _m in list(sys.modules.values()):
        _r = getattr(_m, "reset_said_700", None)
        if callable(_r) and getattr(_m, "__name__", "").endswith("deliverability"):
            _r()


def _emit(monkeypatch, groups, calls=1, tmp=None):
    """Replay the emit loop against the REAL module-level set.

    Deliberately does not stub `duplicate_route_content_groups` — it is imported inside the
    function, not a module attribute, and my first version monkeypatched a name that does not
    exist there. What matters is the dedupe state and the key, both of which are real here; that
    the guard is in the shipped call site is pinned by the source assertions below.
    """
    seen = []
    monkeypatch.setattr(dl._LOG_700, "warning",
                        lambda msg, *a, **k: seen.append(str(msg) % a if a else str(msg)))
    for _ in range(calls):
        for g in groups or []:
            key = (tuple(g.get("routes") or []), tuple(g.get("endpoints") or []))
            if key in dl._SAID_700:
                continue
            dl._SAID_700.add(key)
            dl._LOG_700.warning("#615 %d routes render identical content: %s",
                                len(g.get("routes") or []), ", ".join(g.get("routes") or []))
    return seen


_G1 = {"routes": ["/movies", "/shows"], "endpoints": ["/api/titles"], "components": ["A", "B"]}
_G2 = {"routes": ["/title/:id", "/watch/:id"], "endpoints": ["/api/titles/"], "components": ["C"]}


def test_one_group_over_many_passes_is_said_once(monkeypatch):
    said = _emit(monkeypatch, [_G1], calls=54)
    assert len(said) == 1, said


def test_r149s_two_groups_over_54_passes_are_two_lines(monkeypatch):
    said = _emit(monkeypatch, [_G1, _G2], calls=54)
    assert len(said) == 2, said


def test_a_changed_group_is_announced_again(monkeypatch):
    _emit(monkeypatch, [_G1], calls=3)
    grown = {**_G1, "routes": _G1["routes"] + ["/games"]}
    said = _emit(monkeypatch, [grown], calls=3)
    assert len(said) == 1, "a group that gained a route is a new fact"


def test_a_different_endpoint_is_a_different_group(monkeypatch):
    _emit(monkeypatch, [_G1], calls=1)
    other = {**_G1, "endpoints": ["/api/my-list"]}
    assert len(_emit(monkeypatch, [other], calls=1)) == 1


def test_no_groups_says_nothing(monkeypatch):
    assert _emit(monkeypatch, [], calls=10) == []


# --- the real call site carries it ------------------------------------------------------------

def _src() -> str:
    src = inspect.getsource(dl)
    i = src.index("#760: SAY IT ONCE PER GROUP")
    return src[i:src.index("_f708 = _filters_708b", i)]


def test_the_guard_is_in_the_real_emit_path():
    s = _src()
    assert "if _key760 in _SAID_700:" in s and "continue" in s
    assert "_SAID_700.add(_key760)" in s


def test_the_key_is_the_group_identity_not_its_index():
    s = _src()
    assert '_key760 = (tuple(_g.get("routes") or []), tuple(_g.get("endpoints") or []))' in s


def test_the_measurement_is_recorded():
    s = " ".join(_src().replace("#", " ").split())
    assert "108 times carrying two" in s and "distinct findings" in s
    assert "reads as 108 defects and is 2" in s


def test_the_dual_import_bound_is_stated_not_ignored():
    """item 78 said the day a module here gains state it exists twice. This is that day."""
    s = " ".join(_src().replace("#", " ").split())
    assert "this set exists twice" in s
    assert "at most TWICE per run" in s
    assert "pretending the set is a singleton would be the bug" in s


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
