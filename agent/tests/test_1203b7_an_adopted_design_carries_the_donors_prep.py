r"""#1203b7: an adopted design system carries the DONOR's design-prep, fixes and all.

`#1202hj` lets a fresh run adopt a prior run's `design_system.json` when the design-input
fingerprints match, skipping the analyst. It is a `shutil.copy2`, so the adopting run inherits
whatever that donor's design-prep produced — including what a later fix would have removed.

r145 demonstrated it live, minutes apart in its own log and gate:

    #1202hj Design-Prep: adopting the ENRICHED design_system.json measured by tiktok-web-r144
    GATE ok=False [... 'deliverability_operator_identity_leak' ...]

over `.screens[9].components[1].state` = "default avatar, haibotong7, 0 Following/Followers/
Likes, Edit profile, ...". r145's OWN `component_specs` are clean — re-measured under #1203b3's
corrected prompt, with nothing for the scrub to remove — so that identity arrived with r144's
file, produced before #1203b3 existed. 34 corpus runs adopt a donor this way, so every
design-prep fix has this hole until it is closed at the copy.
"""
import json
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import multi_agent.runtime.design_prep as DP  # noqa: E402
import multi_agent.runtime.material_prep as MP  # noqa: E402


def _ident(monkeypatch, tokens=("haibotong",)):
    import multi_agent.runtime.deliverability as D
    monkeypatch.setattr(D, "_operator_identity_1202rj", lambda: list(tokens), raising=True)
    monkeypatch.setattr(MP, "_OPERATOR_TOKENS_1203B3", None, raising=False)


_R145 = {
    "screens": [
        {"name": "fyp_feed", "components": [
            {"id": "feed", "state": "mostly scrolled; one video playing"}]},
        {"name": "profile_own", "route": "/@haibotong7", "components": [
            {"id": "left-sidebar", "state": "Profile destination is selected."},
            {"id": "profile-header",
             "state": ("default avatar, haibotong7, 0 Following/Followers/Likes, "
                       "Edit profile, Promote post, gear, share, No bio yet")}]},
    ]
}


def _donor(tmp_path, doc=None):
    d = tmp_path / "tiktok-web-r144"
    (d / "design").mkdir(parents=True)
    (d / "design" / "design_system.json").write_text(
        json.dumps(doc if doc is not None else _R145), encoding="utf-8")
    return d


def _adopt(tmp_path, monkeypatch, doc=None):
    donor = _donor(tmp_path, doc)
    out = tmp_path / "tiktok-web-r145"
    (out / "design").mkdir(parents=True)
    monkeypatch.setattr(DP, "record_design_prep_input_1202bv",
                        lambda *a, **k: None, raising=True)
    ok = DP.adopt_design_prep_1202hj(donor, out, "design_inputs/tiktok", {})
    assert ok is True
    return json.loads((out / "design" / "design_system.json").read_text(encoding="utf-8"))


def test_the_inherited_identity_is_gone(monkeypatch, tmp_path):
    """★ The exact field r145 inherited from r144."""
    _ident(monkeypatch)
    ds = _adopt(tmp_path, monkeypatch)
    st = ds["screens"][1]["components"][1]["state"]
    assert "haibotong" not in st, st
    assert MP._IDENTITY_SLOT_1203B3 in st, st


def test_the_rest_of_the_state_survives(monkeypatch, tmp_path):
    """The field describes the screen's state and must still do so — the counts and the
    affordances are what the lane builds from."""
    _ident(monkeypatch)
    ds = _adopt(tmp_path, monkeypatch)
    st = ds["screens"][1]["components"][1]["state"]
    for frag in ("default avatar", "0 Following/Followers/Likes", "Edit profile", "No bio yet"):
        assert frag in st, "%r was lost: %r" % (frag, st)


def test_a_clean_component_is_untouched(monkeypatch, tmp_path):
    _ident(monkeypatch)
    ds = _adopt(tmp_path, monkeypatch)
    assert ds["screens"][0]["components"][0]["state"] == "mostly scrolled; one video playing"
    assert ds["screens"][1]["components"][0]["state"] == "Profile destination is selected."


def test_the_route_is_left_alone(monkeypatch, tmp_path):
    """★ Deliberate: a screen routed at `/@haibotong7` is a DIFFERENT defect — the route should
    not be per-user at all — and a sentence inside a path string is not a repair. Pinned so the
    next reader sees the decision rather than an omission."""
    _ident(monkeypatch)
    ds = _adopt(tmp_path, monkeypatch)
    assert ds["screens"][1]["route"] == "/@haibotong7"


