"""#1202nb: a DDL foreign-key reference must quote its target, because `user` is reserved.

tiktok-r125's ORM declared a `user` table. The DDL the framework regenerates from the ORM (FIX #43,
`introspect_orm_schema` -> `_ddl_type_from_introspect`) wrote `references user(id)` unquoted while
quoting everything else, and Postgres refused the init script:

    ERROR:  syntax error at or near "user"   (docker_up failed 8x in the run, 2x in its resume)

Loaded into postgres:16: the unquoted DDL fails with exactly that error; the quoted DDL creates
all 23 tables. `backend_skeleton._set_col_base_category` rebuilt inline references from unquoted
regex captures and had the same flaw.
"""
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "env_generator" / "llm_generator"))

from multi_agent.runtime.backend_skeleton import _set_col_base_category  # noqa: E402
from multi_agent.runtime.database_scaffold import (  # noqa: E402
    _ddl_type_from_introspect, _fk_type_conflicts_1022, introspect_orm_schema, render_schema_sql)

_MODELS = '''
from sqlalchemy import Column, Integer, String, ForeignKey
from database import Base


class User(Base):
    __tablename__ = "user"
    id = Column(Integer, primary_key=True)
    username = Column(String)


class Follow(Base):
    __tablename__ = "follow"
    id = Column(Integer, primary_key=True)
    follower_user_id = Column(Integer, ForeignKey("user.id"))
    followed_user_id = Column(Integer, ForeignKey("user.id"))
'''

# The fixed spine SQL writes `REFERENCES tenants(id)` / `users(id)` by hand, which is valid; what
# must never appear is an unquoted reference to the reserved word.
UNQUOTED = re.compile(r"references\s+user\s*\(", re.I)


def test_the_introspected_reference_is_quoted():
    t = _ddl_type_from_introspect({"name": "follower_user_id", "type": "INTEGER", "fk": "user.id"},
                                  {"user": "integer"})
    assert t == 'integer references "user"("id") on delete cascade', t


def test_r125s_orm_renders_no_unquoted_reference():
    with tempfile.TemporaryDirectory() as tmp:
        # introspection imports the backend, so it needs the `database` module models.py uses
        (Path(tmp) / "database.py").write_text(
            "from sqlalchemy.orm import declarative_base\nBase = declarative_base()\n",
            encoding="utf-8")
        (Path(tmp) / "models.py").write_text(_MODELS, encoding="utf-8")
        sql = render_schema_sql(introspect_orm_schema(Path(tmp)) or {})
    assert 'references "user"("id")' in sql, sql
    assert not UNQUOTED.search(sql), [ln for ln in sql.splitlines() if UNQUOTED.search(ln)]


def test_coercing_an_inline_reference_keeps_it_quoted():
    col = {"name": "author_id", "type": 'TEXT REFERENCES "user" ("id") ON DELETE CASCADE'}
    _set_col_base_category(col, "integer")
    assert col["type"] == 'integer references "user"("id") ON DELETE CASCADE', col["type"]


def test_the_fk_type_net_still_reads_the_quoted_form():
    ddl = ('CREATE TABLE IF NOT EXISTS "user" (\n    "id" SERIAL PRIMARY KEY\n);\n'
           'CREATE TABLE IF NOT EXISTS "follow" (\n    "id" SERIAL PRIMARY KEY,\n'
           '    "follower_user_id" uuid references "user"("id") on delete cascade\n);\n')
    assert _fk_type_conflicts_1022(ddl) == [
        ("follow", "follower_user_id", "uuid", "user.id", "integer")]
