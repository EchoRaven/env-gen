r"""#1202ie: the psycopg text names ONE of the two types it is about.

A projected create that binds an un-coercible owner value raises deep in psycopg, and the
handler surfaces it verbatim:

    create failed: (psycopg.errors.DatatypeMismatch) column "author_id" is of type integer
    but expression is of type character varying
    [FRAMEWORK-PROJECTED route — the lane cannot edit it, fix the projector/contract]

One type named, the other hidden, and an instruction the lane cannot act on.

tiktok-r107, live: 8 of its 12 failing chains were 500s on projected routes, three of them
this exact insert. The cause is upstream of the handler — `_fw_uid` returns the caller's id
as-is when it will not int(), `_fw_owner_val` does the same when the column type is KNOWN
but the value cannot be coerced, and the rows were created while `users.id` was Text during
the PK oscillation #1202ic documents.

Exercised by EXECUTING the template text, against a real SQLAlchemy model — the helper
ships as a string inside `_MAIN_HEADER`, so a syntax error in it would otherwise surface
only at request time in a generated app, and a hand-rolled stand-in for the model reported
`python_type` where a real column reports `int`.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

SKEL = pathlib.Path(
    "agent/env_generator/llm_generator/multi_agent/runtime/backend_skeleton.py")
PROJ = pathlib.Path(
    "agent/env_generator/llm_generator/multi_agent/runtime/route_projector.py")


def _repo_root() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    for p in here.parents:
        if (p / "agent").is_dir():
            return p
    raise AssertionError("repo root not found")


def _hint():
    """The helper as the generated app gets it: extracted from the template and EXECUTED."""
    src = (_repo_root() / SKEL).read_text()
    i = src.index("def _fw_type_mismatch_hint_1202ie")
    j = src.index("def _fw_owner_val(cls, col, user):", i)
    block = src[i:j]
    ast.parse(block)                      # a syntax error here ships to every app
    ns: dict = {}
    exec(block, ns)
    return ns["_fw_type_mismatch_hint_1202ie"]


@pytest.fixture(scope="module")
def models():
    from sqlalchemy import Column, ForeignKey, Integer
    from sqlalchemy.orm import declarative_base
    Base = declarative_base()

    class User(Base):
        __tablename__ = "users"
        id = Column(Integer, primary_key=True)

    class Video(Base):
        __tablename__ = "videos"
        id = Column(Integer, primary_key=True)
        author_id = Column(Integer, ForeignKey("users.id"))

    return Video


R107 = ('(psycopg.errors.DatatypeMismatch) column "author_id" is of type integer '
        'but expression is of type character varying\nLINE 1: ...es, )')


def test_it_names_both_types_and_the_value(models):
    out = _hint()(models, {"author_id": "48663848-36cc-476e"}, R107)
    assert "integer in the LIVE DATABASE" in out
    assert "int in the model" in out, "a real column reports int, not 'python_type'"
    assert "'48663848-36cc-476e'" in out and "a str" in out


def test_it_says_the_handler_did_not_choose_the_value(models):
    """The note beside it tells the lane to fix the projector; this says why that is not
    where the value came from."""
    out = _hint()(models, {"author_id": "x"}, R107)
    assert "Nothing in this handler chose that value" in out
    assert "re-writing this endpoint cannot help" in out


def test_an_unrelated_exception_is_silent(models):
    assert _hint()(models, {}, ValueError("nope")) == ""


def test_a_mismatch_on_a_column_the_model_lacks_still_reports(models):
    """The DB is the authority on what the row said; an absent attribute must not crash."""
    exc = '(psycopg.errors.DatatypeMismatch) column "ghost" is of type integer but ...'
    out = _hint()(models, {"ghost": "x"}, exc)
    assert "unknown in the model" in out


def test_it_never_raises(models):
    h = _hint()
    for args in ((None, None, None), (models, None, R107), (models, {}, None), ("x", [], 1)):
        assert isinstance(h(*args), str)


def test_the_helper_is_actually_in_the_shipped_template():
    """Reachability: it lives in `_MAIN_HEADER`, not merely in this file's imagination."""
    src = (_repo_root() / SKEL).read_text()
    i = src.index("_MAIN_HEADER")
    assert src.index("def _fw_type_mismatch_hint_1202ie") > i, (
        "the helper must sit inside the emitted header template")


def test_the_create_error_path_calls_it():
    src = (_repo_root() / PROJ).read_text()
    i = src.index("create failed: ")
    # Landmark-anchored (#943): a byte window breaks the moment a comment above it grows,
    # and the ratchet caught this very file doing it.
    # The call sits on the line AFTER the "create failed: " text (the f-string is split),
    # so end at the block's close, not at the first newline — the first draft of this
    # landmark cut the call off and the test went red on a correct implementation.
    seg = src[src.rindex("except Exception as _exc", 0, i):src.index("\n        ]", i)]
    assert "_fw_type_mismatch_hint_1202ie" in seg, "the create path still surfaces the raw dump"


def test_it_only_appends_and_keeps_the_500():
    """It enriches; it must not change the status the gate and the lane both key on."""
    src = (_repo_root() / PROJ).read_text()
    i = src.index("_fw_type_mismatch_hint_1202ie")
    seg = src[src.rindex("raise HTTPException", 0, i):i]
    assert "status_code=500" in seg, "the status must still be 500"
