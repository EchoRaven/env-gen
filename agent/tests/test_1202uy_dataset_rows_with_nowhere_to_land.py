r"""#1202uy: a table registered with only an `id` cannot be seeded, and its dataset rows vanish.

The seeder builds its insert order, class map and PK map from the REGISTERED columns. A table
registered with nothing but `id` contributes no row shape, so it never enters that order and is
never inserted -- and every table whose FK points at it then fails too.

FOUND BY STARTING THE DELIVERED netflix-local-r30 STACK and counting rows:

    titles 0   episodes 0   title_genres 0   my_list 0   ratings 0   continue_watching 0
    seed_dataset.json has titles: 60; the lane's own seed has my_list 22, ratings 14
    registryhub: titles.schema = {"columns": [{"name": "id", "type": "integer", "pk": true}]}
    models.Title exists with its full column list

A Netflix clone with zero titles, released as v1.0.0. The seeder reports success on every
boot: it logs FIX #130's "a seed-provided table is EMPTY -- re-seeding" and then inserts
nothing, because `titles` is not in `_ORDER`.

THE FRAMEWORK SAW ONLY SYMPTOMS. r30's gate logged `business_chain_failing` 68 times and
`validation_ui_evidence_failed` 133 times over 168 snapshots and never once named the cause.

MEASURED over the 136 runs carrying a dataset: 3 hit this. r30 and netflix-resume-validate
lose 60 titles each; tiktok-r81 loses its ENTIRE dataset -- videos 35, sounds 8, comments 295.
Rare and total.

THE RULE IS NARROW ON PURPOSE, after two wider versions over-reported:
  * "no business columns" flagged 203 tables in 49% of runs -- it counts JOIN tables, which
    legitimately carry only foreign keys (r129's `conversation_participants`).
  * "schema is only `id`" flagged 63 tables in 9% -- mostly `users`, `tenants` and
    `oauth_clients`, which the framework bootstraps itself and which work fine that way.
What cannot be anything but broken is a table the DATASET HAS ROWS FOR that the schema cannot
hold.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.scaffolder import (  # noqa: E402
    dataset_rows_with_nowhere_to_land_1202uy,
    record_dataset_rows_with_nowhere_to_land_1202uy,
)

STUB = {"columns": [{"name": "id", "type": "integer", "pk": True}]}
FULL = {"columns": [{"name": "id", "type": "integer"}, {"name": "title", "type": "string"}]}


def _env(tmp_path, dataset):
    be = tmp_path / "app" / "backend"
    be.mkdir(parents=True)
    (be / "seed_dataset.json").write_text(json.dumps(dataset), encoding="utf-8")
    return str(tmp_path)


def test_dataset_content_for_a_stub_table_is_reported(tmp_path):
    """★ r30's exact shape: 60 rows and a schema that cannot hold one."""
    out = dataset_rows_with_nowhere_to_land_1202uy(
        _env(tmp_path, {"titles": [{"id": i} for i in range(60)]}), {"titles": STUB})
    assert len(out) == 1 and out[0].startswith("titles (60 dataset row(s)"), out


def test_it_reads_the_full_registry_record_too(tmp_path):
    """★ The scaffolder passes the whole registry RECORD, not a bare spec. Reading only
    `spec["columns"]` is how a check passes its unit test and sees nothing in production --
    verified against r30's real `registryhub_tables.json` entry, both shapes."""
    record = {"id": "titles", "name": "titles", "status": "implemented",
              "metadata": {}, "schema": STUB}
    out = dataset_rows_with_nowhere_to_land_1202uy(
        _env(tmp_path, {"titles": [{"id": 1}]}), {"titles": record})
    assert len(out) == 1, out


def test_a_table_with_real_columns_is_not_reported(tmp_path):
    """★ The true negative. tiktok-r135 carries a dataset and reports nothing."""
    out = dataset_rows_with_nowhere_to_land_1202uy(
        _env(tmp_path, {"titles": [{"id": 1}]}), {"titles": FULL})
    assert out == [], out


def test_a_stub_table_the_dataset_has_no_rows_for_is_not_reported(tmp_path):
    """★ The narrowing that keeps this honest: `users`, `tenants` and `oauth_clients` are
    registered as stubs in 8 corpus runs and the framework bootstraps them itself."""
    out = dataset_rows_with_nowhere_to_land_1202uy(
        _env(tmp_path, {"titles": [{"id": 1}]}), {"users": STUB, "titles": FULL})
    assert out == [], out


def test_a_join_table_of_foreign_keys_is_not_reported(tmp_path):
    """The other over-report a wider rule produced: a link table has no business columns by
    design."""
    join = {"columns": [{"name": "title_id", "type": "integer"},
                        {"name": "genre_id", "type": "integer"}]}
    out = dataset_rows_with_nowhere_to_land_1202uy(
        _env(tmp_path, {"title_genres": [{"title_id": 1}]}), {"title_genres": join})
    assert out == [], out


def test_an_empty_dataset_table_is_not_reported(tmp_path):
    """An empty list is not content; reporting it would blame the schema for having nothing
    to hold."""
    out = dataset_rows_with_nowhere_to_land_1202uy(
        _env(tmp_path, {"titles": []}), {"titles": STUB})
    assert out == [], out


def test_no_dataset_is_silent(tmp_path):
    (tmp_path / "app" / "backend").mkdir(parents=True)
    assert dataset_rows_with_nowhere_to_land_1202uy(str(tmp_path), {"titles": STUB}) == []


def test_it_never_raises(tmp_path):
    assert dataset_rows_with_nowhere_to_land_1202uy(None, {"t": STUB}) == []
    assert dataset_rows_with_nowhere_to_land_1202uy(str(tmp_path), None) == []
    assert dataset_rows_with_nowhere_to_land_1202uy(
        _env(tmp_path, {"titles": [{"id": 1}]}), {"titles": object()}) == []


def test_the_finding_reaches_an_artifact(tmp_path):
    """#947, with #1202ui's guard against a folder literally named None."""
    assert record_dataset_rows_with_nowhere_to_land_1202uy(str(tmp_path), ["titles (60)"]) is True
    rows = [json.loads(x) for x in
            (tmp_path / "logs" / "dataset_nowhere_to_land_1202uy.jsonl").read_text().splitlines()
            if x.strip()]
    assert rows[0]["count"] == 1 and rows[0]["tables"] == ["titles (60)"]
    assert record_dataset_rows_with_nowhere_to_land_1202uy(None, ["x"]) is False
    assert record_dataset_rows_with_nowhere_to_land_1202uy(str(tmp_path), []) is False
    assert not (Path.cwd() / "None").exists()


def test_it_is_wired():
    """★ A detector nothing calls finds nothing -- and this one is wired where `tables` is
    already in scope, next to the skeleton write that consumes the same dict."""
    src = (LLM_DIR / "multi_agent" / "runtime" / "scaffolder.py").read_text(encoding="utf-8")
    assert "dataset_rows_with_nowhere_to_land_1202uy(out_dir, tables)" in src
    assert "record_dataset_rows_with_nowhere_to_land_1202uy(out_dir, _nl1202uy)" in src
