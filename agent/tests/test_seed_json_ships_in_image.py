"""seed_data.json actually ships into the backend image (outlook run-31, 2026-07-02).

The Dockerfile copied only ``*.py`` — the agent-authored seed_data.json NEVER reached the
container, so the loader fell back to the embedded _SEED in EVERY run regardless of what the
lane authored (live: authored demo@example.com JSON on disk; container had no seed_data.json;
DB seeded fallback avachen users → demo login 401 + sparse screens). Composes with #36
(fingerprint reconcile): once the JSON ships, the changed fingerprint triggers the
authoritative re-seed. Dockerfile now copies ``*.py *.json``; because a .json glob with NO
match fails the docker build, the infra writers guarantee seed_data.json ALWAYS exists
(empty {} if not yet authored — falsy → loader fallback; written only-if-absent so authored
content is never clobbered). ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_skeleton import (  # noqa: E402
    _DOCKERFILE, write_backend_build_infra, write_backend_skeleton)


def test_dockerfile_copies_json():
    assert "COPY *.py *.json ./" in _DOCKERFILE


def test_build_infra_creates_empty_seed_json_when_absent(tmp_path):
    write_backend_build_infra(tmp_path)
    p = tmp_path / "app" / "backend" / "seed_data.json"
    assert p.exists() and p.read_text().strip() == "{}"


def test_authored_seed_json_never_clobbered(tmp_path):
    be = tmp_path / "app" / "backend"
    be.mkdir(parents=True)
    authored = '{"users": [{"email": "demo@example.com"}]}'
    (be / "seed_data.json").write_text(authored, encoding="utf-8")
    write_backend_build_infra(tmp_path)
    assert (be / "seed_data.json").read_text() == authored
    # the full skeleton writer may AMPLIFY a thin authored seed to the density floor
    # (FIX #84) — additive only: every authored row survives verbatim, clones are
    # appended, and no tables are invented.
    write_backend_skeleton(tmp_path, endpoints=[], tables={
        "users": {"columns": [{"name": "id", "type": "integer", "primary_key": True},
                              {"name": "email", "type": "text"}]}})
    import json as _json
    on_disk = _json.loads((be / "seed_data.json").read_text(encoding="utf-8"))
    assert set(on_disk) == {"users"}                            # no invented tables
    assert on_disk["users"][0] == {"email": "demo@example.com"}  # authored row intact
    assert all(isinstance(r, dict) and r.get("email") for r in on_disk["users"])


def test_skeleton_writer_also_ensures_seed_json(tmp_path):
    write_backend_skeleton(tmp_path, endpoints=[], tables={
        "users": {"columns": [{"name": "id", "type": "integer", "primary_key": True}]}})
    p = tmp_path / "app" / "backend" / "seed_data.json"
    assert p.exists() and p.read_text().strip() == "{}"
    df = (tmp_path / "app" / "backend" / "Dockerfile").read_text()
    assert "COPY *.py *.json ./" in df


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
