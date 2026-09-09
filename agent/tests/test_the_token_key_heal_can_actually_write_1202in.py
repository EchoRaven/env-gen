r"""#1202in: #317 was refused on every file it ever wanted to fix, and reported success.

`framework_write_1202cw` refuses by default and takes `clobber_ok` — "the ticket that
argued for overwriting lane files at THIS site". `normalize_frontend_token_key` passed
nothing, so the heal has never applied. tiktok-r108: twelve refusals in one second at
09:55:56, every one from that line.

It qualifies for the exception on #1202cw's own terms — the key is not a lane decision
(the framework prompt states it is fixed), r85 and r86 both wedged deliverability_ui_flow
when api.js read one key and the pages wrote another, and the rewrite is surgical
(refresh/user/tenant/csrf spared) and idempotent (a converged file is never touched, which
is why it only fires on a real mismatch).

And the half that hid it: `changed.append` ran unconditionally, so the result reported
files as normalized that were never written — `normalized: [12 files]`, none of them
written.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    normalize_frontend_token_key as normalize,
)
from env_generator.llm_generator.multi_agent.runtime import path_routed_workspace as PW


def _fe(tmp: Path, files: dict) -> Path:
    fe = tmp / "app" / "frontend"
    for rel, body in files.items():
        p = fe / "src" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    return fe


def test_an_alias_is_actually_rewritten_on_disk(tmp_path):
    """The whole point: the heal must reach the file, not just the report."""
    fe = _fe(tmp_path, {"pages/LoginPage.jsx": "localStorage.setItem('tt_token', t);\n"})
    res = normalize(fe)
    assert (fe / "src/pages/LoginPage.jsx").read_text().strip() == \
        "localStorage.setItem('access_token', t);"
    assert res["normalized"] == ["src/pages/LoginPage.jsx"]


def test_a_converged_file_is_left_alone(tmp_path):
    fe = _fe(tmp_path, {"api.js": "localStorage.getItem('access_token');\n"})
    res = normalize(fe)
    assert (fe / "src/api.js").read_text().strip() == "localStorage.getItem('access_token');"
    assert res["normalized"] == []


def test_distinct_keys_are_spared(tmp_path):
    """refresh_token is a DIFFERENT token; tenant/user/csrf are not tokens at all."""
    body = ("localStorage.getItem('refresh_token');"
            "localStorage.getItem('X_TENANT_ID');"
            "localStorage.getItem('user');\n")
    fe = _fe(tmp_path, {"api.js": body})
    normalize(fe)
    assert (fe / "src/api.js").read_text() == body


def test_a_refusal_is_not_reported_as_normalized(tmp_path, monkeypatch):
    """The half that hid the defect for as long as it existed."""
    import env_generator.llm_generator.multi_agent.runtime.frontend_scaffold as FS
    monkeypatch.setattr(FS, "_fw_write_1202cw", lambda *a, **k: False)
    fe = _fe(tmp_path, {"pages/LoginPage.jsx": "localStorage.setItem('tt_token', t);\n"})
    res = normalize(fe)
    assert res["normalized"] == [], "a refused write must not be reported as normalized"
    assert res.get("refused") == ["src/pages/LoginPage.jsx"], "and it must be reported"


def test_the_write_declares_its_ticket():
    """`clobber_ok` empty means refuse — that is the whole defect."""
    src = inspect.getsource(normalize)
    tree = ast.parse(src.lstrip())
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_fw_write_1202cw"]
    assert calls, "the heal no longer writes at all"
    for c in calls:
        kw = {k.arg for k in c.keywords}
        assert "clobber_ok" in kw, "the write is refused by default without it"


def test_the_result_is_used_not_discarded():
    """Appending regardless of the return value is what made the inertness invisible."""
    src = inspect.getsource(normalize)
    tree = ast.parse(src.lstrip())
    ifs = [n for n in ast.walk(tree)
           if isinstance(n, ast.If) and any(
               isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
               and c.func.id == "_fw_write_1202cw" for c in ast.walk(n.test))]
    assert ifs, "the write's return value is still ignored"


def test_the_ticket_names_why_it_may_clobber():
    """#1202cw asks for an argument, not a token."""
    src = inspect.getsource(normalize)
    assert "#317" in src
    for word in ("prompt", "r85", "wedged"):
        assert word in src, f"the declared reason does not mention {word!r}"


def test_the_writer_still_refuses_without_a_ticket():
    """The protection itself must be intact — this fix declares an exception, not a hole."""
    assert "clobber_ok" in inspect.signature(PW.framework_write_1202cw).parameters
    assert inspect.signature(PW.framework_write_1202cw).parameters["clobber_ok"].default == ""
