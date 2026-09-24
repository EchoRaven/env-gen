"""FIX #215 — a column named ``text`` must not shadow the SQLAlchemy ``text()``
function the framework uses in ``server_default``.

r17 live: backend failed to boot —
``TypeError: 'Column' object is not callable`` at models.py:88. The comments
model had ``text = Column(Text)`` (a comment body) AND, a few lines later,
``likes_count = Column(Integer, default=0, server_default=text('0'))``. Inside the
class body ``text`` already resolved to the just-assigned ``Column`` object, so
``text('0')`` called a Column → TypeError → ``import models`` crashes → the whole
backend won't boot → backend_health/business_chain/ui_flow all fail → delivery
deadlock. The framework must reference the ``text()`` function under a
non-colliding alias. Env-agnostic: ``text`` is one of the most common column
names (comments/messages/posts/notes all have one) and ANY of them with a
defaulted sibling column hit this.
"""

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_skeleton import render_models  # noqa: E402


def _exec_models(tables):
    """Compile+exec the generated models.py exactly as the backend does on boot."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import declarative_base
    Base = declarative_base()
    db_mod = types.ModuleType("database")
    db_mod.Base = Base
    db_mod.engine = create_engine("sqlite://")
    sys.modules["database"] = db_mod
    models_mod = types.ModuleType("models")
    try:
        exec(compile(render_models(tables), "models.py", "exec"), models_mod.__dict__)
    finally:
        sys.modules.pop("database", None)
    return models_mod


_TABLES = {
    # r17's exact collision shape: a `text` column + a defaulted sibling.
    "comments": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "text", "type": "text"},
        {"name": "likes_count", "type": "integer", "default": 0}]},
}


def test_text_column_does_not_break_import():
    # r17: this raised TypeError: 'Column' object is not callable at class-body time.
    mod = _exec_models(_TABLES)
    assert hasattr(mod, "Comment") or any(
        getattr(getattr(mod, n), "__tablename__", None) == "comments"
        for n in dir(mod) if isinstance(getattr(mod, n), type))


def _code_lines(src):
    # emitted CODE only — drop comment lines so an explanatory '# ...text(...' in the
    # generated header doesn't count as a real collision.
    return [ln for ln in src.split("\n") if not ln.strip().startswith("#")]


def test_defaulted_column_still_has_server_default():
    # the fix must not drop the DDL server_default — only de-collide the reference.
    src = render_models(_TABLES)
    assert "server_default=" in src
    # emitted CODE must reference the aliased function, never the bare `text(`
    code = "\n".join(_code_lines(src))
    assert "server_default=_sa_text(" in code
    assert "server_default=text(" not in code


def test_now_default_also_de_collided():
    tables = {"posts": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "text", "type": "text"},
        {"name": "created_at", "type": "datetime", "default": "now()"}]}}
    mod = _exec_models(tables)  # must import cleanly despite text col + now() default
    assert mod is not None
    code = "\n".join(_code_lines(render_models(tables)))
    assert "server_default=text(" not in code
