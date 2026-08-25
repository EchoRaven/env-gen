"""#1104: #106 flipped path-param types one way only, so `username: int` shipped.

`repair_custom_routes_param_types` (#106, instagram run-23) exists because a lane
annotating an integer-PK path param as ``str`` made SQLAlchemy compare
``posts.id = '20'::VARCHAR`` → 500 on every by-id read. It rewrites ``str`` → ``int``.

The other direction was never handled. A param annotated ``int`` whose column holds
TEXT rejects every real value with **422 int_parsing** before the handler runs:

    @router.get("/api/users/{username}")
    def get_user_profile(username: int, ...)     # tiktok-r74, r50, and seven more

★ #338's comment already names this exact shape — it was added because #106's own
heuristic ("the segment before the first param names the table, so that param is its
PK") flipped ``username: str`` → ``username: int`` and 422'd every real username, and
r92's repo carries the lane having to undo it. #338 stopped the framework CAUSING it by
deferring wherever main.py projects the route. It did not stop a lane writing it
unprompted, and the corpus still carries 30 such annotations across 9 runs, 3 of them
with a delivered milestone.

Deferring is not enough for the reverse direction, because the lane's handler is the one
that SERVES: where a custom route survives the override filter it registers first and
wins, with the projected ``username: str`` sitting dead behind it. Verified by booting
r74's delivered backend — ``GET /api/users/probe`` answers 422 before the repair and 200
with the right user after it.

So the reverse flip is judged on evidence, never on the parameter's name:
  * the PROJECTED signature where main.py projects the route (#338's own authority), and
  * otherwise the column's own type in the framework-generated models.py.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_scaffold import (  # noqa: E402
    _string_columns_1104, repair_custom_routes_param_types)

_MODELS = '''
from sqlalchemy import Column, Integer, String
from database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True)
    email = Column(String(255))


class Post(Base):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True)
    caption = Column(String(500))
'''

_HEAD = "from fastapi import APIRouter\nrouter = APIRouter()\n\n"


def _backend(tmp_path, custom, main_py=""):
    be = tmp_path / "backend"
    be.mkdir()
    (be / "models.py").write_text(_MODELS)
    (be / "custom_routes.py").write_text(_HEAD + custom)
    (be / "main.py").write_text(main_py)
    return be


def _src(be):
    return (be / "custom_routes.py").read_text()


def test_a_textual_column_makes_int_wrong(tmp_path):
    be = _backend(tmp_path, '@router.get("/api/users/{username}")\n'
                            'def get_user(username: int):\n    return {"item": {}}\n')
    assert repair_custom_routes_param_types(be)["fixed"] == 1
    assert "username: str" in _src(be)


def test_the_projected_signature_decides_when_the_route_is_projected(tmp_path):
    """★ #338 defers here for str→int. For int→str deferring ships the 422, because
    the lane's handler is the one that serves."""
    main_py = ('@app.get("/api/users/{username}")\n'
               'def _projected_get_api_users_username_0(username: str, db=None):\n'
               '    return {"item": {}}\n')
    be = _backend(tmp_path, '@router.get("/api/users/{username}")\n'
                            'def get_user(username: int):\n    return {"item": {}}\n',
                  main_py=main_py)
    assert repair_custom_routes_param_types(be)["fixed"] == 1
    assert "username: str" in _src(be)


def test_an_integer_pk_param_is_left_alone(tmp_path):
    """★ No false positive: `id` on posts IS an integer, and rewriting it would
    reintroduce the 500 that #106 exists to prevent."""
    be = _backend(tmp_path, '@router.get("/api/posts/{id}")\n'
                            'def get_post(id: int):\n    return {"item": {}}\n')
    assert repair_custom_routes_param_types(be)["fixed"] == 0
    assert "id: int" in _src(be)


def test_the_forward_direction_still_works(tmp_path):
    """Non-regression on #106 itself."""
    be = _backend(tmp_path, '@router.get("/api/posts/{id}")\n'
                            'def get_post(id: str):\n    return {"item": {}}\n')
    assert repair_custom_routes_param_types(be)["fixed"] == 1
    assert "id: int" in _src(be)


