"""#1193 — the ui_page dedup decided against a snapshot and wrote under a lock.

`register_ui_page` reads `_pages_now = self._ui_pages.value()` BEFORE the write, decides
there against a route collision, and then writes inside `JsonStore.update`'s lock. Five agent
roles hold `registryhub_register_ui_page`, so two lanes registering the same screen
concurrently each read a snapshot without the other's entry, each conclude they are first,
and both write.

It is in the ledgers. netflix-r24 carries `/login` under BOTH `login` and `login_page`, and
`/profiles` under BOTH `profiles` and `profiles_page` — all four with
merged_route_aliases=None, so the merge never ran. r21 has the same on `/profiles`. Both runs
FAILED to deliver, and both spent their gate budget on `deliverability_ui_page_unwired`,
which r24 hit 15 times: that check asks whether each registered page NAME is wired, a route
has exactly one component, so one of every duplicate pair can never be satisfied. The five
delivering runs have zero duplicates.
"""
import inspect
import re
import tempfile

from env_generator.llm_generator.multi_agent.runtime import registryhub as R
from env_generator.llm_generator.multi_agent.runtime import json_store as JS

_SRC = inspect.getsource(R.RegistryHub.register_ui_page)


def test_the_write_resolves_the_collision_inside_the_mutator():
    assert "_set_under_lock_1193" in _SRC
    body = _SRC[_SRC.index("def _set_under_lock_1193"):]
    body = body[:body.index("self._ui_pages.update(")]
    assert "m.value()" in body, "it must ask the LIVE view, not the outer snapshot"
    assert 'str(_v1193.get("route")' in body


def test_it_writes_under_the_existing_key_not_a_new_one():
    body = _SRC[_SRC.index("def _set_under_lock_1193"):]
    body = body[:body.index("self._ui_pages.update(")]
    assert "m.set(_k1193, _rec, actor)" in body, "the colliding record must reuse the key"


def test_the_alias_is_recorded_so_the_merge_is_auditable():
    body = _SRC[_SRC.index("def _set_under_lock_1193"):]
    assert "merged_route_aliases" in body and "merged_under_lock_1193" in body


def test_a_dedup_fault_can_never_fail_a_registration():
    body = _SRC[_SRC.index("def _set_under_lock_1193"):]
    body = body[:body.index("self._ui_pages.update(")]
    assert "except Exception" in body
    assert body.rstrip().endswith("return m.set(name, rec, actor)")


def test_the_store_update_really_holds_a_lock():
    """The whole fix rests on the mutator running under the lock with a fresh load — if that
    stopped being true the backstop would be racing too."""
    src = inspect.getsource(JS.JsonStore.update)
    assert "with self._lock" in src and "_file_lock()" in src
    assert src.index("_load_raw") > src.index("with self._lock"), "load must be inside"
    assert src.index("mutator(view)") > src.index("_load_raw")


def test_the_outer_snapshot_check_is_still_there():
    """It is what builds `rec` from the right `existing`; the in-lock check is the backstop
    for the case it cannot see, not a replacement."""
    assert "if route and name not in _pages_now:" in _SRC


# --- #1203pg: the collision is really resolved ---------------------------------------------------
#
# Every assertion above reads the SOURCE of `register_ui_page`. Two mutations were caught by
# that -- reading the outer snapshot instead of the live view, and writing under a new key --
# because each changed a quoted expression. The third was not: wrapping the whole
# route-collision branch in `if False:` leaves every asserted substring verbatim in the source
# and makes #1193 inert, which is the state the ticket describes (r26 ended with /login under
# two names and `merged_under_lock_1193=None` on all four records).
#
# `RegistryHub(tmp_path)` is enough to drive it, so the resolution can be asserted on the
# RECORDS rather than on the text that produces them.


def _hub_1203pg():
    return R.RegistryHub(tempfile.mkdtemp())


def test_two_names_on_one_route_collapse_to_one_record():
    hub = _hub_1203pg()
    hub.register_ui_page(name="login", route="/login", path="src/pages/LoginPage.jsx",
                         component="LoginPage", components=[], actor="lane")
    hub.register_ui_page(name="login_page", route="/login", path="src/pages/LoginPage.jsx",
                         component="LoginPage", components=[], actor="lane")
    pages = hub.list_ui_pages()
    assert list(pages) == ["login"], (
        "the route collision was not resolved -- /login exists under %s" % list(pages))


