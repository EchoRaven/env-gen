"""#1202gc -- the unscoped-owner-read blocker must say whether there is a caller at all.

It said "to any authenticated caller" unconditionally, which held while every such read
projected behind Depends(get_current_user). Once #1202ga made the lane's
`auth_required: false` effective, a flagged read can be served with NO auth — and the
message then understates the exposure in the one direction that matters: it reads as
"logged-in users see too much" when the truth is "anyone does".

This changes no verdict. The same reads block; they just describe themselves correctly, and
name the contract as where the reach is decided — the handler is framework-projected, so
the lane cannot add the filter itself.

The heuristic behind the check is deliberately NOT touched here. Measured over the 116
delivered backends on this machine, 267 tables fire it, and every structural discriminator
tried was refuted by the data: a non-key-column threshold exempts `notifications` (4 cols,
genuinely private); a content-payload test keeps `messages`; an explicit-public contract
exemption releases a real `my_list`; and #633 does not separate `my_list` from `videos`
either. Public-vs-private here is semantic, not structural.
"""
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"))

from multi_agent.runtime.backend_audit import unscoped_owner_read_findings  # noqa: E402

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

MAIN_TMPL = '''
from fastapi import FastAPI, Depends
app = FastAPI()

@app.get("/api/videos")
def _projected_get_api_videos_0({args}):
    rows = db.query(Video).limit(100).all()
    return {{"items": rows}}
'''


def _backend(tmp_path, args):
    bd = tmp_path / "app" / "backend"
    bd.mkdir(parents=True)
    (bd / "models.py").write_text(textwrap.dedent(MODELS))
    (bd / "main.py").write_text(MAIN_TMPL.format(args=args))
    return bd


def test_an_unauthenticated_read_says_so(tmp_path):
    """The defect in one line: this used to claim a caller had logged in."""
    found = unscoped_owner_read_findings(_backend(tmp_path, "db=Depends(get_db)"))
    assert found, "the check stopped firing — the verdict must be unchanged"
    msg = found[0]
    assert "UNAUTHENTICATED" in msg, msg
    assert "any authenticated caller" not in msg


def test_an_authenticated_read_keeps_the_old_wording(tmp_path):
    found = unscoped_owner_read_findings(
        _backend(tmp_path, "db=Depends(get_db), user=Depends(get_current_user)"))
    assert found
    assert "any authenticated caller" in found[0]
    assert "UNAUTHENTICATED" not in found[0]


def test_the_unauthenticated_case_names_the_contract(tmp_path):
    """The handler is framework-projected; the lane cannot add the filter, so the message
    has to point at where the decision actually lives."""
    msg = unscoped_owner_read_findings(_backend(tmp_path, "db=Depends(get_db)"))[0]
    # #1202hq dropped `auth_required` from THIS clause on purpose: after #1202hm the login
    # flag no longer decides whether a read is released, and naming it here is what sent
    # r106's lane to flip `owner_scoped_reads` and empty its feed. The property this test
    # exists for is unchanged — the message must point at the contract, not the handler.
    assert "CONTRACT" in msg and "not the handler" in msg


def test_a_scoped_read_still_does_not_fire(tmp_path):
    bd = _backend(tmp_path, "db=Depends(get_db), user=Depends(get_current_user)")
    (bd / "main.py").write_text(
        MAIN_TMPL.format(args="db=Depends(get_db), user=Depends(get_current_user)")
        .replace("db.query(Video).limit(100).all()",
                 "db.query(Video).filter(Video.author_id == user.id).all()"))
    assert unscoped_owner_read_findings(bd) == []
