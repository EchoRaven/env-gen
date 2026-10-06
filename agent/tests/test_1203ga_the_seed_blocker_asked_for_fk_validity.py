"""#1203ga — the seed blocker said "keep it FK-valid" and nothing checked it.

`audit_authored_seed`'s blocker text ends: "rewrite app/backend/seed_data.json (keep it
FK-valid)". The audit never examined FK validity. `#1168` asks exactly that question — and
answers it from `_psql` against the live app database, which `#1039`'s note in that same module
records as essentially never available; `orphan_fk_rows` reaches the hub output of 3 corpus runs.

The authored seed is on disk the whole time. Counted over the 184 runs that have one, with
#1168's OWN rule (`<x>_id` -> a table named `<x>`/`<x>s`/`<x>es`) and only tables carrying an
explicit `id`: 10883 foreign-key values, of which 247 across 10 RUNS point at a row that is not
in the file — 4 of those runs DELIVERED. Largest: `likes.user_id` 42, `comments.user_id` 30,
`comment_likes.user_id` 22, `saves.user_id` 20, `video_likes.video_id` 15. netflix-r32 ships
`title_genres`, `my_list`, `ratings` and `continue_watching` all pointing at titles 7–12 while
`titles` holds ids 1–6.

REPORTED, NOT BLOCKING — #1168's stated policy for this exact property, and its reason: "a false
seed blocker wedges a run (#566j), and this is evidence for the lane". Promoting it to a gate
would touch 10 of 184 runs and 4 of 80 deliveries, and wants a run's evidence behind it.
"""
import json
import sys
from pathlib import Path

import pytest

_AGENT = Path(__file__).resolve().parents[1]
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

from env_generator.llm_generator.multi_agent.runtime.seed_audit import (  # noqa: E402
    orphan_fk_rows_in_authored_seed_1203ga as orphans)


def test_a_dangling_reference_is_counted():
    data = {"titles": [{"id": 1}, {"id": 2}],
            "episodes": [{"id": 1, "title_id": 1}, {"id": 2, "title_id": 7}]}
    assert orphans(data) == {"episodes.title_id": 1}


def test_every_dangling_row_is_counted_not_just_the_first():
    data = {"users": [{"id": 1}],
            "comments": [{"id": i, "user_id": 99} for i in range(1, 6)]}
    assert orphans(data) == {"comments.user_id": 5}


def test_a_valid_seed_is_silent():
    data = {"users": [{"id": 1}, {"id": 2}],
            "comments": [{"id": 1, "user_id": 1}, {"id": 2, "user_id": 2}]}
    assert orphans(data) == {}


def test_a_null_reference_and_an_id_column_produce_no_finding():
    """The two observable properties — asserted as OUTCOMES, with no claim about which line
    delivers them.

    I first wrote one test per clause (`val is None`, `col == "id"`) and BOTH mutations removing
    those clauses stayed green, through two attempts at making the tests reachable. They are
    genuinely redundant: `"id".endswith("_id")` is already False, and a `None` value is already
    excluded by the later `isinstance(val, (int, str))`. They are kept because `_fk_fields` in
    the same module guards the same way, but a test that names a clause it cannot fail on is
    noise — so this pins what callers can see instead."""
    assert orphans({"users": [{"id": 1}],
                    "comments": [{"id": 1, "user_id": None}, {"id": 2, "user_id": 1}]}) == {}
    assert orphans({"s": [{"id": 1}], "videos": [{"id": 999}]}) == {}
    # not vacuous: the same shapes with a real bad reference are still caught
    assert orphans({"users": [{"id": 1}],
                    "comments": [{"id": 1, "user_id": 9}]}) == {"comments.user_id": 1}


@pytest.mark.parametrize("table", ["sound", "sounds", "soundes"])
def test_all_three_of_1168s_table_spellings_resolve(table):
    """The derivation rule is #1168's, imported in spirit rather than invented here."""
    data = {table: [{"id": 1}], "videos": [{"id": 1, "sound_id": 5}]}
    assert orphans(data) == {"videos.sound_id": 1}


def test_a_target_without_explicit_ids_is_not_guessed():
    """Without an `id` column the row numbering is the database's to choose; assuming 1..N
    would invent findings. r164's `users` has no `id` and must not produce one."""
    data = {"users": [{"username": "a"}, {"username": "b"}],
            "videos": [{"id": 1, "user_id": 99}]}
    assert orphans(data) == {}


