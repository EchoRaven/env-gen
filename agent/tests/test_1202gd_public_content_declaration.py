"""#1202gd — a table's rows are exempt from the unscoped-owner-read blocker only when the
MATERIALS and the CONTRACT both say they are published content.

Measured over the 116 delivered backends on this machine, `_is_user_content_relation` fires
on 267 tables and no structural rule separates public from private: a non-key-column
threshold exempts `notifications` (4 columns, genuinely private); a content-payload test
keeps `messages`, which also carries `text`; #633 does not separate `my_list` from `videos`.
`videos(author_id, ...)` and `saved_items(user_id, ...)` have the same shape. The
distinction is semantic, so the materials have to say it.

Requiring BOTH signals is what makes relaxing this safe: exempting on the contract alone
releases 33 tables in the corpus, one of them a real `my_list` — the r141 leak shape, where
a lane declared a per-user list public by mistake and this audit was the last thing to
notice.
"""
import json
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"))

from multi_agent.runtime.backend_audit import (  # noqa: E402
    _declared_public_1202gd, unscoped_owner_read_findings)

MODELS = '''
from sqlalchemy import Column, Integer, String, ForeignKey
from .database import Base

class Video(Base):
    __tablename__ = "videos"
    id = Column(Integer, primary_key=True)
    author_id = Column(Integer, ForeignKey("users.id"))
    sound_id = Column(Integer, ForeignKey("sounds.id"))
    caption = Column(String)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)

class Sound(Base):
    __tablename__ = "sounds"
    id = Column(Integer, primary_key=True)
'''

MAIN = '''
from fastapi import FastAPI, Depends
app = FastAPI()

@app.get("/api/videos")
def _projected_get_api_videos_0(db=Depends(get_db)):
    rows = db.query(Video).limit(100).all()
    return {"items": rows}
'''


def _run(tmp_path, *, visibility, owner_scoped, table="videos"):
    """#1202hm: the corroborating signal is the TABLE's `owner_scoped_reads`, not any
    endpoint's `auth_required`. The endpoint ledger is still written -- with the read
    AUTHENTICATED -- so every case below also proves the login flag no longer participates."""
    root = tmp_path / "generated" / "env"
    (root / "design").mkdir(parents=True)
    (root / "shared" / "hubs").mkdir(parents=True)
    bd = root / "app" / "backend"
    bd.mkdir(parents=True)
    (bd / "models.py").write_text(textwrap.dedent(MODELS))
    (bd / "main.py").write_text(MAIN)
    ent = {"name": table, "fields": ["id", "author_id"]}
    if visibility is not None:
        ent["visibility"] = visibility
    (root / "design" / "reference_spec.json").write_text(json.dumps({"entities": [ent]}))
    (root / "shared" / "hubs" / "registryhub_endpoints.json").write_text(json.dumps(
        {"GET /api/" + table: {"method": "GET", "path": "/api/" + table,
                               "schema": {"auth_required": True}}}))
    meta = {} if owner_scoped is None else {"owner_scoped_reads": owner_scoped}
    (root / "shared" / "hubs" / "registryhub_tables.json").write_text(json.dumps(
        {table: {"name": table, "metadata": meta,
                 "schema": {"columns": [{"name": "id"}, {"name": "author_id"}]}}}))
    return bd


def test_both_signals_exempt(tmp_path):
    bd = _run(tmp_path, visibility="public", owner_scoped=None)
    assert _declared_public_1202gd(bd, "videos") is True
    assert unscoped_owner_read_findings(bd) == [], "a declared public feed still blocks"


def test_the_contract_alone_does_not_exempt(tmp_path):
    """The r141 shape: a per-user list the materials never called public."""
    bd = _run(tmp_path, visibility=None, owner_scoped=None)
    assert _declared_public_1202gd(bd, "videos") is False
    assert unscoped_owner_read_findings(bd), "released without the materials"


def test_the_contract_wins_over_the_materials(tmp_path):
    """Was `test_the_materials_alone_do_not_exempt`, which corroborated with the LOGIN flag.
    The question is not "must you log in" but "do you see other people's rows", so the
    corroborator is the table's own flag -- and a lane that marks the table owner-scoped
    keeps it scoped whatever the materials say. Measured over the 9 runs whose materials
    carry declarations: 15 of the 29 public declarations sit on a table the contract marks
    owner-scoped, and this refuses every one; the endpoint rule could release them on an
    unrelated sibling's auth_required=False."""
    bd = _run(tmp_path, visibility="public", owner_scoped=True)
    assert _declared_public_1202gd(bd, "videos") is False
    assert unscoped_owner_read_findings(bd)


def test_an_authenticated_read_of_declared_public_rows_is_exempt(tmp_path):
    """r105, live: #1202hh released the owner filter on (materials public AND the table is
    not owner-scoped), so `GET /api/videos` served every row as designed -- while this audit
    demanded `auth_required is False` and called it a leak. The two readers of one fact asked
    different questions, and no lane could clear the blocker without re-breaking the feed."""
    bd = _run(tmp_path, visibility="public", owner_scoped=None)
    assert _declared_public_1202gd(bd, "videos") is True
    assert unscoped_owner_read_findings(bd) == []


def test_an_owner_declaration_never_exempts(tmp_path):
    bd = _run(tmp_path, visibility="owner", owner_scoped=None)
    assert _declared_public_1202gd(bd, "videos") is False
    assert unscoped_owner_read_findings(bd)


def test_absent_declaration_is_the_previous_behaviour(tmp_path):
    """Every reference_spec in the corpus today omits it, so nothing changes for them."""
    bd = _run(tmp_path, visibility=None, owner_scoped=None)
    assert _declared_public_1202gd(bd, "videos") is False
    assert unscoped_owner_read_findings(bd)


def test_a_missing_table_ledger_stays_strict(tmp_path):
    bd = _run(tmp_path, visibility="public", owner_scoped=None)
    (bd.parents[1] / "shared" / "hubs" / "registryhub_tables.json").unlink()
    assert _declared_public_1202gd(bd, "videos") is False


def test_a_missing_spec_is_not_a_fault(tmp_path):
    bd = _run(tmp_path, visibility="public", owner_scoped=None)
    (bd.parents[1] / "design" / "reference_spec.json").unlink()
    assert _declared_public_1202gd(bd, "videos") is False


def test_the_declaration_only_matches_its_own_table(tmp_path):
    bd = _run(tmp_path, visibility="public", owner_scoped=None, table="sounds")
    assert _declared_public_1202gd(bd, "videos") is False


def test_the_schema_the_analyst_is_asked_for_carries_it():
    """A declaration nobody is asked to produce is the batch's most expensive defect class."""
    from multi_agent.runtime.reference_materials import _COMPILE_INSTRUCTIONS as C
    assert '"visibility"' in C, "the compile prompt never asks for it"
    assert "public" in C and "owner" in C
    assert "OMIT" in C, "the prompt must say what to do when the materials do not say"


def test_the_parser_preserves_it():
    from multi_agent.runtime.reference_materials import _parse_spec
    spec = _parse_spec(json.dumps({"entities": [
        {"name": "videos", "fields": ["id"], "visibility": "public"}]}))
    assert spec["entities"][0].get("visibility") == "public"


def test_the_guards_announce_rather_than_swallow():
    """The first draft shipped dead — json/Mapping unimported, every call raised NameError,
    the except swallowed it, and a corpus run reported 'zero behaviour change'."""
    import inspect
    src = inspect.getsource(_declared_public_1202gd)
    assert src.count("warn_once_1201") >= 2, "a fault still reads as 'nothing declared'"