def _register_with_a_stale_snapshot(hub, **kw):
    """Register while the PRE-LOCK snapshot is empty -- i.e. simulate the race.

    #1203pg: the sequential case never reaches `_set_under_lock_1193` at all. The dedup at
    `register_ui_page`'s top reads `_pages_now = self._ui_pages.value()` and merges there, so
    two registrations one after the other are resolved BEFORE the lock and the record carries
    `merged_route_aliases` without `merged_under_lock_1193`. The under-lock resolver is the
    RACE backstop: it only fires when the snapshot did not show the other lane's entry.
    That is why the "branch never runs" mutation was MISSED -- the branch is not reachable
    sequentially, so it needed an injection point rather than a better fixture.

    Returning `{}` for exactly the first `value()` call reproduces it: the pre-lock read sees
    nothing, and the mutator's own `m.value()` inside the lock still sees the live store.
    """
    store = hub._ui_pages
    real = store.value
    calls = {"n": 0}

    def _stale():
        calls["n"] += 1
        return {} if calls["n"] == 1 else real()

    store.value = _stale
    try:
        hub.register_ui_page(**kw)
    finally:
        store.value = real
    assert calls["n"] >= 1, "the pre-lock snapshot was never read -- re-aim this harness"


def test_a_racing_registration_is_resolved_under_the_lock():
    """The case #1193 exists for: both lanes read a snapshot without the other's entry."""
    hub = _hub_1203pg()
    hub.register_ui_page(name="login", route="/login", path="src/pages/LoginPage.jsx",
                         component="LoginPage", components=[], actor="lane")
    _register_with_a_stale_snapshot(
        hub, name="login_page", route="/login", path="src/pages/LoginPage.jsx",
        component="LoginPage", components=[], actor="lane")
    pages = hub.list_ui_pages()
    assert list(pages) == ["login"], (
        "the race produced two records for /login: %s -- which is r26's outcome" % list(pages))


def test_the_under_lock_merge_is_auditable_from_the_record():
    """An unrecorded merge is a silent one. r26 ended with four records all carrying
    `merged_under_lock_1193=None`, which is how we know #1193 never fired on any of them."""
    hub = _hub_1203pg()
    hub.register_ui_page(name="login", route="/login", path="src/pages/LoginPage.jsx",
                         component="LoginPage", components=[], actor="lane")
    _register_with_a_stale_snapshot(
        hub, name="login_page", route="/login", path="src/pages/LoginPage.jsx",
        component="LoginPage", components=[], actor="lane")
    md = (hub.list_ui_pages()["login"].get("metadata") or {})
    assert md.get("merged_under_lock_1193") is True, md
    assert "login_page" in (md.get("merged_route_aliases") or []), md


def test_the_sequential_case_is_resolved_BEFORE_the_lock():
    """Pinned so the division of labour stays visible: if this ever starts carrying
    `merged_under_lock_1193`, the pre-lock dedup has stopped working and the backstop is
    silently doing its job."""
    hub = _hub_1203pg()
    hub.register_ui_page(name="login", route="/login", path="src/pages/LoginPage.jsx",
                         component="LoginPage", components=[], actor="lane")
    hub.register_ui_page(name="login_page", route="/login", path="src/pages/LoginPage.jsx",
                         component="LoginPage", components=[], actor="lane")
    md = (hub.list_ui_pages()["login"].get("metadata") or {})
    assert "login_page" in (md.get("merged_route_aliases") or []), md
    assert md.get("merged_under_lock_1193") is None, (
        "the pre-lock dedup no longer resolves the sequential case: %s" % md)


def test_two_distinct_routes_are_left_alone():
    """Non-vacuity: a resolver that collapsed everything would pass the tests above."""
    hub = _hub_1203pg()
    hub.register_ui_page(name="login", route="/login", path="src/pages/LoginPage.jsx",
                         component="LoginPage", components=[], actor="lane")
    hub.register_ui_page(name="browse", route="/browse", path="src/pages/BrowsePage.jsx",
                         component="BrowsePage", components=[], actor="lane")
    assert sorted(hub.list_ui_pages()) == ["browse", "login"]


def test_re_registering_the_same_name_is_not_a_collision():
    """An update to an existing page must not be treated as a second page."""
    hub = _hub_1203pg()
    for status in ("defined", "implemented"):
        hub.register_ui_page(name="login", route="/login", path="src/pages/LoginPage.jsx",
                             component="LoginPage", components=[], status=status, actor="lane")
    pages = hub.list_ui_pages()
    assert list(pages) == ["login"]
    assert "login" not in (
        (pages["login"].get("metadata") or {}).get("merged_route_aliases") or []), (
        "a page was recorded as an alias of itself")
