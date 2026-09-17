"""#1202qg: once the final delivery gate passes, an in-flight background test-user squad is
cancelled (tiktok-r126 M3 spawned 12 agents after v1.2.0 was cut)."""
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace

from env_generator.llm_generator.multi_agent import orchestrator as O


def _orch(task):
    return SimpleNamespace(_tu_squad_task=task, _logger=logging.getLogger("t"))


def test_a_running_squad_is_cancelled():
    async def go():
        t = asyncio.ensure_future(asyncio.sleep(3600))
        o = _orch(t)
        assert O.Orchestrator._cancel_inflight_squad_1202qg(o, "final gate passed") is True
        await asyncio.sleep(0)
        return t.cancelled()
    assert asyncio.run(go()) is True


def test_nothing_to_cancel():
    assert O.Orchestrator._cancel_inflight_squad_1202qg(_orch(None), "x") is False

    async def go():
        t = asyncio.ensure_future(asyncio.sleep(0))
        await t
        return O.Orchestrator._cancel_inflight_squad_1202qg(_orch(t), "x")
    assert asyncio.run(go()) is False


def test_the_final_path_calls_it_when_it_declares_done():
    src = Path(O.__file__).read_text(encoding="utf-8")
    i = src.index('self._enter_project_phase("done", reason="delivery gate passed")')
    assert "self._cancel_inflight_squad_1202qg(" in src[i:src.index("# FINAL-MILESTONE RELEASE.", i)]
