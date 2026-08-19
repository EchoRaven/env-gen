"""#980: the longest blocking calls in the codebase were on the event loop.

Third class sweep of the session. #963 was "a synchronous call inside `async def` freezes the
whole loop"; r155 lost 683 seconds to it and the silence read as a hang. Asking where else
that shape lives — by AST, not grep — found 12 more sites, and ranked by their own timeouts
the worst are here:

    dependency_tools  npm install   timeout=300   x2
    dependency_tools  pip install   timeout=120   x2
    docker_tools      compose down  timeout=60
    visual_fidelity   subprocess    timeout=20

Five minutes of frozen loop starves the LLM heartbeat (60s), the coordination tick (60s), and
every other lane's turn. This fixes the four 300/120s sites; the rest are recorded in item 372
with their measured caps.

The mechanical risk in a bulk rewrite is an `await` landing in a synchronous function, so a
test walks the AST for exactly that.
"""

import ast
import inspect
import pathlib

import pytest

from env_generator.llm_generator.tools import dependency_tools

SRC = pathlib.Path(inspect.getfile(dependency_tools)).read_text(encoding="utf-8")
TREE = ast.parse(SRC)


def _async_fns():
    return [n for n in ast.walk(TREE) if isinstance(n, ast.AsyncFunctionDef)]


def test_no_blocking_subprocess_survives_in_an_async_function():
    offenders = [
        (fn.name, call.lineno)
        for fn in _async_fns()
        for call in ast.walk(fn)
        if isinstance(call, ast.Call) and ast.unparse(call.func) == "subprocess.run"
    ]
    assert offenders == [], (
        f"a 300s npm install on the event loop stops every lane for five minutes: {offenders}")


def test_no_await_leaked_into_a_sync_function():
    """The mechanical hazard of the rewrite — `await` outside a coroutine is a SyntaxError at
    import time, but a sync helper that merely LOOKS async is worse: it returns a coroutine
    nobody awaits and the work silently never happens."""
    leaked = [
        (fn.name, node.lineno)
        for fn in ast.walk(TREE)
        if isinstance(fn, ast.FunctionDef)
        for node in ast.walk(fn)
        if isinstance(node, ast.Await)
    ]
    assert leaked == [], f"await inside a def (not async def): {leaked}"


def test_the_offload_helper_is_a_coroutine():
    assert inspect.iscoroutinefunction(dependency_tools._run_blocking_980)


def test_the_helper_actually_runs_the_callable():
    import asyncio

    def _work(a, b=0):
        return a + b

    assert asyncio.run(dependency_tools._run_blocking_980(_work, 2, b=3)) == 5


def test_the_helper_does_not_block_the_loop():
    """The property that matters: a slow call must not stop other tasks from being scheduled."""
    import asyncio
    import time

    async def _drive():
        ticks = 0

        async def _ticker():
            nonlocal ticks
            while True:
                ticks += 1
                await asyncio.sleep(0.01)

        t = asyncio.create_task(_ticker())
        await dependency_tools._run_blocking_980(time.sleep, 0.3)
        t.cancel()
        return ticks

    assert asyncio.run(_drive()) > 3, (
        "the ticker barely advanced, so the blocking call still owned the loop")


def test_the_control_would_block():
    """Planted control: the PRE-FIX shape — calling the blocking function directly inside the
    coroutine — starves the ticker. Synthetic, so fixing the real tools cannot turn it red."""
    import asyncio
    import time

    async def _drive():
        ticks = 0

        async def _ticker():
            nonlocal ticks
            while True:
                ticks += 1
                await asyncio.sleep(0.01)

        t = asyncio.create_task(_ticker())
        await asyncio.sleep(0)          # let the ticker start
        time.sleep(0.3)                 # the pre-fix call
        t.cancel()
        return ticks

    assert asyncio.run(_drive()) <= 3, (
        "the control was supposed to starve the ticker; if it does not, the test above "
        "proves nothing")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
