"""#1100: `stub_handler_blockers` looks at GET only, so a do-nothing POST ships.

The gate's subject is a page that renders no real data, so it filters its scan to
``r[0] == "GET"``. A handler whose entire body is ``pass`` fails differently and on
any verb: FastAPI serializes the implicit ``None``, the route answers ``null``, and
a caller that reads a field off the reply throws.

tiktok-r50 shipped exactly that. ``custom_routes.py`` carried three of them —

    @router.post("/auth/signup")
    def auth_signup_stub():
        pass

— and that run's own ``services/api.js`` does
``const data = await fetchApi('/auth/signup', …); return data.item``. A delivered
app in which no account can be created, and the gate said nothing.

★ Two things nearly made this check wrong, and both are asserted below.

**204.** Four of the seven empty-bodied handlers in the corpus (r78/r82/r91) declare
``status_code=204`` and ``return None`` — the CORRECT way to write a no-content
endpoint, not a stub. A check that reads only the body flags all four.

**Shadowing.** r50's third stub is on ``POST /auth/login``, which the AS template
really implements and which ``main.py`` includes FIRST — so the AS serves that route
and the stub is dead. The finding is the two paths the AS does NOT own. Grouping over
every handler on a route (not only the empty ones) is what tells them apart, and it
is why this reuses the existing "the served handler wins" shape rather than scanning
handlers in isolation.

Why the gate never looked: all three stubs sit under ``/auth/``, which
``lifecycle.is_business`` removes from every check on the grounds that the framework
owns that prefix. It owns exactly the six paths ``oauth_routes.py.tmpl`` serves;
signup is not among them. One exclusion assumed the other covered it.

Measured: 65 backends, 2873 route handlers, 7 empty bodies — 4 are correct 204s, 1 is
shadowed, 2 are real. This flags the 2.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_audit import stub_handler_blockers  # noqa: E402

_HEAD = "from fastapi import APIRouter\nrouter = APIRouter()\n\n"


def _backend(tmp_path, body: str) -> Path:
    be = tmp_path / "app" / "backend"
    be.mkdir(parents=True)
    (be / "custom_routes.py").write_text(_HEAD + body)
    return be


def _empty(blockers):
    return [b for b in blockers if "EMPTY BODY" in b]


@pytest.mark.parametrize("stmt", ["pass", "...", "return", "return None",
                                  "raise NotImplementedError"])
def test_a_do_nothing_handler_is_flagged_on_a_post(tmp_path, stmt):
    be = _backend(tmp_path, f'@router.post("/api/things")\ndef make_thing():\n    {stmt}\n')
    out = _empty(stub_handler_blockers(be))
    assert len(out) == 1, out
    assert "make_thing" in out[0] and "POST /api/things" in out[0]


def test_a_docstring_does_not_count_as_work(tmp_path):
    be = _backend(tmp_path,
                  '@router.post("/api/things")\ndef make_thing():\n'
                  '    """Create a thing."""\n    pass\n')
    assert len(_empty(stub_handler_blockers(be))) == 1


@pytest.mark.parametrize("verb", ["post", "put", "patch", "delete"])
def test_every_verb_the_old_scan_skipped(tmp_path, verb):
    """The GET filter is why these shipped; each must now be seen."""
    be = _backend(tmp_path, f'@router.{verb}("/api/things")\ndef touch_thing():\n    pass\n')
    assert len(_empty(stub_handler_blockers(be))) == 1


def test_a_204_handler_returning_none_is_correct_not_a_stub(tmp_path):
    """★ r78/r82/r91 — four handlers that a body-only check would have condemned."""
    be = _backend(tmp_path,
                  '@router.post("/auth/logout", status_code=204)\n'
                  'def auth_logout():\n    return None\n')
    assert _empty(stub_handler_blockers(be)) == []


@pytest.mark.parametrize("code", [204, 205, 304])
def test_every_no_content_status_is_honoured(tmp_path, code):
    be = _backend(tmp_path,
                  f'@router.post("/api/things", status_code={code})\n'
                  'def touch():\n    pass\n')
    assert _empty(stub_handler_blockers(be)) == []


def test_a_real_handler_on_the_route_shadows_the_stub(tmp_path):
    """★ r50's /auth/login: the AS template serves it, so the stub is dead code.

    main.py includes the AS router BEFORE custom_routes, so the real implementation
    wins the route. Flagging the shadowed stub would send the lane to fix a handler
    that never runs."""
    be = tmp_path / "app" / "backend"
    be.mkdir(parents=True)
    (be / "custom_routes.py").write_text(
        _HEAD + '@router.post("/auth/login")\ndef auth_login_stub():\n    pass\n')
    (be / "oauth_routes.py").write_text(
        _HEAD + '@router.post("/auth/login")\ndef login(db=None):\n'
        '    row = db.query("users").first()\n    return {"item": row}\n')
    assert _empty(stub_handler_blockers(be)) == []


def test_the_unshadowed_siblings_are_still_reported(tmp_path):
    """The same file's other two stubs have no AS implementation behind them."""
    be = tmp_path / "app" / "backend"
    be.mkdir(parents=True)
    (be / "custom_routes.py").write_text(
        _HEAD
        + '@router.post("/auth/login")\ndef auth_login_stub():\n    pass\n\n'
        + '@router.post("/auth/signup")\ndef auth_signup_stub():\n    pass\n\n'
        + '@router.post("/auth/logout")\ndef auth_logout_stub():\n    pass\n')
    (be / "oauth_routes.py").write_text(
        _HEAD + '@router.post("/auth/login")\ndef login(db=None):\n'
        '    return {"item": db.query("users").first()}\n')
    out = _empty(stub_handler_blockers(be))
    assert len(out) == 2, out
    assert any("auth_signup_stub" in b for b in out)
    assert any("auth_logout_stub" in b for b in out)
    assert not any("auth_login_stub" in b for b in out)


def test_a_handler_that_does_work_is_never_flagged(tmp_path):
    """Non-vacuity: the check must not fire on ordinary code."""
    be = _backend(tmp_path,
                  '@router.post("/api/things")\ndef make_thing(db=None):\n'
                  '    row = Thing(name="x")\n    db.add(row)\n    db.commit()\n'
                  '    return {"item": row}\n')
    assert _empty(stub_handler_blockers(be)) == []


def test_the_message_names_the_204_way_out(tmp_path):
    """A blocker that only says 'wrong' costs a cycle — #798's rule."""
    be = _backend(tmp_path, '@router.post("/api/things")\ndef make_thing():\n    pass\n')
    assert "status_code=204" in _empty(stub_handler_blockers(be))[0]


def test_the_get_scan_is_unchanged(tmp_path):
    """#173's own subject must still be reported, by its own message."""
    be = _backend(tmp_path,
                  '@router.get("/api/things")\ndef list_things():\n    return {"items": []}\n')
    out = stub_handler_blockers(be)
    assert any("PLACEHOLDER STUB" in b for b in out), out


def test_the_gate_switch_still_disables_everything(tmp_path, monkeypatch):
    be = _backend(tmp_path, '@router.post("/api/things")\ndef make_thing():\n    pass\n')
    monkeypatch.setenv("ENVGEN_STUB_HANDLER_GATE", "0")
    assert stub_handler_blockers(be) == []


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
