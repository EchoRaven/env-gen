"""#1202ni: the regression guard stands down when every failing chain is unchanged since it passed.

tiktok-r125 M2. `follow_lifecycle_isolation_chain_v2` saved `userB` from `item.id`, which the
register response does not have. It passed once because the substitution ladder happened to send a
different user's id, so it was in the last-passing snapshot. It then failed with
`cannot follow yourself`; the verifier registered a corrected v3, and the guard saw re-authoring
and restored the snapshot — dropping v3 and keeping the broken v2 — at 06:43 and 06:49, until #327
poisoned the snapshot at 07:15. For those 32 minutes business_chain was held away from the verifier.

A restore replaces chains with their snapshot versions. When each failing chain already IS its
snapshot version, a restore cannot change the outcome.
"""
from __future__ import annotations

import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.framework_validation import (  # noqa: E402
    restore_regressed_chains, snapshot_passing_chains)
from multi_agent.runtime.json_store import JsonStore  # noqa: E402

V2 = {"steps": [{"method": "POST", "path": "/auth/register", "save": {"userB": "item.id"}},
                {"method": "POST", "path": "/api/users/${userB}/follow"}]}
V3 = {"steps": [{"method": "POST", "path": "/auth/register", "save": {"userB": "user.id"}},
                {"method": "POST", "path": "/api/users/${userB}/follow"}]}
FEED = {"steps": [{"method": "GET", "path": "/api/feed"}]}


def _orch(tmp):
    chains = JsonStore(Path(tmp) / "registryhub_verification_chains.json")
    eps = {"POST:/api/users/{user_id}/follow": {}, "GET:/api/feed": {}}
    rh = types.SimpleNamespace(_verification_chains=chains, get_endpoints=lambda: dict(eps))
    lines = []
    orch = types.SimpleNamespace(
        hubs=types.SimpleNamespace(registryhub=rh),
        _logger=types.SimpleNamespace(warning=lambda m, *a, **k: lines.append(m % a if a else m),
                                      info=lambda *a, **k: None),
        _framework_validation_attempts=3)
    return orch, chains, lines


def _run(chains, statuses):
    cur = dict(chains.value() or {})
    for name, st in statuses.items():
        cur[name] = {**cur[name], "status": st, "last_run_at": time.time()}
    chains.update(lambda _v, _c=cur: _c, change_info={"agent": "chain_executor"})


def _green(tmp):
    orch, chains, lines = _orch(tmp)
    chains.set("follow_v2", dict(V2))
    chains.set("feed", dict(FEED))
    _run(chains, {"follow_v2": "passing", "feed": "passing"})    # the lucky substituted pass
    snapshot_passing_chains(orch)
    return orch, chains, lines


def test_r125_a_new_corrected_chain_is_not_deleted_to_restore_the_broken_one():
    with tempfile.TemporaryDirectory() as tmp:
        orch, chains, lines = _green(tmp)
        chains.set("follow_v3", dict(V3))                          # the verifier's fix
        _run(chains, {"follow_v2": "failing", "follow_v3": "passing", "feed": "passing"})
        fset = restore_regressed_chains(orch, frozenset({"business_chain"}))
        assert "business_chain" in fset
        assert "follow_v3" in chains.value()
        assert int(getattr(orch, "_chains_restore_count", 0) or 0) == 0
        assert orch._framework_validation_attempts == 3
        assert any("#1202ni" in ln for ln in lines)


def test_a_re_authored_failing_chain_is_still_restored():
    """The guard's own case: the verifier edited a passing chain into a broken one."""
    with tempfile.TemporaryDirectory() as tmp:
        orch, chains, _ = _green(tmp)
        chains.set("feed", {"steps": [{"method": "GET", "path": "/api/fed"}]})
        _run(chains, {"follow_v2": "passing", "feed": "failing"})
        fset = restore_regressed_chains(orch, frozenset({"business_chain"}))
        assert "business_chain" not in fset
        assert chains.value()["feed"]["steps"] == FEED["steps"]


def test_a_new_failing_chain_is_still_dropped():
    with tempfile.TemporaryDirectory() as tmp:
        orch, chains, _ = _green(tmp)
        chains.set("broken_new", {"steps": [{"method": "GET", "path": "/api/nope"}]})
        _run(chains, {"broken_new": "failing"})
        fset = restore_regressed_chains(orch, frozenset({"business_chain"}))
        assert "business_chain" not in fset
        assert "broken_new" not in chains.value()


def test_records_without_a_status_keep_the_previous_behaviour():
    with tempfile.TemporaryDirectory() as tmp:
        orch, chains, _ = _orch(tmp)
        chains.set("feed", dict(FEED))
        snapshot_passing_chains(orch)
        chains.set("extra", {"steps": [{"method": "GET", "path": "/api/x"}]})
        fset = restore_regressed_chains(orch, frozenset({"business_chain"}))
        assert "business_chain" not in fset
