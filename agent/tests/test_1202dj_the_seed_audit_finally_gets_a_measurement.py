r"""#1202dj: the seed audit is called only when the database is gone.

`live_row_counts_1039` is not broken. Called against a live stack it answers immediately —
verified against netflix-r44 at 12:05:44, which returned
`{'tenants': 1, 'users': 0, 'titles': 0, ...}` on the first try.

It never gets that chance. The framework cycles the stack (`down -v --remove-orphans`, then
`up`) around each validation, so the database container exists only inside short windows —
`docker ps` during r44 showed `Up 3 seconds` — and the audit is invoked from gate evaluation,
which mostly lands outside them. The corpus is unanimous:

    r41  165 of 165 "DID NOT RUN"      r42  173 of 173      r43  73 of 73
    2728 seed_audit lines across every run log in the repo, 100% the failure warning

That matters because of what the fallback does. #956 recorded it: with `_live == {}` the audit
reverts to the `status == "defined"` filter, which "skips 1729 of 1745 corpus tables", and
#1023d recorded the consequence — `is_clean` is `not flagged_tables`, so "examined nothing"
and "examined everything and found nothing wrong" are the same answer. This is the mechanism
that was supposed to catch #1105, where 58 of 59 runs silently shipped with every seeded user
gone.

The fix takes the measurement at the one moment the stack is known live — validation's
`backend_health` pass, right after `docker_up` — and records it for the gate to read.

The invariant this must not break, and the reason the recorded value expires: NOT MEASURED IS
NOT ZERO. A stale or absent record yields `{}`, exactly as a missing database does, and the
audit reverts to the behavior it has today rather than inventing a clean bill of health.
"""
import json
import time
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime.seed_audit import (
    audit_seed_data,
    record_live_counts_1202dj,
    recent_live_counts_1202dj,
)


class _Schema:
    def __init__(self, tables):
        self._t = tables

    def list_tables(self):
        return self._t

    def list_seed_registrations(self):
        return {}


class _Hubs:
    def __init__(self, tables):
        self.schema_hub = _Schema(tables)


# `users` is a framework-owned SPINE table the audit deliberately skips; `titles`
# is app seed content, which is what this gate is for.
_TABLES = {"titles": {"status": "implemented", "metadata": {"min_seed_rows": 1}}}


def test_a_recorded_measurement_round_trips(tmp_path):
    record_live_counts_1202dj(tmp_path, {"users": 5, "titles": 40})
    assert recent_live_counts_1202dj(tmp_path) == {"users": 5, "titles": 40}


def test_a_stale_measurement_is_not_a_measurement(tmp_path):
    record_live_counts_1202dj(tmp_path, {"users": 5})
    p = Path(tmp_path) / "shared" / "seed_live_counts_1202dj.json"
    rec = json.loads(p.read_text(encoding="utf-8"))
    rec["at"] = time.time() - 100_000
    p.write_text(json.dumps(rec), encoding="utf-8")
    assert recent_live_counts_1202dj(tmp_path) == {}


def test_no_record_is_not_a_measurement(tmp_path):
    assert recent_live_counts_1202dj(tmp_path) == {}


def test_a_corrupt_record_is_not_a_measurement(tmp_path):
    p = Path(tmp_path) / "shared"
    p.mkdir(parents=True, exist_ok=True)
    (p / "seed_live_counts_1202dj.json").write_text("{not json", encoding="utf-8")
    assert recent_live_counts_1202dj(tmp_path) == {}


def test_an_empty_count_map_is_not_recorded_as_a_measurement(tmp_path):
    """`{}` from a failed read must not be stored as 'everything is zero'."""
    record_live_counts_1202dj(tmp_path, {})
    assert recent_live_counts_1202dj(tmp_path) == {}


def test_the_audit_now_sees_an_empty_seeded_table(tmp_path):
    """#1105's shape: the table exists, the seed is gone, and nobody noticed."""
    record_live_counts_1202dj(tmp_path, {"titles": 0})
    rep = audit_seed_data(_Hubs(_TABLES), project_dir=tmp_path)
    assert not rep.is_clean, "the audit still cannot see an empty seeded table"
    assert any(f["table"] == "titles" and f["reason"] == "missing_seed"
               for f in rep.flagged_tables), rep.flagged_tables


def test_the_finding_says_where_the_number_came_from(tmp_path):
    """A count taken at docker_up is not a count taken at gate time; say so."""
    record_live_counts_1202dj(tmp_path, {"titles": 0})
    rep = audit_seed_data(_Hubs(_TABLES), project_dir=tmp_path)
    src = rep.flagged_tables[0]["detail"]["source"]
    assert "1202dj" in src, src


def test_a_healthy_seed_is_not_flagged(tmp_path):
    record_live_counts_1202dj(tmp_path, {"titles": 40})
    rep = audit_seed_data(_Hubs(_TABLES), project_dir=tmp_path)
    assert rep.is_clean, rep.flagged_tables


def test_without_a_record_the_audit_behaves_exactly_as_before(tmp_path):
    """The additive contract #956 wrote down: no measurement changes nothing."""
    rep = audit_seed_data(_Hubs(_TABLES), project_dir=tmp_path)
    assert rep.is_clean, rep.flagged_tables


# --- the reader must resolve the project root the same way the live read does -------------
#
# Caught end-to-end, not by a unit test: the resumed r44 captured counts correctly and the
# audit still logged "SEED AUDIT EXAMINED 0 OF 12 TABLES". `live_row_counts_1039` normalises
# its path two ways this reader did not, and both are already documented traps:
#
#   #1044 — every lane gets a worktree under `<project>/worktrees/<lane>/`, so a caller
#           holding a worktree path must be hoisted to the canonical tree.
#   #563  — callers hold `<project>/app` as often as the project root.
#
# Capturing the number and then being unable to find it from the caller that needs it is the
# same "built but never wired" shape this batch exists to remove.

def test_a_worktree_caller_finds_the_measurement(tmp_path):
    record_live_counts_1202dj(tmp_path, {"titles": 60})
    wt = Path(tmp_path) / "worktrees" / "verifier"
    wt.mkdir(parents=True)
    assert recent_live_counts_1202dj(wt) == {"titles": 60}


def test_an_app_root_caller_finds_the_measurement(tmp_path):
    record_live_counts_1202dj(tmp_path, {"titles": 60})
    app = Path(tmp_path) / "app"
    app.mkdir(parents=True)
    assert recent_live_counts_1202dj(app) == {"titles": 60}


def test_recording_from_a_worktree_lands_in_the_canonical_tree(tmp_path):
    """Otherwise two callers write two files and neither sees the other's."""
    wt = Path(tmp_path) / "worktrees" / "backend"
    wt.mkdir(parents=True)
    record_live_counts_1202dj(wt, {"titles": 7})
    assert (Path(tmp_path) / "shared" / "seed_live_counts_1202dj.json").is_file()
    assert recent_live_counts_1202dj(tmp_path) == {"titles": 7}


def test_an_unrelated_path_still_measures_nothing(tmp_path):
    """Normalising must not turn 'no record' into someone else's record."""
    assert recent_live_counts_1202dj(tmp_path / "elsewhere") == {}
