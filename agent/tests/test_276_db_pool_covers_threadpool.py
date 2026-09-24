"""#276 — the generated DB engine's connection pool must cover the request thread pool.

r60 (opus-4.7), live: after hours of a healthy app, the backend container went `unhealthy`,
/health stopped responding, and api_smoke reported TimeoutError (not 404/500) on
/api/feed/for-you and the video write endpoints — the WHOLE surface, intermittently. The
container process was S (sleeping), CPU ~0%, 80 MB — not crashed, not OOM, not spinning:
BLOCKED waiting.

Root cause is in the framework-generated database.py, which the lane cannot edit:

    engine = create_engine(_URL, pool_pre_ping=True, future=True)

No pool sizing, so SQLAlchemy's default is pool_size=5 + max_overflow=10 = 15 connections
with pool_timeout=30s. FastAPI runs SYNC handlers (all of ours are `def`, not `async`) on a
thread pool of 40 by default. Under load, 40 concurrent handlers contend for 15 connections;
the ~25 that lose block up to 30s and then raise TimeoutError — including the health check,
which is why the container flips `unhealthy` and everything "times out" while the process
sits idle. It recovers when load drops, then wedges again: exactly the intermittent pattern.

The pool must be at least as large as the number of request workers that can each hold a
connection. Size the pool to the thread pool (bounded, with a little headroom), so a
connection is always available and no handler blocks on checkout.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import (  # noqa: E402
    _DATABASE_PY,
)


def _create_engine_call() -> str:
    """The create_engine call plus the pool-kwargs block (both live in database.py)."""
    m = re.search(r"engine\s*=\s*create_engine\((.*?)\)\n", _DATABASE_PY, re.S)
    assert m, "create_engine(...) not found"
    pool = re.search(r"else\s*(\{[^}]*\})", _DATABASE_PY, re.S)   # the non-sqlite dict
    return m.group(1) + " " + (pool.group(1) if pool else "")


def test_pool_size_is_declared():
    call = _create_engine_call()
    assert "pool_size" in call, "engine must declare pool_size, not rely on the default 5"


def test_max_overflow_is_declared():
    call = _create_engine_call()
    assert "max_overflow" in call


def test_total_pool_covers_the_request_thread_pool():
    """pool_size + max_overflow must be >= FastAPI's default 40-thread pool (with headroom),
    so 40 concurrent sync handlers never starve for a connection."""
    call = _create_engine_call()
    ps = int(re.search(r"pool_size\D+(\d+)", call).group(1))
    mo = int(re.search(r"max_overflow\D+(\d+)", call).group(1))
    assert ps + mo >= 40, f"pool total {ps + mo} < 40 request threads — the r60 wedge"


def test_pre_ping_and_future_are_kept():
    call = _create_engine_call()
    assert "pool_pre_ping=True" in call and "future=True" in call


def test_pool_timeout_is_bounded_not_infinite():
    """A finite checkout wait so a genuine exhaustion fails fast (visible) instead of hanging
    forever — but with a real pool it should essentially never be hit."""
    call = _create_engine_call()
    assert "pool_timeout" in call


def test_generated_database_py_still_compiles():
    import ast
    ast.parse(_DATABASE_PY)
