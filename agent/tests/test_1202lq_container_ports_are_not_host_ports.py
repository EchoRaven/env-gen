"""#1202lq — the task-suite executor prefixed bare paths with CONTAINER-internal ports.

    _exec_api_action:      url = f"http://localhost:8000{path}"
    _exec_browser_action:  url = f"http://localhost:3000{url}"

8000 and 3000 are what the backend and frontend listen on INSIDE the compose network. From
the host they are whatever compose published, and that is assigned per run. tiktok-r121:

    docker/docker-compose.yml:  database  ports: - "8000:8000"     <- host :8000 is POSTGRES
                                backend   ports: - "3001:8000"     <- the real API
                                frontend  ports: - "8081:3000"     <- nothing on host :3000

Same confusion as #1202ln, where `run_start`'s default sent the pre-delivery healthcheck to
:8000 and Postgres closed the connection 31 times — seven aborted runs, and one of them
re-opened a delivery gate that had gone completely clear.

The resolver is REUSED, not copied: #665's lesson is that the copy drifts, and #1136 was
that drift (a second hand-rolled container lookup that resolved a stranger's port).
"""
import ast
import inspect

import pytest

from env_generator.llm_generator.tools import run_tools as rt
from env_generator.llm_generator.tools import task_suite_executor as tse


R121 = """\
services:
  database:
    ports:
      - "8000:8000"
  backend:
    ports:
      - "3001:8000"
  frontend:
    ports:
      - "8081:3000"
"""


def _env(tmp_path, text=R121):
    d = tmp_path / "docker"
    d.mkdir(parents=True)
    (d / "docker-compose.yml").write_text(text, encoding="utf-8")
    return tmp_path


class _WS:
    def __init__(self, root):
        self.base_root = str(root)


def _exec(root):
    e = object.__new__(tse.ExecuteTaskSuiteTool)
    e.workspace = _WS(root)
    return e


def test_the_backend_resolves_to_the_published_port_not_the_internal_one(tmp_path):
    assert rt._resolved_base_url_1202ln(
        _env(tmp_path), rt._BACKEND_SERVICES_1202LN) == "http://localhost:3001"


def test_the_frontend_resolves_to_the_published_port_not_3000(tmp_path):
    assert rt._resolved_base_url_1202ln(
        _env(tmp_path), rt._FRONTEND_SERVICES_1202LQ) == "http://localhost:8081"


def test_the_executor_resolves_both_ends(tmp_path):
    e = _exec(_env(tmp_path))
    assert e._app_base_url_1202lq(frontend=False) == "http://localhost:3001"
    assert e._app_base_url_1202lq(frontend=True) == "http://localhost:8081"


def test_neither_end_ever_returns_the_database(tmp_path):
    """★ The r121 failure in one assertion."""
    e = _exec(_env(tmp_path))
    for frontend in (False, True):
        url = e._app_base_url_1202lq(frontend=frontend)
        assert url and ":8000" not in url, (
            "resolved to host :8000, which is this run's DATABASE")


def test_an_unresolvable_root_answers_none(tmp_path):
    assert _exec(tmp_path)._app_base_url_1202lq(frontend=False) is None
    e = object.__new__(tse.ExecuteTaskSuiteTool)
    e.workspace = _WS(None)
    assert e._app_base_url_1202lq(frontend=True) is None


def test_a_bare_path_with_no_resolvable_port_refuses(tmp_path):
    """#207's 'skip honestly' — a probe that answers about another run's service reports
    confidently about the wrong app."""
    e = _exec(tmp_path)                       # no compose file
    res = e._exec_api_action("api_call", {"method": "GET", "path": "/api/feed"})
    assert res["success"] is False
    assert res["error_code"] == "E_API_INVALID_INPUT"
    assert "1202lq" in res["error"] and "database" in res["error"].lower()


def test_neither_call_site_still_hardcodes_a_container_port():
    src = inspect.getsource(tse)
    assert 'http://localhost:8000{' not in src
    assert 'http://localhost:3000{' not in src
    assert 'f"http://localhost:8000' not in src
    assert 'f"http://localhost:3000' not in src


def test_both_call_sites_ask_the_resolver():
    """#934: a guard on one of two producing branches is not a guard."""
    src = inspect.getsource(tse)
    tree = ast.parse(src)
    callers = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for n in ast.walk(fn):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "_app_base_url_1202lq"):
                callers.add(fn.name)
    assert {"_exec_api_action", "_exec_browser_action"} <= callers, callers


def test_the_resolver_is_reused_not_reimplemented():
    src = inspect.getsource(tse.ExecuteTaskSuiteTool._app_base_url_1202lq)
    assert "_resolved_base_url_1202ln" in src
    assert "docker" not in src.replace("docker-compose.yml", ""), (
        "a second hand-rolled compose/container lookup is the #1136 drift")
