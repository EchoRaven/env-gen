"""#990: the blocking compose helper must not run on the event loop.

#980 swept for `subprocess.run` sitting DIRECTLY inside `async def` and offloaded the four
worst (two npm installs at 300s, two pip at 120s). It missed every call that reaches
subprocess through a HELPER — and `_run_compose` is exactly that shape. r161 paid the bill:

    08:47:18 [W] verifier ❌ docker_up FAILED (300696ms): Start timed out

300.7 seconds of frozen loop. The LLM heartbeat (60s), the coordination tick (60s) and every
other lane stopped dead — #963's failure mode at the magnitude that cost r155 a healthy run,
which I misread as a hang and killed.

#980's own note deferred these sites because "nothing measured says the short ones hurt."
Something does now, so the deferral is spent.
"""

import ast
import asyncio
import inspect
import pathlib

import pytest

from env_generator.llm_generator.tools import docker_tools

SRC = pathlib.Path(inspect.getfile(docker_tools)).read_text(encoding="utf-8")
TREE = ast.parse(SRC)
BLOCKING = {"_run_compose", "_docker_daemon_reachable"}


def test_no_async_path_calls_the_helper_directly():
    offenders = []
    for fn in ast.walk(TREE):
        if not isinstance(fn, ast.AsyncFunctionDef):
            continue
        for call in ast.walk(fn):
            if not isinstance(call, ast.Call):
                continue
            if ast.unparse(call.func).split(".")[-1] not in BLOCKING:
                continue
            # acceptable only as the FIRST ARGUMENT of the offload helper
            src_line = SRC.split("\n")[call.lineno - 1]
            if "_await_blocking_990(" not in src_line:
                offenders.append((fn.name, call.lineno))
    assert offenders == [], f"a 300s compose call on the event loop: {offenders}"


def test_no_await_leaked_into_a_sync_function():
    """The bulk-rewrite hazard: `await` in a plain def returns a coroutine nobody awaits and
    the work silently never happens."""
    leaked = [
        (fn.name, n.lineno)
        for fn in ast.walk(TREE) if isinstance(fn, ast.FunctionDef)
        for n in ast.walk(fn) if isinstance(n, ast.Await)
    ]
    assert leaked == [], f"await inside a def: {leaked}"


def test_a_sync_caller_may_still_call_it_directly():
    """Sync-to-sync is fine and must not be rewritten — only the coroutine paths matter."""
    sync_calls = [
        call.lineno
        for fn in ast.walk(TREE) if isinstance(fn, ast.FunctionDef)
        for call in ast.walk(fn)
        if isinstance(call, ast.Call) and ast.unparse(call.func).split(".")[-1] == "_run_compose"
    ]
    assert sync_calls, "the sync path should still exist; if not, this rewrite went too far"


def test_the_offload_helper_is_a_coroutine():
    assert inspect.iscoroutinefunction(docker_tools._await_blocking_990)


def test_it_passes_arguments_through():
    def _work(a, b=0):
        return a + b

    assert asyncio.run(docker_tools._await_blocking_990(_work, 2, b=5)) == 7


def test_the_loop_keeps_scheduling_during_a_slow_call():
    import time

    async def _drive():
        ticks = 0

        async def _ticker():
            nonlocal ticks
            while True:
                ticks += 1
                await asyncio.sleep(0.01)

        t = asyncio.create_task(_ticker())
        await docker_tools._await_blocking_990(time.sleep, 0.3)
        t.cancel()
        return ticks

    assert asyncio.run(_drive()) > 3, "the blocking call still owned the loop"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
