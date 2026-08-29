"""#1149: a heal that declines must say WHY.

Every ``repair_*`` in backend_scaffold already returned ``{"injected": False,
"reason": ...}`` on its no-op paths — and ``repair_backend_auth`` threw the
reason away.  The cost was not cosmetic: in the log, a heal that correctly
no-ops because the scaffold now emits the artifact by construction ("already
present") is INDISTINGUISHABLE from a heal whose detector is broken ("no
FastAPI app").  Three heals (#46/#47/#82) sat silent across the whole corpus
and the only way to tell healthy from dead was to open a delivered run's
``main.py`` by hand.  These tests keep the cause observable.
"""
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime import backend_scaffold as bs


def _mk(tmp_path: Path, body: str) -> Path:
    be = tmp_path / "app" / "backend"
    be.mkdir(parents=True)
    (be / "main.py").write_text(body, encoding="utf-8")
    return be


def test_missing_main_py_names_that_cause(tmp_path):
    be = tmp_path / "app" / "backend"
    be.mkdir(parents=True)
    res = bs.repair_inline_token_auth(be)
    assert not res.get("fixed")
    assert res.get("reason") == "no main.py"


def test_a_backend_without_the_fake_shape_is_not_silently_skipped(tmp_path):
    be = _mk(tmp_path, "from fastapi import FastAPI\napp = FastAPI()\n")
    res = bs.repair_inline_token_auth(be)
    assert not res.get("fixed")
    # healthy no-op, but it must be legible as one
    assert res.get("reason") == "no inline fake-token parse"


def test_already_repaired_is_distinguishable_from_never_applicable(tmp_path):
    be = _mk(tmp_path, 'x = _framework_jwt_sub(tok)\n' + bs._FAKE_PARTS_MARKER + '\n')
    res = bs.repair_inline_token_auth(be)
    assert res.get("reason") == "already repaired", res
    # the two healthy causes must not collapse onto one string
    other = bs.repair_inline_token_auth(
        _mk(tmp_path / "b", "from fastapi import FastAPI\napp = FastAPI()\n"))
    assert other.get("reason") != res.get("reason")


def test_every_decline_branch_of_the_silent_heals_carries_a_reason():
    """The three heals that never fired in 213 logs are the ones whose silence
    we could not read.  Anchor on the def line and stop at the NEXT top-level
    def — never a fixed byte window (#943)."""
    src = Path(bs.__file__).read_text(encoding="utf-8")
    for fn in ("repair_inline_token_auth",
               "repair_auth_enforcement_middleware",
               "repair_integrity_error_handler"):
        i = src.index("def %s(" % fn)
        j = src.index("\ndef ", i + 1)
        body = src[i:j]
        for line in body.splitlines():
            t = line.strip()
            if not t.startswith("return {"):
                continue
            if '"fixed": 0' in t or '"injected": False' in t:
                assert ('"reason"' in t or '"error"' in t or t.endswith("(")
                        or '"reason"' in body[body.index(t):][:300]), \
                    "%s: decline without a cause -> %s" % (fn, t)


def test_the_caller_reports_the_cause_it_was_given():
    """repair_backend_auth must surface the reasons, not swallow them."""
    hp = Path(
        bs.__file__).with_name("heal_pipeline.py").read_text(encoding="utf-8")
    i = hp.index("def repair_backend_auth(")
    j = hp.index("def repair_backend_packaging(", i)
    body = hp[i:j]
    assert "#1149" in body
    assert '_r.get("reason")' in body
    # and it must name the three heals whose silence was unreadable
    for name in ("inline_token_46", "auth_middleware_47", "integrity_map_82"):
        assert name in body, name


def test_no_backend_heal_reports_an_unexplained_no_op(tmp_path):
    """#1149c: r13's first hour logged three heals as "(no cause reported)" 19 times --
    router_prologue, auth_imports_48 and param_types_106. An unexplained no-op is the
    exact ambiguity #1149 exists to remove, so the reporter's own fallback string must
    stop being reachable for these three."""
    be = tmp_path / "app" / "backend"
    be.mkdir(parents=True)
    (be / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n",
                                encoding="utf-8")
    for fn in (bs.repair_custom_routes_router_prologue,
               bs.repair_auth_import_paths,
               bs.repair_custom_routes_param_types):
        res = fn(be)
        assert isinstance(res, dict), fn.__name__
        assert not (res.get("repaired") or res.get("fixed")), fn.__name__
        assert res.get("reason") or res.get("error"), \
            "%s declined without a cause" % fn.__name__


def test_router_prologue_separates_its_two_healthy_causes(tmp_path):
    be = tmp_path / "app" / "backend"
    be.mkdir(parents=True)
    absent = bs.repair_custom_routes_router_prologue(be)
    (be / "custom_routes.py").write_text(
        "from fastapi import APIRouter\nrouter = APIRouter()\n"
        "@router.get('/x')\ndef x(): return {}\n", encoding="utf-8")
    defined = bs.repair_custom_routes_router_prologue(be)
    assert absent.get("reason") == "no custom_routes.py"
    assert defined.get("reason") == "router already defined"
