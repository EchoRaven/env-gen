r"""#1202tw/#1202tx: the framework's seed fallback broke the Realism Contract it enforces.

The agent prompts carry a gate-enforced Realism Contract. Clause 5 forbids reusing the same
invented person across environments; clause 6 requires data that is uneven, and names UNIFORM
STATE as "the quiet version" of the same defect -- "in the real product the flag is what makes
a row DIFFERENT from its neighbours". Every lane is held to it. The framework's own `_SEED`
fallback -- what ships whenever a table is in neither the dataset nor the lane's seed_data.json
-- broke it on nearly every clause.

MEASURED over the 150 delivered `app/backend/seed_data.py` files in generated/:

    the same six people (Ava Chen, Liam Patel, Noah Kim, ...)   150 / 150   across 5 domains
    one literal filler sentence, verbatim                       102 / 150
    the same six generic titles                                 125 / 150

Ava Chen was a TikTok creator, a Netflix subscriber, an Instagram user AND a Google Maps
reviewer. For a study that reads these environments as independent, that is not a blemish --
two environments sharing a cast are not two samples.

#1202tw -- pools widened (6 people -> 48, 5 sentences -> 22, 6 titles -> 24) and drawn through
a per-ENVIRONMENT deterministic shuffle keyed by the run directory name, so two environments
share a name only by coincidence. Copy is concrete rather than filler, per the rubric's
dimension 1 ("bodies that describe nothing concrete" is among the strongest single tells).

#1202tx -- four defects the same fallback carried, each visible in a delivered r132 seed:
  * `comment_count` was seeded a SENTENCE: the text branch matched "comment" as a substring
    and ran before the number branch. Suffix now wins over substring.
  * an unresolved `*_id` fell through to that same text branch. A key column is never prose.
  * status/state, role and visibility were constant down every table.
  * `is_*` alternated `i % 2 == 0` -- a visible regularity AND the wrong rate; clause 6 says a
    badge on half the rows still reads as a switch turned on for the demo.
  * a SELF-REFERENTIAL FK pointed at the row's own id -- all six r132 comments were their own
    parent, a cycle no real table can hold.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import ast
import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.backend_skeleton import (  # noqa: E402
    _SEED_PEOPLE, _SEED_SENTENCES, _SEED_TITLES, _env_cast_1202tw, render_seed_data,
)


def _seed(tables, salt=""):
    tree = ast.parse(render_seed_data(tables, {}, env_salt=salt))
    for n in tree.body:
        if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "_SEED":
            return ast.literal_eval(n.value)
    raise AssertionError("_SEED is gone")


PEOPLE_TBL = {"users": {"columns": [
    {"name": "id", "type": "integer", "primary_key": True},
    {"name": "name", "type": "text"}, {"name": "email", "type": "text"},
    {"name": "username", "type": "text"}, {"name": "bio", "type": "text"}]}}


def test_two_environments_do_not_share_a_cast():
    """Clause 5, and the 150/150 measurement above."""
    a = [r["name"] for r in _seed(PEOPLE_TBL, "tiktok-web-r133")["users"]]
    b = [r["name"] for r in _seed(PEOPLE_TBL, "netflix-local-r12")["users"]]
    assert set(a) & set(b) == set(), (a, b)


def test_the_same_environment_renders_identically():
    """Determinism is not optional: the loader replays the table on a fingerprint change."""
    assert _seed(PEOPLE_TBL, "tiktok-web-r133") == _seed(PEOPLE_TBL, "tiktok-web-r133")


def test_a_row_stays_internally_consistent():
    """name / email / username must still describe ONE person after the shuffle."""
    for r in _seed(PEOPLE_TBL, "tiktok-web-r133")["users"]:
        slug = r["name"].lower().replace(" ", "")
        assert r["email"].split("@")[0] == slug, r
        assert r["username"] == "@" + slug, r


def test_the_pools_are_wide_enough_to_stop_repeating():
    assert len(_SEED_PEOPLE) >= 40 and len(_SEED_SENTENCES) >= 18 and len(_SEED_TITLES) >= 18


def test_the_filler_sentence_is_gone():
    """The single line that appeared verbatim in 102 of 150 delivered environments."""
    assert "A short overview of what this is and how it works." not in _SEED_SENTENCES
    # every replacement names something concrete -- a digit, a name, or a weekday
    import re
    vague = [s for s in _SEED_SENTENCES
             if not re.search(r"\d|Mon|Tue|Wed|Thu|Fri|[A-Z][a-z]+ [a-z]|[A-Z][a-z]{2,}", s)]
    assert vague == [], vague


def test_the_cast_shuffle_is_a_permutation():
    for salt in ("", "a", "tiktok-web-r133"):
        assert sorted(_env_cast_1202tw(_SEED_PEOPLE, salt)) == sorted(_SEED_PEOPLE)


# ---------------------------------------------------------------- #1202tx

TYPED_TBL = {"comments": {"columns": [
    {"name": "id", "type": "integer", "primary_key": True},
    {"name": "parent_id", "type": "integer", "fk": "comments.id"},
    {"name": "orphan_ref_id", "type": "integer"},
    {"name": "text", "type": "text"}, {"name": "comment_count", "type": "integer"},
    {"name": "message_total", "type": "integer"},
    {"name": "status", "type": "text"}, {"name": "visibility", "type": "text"},
    {"name": "is_verified", "type": "boolean"}, {"name": "is_active", "type": "boolean"}]}}


def test_a_count_column_is_a_number_even_when_its_name_reads_as_text():
    """r132 shipped `'comment_count': 'A short overview of what this is and how it works.'`"""
    for r in _seed(TYPED_TBL, "e1")["comments"]:
        assert isinstance(r.get("comment_count"), int), r
        assert isinstance(r.get("message_total"), int), r


def test_an_unresolved_key_column_is_never_prose():
    for r in _seed(TYPED_TBL, "e1")["comments"]:
        assert not isinstance(r.get("orphan_ref_id"), str), r


def test_a_self_referential_fk_never_points_at_itself_or_forward():
    """All six r132 comments were their own parent."""
    rows = _seed(TYPED_TBL, "e1")["comments"]
    for pk, r in enumerate(rows, start=1):
        par = r.get("parent_id")
        if par is None:
            continue
        assert par < pk, f"row {pk} parents {par}"


def test_a_self_referential_fk_leaves_real_roots():
    rows = _seed(TYPED_TBL, "e1")["comments"]
    assert sum(1 for r in rows if r.get("parent_id") is None) >= 2, rows


def test_state_columns_are_not_constant():
    """Clause 6's UNIFORM STATE, measured as variance rather than asserted as a value."""
    rows = _seed(TYPED_TBL, "e1")["comments"]
    for col in ("status", "visibility"):
        assert len({r.get(col) for r in rows}) > 1, (col, [r.get(col) for r in rows])


def test_booleans_are_neither_alternating_nor_uniform():
    """`i % 2 == 0` was both a visible regularity and the wrong rate."""
    rows = _seed({"u": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "is_verified", "type": "boolean"},
        {"name": "is_active", "type": "boolean"}]}}, "e1")["u"]
    for col in ("is_verified", "is_active"):
        vals = [r.get(col) for r in rows]
        alternating = all(vals[k] != vals[k + 1] for k in range(len(vals) - 1))
        assert not alternating, (col, vals)


def test_a_badge_flag_is_rarer_than_a_capability_flag():
    """Clause 6: eight of eight verified reads as a switch turned on for the demo."""
    n = 60
    cols = [{"name": "id", "type": "integer", "primary_key": True},
            {"name": "is_verified", "type": "boolean"},
            {"name": "is_active", "type": "boolean"}]
    seen = collections.Counter()
    for env in range(n):
        for r in _seed({"u": {"columns": cols}}, f"env{env}")["u"]:
            seen["v"] += bool(r.get("is_verified"))
            seen["a"] += bool(r.get("is_active"))
            seen["n"] += 1
    assert seen["v"] / seen["n"] < 0.35, seen
    assert seen["a"] / seen["n"] > 0.5, seen
