"""Seed is split into a framework LOADER (seed_data.py) + an agent-owned DATA artifact
(seed_data.json), per the agent-only seed-ownership decision (2026-06-29). The loader must:
prefer seed_data.json when present, fall back to the embedded default (never blank), hash
the demo password for users, and BACKFILL a missing owner FK so owner-scoped reads are
never empty even if the agent's seed omitted it.
"""

import ast
import importlib.util
import json
import sys
import types
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.backend_skeleton import render_seed_data, render_seed_json  # noqa: E402


def _tables():
    col = lambda name, typ, **kw: {"name": name, "type": typ, **kw}
    return {
        "users": {"schema": {"columns": [
            col("id", "serial", primary_key=True), col("email", "text"),
            col("password_hash", "text"), col("avatar_url", "text")]}},
        "folders": {"schema": {"columns": [
            col("id", "serial", primary_key=True), col("user_id", "integer"), col("name", "text")]}},
        "messages": {"schema": {"columns": [
            col("id", "serial", primary_key=True), col("user_id", "integer"),
            col("folder_id", "integer"), col("subject", "text")]}},
    }


def test_rendered_loader_is_valid_python_and_json_is_valid():
    ast.parse(render_seed_data(_tables()))                 # importable module
    data = json.loads(render_seed_json(_tables()))         # valid JSON artifact
    assert data["folders"] and data["messages"]
    # the default JSON already carries owners (deterministic fallback stays consistent)
    assert all("user_id" in r for r in data["folders"])


class _Meta(type):
    def __getattr__(cls, name):          # every column name "exists" on the model class
        return None


class _FakeModel(metaclass=_Meta):
    def __init__(self, **kw):
        self.kw = kw


class _FakeQuery:
    def first(self):
        return None                      # every table starts EMPTY


class _FakeSession:
    def __init__(self, sink):
        self._sink = sink
    def query(self, cls):
        return _FakeQuery()
    def add(self, obj):
        self._sink.append(obj.kw)
    def commit(self):
        pass
    def rollback(self):
        pass
    def close(self):
        pass


def _load_seed_module(tmp_path, json_data):
    (tmp_path / "seed_data.py").write_text(render_seed_data(_tables()), encoding="utf-8")
    if json_data is not None:
        (tmp_path / "seed_data.json").write_text(json.dumps(json_data), encoding="utf-8")
    sink = []
    fake_db = types.ModuleType("database")
    fake_db.SessionLocal = lambda: _FakeSession(sink)
    fake_models = types.ModuleType("models")
    fake_models.__getattr__ = lambda name: _FakeModel        # any class name → fake model
    sys.modules["database"] = fake_db
    sys.modules["models"] = fake_models
    try:
        spec = importlib.util.spec_from_file_location("seed_data_under_test", tmp_path / "seed_data.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.seed_if_empty()
    finally:
        sys.modules.pop("database", None)
        sys.modules.pop("models", None)
    return sink


def test_loader_prefers_the_json_artifact(tmp_path):
    # agent-authored JSON with a DISTINCTIVE subject — proves the loader used the JSON,
    # not the embedded default. user_id omitted on purpose → must be backfilled.
    rows = _load_seed_module(tmp_path, {
        "users": [{"email": "real@x.io", "password": "password"}],
        "folders": [{"name": "Agent Folder"}],
        "messages": [{"subject": "AUTHORED_BY_AGENT"}],
    })
    subjects = [r.get("subject") for r in rows if "subject" in r]
    assert "AUTHORED_BY_AGENT" in subjects                 # JSON won over the embedded default


def test_loader_backfills_missing_owner_and_hashes_password(tmp_path):
    rows = _load_seed_module(tmp_path, {
        "users": [{"email": "real@x.io", "password": "password"}],
        "folders": [{"name": "No Owner Folder"}],          # user_id omitted
        "messages": [{"subject": "x"}],
    })
    folder = next(r for r in rows if r.get("name") == "No Owner Folder")
    assert folder.get("user_id") == 1                      # owner backfilled to a real user id
    user = next(r for r in rows if r.get("email") == "real@x.io")
    assert "password" not in user and user.get("password_hash")  # plaintext hashed, not stored


def test_loader_overrides_placeholder_password_hash(tmp_path):
    # The agent often authors a PLACEHOLDER password_hash ('hashed_password') or a
    # wrong-scheme hash (it can't know the salt/scheme). The loader MUST ignore it and
    # hash the known 'password', else the demo/QA user is UN-LOGINABLE → auth_ok=False →
    # every page blank (outlook run-6 2026-06-30).
    import hashlib
    rows = _load_seed_module(tmp_path, {
        "users": [{"email": "demo@x.io", "password_hash": "hashed_password"}],  # bogus, no plaintext
        "folders": [{"name": "F"}],
        "messages": [{"subject": "x"}],
    })
    user = next(r for r in rows if r.get("email") == "demo@x.io")
    expected = hashlib.sha256(("password" + "app_sandbox_salt_2024").encode("utf-8")).hexdigest()
    assert user.get("password_hash") == expected            # placeholder OVERRIDDEN with hash('password')
    assert user["password_hash"] != "hashed_password"


def test_loader_respects_explicit_plaintext_password(tmp_path):
    # An explicit plaintext password is honored (hashed), overriding any password_hash.
    import hashlib
    rows = _load_seed_module(tmp_path, {
        "users": [{"email": "u@x.io", "password": "custom", "password_hash": "bogus"}],
        "folders": [{"name": "F"}], "messages": [{"subject": "x"}],
    })
    user = next(r for r in rows if r.get("email") == "u@x.io")
    expected = hashlib.sha256(("custom" + "app_sandbox_salt_2024").encode("utf-8")).hexdigest()
    assert user.get("password_hash") == expected
    assert "password" not in user                           # plaintext not stored


def test_loader_invents_no_image_url(tmp_path):
    # #1202qo: a user with NO avatar_url keeps none - no external placeholder is invented
    rows = _load_seed_module(tmp_path, {
        "users": [{"email": "real@x.io", "password": "password"}],
        "folders": [{"name": "F"}],
        "messages": [{"subject": "x"}],
    })
    user = next(r for r in rows if r.get("email") == "real@x.io")
    assert "picsum" not in str(user.get("avatar_url") or ""), user
    assert not user.get("avatar_url"), user


def test_loader_keeps_agent_supplied_image_url(tmp_path):
    rows = _load_seed_module(tmp_path, {
        "users": [{"email": "real@x.io", "password": "password", "avatar_url": "https://cdn/me.png"}],
    })
    user = next(r for r in rows if r.get("email") == "real@x.io")
    assert user.get("avatar_url") == "https://cdn/me.png"   # never overwrites what the agent wrote


def test_loader_falls_back_to_embedded_default_when_no_json(tmp_path):
    rows = _load_seed_module(tmp_path, None)               # no seed_data.json
    assert rows                                            # embedded _SEED still seeds → never blank
    assert any(r.get("user_id") for r in rows if "user_id" in r)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
