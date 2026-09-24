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