def test_a_reference_to_a_table_not_in_the_file_is_ignored():
    """A table seeded by SQL elsewhere is not something this file can judge."""
    data = {"videos": [{"id": 1, "tenant_id": "default", "conversation_id": 7}]}
    assert orphans(data) == {}


def test_the_id_column_itself_is_never_treated_as_a_reference():
    """`"id".endswith("_id")` is already False, so the explicit `col == "id"` clause only bites
    for a pathological table NAME: with a table called `s`, the base of `id` is "" and `"" + "s"`
    resolves. That is the shape this asserts -- a first version used a table called `ids`, where
    nothing resolves either way, and the mutation removing the clause stayed green.

    The clause is kept rather than deleted because `_fk_fields` in the same module guards the
    same way (`k != "id" and str(k).endswith("_id")`); matching the neighbour is worth one
    redundant comparison."""
    data = {"s": [{"id": 1}], "videos": [{"id": 999}]}
    assert orphans(data) == {}


def test_string_ids_are_compared_as_given():
    ok = {"users": [{"id": "u1"}], "posts": [{"id": 1, "user_id": "u1"}]}
    bad = {"users": [{"id": "u1"}], "posts": [{"id": 1, "user_id": "u2"}]}
    assert orphans(ok) == {}
    assert orphans(bad) == {"posts.user_id": 1}


@pytest.mark.parametrize("data", [None, [], "", 0, {"t": "not a list"},
                                  {"t": [1, 2, 3]}, {"t": [{"no_id": 1}]}])
def test_it_is_silent_on_anything_unexpected(data):
    assert orphans(data) == {}


def test_it_never_raises():
    class _Bad(dict):
        def items(self):
            raise ValueError("nope")
    assert orphans(_Bad()) == {}


def test_the_return_shape_matches_1168():
    """Same `{"table.column": count}` contract, so a consumer reads both the same way."""
    out = orphans({"users": [{"id": 1}], "c": [{"id": 1, "user_id": 2}]})
    assert isinstance(out, dict)
    for k, v in out.items():
        assert k.count(".") == 1 and isinstance(v, int)


# ------------------------------------------------------- wiring: reported, never blocking

def test_it_is_wired_into_the_deliverability_pass():
    import ast
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import deliverability as dlv
    tree = ast.parse(inspect.getsource(dlv))
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "orphan_fk_rows_in_authored_seed_1203ga" in called


def test_it_does_not_append_a_blocker():
    """#1168's policy, and #566j's reason. If this becomes a gate it must be a ticket."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import deliverability as dlv
    src = inspect.getsource(dlv)
    i = src.index("orphan_fk_rows_in_authored_seed_1203ga(_data)")
    j = src.index("authored_seed_orphan_fk_1203ga", i)
    assert "blockers.append" not in src[i:j], src[i:j]


def test_the_existing_blocker_still_demands_fk_validity():
    """The text this check finally verifies. If it is ever reworded, this ticket's reason for
    existing changes and should be re-read."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import deliverability as dlv
    assert "keep it FK-valid" in inspect.getsource(dlv)


# --------------------------------------------------------------- the corpus cases

@pytest.mark.parametrize("run,expect_col,expect_n", [
    ("netflix-local-r32", "title_genres.title_id", 6),
    ("tiktok-web-r58", "comments.user_id", 30),
])
def test_the_corpus_cases_this_describes(run, expect_col, expect_n):
    f = Path(__file__).resolve().parents[2] / "generated" / run / "app" / "backend" / "seed_data.json"
    if not f.exists():
        pytest.skip("%s artifacts not on disk" % run)
    out = orphans(json.loads(f.read_text(encoding="utf-8")))
    assert out.get(expect_col) == expect_n, out


def test_a_clean_delivered_run_is_not_flagged():
    """Non-vacuity in the other direction: r164 delivered two milestones and is clean."""
    f = (Path(__file__).resolve().parents[2] / "generated" / "tiktok-web-r164"
         / "app" / "backend" / "seed_data.json")
    if not f.exists():
        pytest.skip("r164 artifacts not on disk")
    assert orphans(json.loads(f.read_text(encoding="utf-8"))) == {}
