"""Handler↔model FK-alias repair — fixes ``<Model>.<missing_owner_alias>``.

Root fix (instagram MM run #9, 2026-06-09): the lane wrote ``Post.user_id`` while the
Post model's owner FK is ``author_id`` → AttributeError 500 on /api/users/me → api_smoke
stall. The repair rewrites only GUARANTEED-broken references to the model's real owner FK.
"""

import ast
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.handler_fk_repair import repair_handler_fk_aliases  # noqa: E402

_MODELS = '''
from sqlalchemy import Column, Integer, String, ForeignKey
from database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String)

class Post(Base):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True)
    author_id = Column(Integer, ForeignKey("users.id"))
    caption = Column(String)

class Tenant(Base):
    __tablename__ = "tenants"
    id = Column(String, primary_key=True)
    name = Column(String)
'''


def _backend(tmp_path, main_src):
    (tmp_path / "models.py").write_text(_MODELS, encoding="utf-8")
    (tmp_path / "main.py").write_text(main_src, encoding="utf-8")
    return tmp_path


def test_rewrites_missing_owner_alias(tmp_path):
    main = (
        "from models import Post\n"
        "def counts(db, uid):\n"
        "    return db.query(Post).filter(Post.user_id == uid).count()\n"
    )
    be = _backend(tmp_path, main)
    res = repair_handler_fk_aliases(be)
    assert res["fixed"] == ["Post.user_id -> Post.author_id (x1)"]
    out = (be / "main.py").read_text(encoding="utf-8")
    assert "Post.author_id == uid" in out
    assert "Post.user_id" not in out
    ast.parse(out)


def test_valid_reference_untouched(tmp_path):
    main = (
        "from models import Post\n"
        "def counts(db, uid):\n"
        "    return db.query(Post).filter(Post.author_id == uid).count()\n"
    )
    be = _backend(tmp_path, main)
    res = repair_handler_fk_aliases(be)
    assert res["fixed"] == []
    assert "Post.author_id == uid" in (be / "main.py").read_text(encoding="utf-8")


def test_idempotent(tmp_path):
    main = "from models import Post\nx = Post.user_id\n"
    be = _backend(tmp_path, main)
    assert repair_handler_fk_aliases(be)["fixed"]  # first pass fixes
    assert repair_handler_fk_aliases(be)["fixed"] == []  # second pass: nothing


def test_model_without_owner_fk_untouched(tmp_path):
    # Tenant has no owner FK → a Tenant.user_id ref is not auto-rewritten (no target)
    main = "from models import Tenant\nx = Tenant.user_id\n"
    be = _backend(tmp_path, main)
    assert repair_handler_fk_aliases(be)["fixed"] == []


def test_no_models_file(tmp_path):
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    assert repair_handler_fk_aliases(tmp_path)["fixed"] == []
