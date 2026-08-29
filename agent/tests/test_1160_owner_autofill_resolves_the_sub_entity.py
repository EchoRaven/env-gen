"""#1160: the auto-fill wrote the caller's USER id into a PROFILE column.

`_fw_owner_val` resolves the owner value through the column's declared
ForeignKey — the same blindness #1158 fixed on the validation side.
render_models emits plain Column(Integer), so the sub-entity branch never ran
and the function fell back to the user id.

Measured on r13's delivered stack: user id 15 owned profile id 19, and POSTing
{"title_id": 5} with no profile_id stored {"profile_id": 15}. Every my_list /
ratings / continue_watching row pointed at a profile that does not exist, and
per-profile scoping was meaningless — the reads only agreed because they
filtered on the same wrong value. After the fix the same call stores the
caller's real profile (verified live: user 21, profile 27 -> profile_id 27).

#1160c is the second half. A client-supplied FK can arrive as a JSON string,
and binding "27" against an INTEGER pk makes postgres raise
`operator does not exist: integer = character varying`. `_fw_owns` answers a
raised exception with True (fail-open, so a framework bug never blocks a
legitimate write), so the type error did not 500 — it silently ACCEPTED every
id, including another user's. Caught on the live stack before it shipped.
"""
import ast

import pytest
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import _MAIN_HEADER


def _extract(name: str) -> str:
    i = _MAIN_HEADER.index("def %s(" % name)
    return _MAIN_HEADER[i:_MAIN_HEADER.index("\ndef ", i + 1)]


@pytest.fixture
def ns():
    Base = declarative_base()

    class User(Base):
        __tablename__ = "users"
        id = Column(Integer, primary_key=True)

    class Profile(Base):
        __tablename__ = "profiles"
        id = Column(Integer, primary_key=True)
        user_id = Column(Integer)      # r13's shape: no ForeignKey
        name = Column(String)

    class MyList(Base):
        __tablename__ = "my_list"
        id = Column(Integer, primary_key=True)
        profile_id = Column(Integer)   # r13's shape: no ForeignKey
        title_id = Column(Integer)

    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    SessionLocal = sessionmaker(bind=eng)
    with SessionLocal() as s:
        s.add_all([User(id=15), User(id=16),
                   Profile(id=19, user_id=15, name="mine"),
                   Profile(id=1, user_id=16, name="theirs")])
        s.commit()
    g = {"Base": Base, "User": User, "Profile": Profile, "MyList": MyList,
         "SessionLocal": SessionLocal, "_fw_dbg": lambda *a, **k: None}
    for fn in ("_fw_uid", "_fw_owns", "_fw_owner_val"):
        exec(compile(ast.parse(_extract(fn)), "<hdr>", "exec"), g)
    return g


class _U:
    def __init__(self, uid):
        self.id = uid


def test_the_autofill_returns_the_profile_not_the_user_id(ns):
    """r13 stored 15 (the user) where 19 (their profile) belonged."""
    assert ns["_fw_owner_val"](ns["MyList"], "profile_id", _U(15)) == 19


def test_a_direct_user_column_is_unchanged(ns):
    assert ns["_fw_owner_val"](ns["Profile"], "user_id", _U(15)) == 15


def test_a_string_fk_is_coerced_before_the_query(ns):
    """#1160c: binding "19" against an INTEGER pk raised, and the except answered
    True — fail-open accepted every id, another user's included."""
    assert ns["_fw_owns"](ns["MyList"], "profile_id", "19", _U(15)) is True
    assert ns["_fw_owns"](ns["MyList"], "profile_id", "1", _U(15)) is False


def test_a_value_that_cannot_be_the_columns_type_owns_nothing(ns):
    assert ns["_fw_owns"](ns["MyList"], "profile_id", "not-a-number", _U(15)) is False


def test_the_coercion_precedes_the_query_in_source():
    body = _extract("_fw_owns")
    assert "#1160c" in body
    assert body.index("python_type") < body.index("SessionLocal")