def test_a_clean_donor_doc_is_copied_byte_for_byte(monkeypatch, tmp_path):
    """Nothing to scrub means no rewrite: the adopting run gets the donor's bytes, which is
    what #1202hj promises."""
    _ident(monkeypatch)
    clean = {"screens": [{"name": "x", "components": [{"id": "a", "state": "idle"}]}]}
    donor = _donor(tmp_path, clean)
    out = tmp_path / "out"
    (out / "design").mkdir(parents=True)
    monkeypatch.setattr(DP, "record_design_prep_input_1202bv", lambda *a, **k: None)
    assert DP.adopt_design_prep_1202hj(donor, out, "di", {}) is True
    assert ((out / "design" / "design_system.json").read_bytes()
            == (donor / "design" / "design_system.json").read_bytes())


def test_the_donor_is_never_modified(monkeypatch, tmp_path):
    """★ The donor is a FINISHED run and its artifacts are evidence — I have polluted a run's
    seed files before and had to disclose it. The scrub happens on the copy."""
    _ident(monkeypatch)
    donor = _donor(tmp_path)
    before = (donor / "design" / "design_system.json").read_bytes()
    out = tmp_path / "out"
    (out / "design").mkdir(parents=True)
    monkeypatch.setattr(DP, "record_design_prep_input_1202bv", lambda *a, **k: None)
    DP.adopt_design_prep_1202hj(donor, out, "di", {})
    assert (donor / "design" / "design_system.json").read_bytes() == before


def test_an_unresolvable_identity_copies_unchanged(monkeypatch, tmp_path):
    """`_operator_identity_1202rj` returns [] when the build environment says nothing; the
    adoption must still succeed and must not guess."""
    _ident(monkeypatch, tokens=())
    donor = _donor(tmp_path)
    out = tmp_path / "out"
    (out / "design").mkdir(parents=True)
    monkeypatch.setattr(DP, "record_design_prep_input_1202bv", lambda *a, **k: None)
    assert DP.adopt_design_prep_1202hj(donor, out, "di", {}) is True
    ds = json.loads((out / "design" / "design_system.json").read_text())
    assert "haibotong7" in ds["screens"][1]["components"][1]["state"]


def test_an_unreadable_doc_does_not_fail_the_adoption(monkeypatch, tmp_path):
    """The adoption's job is to deliver the doc; a scrub that cannot parse it must leave it as
    copied and announce, never abort the phase into a 10-minute analyst spawn."""
    _ident(monkeypatch)
    donor = tmp_path / "d"
    (donor / "design").mkdir(parents=True)
    (donor / "design" / "design_system.json").write_text("{not json", encoding="utf-8")
    out = tmp_path / "out"
    (out / "design").mkdir(parents=True)
    monkeypatch.setattr(DP, "record_design_prep_input_1202bv", lambda *a, **k: None)
    assert DP.adopt_design_prep_1202hj(donor, out, "di", {}) is True
    assert (out / "design" / "design_system.json").read_text() == "{not json"


def test_the_scrub_is_called_at_the_copy():
    """★ Tested the helper, not the caller, too many times. Three properties: the call is
    inside `adopt_design_prep_1202hj`, it is given the DESTINATION path (not the donor's), and
    it sits between the copy and the fingerprint record — a scrub after the return, or on
    `src`, would be the defect with a function added."""
    import ast
    import inspect

    src = inspect.getsource(DP.adopt_design_prep_1202hj)
    tree = ast.parse(src.lstrip())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", "") == "_scrub_adopted_design_system_1203b7"]
    assert len(calls) == 1, "called %d time(s)" % len(calls)
    assert getattr(calls[0].args[0], "id", "") == "dst", ast.dump(calls[0])[:140]
    body = [n for n in ast.walk(tree) if isinstance(n, ast.Try)][0].body
    lines = [getattr(st, "lineno", 0) for st in body]
    copy_ln = [st.lineno for st in body
               if "copy2" in ast.dump(st)][0]
    scrub_ln = calls[0].lineno
    rec_ln = [st.lineno for st in body
              if "record_design_prep_input_1202bv" in ast.dump(st)][0]
    assert copy_ln < scrub_ln < rec_ln, (copy_ln, scrub_ln, rec_ln, lines)
