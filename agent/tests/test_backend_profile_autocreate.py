"""#390 + #391: per-user-data writes are scoped to a SUB-ENTITY of the account (netflix
profiles; equally a game's characters, a workspace's members). _fw_owner_val resolves the
owner value to the caller's sub-entity id; when the caller has none it used to fall back to
the USER id → FK violation → 404 "referenced resource not found" → business_chain wedged
INTERMITTENTLY (netflix r14). #390 auto-creates a default sub-entity when none exists.

#391 GENERALIZES the detection from the hardcoded table name "profiles" to the PATTERN
(owner col → a table T that itself FKs to a users/accounts table), so it applies to ANY
account→sub-entity app and stays INERT for apps that scope directly by user_id.

_fw_owner_val is runtime code in the generated backend (the _MAIN_HEADER template). This
test extracts _fw_uid + _fw_owner_val from the rendered main.py and exercises them against
in-memory-sqlite models in three shapes.
"""
import re

from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import render_skeleton_main

_SRC = render_skeleton_main(
    [], {"users": {"columns": [{"name": "id", "type": "integer", "primary_key": True}]}})


def _grab(name):
    m = re.search(r"\ndef " + name + r"\(.*?\n(?=\ndef |\nBase\.metadata)", _SRC, re.S)
    assert m, f"could not extract {name} from generated main.py"
    return m.group(0)


_FW_UID = _grab("_fw_uid")
_FW_OWNER = _grab("_fw_owner_val")


def _resolve(sub_name, owner_col, *, give_sub=False, direct=False):
    """Build a fresh in-memory app of the given shape, then call the GENERATED
    _fw_owner_val(OwnerCls, owner_col, {"id": 1}) and return what it resolved the owner to."""
    Base = declarative_base()
    eng = create_engine("sqlite://")
    SL = sessionmaker(bind=eng)
    classes = {}

    class User(Base):
        __tablename__ = "users"
        id = Column(Integer, primary_key=True)
        email = Column(String)
    classes["users"] = User

    if not direct:
        Sub = type("Sub", (Base,), {
            "__tablename__": sub_name,
            "id": Column(Integer, primary_key=True),
            "user_id": Column(Integer, ForeignKey("users.id")),
            # #393: declare name NULLABLE in the ORM even though a real app's DDL has it
            # NOT NULL — this reproduces the render_models ORM/DDL mismatch that made #390
            # skip `name` and NotNullViolation. #393 must fill it anyway.
            "name": Column(String, nullable=True),
            "is_kids": Column(Boolean, nullable=False, default=False),
            # #394: a non-string column (datetime) with no default must get a TYPE-CORRECT
            # value, not the string "default" (which InvalidDatetimeFormat'd on postgres).
            "created_at": Column(DateTime, nullable=False),
        })
        Owner = type("Owner", (Base,), {
            "__tablename__": "ratings",
            "id": Column(Integer, primary_key=True),
            owner_col: Column(Integer, ForeignKey(sub_name + ".id")),
            "value": Column(Integer),
        })
        classes[sub_name] = Sub
    else:
        Owner = type("Owner", (Base,), {
            "__tablename__": "notes",
            "id": Column(Integer, primary_key=True),
            owner_col: Column(Integer, ForeignKey("users.id")),
            "body": Column(String),
        })

    Base.metadata.create_all(eng)
    s = SL()
    s.add(User(id=1, email="a@b.c"))
    if not direct and give_sub:
        s.add(classes[sub_name](user_id=1, name="Existing", created_at=datetime(2020, 1, 1)))
    s.commit()
    s.close()

    ns = {"json": __import__("json"), "Base": Base, "SessionLocal": SL}
    exec(_FW_UID, ns)
    exec(_FW_OWNER, ns)

    def _count(name):
        d = SL()
        try:
            return d.query(classes[name]).count()
        finally:
            d.close()

    def _first(name):
        d = SL()
        try:
            return d.query(classes[name]).first()
        finally:
            d.close()

    return ns["_fw_owner_val"](Owner, owner_col, {"id": 1}), _count, _first


def test_netflix_profiles_autocreated_when_absent():
    val, count, first = _resolve("profiles", "profile_id")
    assert val == 1                       # resolved to the auto-created profile's id
    assert count("profiles") == 1         # exactly one default profile created


def test_fills_required_column_despite_orm_nullable_true():
    # #393: name is declared nullable=True in the ORM (reproducing the render_models
    # ORM/DDL mismatch) — the auto-create must STILL fill it (the DB has it NOT NULL).
    val, count, first = _resolve("profiles", "profile_id")
    assert count("profiles") == 1
    assert first("profiles").name == "Me"   # filled, NOT left null


def test_fills_datetime_column_with_typed_value_not_default_string():
    # #394: a datetime column must get a real datetime, not the string "default"
    # (which InvalidDatetimeFormat'd on postgres and failed the whole auto-create).
    val, count, first = _resolve("profiles", "profile_id")
    assert count("profiles") == 1
    created = first("profiles").created_at
    assert isinstance(created, datetime), f"created_at got {created!r}, not a datetime"


def test_generalizes_to_any_named_sub_entity():
    # #391: a differently-named sub-entity (characters) is handled by SHAPE — proves the
    # detection is NOT hardcoded to the table name "profiles".
    val, count, _ = _resolve("characters", "character_id")
    assert val == 1
    assert count("characters") == 1


def test_existing_sub_entity_reused_not_duplicated():
    val, count, _ = _resolve("profiles", "profile_id", give_sub=True)
    assert val == 1
    assert count("profiles") == 1         # the existing one, no duplicate created


def test_direct_user_scoping_is_inert():
    # an app that scopes directly by user_id (owner col -> users, which is NOT a sub-entity)
    # must be completely unaffected: returns the user id, creates nothing.
    val, _, _ = _resolve(None, "user_id", direct=True)
    assert val == 1                       # the user id, unchanged


def test_generated_main_imports_sessionlocal():
    """#392: _fw_owner_val uses SessionLocal, but main.py imported only Base/engine/get_db —
    so every call NameError'd → the outer except silently fell back to the user id →
    #379 resolution + #390 auto-create NEVER ran → per-profile writes FK-404'd. Assert the
    generated main.py imports every `database` name its _fw_owner_val body uses."""
    import ast
    src = render_skeleton_main([], {
        "users": {"columns": [{"name": "id", "type": "integer", "primary_key": True}]},
        "profiles": {"columns": [
            {"name": "id", "type": "integer", "primary_key": True},
            {"name": "user_id", "type": "integer", "fk": "users.id"},
            {"name": "name", "type": "text not null"}]},
    })
    imported = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ImportFrom) and node.module == "database":
            imported |= {a.name for a in node.names}
    # _fw_owner_val references SessionLocal + Base — both must be imported or it NameErrors
    assert "SessionLocal" in imported, "main.py uses SessionLocal but does not import it"
    assert "Base" in imported


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
