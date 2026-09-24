"""#1195 — a route-less registration whose component is already registered is the same page.

#1193 resolves a route collision inside the lock, but its test is `if route and name not in
live` — it skips entirely when route is "". Route-less registrations are the norm, not the
exception: 20 of r23's 32 records, 21 of r24's 44, 7 of r25's 16, 6 of r26's 31. And once the
name exists the route test never runs again, so a route filled in by a later update slips
past both checks.

r26 shows the whole sequence in its log, twice:

    register_ui_page  name=login       path=.../pages/LoginPage.jsx
    register_ui_page  name=login_page  path=.../pages/LoginPage.jsx

and ended with /login under both names and /profiles likewise, all four carrying
merged_under_lock_1193=None — #1193 never fired on any of them. That is what
`deliverability_ui_page_unwired` then blocks on: one of every pair names a component that a
route already claims, so it can never be shown as wired.

The direction of the component test is the whole safety argument, and it is asymmetric.
"""
import inspect

from env_generator.llm_generator.multi_agent.runtime import registryhub as R

_SRC = inspect.getsource(R.RegistryHub.register_ui_page)
_MUT = _SRC[_SRC.index("def _set_under_lock_1193"):_SRC.index("self._ui_pages.update(")]


def test_a_routeless_registration_matches_on_component():
    assert "_merged_by_path_1195" in _MUT or "merged_by_path_1195" in _MUT
    assert '_v1195.get("path")' in _MUT


def test_it_only_fires_when_the_incoming_record_has_no_route():
    """★ The safety argument. Two routes may legitimately render one component (a shared
    list page), so a component match between two ROUTED records proves nothing. A record
    with no route cannot be a distinct route, so the match is only made in that direction."""
    guard = _MUT[_MUT.index("_path1195 = "):_MUT.index("for _k1195")]
    assert 'not str(route or "").strip()' in guard, "must require an EMPTY incoming route"
    assert "_path1195 and" in guard, "and a non-empty component FILE to match on"


def test_it_keeps_the_existing_record_and_its_route():
    body = _MUT[_MUT.index("for _k1195"):_MUT.index("if route and name not in _live")]
    assert "m.set(_k1195, _rec, actor)" in body, "write under the EXISTING key"
    assert '_rec["route"] = _rec.get("route") or _v1195.get("route")' in body, (
        "a route-less incoming record must not blank the existing route")


def test_the_route_check_still_runs_after_it():
    """#1195 is an additional door, not a replacement — a routed collision still merges."""
    assert "if route and name not in _live:" in _MUT
    assert _MUT.index("_path1195") < _MUT.index("if route and name not in _live:")


def test_both_merges_stay_auditable():
    assert "merged_route_aliases" in _MUT
    assert _MUT.count("merged_route_aliases") >= 2, "both paths must record the alias"


def test_a_fault_still_falls_through_to_a_plain_write():
    assert "except Exception" in _MUT
    assert _MUT.rstrip().endswith("return m.set(name, rec, actor)")
