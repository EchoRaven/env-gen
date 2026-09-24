"""The QA tooling (browser test-user + visual gate) must validate the POPULATED app.

The references depict screens with data; the seed populates the DEMO user (the first seeded
user, password "password"). But the tooling registered a fresh throwaway user — and with
multi-tenant read-scoping a fresh user sees EMPTY lists, so the tooling screenshotted empty
pages and compared them to populated references (a false 'visual mismatch' / empty walk).
_seed_demo_login extracts the demo user's credentials from the generated seed so the tooling
can log in AS the seeded user and validate populated screens. Domain-agnostic.

LOCAL-ONLY (agent/tests/ gitignored).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.visual_fidelity import _seed_demo_login  # noqa: E402


def _write_seed(tmp_path, body):
    be = tmp_path / "app" / "backend"
    be.mkdir(parents=True)
    (be / "seed_data.py").write_text(body, encoding="utf-8")
    return tmp_path


def test_extracts_first_seed_user_email_and_password(tmp_path):
    _write_seed(tmp_path,
                "_ORDER = ['users']\n_CLASS = {'users': 'User'}\n"
                "_SEED = {'users': [{'email': 'ava.chen@contoso.com', 'name': 'Ava Chen', "
                "'password_hash': 'abc', 'tenant_id': 'default'}], 'contacts': []}\n\n\n"
                "def seed_if_empty():\n    pass\n")
    demo = _seed_demo_login(tmp_path)
    assert demo is not None
    assert demo["email"] == "ava.chen@contoso.com"
    assert demo["password"] == "password"   # the framework's fixed seed password
    assert demo["name"] == "Ava Chen"


def test_no_seed_file_returns_none(tmp_path):
    assert _seed_demo_login(tmp_path) is None


def test_seed_without_users_returns_none(tmp_path):
    _write_seed(tmp_path, "_SEED = {'contacts': [{'id': 1}]}\n")
    assert _seed_demo_login(tmp_path) is None


def test_prefers_json_seed_over_py_seed_fallback(tmp_path):
    """The loader inserts seed_data.json into the DB; _seed_demo_login MUST return ITS
    first user, not the embedded _SEED default in seed_data.py. Live 2026-06-30 (outlook):
    json=demo@example.com but _SEED=avachen@example.com → QA registered a fresh empty
    avachen account and browsed as it → EVERY data page false-flagged blank → frontend
    churned on phantom fixes."""
    import json
    be = tmp_path / "app" / "backend"
    be.mkdir(parents=True)
    (be / "seed_data.py").write_text(
        "_SEED = {'users': [{'email': 'avachen@example.com', 'name': 'Ava Chen'}]}\n",
        encoding="utf-8")
    (be / "seed_data.json").write_text(
        json.dumps({"users": [{"email": "demo@example.com", "name": "Demo User"}],
                    "folders": []}), encoding="utf-8")
    demo = _seed_demo_login(tmp_path)
    assert demo is not None
    assert demo["email"] == "demo@example.com"   # JSON wins (the user the DB actually has)
    assert demo["name"] == "Demo User"
    assert demo["password"] == "password"


def test_falls_back_to_py_seed_when_no_json(tmp_path):
    """No JSON → use the embedded _SEED default (preserves prior behavior)."""
    be = tmp_path / "app" / "backend"
    be.mkdir(parents=True)
    (be / "seed_data.py").write_text(
        "_SEED = {'users': [{'email': 'fallback@example.com', 'name': 'FB'}]}\n",
        encoding="utf-8")
    demo = _seed_demo_login(tmp_path)
    assert demo is not None and demo["email"] == "fallback@example.com"


def test_json_without_users_falls_back_to_py(tmp_path):
    """A JSON with no users must not shadow a usable _SEED fallback."""
    import json
    be = tmp_path / "app" / "backend"
    be.mkdir(parents=True)
    (be / "seed_data.json").write_text(json.dumps({"folders": []}), encoding="utf-8")
    (be / "seed_data.py").write_text(
        "_SEED = {'users': [{'email': 'py@example.com', 'name': 'PY'}]}\n", encoding="utf-8")
    demo = _seed_demo_login(tmp_path)
    assert demo is not None and demo["email"] == "py@example.com"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
