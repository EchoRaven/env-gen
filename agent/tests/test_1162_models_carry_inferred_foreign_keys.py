"""#1162: a conventional FK column the contract did not declare is still an FK.

`_fk_target` only sees an EXPLICIT `fk`/`references`, and lanes routinely register
`profile_id` as a bare integer — netflix-local-r13's whole models.py carried TWO
ForeignKeys. Everything that introspects `column.foreign_keys` was blind, which is
one root with three symptoms already patched at the consumers: #1158 (_fw_owns
403'd a caller's OWN sub-entity), #1158b (then fail-opened on another user's), and
#1160 (_fw_owner_val wrote the USER id into a PROFILE column).

Rendering r13's real contract: 2 ForeignKeys -> 12, and the ownership family then
works through its ORIGINAL declared-FK path.
"""
import ast
import json
import re
import types
from pathlib import Path

import pytest
import sqlalchemy.orm as _orm
from sqlalchemy import create_engine

from env_generator.llm_generator.multi_agent.runtime import backend_skeleton as bs
from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import (
    _infer_fk_target_1162 as infer, render_models)

TABLES = {"users", "tenants", "profiles", "titles", "genres", "my_list"}


def test_a_column_naming_a_table_points_at_it():
    assert infer("profile_id", TABLES) == "profiles.id"
    assert infer("title_id", TABLES) == "titles.id"
    assert infer("genre_id", TABLES) == "genres.id"


def test_it_is_not_the_seeding_rule():
    """`_seed_infer_fk` answers "what should the SEED put here" and maps profile_id
    -> users. As an ORM target that is wrong and actively harmful: declaring
    ForeignKey("users.id") sends _fw_owns down its "target is users -> the value
    must equal the caller's uid" branch, i.e. the exact 403 #1158 fixed."""
    assert bs._seed_infer_fk("profile_id", TABLES) == "users"
    assert infer("profile_id", TABLES) == "profiles.id"


def test_an_actor_column_with_no_table_falls_back_to_the_spine():
    assert infer("author_id", TABLES) == "users.id"


def test_a_column_matching_nothing_infers_nothing():
    """Conservative: a wrong FK is worse than none — it would resolve and mislead."""
    assert infer("external_id", TABLES) is None
    assert infer("parent_id", TABLES) is None
    assert infer("name", TABLES) is None


def _contract(run):
    p = (Path(bs.__file__).parents[5] / "generated" / ("netflix-local-%s" % run)
         / "shared" / "hubs" / "registryhub_tables.json")
    if not p.exists():
        pytest.skip("%s artifact not on this box" % run)
    d = json.loads(p.read_text(encoding="utf-8"))
    return {k: v for k, v in d.items()
            if isinstance(v, dict) and not str(k).startswith("_")}


def test_r13s_real_contract_gains_foreign_keys():
    src = render_models(_contract("r13"))
    fks = re.findall(r'(\w+) = Column\([^)]*ForeignKey\("([^"]+)"\)', src)
    assert len(fks) >= 10, len(fks)
    assert ("profile_id", "profiles.id") in fks
    # every inferred target must match the column's own stem
    for col, tgt in fks:
        if col == "tenant_id":
            continue
        assert tgt.split(".")[0].startswith(col[:-3].rstrip("s")[:4]), (col, tgt)


def test_the_rendered_models_still_create_cleanly():
    """create_all really runs at boot (main.py) and it sorts ALL tables, so a cycle
    or an unresolvable target would be a boot failure, not a metadata nit."""
    import sys
    sys.modules.setdefault("database", types.ModuleType("database"))
    sys.modules["database"].Base = _orm.declarative_base()
    g = {}
    exec(compile(render_models(_contract("r13")), "<models>", "exec"), g)
    g["Base"].metadata.create_all(create_engine("sqlite://"))


def test_the_spine_is_excluded_from_inference():
    """users/tenants are absent from 01_init.sql in every measured run (r13 models
    11 / DDL 9), so create_all CREATES them and an FK there becomes a real DDL
    constraint. App tables all exist in the DDL, so their inferred FK stays ORM
    metadata."""
    src = Path(bs.__file__).read_text(encoding="utf-8")
    i = src.index("def emit(table: str, cols:")
    body = src[i:src.index("    header = (", i)]
    assert "emit(\"tenants\"" in body and "infer_fks=True" not in body.split(
        'emit("users"')[0].split('emit("tenants"')[1]
    assert "emit(name, cols, infer_fks=True)" in body
