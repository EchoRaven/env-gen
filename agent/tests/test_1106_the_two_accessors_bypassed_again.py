"""#1106: #1095's fix, completed two functions later.

`_pk_type_of` hand-rolled `table["schema"]["columns"]` and #1095 replaced it with
`_columns_of`, the shape-tolerant accessor that exists because a table record may
arrive FLATTENED. Two functions below it, `_table_has_fk_to` and the `_ufks` count in
`interaction_tables_to_provision` still hand-roll the same access — and additionally
read `c.get("references")` directly, missing the two other FK spellings this file's own
`_fk_target` accepts: an explicit `fk` field, and an inline ``REFERENCES`` in the type.

A miss is not inert. Both callers decide whether an interaction join table ALREADY
EXISTS (#196), so a false "no" provisions a duplicate of a table the contract declared.

★ Neither shape occurs in the corpus: 0 of 865 table records are flattened and 0 of 856
FK columns are inline. This changes nothing that is running today. It is here because
the accessors exist for exactly these shapes and two of their call sites were bypassing
them — the same reason #1095 shipped, two functions away.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_skeleton import (  # noqa: E402
    _fk_target, _table_has_fk_to, interaction_tables_to_provision)


def _nested(*cols):
    return {"schema": {"columns": list(cols)}}


def _flat(*cols):
    return {"columns": list(cols)}


_KEYED = {"name": "user_id", "type": "integer", "references": "users(id)"}
_FKFIELD = {"name": "user_id", "type": "integer", "fk": "users.id"}
_INLINE = {"name": "user_id", "type": "integer REFERENCES users(id)"}


def test_the_shape_that_already_worked_still_does(nested=None):
    assert _table_has_fk_to(_nested(_KEYED), "users") is True


@pytest.mark.parametrize("col,label", [(_FKFIELD, "an explicit fk field"),
                                       (_INLINE, "an inline REFERENCES in the type")])
def test_every_fk_spelling_this_file_accepts(col, label):
    """`_fk_target` takes all three; this call site took one."""
    assert _fk_target(col), f"premise: _fk_target must read {label}"
    assert _table_has_fk_to(_nested(col), "users") is True, label


@pytest.mark.parametrize("col", [_KEYED, _FKFIELD, _INLINE])
def test_a_flattened_record_is_read(col):
    """#1095's own case: columns at the top level, no `schema` wrapper."""
    assert _table_has_fk_to(_flat(col), "users") is True


def test_an_unrelated_fk_is_not_a_match():
    """Non-vacuity: it must still answer False when the FK points elsewhere."""
    assert _table_has_fk_to(_nested({"name": "post_id", "type": "integer",
                                     "references": "posts(id)"}), "users") is False


def test_a_table_with_no_columns_is_not_a_match():
    assert _table_has_fk_to({}, "users") is False
    assert _table_has_fk_to(None, "users") is False


def _follow_eps():
    return [{"method": "POST", "path": "/api/users/{id}/follow"}]


def test_an_existing_self_join_is_not_provisioned_again():
    """★ The consequence: the `_ufks >= 2` guard exists so a self-referential join the
    contract ALREADY declares is left alone. Spelled with `fk`, the old code counted
    zero user FKs and re-provisioned it."""
    tables = {
        "users": _nested({"name": "id", "type": "serial primary key"}),
        "follows": _nested(
            {"name": "id", "type": "serial primary key"},
            {"name": "follower_id", "type": "integer", "fk": "users.id"},
            {"name": "followee_id", "type": "integer", "fk": "users.id"}),
    }
    out = interaction_tables_to_provision(_follow_eps(), tables)
    assert not any(str(t.get("name")) == "follows" for t in out), out


def test_the_same_join_spelled_the_old_way_is_still_left_alone():
    """Non-regression: the spelling that always worked must keep working."""
    tables = {
        "users": _nested({"name": "id", "type": "serial primary key"}),
        "follows": _nested(
            {"name": "id", "type": "serial primary key"},
            {"name": "follower_id", "type": "integer", "references": "users(id)"},
            {"name": "followee_id", "type": "integer", "references": "users(id)"}),
    }
    out = interaction_tables_to_provision(_follow_eps(), tables)
    assert not any(str(t.get("name")) == "follows" for t in out), out


def test_a_missing_join_is_still_provisioned():
    """Non-vacuity for the other direction: with no follows table, one is added."""
    tables = {"users": _nested({"name": "id", "type": "serial primary key"})}
    out = interaction_tables_to_provision(_follow_eps(), tables)
    assert any(str(t.get("name")) == "follows" for t in out), out


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
