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


# --------------------------------------------------------------- fix #62
def test_wraps_trailing_kwargs_shape_in_custom_routes(tmp_path):
    """outlook run-47 (live): the lane's raw psycopg lives in custom_routes.py
    and passes kwargs — psycopg.connect(conninfo, row_factory=dict_row) — which
    the old only-argument/main.py-only repair never matched -> auth/me+folders
    500'd 5+ cycles on a correct app."""
    import ast
    from multi_agent.runtime.psycopg_dsn_repair import repair_psycopg_dsn
    be = tmp_path
    (be / "custom_routes.py").write_text(
        "import os\nimport psycopg\nfrom psycopg.rows import dict_row\n\n"
        "def get_db():\n"
        "    conninfo = os.getenv(\"DATABASE_URL\")\n"
        "    conn = psycopg.connect(conninfo, row_factory=dict_row)\n"
        "    return conn\n", encoding="utf-8")
    out = repair_psycopg_dsn(be)
    assert out["wrapped"] == 1
    src = (be / "custom_routes.py").read_text(encoding="utf-8")
    assert "psycopg.connect(_psycopg_dsn(conninfo), row_factory=dict_row)" in src
    ast.parse(src)                       # still valid python
    # the helper actually strips the dialect
    ns = {}
    exec(compile("\n".join(l for l in src.splitlines()
                           if not l.startswith(("import psycopg", "from psycopg"))),
                 "cr.py", "exec"), {"os": __import__("os")}, ns)


def test_env_lookup_first_arg_and_idempotent(tmp_path):
    import ast
    from multi_agent.runtime.psycopg_dsn_repair import repair_psycopg_dsn
    (tmp_path / "custom_routes.py").write_text(
        "import os, psycopg\n\n"
        "def q():\n"
        "    with psycopg.connect(os.environ.get(\"DATABASE_URL\"), autocommit=True) as c:\n"
        "        return c\n", encoding="utf-8")
    assert repair_psycopg_dsn(tmp_path)["wrapped"] == 1
    src = (tmp_path / "custom_routes.py").read_text(encoding="utf-8")
    assert 'psycopg.connect(_psycopg_dsn(os.environ.get("DATABASE_URL")), autocommit=True)' in src
    ast.parse(src)
    assert repair_psycopg_dsn(tmp_path)["wrapped"] == 0     # idempotent


def test_string_literal_dsn_left_alone(tmp_path):
    from multi_agent.runtime.psycopg_dsn_repair import repair_psycopg_dsn
    (tmp_path / "custom_routes.py").write_text(
        "import psycopg\n\nconn = psycopg.connect(\"host=db user=u\", autocommit=True)\n",
        encoding="utf-8")
    assert repair_psycopg_dsn(tmp_path)["wrapped"] == 0


def test_both_files_repaired(tmp_path):
    from multi_agent.runtime.psycopg_dsn_repair import repair_psycopg_dsn
    for f in ("main.py", "custom_routes.py"):
        (tmp_path / f).write_text(
            "import os, psycopg\nconn = psycopg.connect(os.getenv(\"DATABASE_URL\"))\n",
            encoding="utf-8")
    assert repair_psycopg_dsn(tmp_path)["wrapped"] == 2
