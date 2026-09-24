"""FIX #113 — staged design assets are re-staged BEFORE every docker image build
(run-29 M4 live, 2026-07-08 12:35).

The visual gate's 12:35 captures showed the SPA fully rendered (JS bundle under
/assets/ loaded fine) while EVERY <img src="/assets/icons/*.svg"> was the
broken-image glyph → that image was BUILT from a tree whose public/assets/ was
momentarily EMPTY. Mechanism: staged assets are tracked files in the codehub repo,
and a lane integration checkout window can drop them from the working tree;
stage_design_assets only re-runs on FRAMEWORK validation ticks, so a lane-triggered
docker build (DockerUpTool --build / DockerBuildTool / verifier run) bakes the
asset-less tree into the image. The judge then scores broken glyphs (dm_inbox 0.00)
— burning the judgment budget on a self-inflicted state. Assets must be staged
BY CONSTRUCTION at every build entry point. ENV-AGNOSTIC + LOCAL-ONLY.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.frontend_scaffold import ensure_assets_staged_for_build  # noqa: E402


def _mk_tree(tmp_path):
    root = tmp_path / "gen"
    (root / "design" / "assets" / "icons").mkdir(parents=True)
    (root / "design" / "assets" / "icons" / "Home_abc123.svg").write_text("<svg/>")
    (root / "app" / "frontend" / "public").mkdir(parents=True)
    (root / "docker").mkdir()
    (root / "docker" / "docker-compose.yml").write_text("services: {}\n")
    return root


def test_helper_resolves_root_from_compose_file_and_stages(tmp_path):
    root = _mk_tree(tmp_path)
    staged = ensure_assets_staged_for_build(root / "docker" / "docker-compose.yml")
    assert staged
    assert (root / "app" / "frontend" / "public" / "assets" / "icons"
            / "Home_abc123.svg").is_file()


def test_helper_accepts_root_or_docker_dir_and_is_graceful(tmp_path):
    root = _mk_tree(tmp_path)
    assert ensure_assets_staged_for_build(root / "docker")
    assert ensure_assets_staged_for_build(root)
    # no design/assets anywhere → no-op, never raises
    assert ensure_assets_staged_for_build(tmp_path / "nowhere") == []


def test_run_compose_build_stages_assets(tmp_path, monkeypatch):
    """the agent tools' single compose choke point re-stages on build/--build."""
    import tools.docker_tools as dt

    root = _mk_tree(tmp_path)
    compose = root / "docker" / "docker-compose.yml"

    class _CP:
        returncode, stdout, stderr = 0, "", ""

    monkeypatch.setattr(dt.subprocess, "run", lambda *a, **k: _CP())
    dt._run_compose(compose, ["up", "-d", "--build"], cwd=compose.parent, timeout=10)
    assert (root / "app" / "frontend" / "public" / "assets" / "icons"
            / "Home_abc123.svg").is_file()


def test_run_compose_nonbuild_does_not_stage(tmp_path, monkeypatch):
    import tools.docker_tools as dt

    root = _mk_tree(tmp_path)
    compose = root / "docker" / "docker-compose.yml"

    class _CP:
        returncode, stdout, stderr = 0, "", ""

    monkeypatch.setattr(dt.subprocess, "run", lambda *a, **k: _CP())
    dt._run_compose(compose, ["ps"], cwd=compose.parent, timeout=10)
    assert not (root / "app" / "frontend" / "public" / "assets").exists()


def test_validation_runner_and_runhub_wired():
    import inspect
    from multi_agent.runtime import validation_runner
    assert "ensure_assets_staged_for_build" in inspect.getsource(validation_runner)
    from multi_agent.runtime.hubs.runhub import service
    assert "ensure_assets_staged_for_build" in inspect.getsource(service)


def test_fix121_build_entry_also_repairs_backend_params(tmp_path, monkeypatch):
    """FIX #121 (run-39 M4 STUCK): heal fixed custom_routes' username annotation on
    disk at 11:55, but the code the validations DEPLOYED still carried `username:
    int` (+ .isdigit() → str probes 422, int probes 500) — a lane integration
    checkout between heal and the build reverted the file (the same build-input
    divergence #113 fixed for assets). The build entry point must apply the
    projection param repair too, so whatever tree the image bakes is correct."""
    import tools.docker_tools as dt

    root = _mk_tree(tmp_path)
    be = root / "app" / "backend"
    be.mkdir(parents=True)
    (be / "main.py").write_text(
        'from fastapi import FastAPI\napp = FastAPI()\n\n'
        '@app.get("/api/users/{username}")\n'
        'def _projected_get_api_users_username_1(username: str):\n'
        '    return {"item": {"username": username}}\n', encoding="utf-8")
    (be / "custom_routes.py").write_text(
        'from fastapi import APIRouter\nrouter = APIRouter()\n\n'
        '@router.get("/api/users/{username}")\n'
        'def get_user_profile(username: int):\n'
        '    return {"user": username}\n', encoding="utf-8")
    compose = root / "docker" / "docker-compose.yml"

    class _CP:
        returncode, stdout, stderr = 0, "", ""

    monkeypatch.setattr(dt.subprocess, "run", lambda *a, **k: _CP())
    dt._run_compose(compose, ["up", "-d", "--build"], cwd=compose.parent, timeout=10)
    src = (be / "custom_routes.py").read_text(encoding="utf-8")
    assert "def get_user_profile(username: str):" in src
