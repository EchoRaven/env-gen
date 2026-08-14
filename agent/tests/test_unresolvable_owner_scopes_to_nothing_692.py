r"""#692: an unresolvable sub-entity owner made WRITES fail loudly and READS leak silently.

Found by auditing what r146 actually SHIPPED, after the gate went green — the rule #569 left
behind. The delivered `app/backend/main.py` projects every owner-scoped read as

    db.query(MyList).filter(MyList.profile_id == _fw_owner_val(MyList, "profile_id", user))

and `_fw_owner_val` has a fallback path that returns the caller's USER id. Reaching it means the
column's SHAPE said this table is owned through a per-user sub-entity (netflix `profiles`; equally
`characters`, `members`, `sub_accounts`), the caller has no row in it, and #390's auto-create could
not make one — a state #390/#391/#393/#394 all exist because it was observed in real netflix runs
(NotNullViolation on profiles.name, InvalidDatetimeFormat on a timestamp column).

The two call sites then diverge, and only one of them was ever considered:

    WRITE  binds owner = user_id  -> FK violation -> 404. Loud, and the entire subject of those
           four fixes.
    READ   filters owner_col == user_id -> silently returns the rows of the SUB-ENTITY whose id
           happens to equal the caller's user id. Profile ids and user ids are independent
           sequences, so that is generally somebody else's data. No foreign key protects a read;
           nothing fails; the caller is simply served the wrong rows.

route_projector emits that filter at four sites (1038, 1125, 1197, 1244 — parent-scoped, scoped
list, query and single-row reads), so every projected owner-scoped read in every generated app
inherits it.

Frequency is NOT measurable offline: `_fw_dbg` writes to the backend container log under FW_DEBUG,
not to the generation log, and `grep autocreate_sub_entity` over all 253 run logs returns nothing
for that reason. The defect here is the ASYMMETRY rather than a rate — an owner that cannot be
resolved does not mean "fall back to something", it means "this caller owns nothing yet" — so the
fix stands on correctness and the rate is left to a run.

Only the shape-matched-but-unresolved branch changes. A shape that never matched (apps that scope
directly by user_id) and a detection that raised keep the old fallback, because there the user id
is either correct or the best guess available. -1 cannot collide with an autoincrement PK, and it
leaves the WRITE behaviour as it was: an FK violation and a 404, just no longer aimed at a real
row belonging to another user.

These tests EXECUTE the generated helper rather than grepping the template: the function is
extracted from `_MAIN_HEADER` and exec'd against stubs, so what is asserted is the behaviour the
generated app will have.
"""
import ast
import textwrap

import pytest

from env_generator.llm_generator.multi_agent.runtime import backend_skeleton as bs


# --- extract the generated helper and run it ----------------------------------------------------

def _extract(func_name: str) -> str:
    """Pull one function's source out of the generated-main.py template."""
    tree = ast.parse(bs._MAIN_HEADER)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            lines = bs._MAIN_HEADER.splitlines()[node.lineno - 1:node.end_lineno]
            return textwrap.dedent("\n".join(lines))
    raise AssertionError(f"{func_name} is not in the template")


class _Col:
    def __init__(self, name, fks=(), py=int, pk=False, default=None):
        self.name, self.foreign_keys, self.primary_key = name, list(fks), pk
        self.default = self.server_default = default
        self.type = type("T", (), {"python_type": py})()


class _FK:
    def __init__(self, column):
        self.column = column


class _Table:
    def __init__(self, name, columns=()):
        self.name, self.columns = name, list(columns)


def _owner_cls(*, sub_has_user_fk=True):
    """A model whose owner column FKs to `profiles`, which itself FKs to `users`."""
    users_id = _Col("id"); users_id.table = _Table("users")
    prof_user = _Col("user_id", fks=[_FK(users_id)] if sub_has_user_fk else [])
    prof_id = _Col("id")
    prof_tbl = _Table("profiles", [prof_id, prof_user])
    prof_id.table = prof_user.table = prof_tbl

    owner_col = _Col("profile_id", fks=[_FK(prof_id)])

    class _MyList:
        __table__ = _Table("my_list")
    _MyList.profile_id = type("P", (), {
        "property": type("Q", (), {"columns": [owner_col]})(),
        "type": type("T", (), {"python_type": int})(),
    })()
    return _MyList, prof_tbl


class _Sub:
    __table__ = _Table("profiles", [_Col("id", pk=True), _Col("user_id"), _Col("name", py=str)])
    # The helper does `getattr(_Sub, _sub_ufk)` and `order_by(getattr(_Sub, _tgt_col))`.
    # Without these the AttributeError is swallowed by the outer handler and every case
    # silently returns the user id — which is what the first run of this file showed.
    id = "id-col"
    user_id = "user_id-col"

    def __init__(self, **kw):
        self.__dict__.update(kw)
        self.id = kw.get("id")


