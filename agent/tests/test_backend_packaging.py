"""Backend packaging build-safety repair.

The lane writes a hatchling pyproject with a FLAT layout (main.py at the root, no
src/<pkg>); the Dockerfile's `uv pip install .` then can't build a wheel and the
docker build dies (instagram MM, 2026-06-08: M5 blocked on docker_up timeout).
The repair adds `[tool.hatch.build.targets.wheel] bypass-selection = true` so the
deps install and the build succeeds.
"""

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.backend_scaffold import repair_backend_packaging  # noqa: E402

_HATCHLING_FLAT = """\
[project]
name = "instagram-backend"
version = "0.1.0"
dependencies = ["fastapi", "uvicorn"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
"""


def _backend(tmp_path, pyproject=_HATCHLING_FLAT, with_pkg=False, with_src=False):
    (tmp_path / "main.py").write_text("app = 1\n", encoding="utf-8")
    if pyproject is not None:
        (tmp_path / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    if with_pkg:
        (tmp_path / "instagram_backend").mkdir()
        (tmp_path / "instagram_backend" / "__init__.py").write_text("", encoding="utf-8")
    if with_src:
        (tmp_path / "src").mkdir()
        # a non-package src/ (subdirs but NO __init__.py) — run #14's shape
        (tmp_path / "src" / "routes").mkdir()
    return tmp_path


def test_adds_bypass_selection_for_hatchling_flat_layout(tmp_path):
    be = _backend(tmp_path)
    res = repair_backend_packaging(be)
    assert res["repaired"] is True
    text = (be / "pyproject.toml").read_text(encoding="utf-8")
    assert "[tool.hatch.build.targets.wheel]" in text
    assert "bypass-selection = true" in text


def test_idempotent(tmp_path):
    be = _backend(tmp_path)
    assert repair_backend_packaging(be)["repaired"] is True
    assert repair_backend_packaging(be)["repaired"] is False  # 2nd run: already configured


def test_noop_when_not_hatchling(tmp_path):
    pp = '[project]\nname = "x"\n[build-system]\nrequires = ["setuptools"]\nbuild-backend = "setuptools.build_meta"\n'
    be = _backend(tmp_path, pyproject=pp)
    res = repair_backend_packaging(be)
    assert res["repaired"] is False
    assert "bypass-selection" not in (be / "pyproject.toml").read_text(encoding="utf-8")


def test_noop_when_real_package_resolvable(tmp_path):
    # a REAL importable package (<pkg>/__init__.py) means hatchling can build — leave it
    be = _backend(tmp_path, with_pkg=True)
    assert repair_backend_packaging(be)["repaired"] is False


def test_repairs_bare_src_without_init(tmp_path):
    """run #14: src/{routes,…} with NO __init__.py is NOT a buildable package — hatchling
    fails, so the repair must still add bypass-selection (the old dir-only check skipped
    it → docker_up stalled the milestone)."""
    be = _backend(tmp_path, with_src=True)
    res = repair_backend_packaging(be)
    assert res["repaired"] is True
    assert "bypass-selection = true" in (be / "pyproject.toml").read_text(encoding="utf-8")


def test_noop_when_dir_matches_project_name(tmp_path):
    be = _backend(tmp_path, with_pkg=True)  # instagram_backend/ dir present
    assert repair_backend_packaging(be)["repaired"] is False


def test_noop_when_no_pyproject(tmp_path):
    (tmp_path / "main.py").write_text("app = 1\n", encoding="utf-8")
    assert repair_backend_packaging(tmp_path)["repaired"] is False
