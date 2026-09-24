"""#1202he — `scan_dead_files` resolves one side of the import graph and not the other.

`file_set` is built from `str(f.resolve())`, but the candidates come back from
`_normalize_py_import(src, ...)` built on the UNRESOLVED `app_root`. Give the scan a relative
root and every edge misses, so every imported module reads as dead:

    relative root -> 7 findings, six of them real backend modules that main.py imports
                     (oauth_routes, auth_dependency, custom_routes, seed_data, jwt_manager,
                      oauth_store)
    absolute root -> 1 finding

No production caller passes a relative root — r102's live run reports only the one genuine
frontend file, so today's blast radius is ZERO and this is a latent footgun, not an outage.
It is worth closing anyway because of what the failure looks like when it fires: the audit
tells the lane to delete files the app imports at startup.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.coverage_audit import scan_dead_files  # noqa: E402


def _app(tmp_path):
    be = tmp_path / "backend"
    be.mkdir(parents=True)
    (be / "main.py").write_text(
        "from helper import thing\nimport sidecar as _s\nprint(thing, _s)\n", encoding="utf-8")
    (be / "helper.py").write_text("thing = 1\n", encoding="utf-8")
    (be / "sidecar.py").write_text("value = 2\n", encoding="utf-8")
    (be / "orphan.py").write_text("nobody = 3\n", encoding="utf-8")
    return tmp_path


def test_an_absolute_root_sees_the_imports(tmp_path):
    app = _app(tmp_path)
    dead = {d.get("path") for d in scan_dead_files(app.resolve())}
    assert "backend/orphan.py" in dead, dead
    assert "backend/helper.py" not in dead and "backend/sidecar.py" not in dead, dead


def test_a_relative_root_gives_the_same_answer(monkeypatch, tmp_path):
    """The whole defect: the answer must not depend on how the caller spelled the path."""
    app = _app(tmp_path)
    monkeypatch.chdir(tmp_path.parent)
    rel = Path(tmp_path.name)
    dead = {d.get("path") for d in scan_dead_files(rel)}
    assert "backend/helper.py" not in dead, (
        "a relative root broke the import graph, so an imported module reads as dead: %s" % dead)
    assert "backend/sidecar.py" not in dead, dead
    assert "backend/orphan.py" in dead, (
        "the genuinely unreferenced file stopped being reported: %s" % dead)


def test_the_two_spellings_agree(monkeypatch, tmp_path):
    app = _app(tmp_path)
    absolute = {d.get("path") for d in scan_dead_files(app.resolve())}
    monkeypatch.chdir(tmp_path.parent)
    relative = {d.get("path") for d in scan_dead_files(Path(tmp_path.name))}
    assert absolute == relative, (absolute, relative)
