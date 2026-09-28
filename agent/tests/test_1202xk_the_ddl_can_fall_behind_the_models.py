"""#1202xk: models.py and the init DDL are built from two independent reads of a mutable hub.

`scaffolder.generate_database` does `schema_hub.list_tables()` -> `synthesize_missing_tables`
-> `write_database_scaffold`. `scaffolder.generate_backend_skeleton` does those same three
steps AGAIN for `render_models`. Two methods, invoked at different times, reading a hub the
lanes keep writing to -- so a table the lane finishes registering between them lands in
models.py and not in the DDL.

What it looks like when it fires, from the delivered googlemaps-r16: the DDL creates
`places`, `routes`, `saved_list_items` and `places_autocomplete` as `("id" SERIAL PRIMARY
KEY)` and nothing else, while models.py maps 13 columns on `places` alone. `create_all` skips
a table that exists, so the stub survives and every read of those columns 500s -- and no gate
says why, which is the whole reason this reports.

MEASURED across the 148 delivered backends carrying both files: 2 are affected --
googlemaps-r16 (6 tables) and tiktok-web-r107 (`videos.metadata`). Neither is recent, newest
2026-09-07. The cause is a live race rather than a fixed bug, so this reports instead of
assuming it cannot recur.

REPORTS, NEVER BLOCKS -- the bargain #1202h and #1202uv strike.
"""
import ast
import json
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.database_scaffold import ddl_behind_models_1202xk  # noqa: E402
from multi_agent.runtime.scaffolder import record_ddl_behind_models_1202xk  # noqa: E402

_SCAFFOLDER = os.path.join(_AGENT, "env_generator", "llm_generator", "multi_agent",
                           "runtime", "scaffolder.py")

_MODELS = '''
from database import Base
from sqlalchemy import Column, Integer, String

class Place(Base):
    __tablename__ = "places"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    lat = Column(String)
'''

_DDL_STUB = 'CREATE TABLE IF NOT EXISTS "places" (\n    "id" SERIAL PRIMARY KEY\n);\n'
_DDL_FULL = ('CREATE TABLE IF NOT EXISTS "places" (\n    "id" SERIAL PRIMARY KEY,\n'
             '    "name" TEXT,\n    "lat" TEXT\n);\n')


def _app(tmp_path, ddl, models=_MODELS):
    (tmp_path / "app" / "backend").mkdir(parents=True)
    (tmp_path / "app" / "database" / "init").mkdir(parents=True)
    (tmp_path / "app" / "backend" / "models.py").write_text(models, encoding="utf-8")
    (tmp_path / "app" / "database" / "init" / "01_init.sql").write_text(ddl, encoding="utf-8")
    return tmp_path


def test_an_id_only_stub_against_a_mapped_table_is_reported(tmp_path):
    """★ googlemaps-r16's shape, in miniature."""
    got = ddl_behind_models_1202xk(_app(tmp_path, _DDL_STUB))
    assert len(got) == 1, got
    assert got[0].startswith("places:") and "lat" in got[0] and "name" in got[0], got


def test_an_agreeing_pair_is_silent(tmp_path):
    assert ddl_behind_models_1202xk(_app(tmp_path, _DDL_FULL)) == []


def test_a_column_added_by_a_later_alter_counts_as_created(tmp_path):
    """A migration is still the DDL creating it; reporting it would be a false positive."""
    ddl = _DDL_STUB + 'ALTER TABLE "places" ADD COLUMN IF NOT EXISTS "name" TEXT;\n' \
                      'ALTER TABLE places ADD COLUMN lat TEXT;\n'
    assert ddl_behind_models_1202xk(_app(tmp_path, ddl)) == []


def test_a_renamed_attribute_is_matched_on_its_DB_NAME(tmp_path):
    """★ #216 maps a `metadata` column as `metadata_ = Column('metadata', ...)`. Reading the
    attribute instead of the first argument would report every such column as missing."""
    models = _MODELS + (
        '\nclass Video(Base):\n'
        '    __tablename__ = "videos"\n'
        '    id = Column(Integer, primary_key=True)\n'
        '    metadata_ = Column("metadata", String)\n')
    ddl = _DDL_FULL + ('CREATE TABLE IF NOT EXISTS "videos" (\n    "id" SERIAL PRIMARY KEY,\n'
                       '    "metadata" TEXT\n);\n')
    assert ddl_behind_models_1202xk(_app(tmp_path, ddl, models)) == []


def test_a_table_the_ddl_never_creates_at_all_is_not_this_check(tmp_path):
    """A wholly absent table is a different failure with a different owner; saying both here
    would bury the one this can attribute."""
    ddl = 'CREATE TABLE IF NOT EXISTS "other" (\n    "id" SERIAL PRIMARY KEY\n);\n'
    assert ddl_behind_models_1202xk(_app(tmp_path, ddl)) == []


def test_missing_files_are_silent(tmp_path):
    assert ddl_behind_models_1202xk(tmp_path) == []
    assert ddl_behind_models_1202xk("/nonexistent/path/xk") == []


def test_the_artifact_is_written_and_appends(tmp_path):
    """★ #947: the log is not kept, and this is exactly the question that cannot be answered
    after the run without an artifact."""
    assert record_ddl_behind_models_1202xk(tmp_path, ["places: lat"]) is True
    assert record_ddl_behind_models_1202xk(tmp_path, ["routes: copyrights"]) is True
    p = tmp_path / "logs" / "ddl_behind_models_1202xk.jsonl"
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(rows) == 2 and rows[0]["count"] == 1 and rows[0]["tables"] == ["places: lat"]


def test_an_empty_finding_writes_nothing(tmp_path):
    assert record_ddl_behind_models_1202xk(tmp_path, []) is False
    assert not (tmp_path / "logs" / "ddl_behind_models_1202xk.jsonl").exists()


def test_the_detector_is_called_where_both_files_first_exist():
    """A detector nothing calls is #1202wm's dead mechanism, and this session has caught the
    call site untested four times."""
    with open(_SCAFFOLDER, encoding="utf-8") as fh:      # #1202eu
        tree = ast.parse(fh.read())
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == "generate_backend_skeleton"), None)
    assert fn is not None, "generate_backend_skeleton is gone"
    # CALLED, not merely mentioned. `in body` passed a mutation that replaced the call with
    # `_ddl1202xk = []` and left the import line -- the sixth time this session that matching
    # a NAME instead of a CALL let a dead call site through.
    called = {getattr(n.func, "id", "") for n in ast.walk(fn) if isinstance(n, ast.Call)}
    assert "ddl_behind_models_1202xk" in called, "the detector is never called"
    assert "record_ddl_behind_models_1202xk" in called, (
        "the finding never reaches an artifact")
    lines = {}
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            lines.setdefault(getattr(n.func, "id", ""), n.lineno)
    assert lines["write_backend_skeleton"] < lines["ddl_behind_models_1202xk"], (
        "the check runs before models.py is written, so it can only ever see a stale file")
