"""#1202w7: the run's own test users ship inside the delivered product.

Every validation flow that signs up, every chain that needs a second actor, every password
probe writes a row into the delivered app's actor table, and nothing removes or marks them.
Counted against the four delivered stacks still running:

    tiktok-r135   12 users,   9 seeded,   3 added by the run   (25%)
    tiktok-r132   12 users,   9 seeded,   3 added               (25%)
    tiktok-r126   92 users,   9 seeded,  83 added               (90%)
    netflix-r30  231 users,   6 seeded, 225 added               (97%)

User-visible, not merely untidy: r126's `GET /api/creators/suggested` reports `total: 92`, so
nine real creators sit in a list that is ninety percent `verifier_sender_3`,
`signup_flow_user` and `smoke_user`.

COUNTED, NOT CLEANED. Deleting rows at delivery risks the FKs every other seeded table points
through and there is no live run to validate it against; marking them at creation needs the
names the VERIFIER invents at runtime, which the framework cannot enumerate from its own
source, so a matcher would be guessing. `delivered - seeded` needs neither — it is arithmetic
on two numbers the framework already holds, and it does not depend on what anything is named.

`created_at IS NULL` separates them perfectly in every stack today, and is deliberately NOT
used: that works only because #1202rw's seeds leave the column empty, so the rule would break
on the day that defect is fixed.
"""
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import seed_audit as SA      # noqa: E402


def _project(tmp_path, seeded_users, live_counts, monkeypatch, sub=""):
    root = tmp_path / sub if sub else tmp_path
    be = root / "app" / "backend"
    be.mkdir(parents=True, exist_ok=True)
    (be / "seed_dataset.json").write_text(
        json.dumps({"users": [{"id": i} for i in range(seeded_users)]}), encoding="utf-8")
    monkeypatch.setattr(SA, "live_row_counts_1039", lambda *a, **k: dict(live_counts))
    return root


def test_the_r126_shape_is_counted(tmp_path, monkeypatch):
    p = _project(tmp_path, 9, {"users": 92, "videos": 39}, monkeypatch)
    assert SA.run_created_actor_rows_1202w7(p) == {
        "table": "users", "delivered": 92, "seeded": 9, "added_by_run": 83, "share": 0.9022}


def test_a_clean_run_reads_zero(tmp_path, monkeypatch):
    p = _project(tmp_path, 9, {"users": 9}, monkeypatch)
    r = SA.run_created_actor_rows_1202w7(p)
    assert r["added_by_run"] == 0 and r["share"] == 0.0


def test_an_unmeasurable_run_is_empty_not_clean(tmp_path, monkeypatch):
    """#1039's rule, restated: `{}` must mean "not measured" and never "nothing was added"."""
    assert SA.run_created_actor_rows_1202w7(
        _project(tmp_path, 9, {}, monkeypatch, "a")) == {}             # no live DB
    assert SA.run_created_actor_rows_1202w7(
        _project(tmp_path, 0, {"users": 92}, monkeypatch, "b")) == {}  # no seed to compare
    assert SA.run_created_actor_rows_1202w7(
        _project(tmp_path, 9, {"videos": 39}, monkeypatch, "c")) == {} # no actor table


def test_a_shrunken_table_never_reads_negative(tmp_path, monkeypatch):
    p = _project(tmp_path, 20, {"users": 5}, monkeypatch)
    assert SA.run_created_actor_rows_1202w7(p)["added_by_run"] == 0


def test_the_reading_reaches_an_artifact(tmp_path):
    """#947. This exists to be the evidence a future cleanup decision is made on, exactly as
    #1202w4 is for #351 — a reading that dies with the console cannot play that part."""
    r = {"table": "users", "delivered": 92, "seeded": 9, "added_by_run": 83, "share": 0.9022}
    assert SA.record_run_created_actor_rows_1202w7(tmp_path, r)
    rec = json.loads(
        (tmp_path / "logs" / "run_created_actor_rows_1202w7.jsonl").read_text().strip())
    assert rec["added_by_run"] == 83 and rec["delivered"] == 92 and "at" in rec
    assert not SA.record_run_created_actor_rows_1202w7(tmp_path, {})
    assert not SA.record_run_created_actor_rows_1202w7(None, r)


def test_it_does_not_key_on_created_at():
    """The discriminator that works today and must not be used: `created_at IS NULL` splits
    seeded from run-created perfectly in all four stacks, and only because #1202rw leaves it
    empty. A rule built on another defect breaks when that defect is fixed."""
    import inspect

    src = inspect.getsource(SA.run_created_actor_rows_1202w7)
    assert "created_at" not in src


def test_it_does_not_guess_at_probe_names():
    """The other tempting matcher. `verifier_sender_3` and `signup_flow_user` are named by the
    verifier at runtime, so the framework cannot enumerate them and a list would be a guess."""
    import inspect

    src = inspect.getsource(SA.run_created_actor_rows_1202w7)
    for guess in ("verifier", "smoke", "probe", "flow_user", "example.com"):
        assert guess not in src, f"the count must not depend on the name `{guess}`"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
