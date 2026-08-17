r"""#566l (netflix r122 run_validation 20-min hang): `up -d --build` re-ran the app's network package
installs (npm/uv) every validation with no caching, so a flaky-registry window burned the full 1200s
docker-up cap → no successful run → M1 gate wedge. Fixes (all in validation_runner, no Dockerfile edits,
BuildKit stays pinned off):
  (a) build with RETRY (classic layer cache = offline for completed layers),
  (b) FAIL-FAST: dedicated build timeout + short up-only timeout + clear network-hang diagnostic,
  (c) SKIP the rebuild when the app source is unchanged since the last SUCCESSFUL build.
"""
import subprocess
import types

from env_generator.llm_generator.multi_agent.runtime import validation_runner as vr


# ── (c) fingerprint ────────────────────────────────────────────────────────────────────────
def _mk_app(tmp_path):
    root = tmp_path / "app"
    (root / "backend").mkdir(parents=True)
    (root / "frontend" / "src").mkdir(parents=True)
    (root / "backend" / "main.py").write_text("print('x')")
    (root / "frontend" / "src" / "App.jsx").write_text("export default () => null;")
    compose = tmp_path / "docker" / "docker-compose.yml"
    compose.parent.mkdir(parents=True)
    compose.write_text("services: {}\n")
    return compose, root


def test_fingerprint_deterministic_and_changes_on_edit(tmp_path):
    compose, root = _mk_app(tmp_path)
    fp1 = vr._app_source_fingerprint(compose)
    assert fp1 and vr._app_source_fingerprint(compose) == fp1     # deterministic
    (root / "backend" / "main.py").write_text("print('y')")       # edit a source file
    assert vr._app_source_fingerprint(compose) != fp1             # changed


def test_fingerprint_ignores_build_outputs(tmp_path):
    compose, root = _mk_app(tmp_path)
    fp1 = vr._app_source_fingerprint(compose)
    nm = root / "frontend" / "node_modules" / "lib"
    nm.mkdir(parents=True)
    (nm / "index.js").write_text("// dep")
    (root / "frontend" / "dist").mkdir()
    (root / "frontend" / "dist" / "bundle.js").write_text("// built")
    assert vr._app_source_fingerprint(compose) == fp1             # node_modules/dist excluded


def test_fingerprint_none_when_no_app(tmp_path):
    compose = tmp_path / "docker" / "docker-compose.yml"
    compose.parent.mkdir(parents=True)
    compose.write_text("services: {}\n")
    assert vr._app_source_fingerprint(compose) is None            # None → caller rebuilds (fail-safe)


def test_build_fingerprint_roundtrip(tmp_path):
    cwd = tmp_path
    assert vr._read_build_fingerprint(cwd) is None
    vr._write_build_fingerprint(cwd, "abc123")
    assert vr._read_build_fingerprint(cwd) == "abc123"


# ── (b) timeout capture ─────────────────────────────────────────────────────────────────────
def test_compose_capture_converts_timeout_to_failure(tmp_path, monkeypatch):
    def _boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd=["docker", "compose", "build"], timeout=1,
                                        output="partial-out", stderr="partial-err")
    monkeypatch.setattr(vr, "_compose", _boom)
    cp, timed_out = vr._compose_capture(tmp_path / "c.yml", "build", cwd=tmp_path, timeout=1)
    assert timed_out is True and cp.returncode == 124
    assert "partial" in (cp.stdout + cp.stderr)


# ── (a) build with retry ────────────────────────────────────────────────────────────────────
def _fake_cp(rc, out="", err=""):
    return subprocess.CompletedProcess(["docker", "compose", "build"], rc, out, err)


def test_build_retry_success_first_attempt(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(vr, "_compose", lambda *a, **k: (calls.append(1), _fake_cp(0))[1])
    ok, detail = vr._build_with_retry(tmp_path / "c.yml", tmp_path)
    assert ok and detail == "" and len(calls) == 1


def test_build_retry_recovers_on_second_attempt(tmp_path, monkeypatch):
    seq = [_fake_cp(1, err="npm ETIMEDOUT"), _fake_cp(0)]
    monkeypatch.setattr(vr, "_compose", lambda *a, **k: seq.pop(0))
    ok, _ = vr._build_with_retry(tmp_path / "c.yml", tmp_path)
    assert ok and seq == []                                        # used exactly 2 attempts


def test_build_retry_exhausts_and_reports(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(vr, "_compose",
                        lambda *a, **k: (calls.append(1), _fake_cp(1, err="npm ETIMEDOUT"))[1])
    ok, detail = vr._build_with_retry(tmp_path / "c.yml", tmp_path)
    assert not ok
    assert len(calls) == vr._BUILD_RETRIES + 1                     # bounded attempts
    assert "docker build" in detail and "ETIMEDOUT" in detail


def test_build_retry_timeout_diagnostic_mentions_network(tmp_path, monkeypatch):
    def _boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd=["docker", "compose", "build"], timeout=1)
    monkeypatch.setattr(vr, "_compose", _boom)
    ok, detail = vr._build_with_retry(tmp_path / "c.yml", tmp_path)
    assert not ok and "exceeded" in detail and ("npm" in detail or "network" in detail)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