def _run(*, sub_row, autocreate_ok, cls=None, sub_cls=_Sub):
    """Execute the generated _fw_owner_val against stubs; return what it resolves to."""
    cls_, prof_tbl = _owner_cls() if cls is None else cls
    calls = []

    class _Q:
        def filter(self, *a, **k): return self
        def order_by(self, *a, **k): return self
        def first(self): return sub_row

    class _S:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def query(self, *a, **k): return _Q()
        def add(self, o):
            if not autocreate_ok:
                raise RuntimeError("NotNullViolation: profiles.name")
        def commit(self): pass
        def refresh(self, o): o.id = 4242
        def rollback(self): pass

    class _Mapper:
        local_table = prof_tbl
        class_ = sub_cls

    ns = {
        "_fw_uid": lambda u: u["id"],
        "_fw_dbg": lambda *a, **k: calls.append(a),
        "SessionLocal": _S,
        "Base": type("B", (), {"registry": type("R", (), {"mappers": [_Mapper()]})()}),
    }
    exec(_extract("_fw_owner_val"), ns)
    return ns["_fw_owner_val"](cls_, "profile_id", {"id": 7}), calls


# --- the defect: an unresolvable owner must not become the user id ------------------------------

def test_an_unresolvable_sub_entity_scopes_to_no_rows():
    """The whole point: NOT 7, which is a profile id belonging to somebody else."""
    v, _ = _run(sub_row=None, autocreate_ok=False)
    assert v == -1


def test_it_does_not_return_the_user_id_there():
    v, _ = _run(sub_row=None, autocreate_ok=False)
    assert v != 7


def test_the_unresolved_state_is_logged():
    _, calls = _run(sub_row=None, autocreate_ok=False)
    assert any(c and c[0] == "fw_owner_val.unresolved_sub_entity" for c in calls)


def test_the_log_carries_the_user_id_it_refused_to_use():
    _, calls = _run(sub_row=None, autocreate_ok=False)
    rec = [c for c in calls if c and c[0] == "fw_owner_val.unresolved_sub_entity"][0]
    assert rec[1]["uid"] == 7
    assert rec[1]["col"] == "profile_id"


# --- everything that worked before still works --------------------------------------------------

def test_an_existing_sub_entity_still_resolves_to_it():
    row = type("P", (), {"id": 99})()
    v, _ = _run(sub_row=row, autocreate_ok=True)
    assert v == 99


def test_a_successful_auto_create_still_resolves_to_the_new_row():
    """#390's path is untouched — only the failure after it changes."""
    v, _ = _run(sub_row=None, autocreate_ok=True)
    assert v == 4242


def test_an_app_that_scopes_directly_by_user_id_is_unaffected():
    """No per-user sub-entity in the shape -> the user id is CORRECT and must survive."""
    users_id = _Col("id"); users_id.table = _Table("users")

    class _Direct:
        __table__ = _Table("posts")
    _Direct.profile_id = type("P", (), {
        "property": type("Q", (), {"columns": [_Col("user_id", fks=[_FK(users_id)])]})(),
        "type": type("T", (), {"python_type": int})(),
    })()
    v, _ = _run(sub_row=None, autocreate_ok=False, cls=(_Direct, _Table("users")))
    assert v == 7, "an app scoping straight by user id must keep the user id"


def test_a_detection_that_raises_keeps_the_old_fallback():
    """We cannot know whether the shape matched, so the conservative value stays."""
    class _Broken:
        __table__ = _Table("x")
    _Broken.profile_id = property(lambda self: (_ for _ in ()).throw(RuntimeError("boom")))
    v, _ = _run(sub_row=None, autocreate_ok=False, cls=(_Broken, _Table("users")))
    assert v == 7


# --- the template stays valid --------------------------------------------------------------------

def test_the_generated_module_still_parses():
    ast.parse(bs._MAIN_HEADER)


def test_the_template_is_not_format_interpolated():
    """The patch adds a dict literal; braces would be eaten by .format() or an f-string."""
    import inspect
    src = inspect.getsource(bs)
    assert "_MAIN_HEADER = '''" in src, "a leading f would make {} interpolation"
    i = src.index("_MAIN_HEADER")
    tail = src[src.index("_MAIN_HEADER +", i):] if "_MAIN_HEADER +" in src else ""
    assert ".format(" not in tail.split("\n")[0]


# --- provenance -----------------------------------------------------------------------------------

def _block():
    h = bs._MAIN_HEADER
    i = h.index("#692: WHEN THE SUB-ENTITY CANNOT BE RESOLVED")
    return h[i:h.index("_v = -1", i)]


def test_both_call_sites_are_recorded():
    flat = " ".join(_block().replace("#", " ").split())
    assert "FK violation -> 404. Loud." in flat
    assert "No FK protects a read" in flat


def test_the_projector_reach_is_recorded():
    flat = " ".join(_block().replace("#", " ").split())
    assert "four sites" in flat


def test_the_choice_of_sentinel_is_justified():
    flat = " ".join(_block().replace("#", " ").split())
    assert "cannot collide with an autoincrement PK" in flat


def test_the_untouched_branches_are_named():
    flat = " ".join(_block().replace("#", " ").split())
    assert "a shape that never matched" in flat
    assert "a detection that raised" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