def test_the_forward_direction_still_defers_to_the_projection(tmp_path):
    """#338 unchanged: where main.py projects the route, str stays str."""
    main_py = ('@app.get("/api/users/{username}")\n'
               'def _projected_get_api_users_username_0(username: str, db=None):\n'
               '    return {"item": {}}\n')
    be = _backend(tmp_path, '@router.get("/api/users/{username}")\n'
                            'def get_user(username: str):\n    return {"item": {}}\n',
                  main_py=main_py)
    assert repair_custom_routes_param_types(be)["fixed"] == 0
    assert "username: str" in _src(be)


def test_the_forward_pass_never_flips_a_natural_key(tmp_path):
    """★ #338's complaint, fixed at its root rather than deferred around.

    The forward rule asks only whether the RESOURCE's PK is an integer — for
    /api/users/{username} it reads `users`, sees users.id is an Integer, and rewrites
    `username: str` to `int`, 422ing every real username. Asking whether the PARAM's
    own column holds text settles it without a projection to defer to.

    It is also what makes the repair converge: without it the two directions
    oscillate, one rewriting to str and the other straight back."""
    be = _backend(tmp_path, '@router.get("/api/users/{username}")\n'
                            'def get_user(username: str):\n    return {"item": {}}\n')
    assert repair_custom_routes_param_types(be)["fixed"] == 0
    assert "username: str" in _src(be)


def test_a_param_that_is_not_a_column_is_untouched(tmp_path):
    """No column, no projection — no evidence, so no rewrite."""
    be = _backend(tmp_path, '@router.get("/api/widgets/{code}")\n'
                            'def get_widget(code: int):\n    return {"item": {}}\n')
    assert repair_custom_routes_param_types(be)["fixed"] == 0
    assert "code: int" in _src(be)


def test_a_multiline_signature_is_rewritten(tmp_path):
    """r74/r61/r75 all wrap the signature — the corpus shape."""
    be = _backend(tmp_path,
                  '@router.get("/api/users/{username}")\n'
                  'def get_user_profile(\n'
                  '    username: int,\n'
                  '    db=None,\n'
                  '):\n    return {"item": {}}\n')
    assert repair_custom_routes_param_types(be)["fixed"] == 1
    assert "username: str" in _src(be)


def test_it_is_idempotent(tmp_path):
    be = _backend(tmp_path, '@router.get("/api/users/{username}")\n'
                            'def get_user(username: int):\n    return {"item": {}}\n')
    repair_custom_routes_param_types(be)
    once = _src(be)
    assert repair_custom_routes_param_types(be)["fixed"] == 0
    assert _src(be) == once


def test_it_never_writes_a_syntax_error(tmp_path):
    import ast
    be = _backend(tmp_path,
                  '@router.get("/api/users/{username}")\n'
                  'def get_user(username: int, q: int = 0):\n    return {"item": {}}\n'
                  '\n@router.post("/api/users/{username}/follow")\n'
                  'def follow(username: int):\n    return {"ok": True}\n')
    repair_custom_routes_param_types(be)
    ast.parse(_src(be))


def test_the_column_reader_sees_only_textual_columns():
    cols = _string_columns_1104(_MODELS)
    assert cols["users"] == {"username", "email"}
    assert "id" not in cols["users"]
    assert cols["posts"] == {"caption"}


def test_a_schema_with_no_integer_pk_is_still_repaired(tmp_path):
    """The old early return bailed on `no integer-PK tables`, which would skip the
    reverse pass entirely for a UUID-keyed schema."""
    be = tmp_path / "backend"
    be.mkdir()
    (be / "models.py").write_text(
        'from sqlalchemy import Column, String\nfrom database import Base\n\n\n'
        'class User(Base):\n    __tablename__ = "users"\n'
        '    id = Column(String(36), primary_key=True)\n'
        '    username = Column(String(64))\n')
    (be / "custom_routes.py").write_text(
        _HEAD + '@router.get("/api/users/{username}")\n'
                'def get_user(username: int):\n    return {"item": {}}\n')
    (be / "main.py").write_text("")
    assert repair_custom_routes_param_types(be)["fixed"] == 1
    assert "username: str" in _src(be)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
