"""BLOCKER G (2026-06-19): a frontend vite build failed during M2 docker-validation,
but BuildKit (on by default) elided esbuild's file:line code-frame when stdout was a
captured pipe, so every lane saw only `[vite:esbuild] Transform failed with 1 error`
and re-ran the build blindly until the run wedged on docker_up. validation_runner's
_compose must pin the CLASSIC builder (DOCKER_BUILDKIT=0), like every other build path,
so the full error reaches the repair agent.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import validation_runner  # noqa: E402


def test_compose_pins_classic_builder(monkeypatch, tmp_path):
    seen = {}

    def _fake_run(cmd, **kw):
        seen["env"] = kw.get("env")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(validation_runner.subprocess, "run", _fake_run)
    validation_runner._compose(tmp_path / "docker-compose.yml", "up", "-d", "--build",
                               cwd=tmp_path)
    env = seen["env"]
    assert env is not None, "_compose must pass an explicit env (classic builder)"
    assert env.get("DOCKER_BUILDKIT") == "0"
    assert env.get("COMPOSE_DOCKER_CLI_BUILD") == "0"
    # the rest of the environment must be preserved (PATH etc.)
    assert "PATH" in env


def test_docker_up_routes_to_verifier():
    from multi_agent.runtime import remediation_dispatcher as rd
    src = Path(rd.__file__).read_text(encoding="utf-8")
    # docker_up build failures must route to the verifier (it owns docker_build/logs).
    i = src.index('"docker_up": (')
    window = src[i:i + 600]  # entry has an explanatory comment before the owner
    assert '"verifier"' in window


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
