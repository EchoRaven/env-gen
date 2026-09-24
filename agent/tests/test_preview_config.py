"""BUG E (2026-06-19): the Env Forge UI showed no preview for a released app.
The framework now writes a deterministic, agent-INVISIBLE preview pointer at
<output_dir>/config.yaml on release (read by app/hub_reader.py:_preview_url).
It is framework metadata — NOT an agent surface — so it is written via a raw
Path.write_text at the integration root, outside every agent worktree.
"""
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.orchestrator import Orchestrator  # noqa: E402


def _orch(tmp_path, ui_port=8080):
    o = Orchestrator.__new__(Orchestrator)  # bypass heavy __init__
    o.output_dir = Path(tmp_path)
    o.context = SimpleNamespace(ui_port=ui_port)
    o._logger = logging.getLogger("test_preview_config")
    return o


def test_writes_preview_pointer_at_output_root(tmp_path):
    _orch(tmp_path)._write_preview_config("1.1.0")
    cfg = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    assert "preview_url: http://localhost:8080/" in cfg
    assert "host_port: 8080" in cfg
    assert "release_tag: 1.1.0" in cfg
    assert "AUTO-GENERATED" in cfg  # marked framework-owned / not agent-editable


def test_no_ui_port_is_a_safe_noop(tmp_path):
    o = _orch(tmp_path, ui_port=None)
    o._write_preview_config("1.0.0")
    assert not (tmp_path / "config.yaml").exists()  # nothing written, no raise


def test_write_failure_never_raises(tmp_path):
    o = _orch(tmp_path)
    o.output_dir = tmp_path / "does" / "not" / "exist"  # parent missing → write errors
    o._write_preview_config("1.0.0")  # must swallow the error (best-effort)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
