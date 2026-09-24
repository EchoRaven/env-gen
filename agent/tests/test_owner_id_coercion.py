"""Owner-scope comparisons coerce the caller id (run-39 STUCK, 2026-07-02).

Auth deps commonly carry the JWT `sub` as a STRING; the projected owner filters compared it
raw against INTEGER owner columns → postgres `operator does not exist: integer = character
varying` → EVERY scoped read/write 500'd → business_endpoints_reachable STUCK-abort (run-39,
universal 500s incl /api/folders,/api/messages). All emitted comparisons now go through
_fw_uid (digits → int, text/uuid ids untouched), defined in the skeleton main header and in
the projector's guarded prelude. LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_skeleton import render_skeleton_main  # noqa: E402

_TABLES = {
    "users": {"columns": [{"name": "id", "type": "integer", "primary_key": True}]},
    "messages": {"columns": [{"name": "id", "type": "integer", "primary_key": True},
                             {"name": "user_id", "type": "integer", "foreign_key": "users.id"}],
                 "metadata": {"owner_scoped_reads": True}},
}
_EPS = [{"method": "GET", "path": "/api/messages"},
        {"method": "GET", "path": "/api/messages/{messageId}"}]


def _helper(src):
    ns = {}
    block = src.split("def _fw_uid(user):")[1].split("\n\n")[0]
    exec(compile("def _fw_uid(user):" + block, "h.py", "exec"), ns)
    return ns["_fw_uid"]


def test_skeleton_defines_helper_and_uses_it():
    src = render_skeleton_main(_EPS, _TABLES)
    compile(src, "main.py", "exec")
    assert "def _fw_uid(user):" in src
    assert "_fw_uid(user)" in src.split("def _fw_uid")[1]     # used by handlers
    assert "== user.id" not in src                             # no raw comparisons remain


def test_helper_semantics():
    src = render_skeleton_main(_EPS, _TABLES)
    f = _helper(src)

    class U:
        id = "7"                                   # string sub over int PK (the run-39 case)
    assert f(U()) == 7 and isinstance(f(U()), int)

    class V:
        id = "9c-4e-uuid"
    assert f(V()) == "9c-4e-uuid"                  # text/uuid ids untouched
    assert f({"sub": "12"}) == 12                  # dict dep with sub only
    assert f(5) == 5                               # bare id


def test_projector_prelude_defines_helper(tmp_path):
    from multi_agent.runtime.route_projector import project_missing_routes
    be = tmp_path
    (be / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n\n"
        "@app.get('/health')\ndef health():\n    return {}\n\n"
        "if __name__ == '__main__':\n    pass\n", encoding="utf-8")
    (be / "models.py").write_text(
        "from sqlalchemy.orm import declarative_base\nBase = declarative_base()\n", encoding="utf-8")
    project_missing_routes(be, [{"method": "GET", "path": "/api/notes"}])
    src = (be / "main.py").read_text(encoding="utf-8")
    assert "def _fw_uid(user):" in src
    compile(src, "main.py", "exec")
