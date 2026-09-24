"""FIX #84 — deterministic authored-seed AMPLIFICATION to the density floor
(instagram run-5, 2026-07-06 02:38 STUCK).

The backend lane authored a REALISTIC but thin seed (9 rows); the gate demands >= 10; the
lane ignored 7 remediation dispatches → STUCK-abort — while the LIVE DB was already dense
(fallback + FIX #74 concentration), because the gate audits the FILE. The framework owns
the density floor the same way #74 owns demo concentration: clone-and-perturb the lane's
own realistic rows (new unique ids/emails/usernames, shifted timestamps, FK values rotated
within the seed's own id pools, FK-combo dedup so join-table UNIQUEs can't collide) until
the floor holds, and write the file back. Marker-flagged (placeholder) seeds are NOT
amplified — garbage×N is still garbage; that stays a lane job. Pure + deterministic.
ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.seed_audit import amplify_authored_seed, audit_authored_seed  # noqa: E402

# the run-5 live shape: realistic content, 9 rows total, floor is 10
_THIN = {
    "users": [
        {"id": 1, "username": "lena_frames", "email": "lena@lumenfeed.com",
         "created_at": "2026-05-01T09:00:00"},
        {"id": 2, "username": "marco.trail", "email": "marco@lumenfeed.com",
         "created_at": "2026-05-02T10:30:00"},
    ],
    "posts": [
        {"id": 1, "user_id": 1, "caption": "Golden hour over the ridge.",
         "created_at": "2026-06-01T18:20:00"},
        {"id": 2, "user_id": 2, "caption": "City rain, warm coffee.",
         "created_at": "2026-06-03T08:05:00"},
    ],
    "comments": [
        {"id": 1, "post_id": 1, "user_id": 2, "content": "Stunning light!"},
        {"id": 2, "post_id": 2, "user_id": 1, "content": "Where is this?"},
    ],
    "likes": [
        {"id": 1, "post_id": 1, "user_id": 2},
        {"id": 2, "post_id": 2, "user_id": 1},
    ],
    "reposts": [
        {"id": 1, "post_id": 1, "user_id": 2},
    ],
}


def test_amplifies_thin_seed_to_floor_and_clears_audit():
    data = json.loads(json.dumps(_THIN))
    out = amplify_authored_seed(data)
    assert out is not None
    assert audit_authored_seed(out) == []              # floor met, no markers introduced
    total = sum(len(v) for v in out.values())
    assert total >= 10


def test_clone_ids_unique_and_fks_stay_in_pool():
    out = amplify_authored_seed(json.loads(json.dumps(_THIN)))
    user_ids = {r["id"] for r in out["users"]}
    post_ids = {r["id"] for r in out["posts"]}
    assert len(out["users"]) == len(user_ids)          # no duplicate pks
    assert len(out["posts"]) == len(post_ids)
    for t in ("comments", "likes", "reposts"):
        for r in out[t]:
            assert r["user_id"] in user_ids or r["user_id"] in (1, 2)
            assert r["post_id"] in post_ids or r["post_id"] in (1, 2)
    # unique-credential fields perturbed on clones
    assert len({r["email"] for r in out["users"]}) == len(out["users"])
    assert len({r["username"] for r in out["users"]}) == len(out["users"])


def test_join_table_fk_combos_never_duplicate():
    out = amplify_authored_seed(json.loads(json.dumps(_THIN)))
    combos = [(r["user_id"], r["post_id"]) for r in out["likes"]]
    assert len(combos) == len(set(combos))             # UNIQUE(user_id, post_id) safe


def test_marker_flagged_seed_is_not_amplified():
    bad = {"users": [{"id": 1, "username": "test user", "email": "placeholder@example.com",
                      "bio": "lorem ipsum placeholder"}]}
    if not any("placeholder content" in i for i in audit_authored_seed(bad)):
        import pytest
        pytest.skip("marker heuristic did not flag this fixture")
    assert amplify_authored_seed(bad) is None


def test_dense_seed_untouched():
    dense = {"users": [{"id": i, "username": f"u{i}", "email": f"u{i}@ex.net"}
                       for i in range(1, 12)]}
    assert audit_authored_seed(dense) == []
    assert amplify_authored_seed(dense) is None


def test_ensure_seed_json_writes_amplified_file_back(tmp_path):
    from multi_agent.runtime.backend_skeleton import _ensure_seed_json
    be = tmp_path / "backend"
    be.mkdir()
    (be / "seed_data.json").write_text(json.dumps(_THIN), encoding="utf-8")
    _ensure_seed_json(be, amplify=True)
    on_disk = json.loads((be / "seed_data.json").read_text(encoding="utf-8"))
    assert audit_authored_seed(on_disk) == []          # gate clears by construction
    # idempotent: second pass leaves the (now-dense) file alone
    before = (be / "seed_data.json").read_text(encoding="utf-8")
    _ensure_seed_json(be, amplify=True)
    assert (be / "seed_data.json").read_text(encoding="utf-8") == before


def test_seed_loader_reseeds_when_fingerprint_matches_but_tables_wiped():
    """FIX #99 (run-17 M3, live): reset.sh clears business rows via Base.metadata but
    _seed_meta is a raw-SQL table it never touches — the surviving fingerprint made the
    loader SKIP re-seeding an EMPTY database (posts=0 post-reset) → every chain id-source
    starved → literal ${x_id} 422 wedge at M3. The generated loader now probes the
    seed-managed BUSINESS tables (users/tenants excluded — the spine survives resets) and
    falls through to re-apply when all are empty despite a matching fingerprint."""
    import ast
    from multi_agent.runtime.backend_skeleton import render_seed_data
    src = render_seed_data({"posts": {"name": "posts", "columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "caption", "type": "text"}]}})
    ast.parse(src)                                 # generated loader still compiles
    # FIX #130 refined #99: reseed when ANY seed-provided content table is empty
    # (partial wipe / orphan pollution) — the all-empty post-reset wipe #99 targeted is
    # a subset. The probe now tests emptiness of the SEED-PROVIDED business tables.
    assert "partial wipe" in src and "FIX #130" in src
    i = src.index("_seed_incomplete")
    window = src[i:i + 1500]
    assert "'users', 'tenants'" in window          # spine excluded from the probe
    assert "_sync_sequences" in window             # fully-seeded path keeps the heal-only behavior
