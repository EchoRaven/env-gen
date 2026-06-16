"""Raw-psycopg DSN repair — wraps psycopg.connect() to strip the SQLAlchemy dialect.

Root fix (instagram MM run #10, 2026-06-09): handlers opened raw psycopg connections with
the SQLAlchemy ``postgresql+psycopg://`` URL → ``ProgrammingError: missing "=" …`` 500 on
/api/users/suggested, /api/feed, /api/explore, … → api_smoke stall.
"""

import ast
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.psycopg_dsn_repair import repair_psycopg_dsn  # noqa: E402


def _backend(tmp_path, main_src):
    (tmp_path / "main.py").write_text(main_src, encoding="utf-8")
    return tmp_path


_MAIN = '''import os
import psycopg


def _database_url():
    return os.getenv("DATABASE_URL")


def get_feed():
    with psycopg.connect(_database_url()) as conn:
        return conn


def get_profile(database_url):
    with psycopg.connect(database_url) as conn:
        return conn
'''


def test_wraps_connect_sites_and_parses(tmp_path):
    be = _backend(tmp_path, _MAIN)
    res = repair_psycopg_dsn(be)
    assert res["wrapped"] == 2
    out = (be / "main.py").read_text(encoding="utf-8")
    assert "psycopg.connect(_psycopg_dsn(_database_url()))" in out
    assert "psycopg.connect(_psycopg_dsn(database_url))" in out
    assert "def _psycopg_dsn(" in out
    ast.parse(out)  # still valid Python


def test_helper_strips_sqlalchemy_dialect(tmp_path):
    be = _backend(tmp_path, _MAIN)
    repair_psycopg_dsn(be)
    src = (be / "main.py").read_text(encoding="utf-8")
    ns: dict = {}
    # exec just the helper
    import re
    m = re.search(r"def _psycopg_dsn.*?(?=\ndef |\nclass |\n@|\Z)", src, re.S)
    exec(m.group(0), ns)
    fn = ns["_psycopg_dsn"]
    assert fn("postgresql+psycopg://u:p@h:5432/db") == "postgresql://u:p@h:5432/db"
    assert fn("postgresql+asyncpg://u:p@h/db") == "postgresql://u:p@h/db"
    assert fn("postgresql://u:p@h/db") == "postgresql://u:p@h/db"  # already clean
    assert fn(None) == ""


def test_idempotent(tmp_path):
    be = _backend(tmp_path, _MAIN)
    assert repair_psycopg_dsn(be)["wrapped"] == 2
    assert repair_psycopg_dsn(be)["wrapped"] == 0  # second pass: nothing


def test_no_raw_psycopg_untouched(tmp_path):
    be = _backend(tmp_path, "import os\ndef get_db():\n    return 1\n")
    assert repair_psycopg_dsn(be)["wrapped"] == 0
    assert "_psycopg_dsn" not in (be / "main.py").read_text(encoding="utf-8")
