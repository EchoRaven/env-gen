"""#1158: the per-user SUB-ENTITY ownership path was unreachable.

`_fw_owns` (#566s) resolves a client-supplied owner FK by reading the column's
declared ForeignKey.  `render_models` emits plain ``Column(Integer)`` — netflix
-local-r13's whole models.py declares TWO ForeignKeys — so `foreign_keys` is
empty for ``my_list.profile_id`` and every FK like it, the target stays None,
and the "direct user-owned FK" branch then compares a PROFILE id against the
caller's USER id.

Measured on r13's delivered stack: a freshly registered user created a profile
(id 9, user_id 10, confirmed through the owner-scoped list) and POSTing
``{"profile_id": 9, "title_id": 1}`` to /api/my-list answered
403 "profile_id does not belong to the caller".  Only writes that OMIT the FK
worked — which is why the app itself never hit it: the scaffolded
`addToMyList(title_id)` sends title_id alone.
"""
import ast

import pytest
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import _MAIN_HEADER


def _extract(name: str) -> str:
    """Pull one function's source out of the rendered header (#943: located by the
    def, cut at the next top-level def — never a fixed window)."""
    i = _MAIN_HEADER.index("def %s(" % name)
    j = _MAIN_HEADER.index("\ndef ", i + 1)
    return _MAIN_HEADER[i:j]


@pytest.fixture
def ns():
    Base = declarative_base()

    class User(Base):
        __tablename__ = "users"
        id = Column(Integer, primary_key=True)

    class Profile(Base):
        __tablename__ = "profiles"
        id = Column(Integer, primary_key=True)
        user_id = Column(Integer)          # r13's shape: no ForeignKey
        name = Column(String)

    class MyList(Base):
        __tablename__ = "my_list"
        id = Column(Integer, primary_key=True)
        profile_id = Column(Integer)       # r13's shape: no ForeignKey
        title_id = Column(Integer)

    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    SessionLocal = sessionmaker(bind=eng)
    with SessionLocal() as _s:
        _s.add_all([User(id=10), User(id=11),
                    Profile(id=9, user_id=10, name="mine"),
                    Profile(id=1, user_id=11, name="someone else's")])
        _s.commit()
    g = {"Base": Base, "User": User, "Profile": Profile, "MyList": MyList,
         "SessionLocal": SessionLocal, "_fw_dbg": lambda *a, **k: None}
    exec(compile(ast.parse(_extract("_fw_uid")), "<hdr>", "exec"), g)
    exec(compile(ast.parse(_extract("_fw_owns")), "<hdr>", "exec"), g)
    g["_models"] = (User, Profile, MyList)
    return g


class _U:
    def __init__(self, uid):
        self.id = uid


def test_the_declared_foreignkey_is_not_required(ns):
    """my_list.profile_id has none, and the target must still resolve to profiles."""
    src = _extract("_fw_owns")
    assert "#1158" in src
    assert "_stem + \"s\"" in src


def test_a_user_fk_still_compares_against_the_caller(ns):
    """`user_id` resolves by name to `users`, which stays the uid comparison."""
    assert ns["_fw_owns"](ns["Profile"], "user_id", 10, _U(10)) is True
    assert ns["_fw_owns"](ns["Profile"], "user_id", 11, _U(10)) is False


def test_an_absent_fk_is_left_to_the_auto_fill(ns):
    assert ns["_fw_owns"](ns["MyList"], "profile_id", None, _U(10)) is True
    assert ns["_fw_owns"](ns["MyList"], "profile_id", "", _U(10)) is True


def test_an_unresolvable_stem_keeps_the_conservative_default(ns):
    """#1158 only ADDS resolution; it must never weaken the fallback.

    `title_id` has no `titles` table in this fixture, so the target stays unknown
    and the pre-#1158 rule still applies: an unknown owner target must equal the
    caller's uid. That default is what #566s installed against a cross-user IDOR
    (netflix r127), so widening it here would trade a real defect for a worse one.
    In practice the projected handler only ever passes the OWNER column, so this
    path is about not regressing the guard, not about title_id."""
    assert ns["_fw_owns"](ns["MyList"], "title_id", 999, _U(10)) is False
    assert ns["_fw_owns"](ns["MyList"], "title_id", 10, _U(10)) is True


def test_a_resolvable_sub_entity_is_judged_by_ownership_not_by_uid(ns):
    """The whole point: profile 9 owned by user 10 must be ACCEPTED for user 10,
    which the uid comparison could never do (9 != 10). Needs a session to look the
    row up, so the resolution is asserted at the source level here and end-to-end
    on the delivered stack in the ticket."""
    src = _extract("_fw_owns")
    i = src.index("#1158")
    block = src[i:src.index("_USER_TABLES", i)]
    assert "Base.registry.mappers" in block
    assert "_tgt_col = \"id\"" in block


def test_the_callers_own_sub_entity_is_accepted(ns):
    """profile 9 belongs to user 10. The uid comparison could never allow this (9 != 10)
    and r13's delivered stack answered 403 'profile_id does not belong to the caller'."""
    assert ns["_fw_owns"](ns["MyList"], "profile_id", 9, _U(10)) is True


def test_another_users_sub_entity_is_still_rejected(ns):
    """#1158b. The half fix — resolving the target table but not the target's OWN user
    column — left `_sub_ufk` None and fell through to fail-open, and on the live r13
    stack POSTing another user's profile_id=1 answered 201 where it had answered 403.
    That is the cross-user IDOR #566s exists to stop (netflix r127): a worse defect than
    the one being fixed. This test is the reason the fix is two-level."""
    assert ns["_fw_owns"](ns["MyList"], "profile_id", 1, _U(10)) is False


def test_a_sub_entity_that_does_not_exist_is_rejected(ns):
    assert ns["_fw_owns"](ns["MyList"], "profile_id", 9999, _U(10)) is False
