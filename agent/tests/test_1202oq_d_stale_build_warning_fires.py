"""#1202oq-d: the stale-build warning is produced by `maybe_run` itself, not just present in the file.

An audit of this suite mutated `if str(_cur1202lx.get("verdict") or "") == "changed":` to
`if False:` (warning never fires) and to `if True:` (fires every round, i.e. meaningless); 11/11 of
#1202lx's tests and 778 tests across 86 visual/fidelity/capture files stayed green, because the
only test of this branch asserted the sentence's position in the source.
"""
import asyncio
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import multi_agent.runtime.visual_fidelity as vf  # noqa: E402


def _orch(lines):
    def _warn(msg, *a, **k):
        lines.append(msg % a if a else msg)
    _noop = lambda *a, **k: None  # noqa: E731
    logger = types.SimpleNamespace(warning=_warn, info=_noop, error=_noop, debug=_noop)
    workhub = types.SimpleNamespace(create_task=lambda **k: {"id": "t1"})

    class _Bus:
        async def send(self, *a, **k):
            return None
    return types.SimpleNamespace(
        _reference_images=[{"name": "inbox", "route": "/inbox", "auth": True, "path": "x.png"}],
        _compute_app_source_signature=lambda: "sig1",
        output_dir=str(ROOT), llm=None, _logger=logger,
        hubs=types.SimpleNamespace(workhub=workhub), message_bus=_Bus())


def _lines_after_a_round(monkeypatch, currency):
    lines = []
    gate = vf.VisualFidelityGate(_orch(lines))
    gate.reset_for_milestone()

    async def _fake_run(*a, **k):
        return {"passed": False, "capture_transient": False, "summary": "judged",
                "skipped": [], "build_currency_1202lx": currency,
                "screens": [{"name": "inbox", "similarity": 0.4, "route": "/inbox"}]}
    monkeypatch.setattr(vf, "run_visual_fidelity", _fake_run)
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(gate.maybe_run())
    finally:
        loop.close()
    return lines


def test_a_verdict_on_an_older_image_is_announced(monkeypatch):
    lines = _lines_after_a_round(monkeypatch, {"verdict": "changed",
                                               "detail": "app/ changed since the build"})
    assert any("#1202lx VISUAL VERDICT IS ABOUT AN OLDER BUILD" in ln for ln in lines), lines


def test_a_current_image_is_not(monkeypatch):
    lines = _lines_after_a_round(monkeypatch, {"verdict": "current", "detail": "same source"})
    assert not any("#1202lx" in ln for ln in lines), lines
