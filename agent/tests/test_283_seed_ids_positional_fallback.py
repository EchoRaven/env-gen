"""FIX #283 — load_seed_ids is BLIND whenever the authored seed omits explicit ids (tiktok r68, live).

#144 built a deterministic recovery source for literal-id 404s: {table → first explicit
non-None row id} read from the authored app/backend/seed_data.json. #130/#135 lean on the same
assumption (they re-seed MISSING rows *BY PK*).

r68 (live) showed the assumption is never enforced. Its seed carries 23 videos / 10 sounds /
5 users and **not one row declares an `id`** — yet the very same file's FK columns already
assume positional autoincrement ids:

    users[0]  -> {}                                (no id key at all)
    videos[0] -> {"author_id": 1, "sound_id": 1}   (points at users[0] / sounds[0])
    likes[0]  -> {"user_id": 1, "video_id": 2}     (points at users[0] / videos[1])

So the seed depends on ids being 1..N in insertion order while declaring none of them.
`load_seed_ids('generated/tiktok-web-r68')` returns `{}` — verified by hand — leaving the
literal-id recovery ladder without its deterministic rung.

Fix: when a table's rows carry no explicit id, fall back to the POSITIONAL id the database is
about to assign (first row → 1). Same value the seed's own FKs already point at, and type-safe
by construction: these ids are only ever consumed to replace a NUMERIC literal in a path, so a
text/uuid-PK table can never be reached through this route. Explicit ids always win — a seed
that declares them is untouched. ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import multi_agent.runtime.chain_executor as ce  # noqa: E402


def _seed(tmp_path, payload):
    d = tmp_path / "app" / "backend"
    d.mkdir(parents=True)
    (d / "seed_data.json").write_text(json.dumps(payload), encoding="utf-8")
    return tmp_path


def test_explicit_ids_still_win(tmp_path):
    """Unchanged #144 behaviour: a declared id is authoritative."""
    p = _seed(tmp_path, {"videos": [{"id": 7, "caption": "a"}, {"id": 8}]})
    assert ce.load_seed_ids(p) == {"videos": 7}


def test_r68_shape_falls_back_to_positional(tmp_path):
    """The live wedge: rows with no id at all must still yield the DB's first id (1)."""
    p = _seed(tmp_path, {
        "users": [{"email": "a@b.c", "name": "A"}, {"email": "d@e.f", "name": "D"}],
        # r68's real videos row: FKs AND data columns (author/video_url/caption/…)
        "videos": [{"author_id": 1, "sound_id": 1, "video_url": "/v/1.mp4",
                    "caption": "c"}, {"author_id": 2, "caption": "d"}],
    })
    assert ce.load_seed_ids(p) == {"users": 1, "videos": 1}


def test_first_explicit_id_wins_over_position(tmp_path):
    """A table whose FIRST row lacks an id but a later row declares one: the declared
    id is real data and must be preferred over a guess."""
    p = _seed(tmp_path, {"videos": [{"caption": "no id"}, {"id": 42}]})
    assert ce.load_seed_ids(p) == {"videos": 42}


def test_empty_table_yields_nothing(tmp_path):
    """No rows → no id to recover; must not invent one."""
    p = _seed(tmp_path, {"videos": [], "sounds": [{"title": "t"}]})
    assert ce.load_seed_ids(p) == {"sounds": 1}


def test_non_list_and_missing_file_are_safe(tmp_path):
    p = _seed(tmp_path, {"_meta": {"x": 1}, "videos": "not-a-list"})
    assert ce.load_seed_ids(p) == {}
    assert ce.load_seed_ids(tmp_path / "nope") == {}


def test_rows_that_are_not_mappings_are_skipped(tmp_path):
    p = _seed(tmp_path, {"videos": ["junk", {"caption": "real"}]})
    # first MAPPING row is positionally the 2nd row → id 2
    assert ce.load_seed_ids(p) == {"videos": 2}


def test_pure_association_tables_get_no_fabricated_id(tmp_path):
    """A join row is ALL FKs — composite pk, no `id` column exists. Inventing one would
    fabricate a column (caught by the pre-existing test_chain_literal_id_seed_recovery,
    which my first cut of #283 broke). r68's likes/saves are exactly this shape."""
    p = _seed(tmp_path, {
        "follows": [{"follower_id": 1, "followee_id": 2}],
        "likes": [{"user_id": 1, "video_id": 2}],
        "videos": [{"author_id": 1, "caption": "real data column"}],
    })
    assert ce.load_seed_ids(p) == {"videos": 1}
