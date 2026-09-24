"""#1202gt — the blocker tells the lane to scope a read the materials declare PUBLIC.

The unscoped-owner-read blocker (#919) says, flatly:

    "Scope the read to the caller (#919)"

and appends the alternative — "if this read is genuinely public the projected route follows
the CONTRACT, so `auth_required` is where it is decided" — ONLY when the handler is currently
unauthenticated (`_authed_1202gc`). So the moment the lane follows the first sentence, the
handler gains `Depends(get_current_user)`, and the sentence that could reverse the mistake
stops being printed. The hint is switched off BY the mistake it exists to prevent.

Live, r99 resume 21:11 -> 21:15: `GET /api/videos` and `GET /api/explore` were both flagged;
the lane scoped both to `author_id == caller`; the two findings cleared and the FYP feed now
shows only your own videos, with the logged-out variant impossible. r97 and r98 died on the
same loop. Meanwhile the materials for this very run declare `videos: public` — the framework
holds the fact and never says it on this path (#1202gl put that sentence on the ui_flow
message instead, which is a different blocker the lane was not reading here).

Narrow on purpose (#647): the contract alternative is offered only for a table the MATERIALS
declare public. A genuinely per-user table (`my_list`, the r141 leak shape) must keep the flat
"scope it" instruction, or this becomes a way to talk a lane out of a real leak fix.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_audit import (  # noqa: E402
    _declared_public_materials_1202gt, unscoped_owner_read_findings)

# Shaped from generated/tiktok-web-r99/app/backend/models.py: real ForeignKey declarations
# and a SECOND entity FK, which is what `_is_user_content_relation` actually keys on. A model
# with a bare `Column(Integer)` owner and no second FK never reaches the finding at all.
_MODELS = '''
from sqlalchemy import Column, Integer, Text, ForeignKey
from database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)

class Sound(Base):
    __tablename__ = "sounds"
    id = Column(Integer, primary_key=True)

class Title(Base):
    __tablename__ = "titles"
    id = Column(Integer, primary_key=True)

class Video(Base):
    __tablename__ = "videos"
    id = Column(Integer, primary_key=True)
    author_id = Column(Integer, ForeignKey("users.id"))
    sound_id = Column(Integer, ForeignKey("sounds.id"))
    caption = Column(Text)

class MyList(Base):
    __tablename__ = "my_list"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    title_id = Column(Integer, ForeignKey("titles.id"))
'''

_MAIN_SCOPED_AWAY = '''
from fastapi import FastAPI, Depends
from database import get_db
from models import User, Video, MyList
app = FastAPI()

@app.get("/api/videos")
def _projected_get_api_videos_0(db=Depends(get_db), user=Depends(get_current_user)):
    rows = db.query(Video).limit(100).all()
    return {"items": rows}

@app.get("/api/my-list")
def _projected_get_api_my_list_1(db=Depends(get_db), user=Depends(get_current_user)):
    rows = db.query(MyList).limit(100).all()
    return {"items": rows}
'''


def _project(tmp_path, visibility):
    be = tmp_path / "app" / "backend"
    be.mkdir(parents=True)
    (be / "models.py").write_text(_MODELS, encoding="utf-8")
    (be / "main.py").write_text(_MAIN_SCOPED_AWAY, encoding="utf-8")
    design = tmp_path / "design"
    design.mkdir()
    import json
    (design / "reference_spec.json").write_text(json.dumps(
        {"entities": [{"name": "videos", "fields": [], "visibility": visibility},
                      {"name": "my_list", "fields": [], "visibility": "owner"}]}),
        encoding="utf-8")
    return be


def test_the_materials_half_is_readable_on_its_own(tmp_path):
    be = _project(tmp_path, "public")
    assert _declared_public_materials_1202gt(be, "videos") is True
    assert _declared_public_materials_1202gt(be, "my_list") is False


def test_no_spec_declares_nothing(tmp_path):
    be = tmp_path / "app" / "backend"
    be.mkdir(parents=True)
    assert _declared_public_materials_1202gt(be, "videos") is False


def test_a_public_table_gets_the_contract_route_even_when_the_handler_is_authed(tmp_path):
    """The whole defect: scoping it must not silence the sentence that undoes the scoping."""
    be = _project(tmp_path, "public")
    hits = [h for h in unscoped_owner_read_findings(be) if "`videos`" in h]
    assert hits, "the videos read stopped being flagged at all:\n%s" % (
        unscoped_owner_read_findings(be),)
    h = hits[0]
    assert "auth_required" in h, (
        "an authed handler over a table the materials call PUBLIC is still told only to "
        "scope it — the hint is off exactly when it is needed:\n%s" % h)
    assert "PUBLIC" in h or "public" in h


def test_a_private_table_keeps_the_flat_instruction(tmp_path):
    """#647 — never widen a rule past its evidence. my_list is the r141 leak shape."""
    be = _project(tmp_path, "public")
    hits = [h for h in unscoped_owner_read_findings(be) if "`my_list`" in h]
    assert hits, "my_list stopped being flagged — a real leak blocker was weakened"
    h = hits[0]
    assert "Scope the read to the caller" in h
    assert "auth_required" not in h, (
        "a per-user table is now being offered a way to declare itself public:\n%s" % h)


def test_the_materials_declaring_owner_changes_nothing(tmp_path):
    be = _project(tmp_path, "owner")
    hits = [h for h in unscoped_owner_read_findings(be) if "`videos`" in h]
    assert hits and "auth_required" not in hits[0], (
        "a table the materials call owner-private got the public route:\n%s" % hits[0])


def test_the_materials_fact_reaches_the_unauthenticated_branch_too(tmp_path):
    """r100 resume, live: the lane made the feed public, the blocker fired on an
    UNAUTHENTICATED handler, and the message it got was the generic clause alone —
    "`auth_required` is where it is decided" — with no word that the materials ALREADY
    declare `videos` public or that #1202gd's audit exempts such a read. That is the fact
    that stops the lane scoping it back, and the first cut of #1202gt attached it only to
    the authed branch, which is the one this run was not in.
    """
    be = _project(tmp_path, "public")
    src = (be / "main.py").read_text(encoding="utf-8").replace(
        ", user=Depends(get_current_user)", "")
    (be / "main.py").write_text(src, encoding="utf-8")
    hits = [h for h in unscoped_owner_read_findings(be) if "`videos`" in h]
    assert hits, "the unauthenticated read stopped being flagged"
    h = hits[0]
    assert "UNAUTHENTICATED" in h, "fixture did not reach the unauthenticated branch: %s" % h
    assert "MATERIALS" in h, (
        "the unauthenticated branch still omits the materials declaration:\n%s" % h)
    assert "auth_required" in h


def test_the_private_table_stays_plain_in_the_unauthenticated_branch(tmp_path):
    """#647 — the widening must not reach a table the materials never called public."""
    be = _project(tmp_path, "public")
    src = (be / "main.py").read_text(encoding="utf-8").replace(
        ", user=Depends(get_current_user)", "")
    (be / "main.py").write_text(src, encoding="utf-8")
    hits = [h for h in unscoped_owner_read_findings(be) if "`my_list`" in h]
    assert hits and "MATERIALS" not in hits[0], (
        "a per-user table was told the materials call it public:\n%s" % (hits or "")[:200])
