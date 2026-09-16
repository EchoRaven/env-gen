"""#1202pk: #119 must not narrow a `str` path param to `int` without evidence that
the resource table has an integer PK (r125: videos.id is a String uuid)."""
import textwrap
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.backend_scaffold import (
    repair_custom_routes_param_types_vs_projection as repair,
)

MAIN = textwrap.dedent('''
    from fastapi import APIRouter
    router = APIRouter()
    @router.post("/api/videos/{video_id}/like")
    def like(video_id: int):
        return {}
    @router.get("/api/posts/{post_id}")
    def get_post(post_id: int):
        return {}
    @router.get("/api/users/{username}")
    def get_user(username: str):
        return {}
''')

MODELS = textwrap.dedent('''
    class Video(Base):
        __tablename__ = "video"
        id = Column(Integer, primary_key=True)
    class Videos(Base):
        __tablename__ = "videos"
        id = Column(String, primary_key=True)
    class Post(Base):
        __tablename__ = "posts"
        id = Column(Integer, primary_key=True)
    class User(Base):
        __tablename__ = "users"
        id = Column(Integer, primary_key=True)
        username = Column(String)
''')

CUSTOM = textwrap.dedent('''
    from fastapi import APIRouter
    router = APIRouter()
    @router.post("/api/videos/{video_id}/like")
    def like(video_id: str):
        return {}
    @router.get("/api/posts/{post_id}")
    def get_post(post_id: str):
        return {}
    @router.get("/api/users/{username}")
    def get_user(username: int):
        return {}
''')


def _be(tmp_path, models=MODELS):
    (tmp_path / "main.py").write_text(MAIN)
    (tmp_path / "custom_routes.py").write_text(CUSTOM)
    if models is not None:
        (tmp_path / "models.py").write_text(models)
    return tmp_path


def test_a_string_pk_resource_keeps_its_str_param(tmp_path):
    be = _be(tmp_path)
    repair(be)
    assert "def like(video_id: str)" in (be / "custom_routes.py").read_text()


def test_an_integer_pk_resource_is_still_narrowed(tmp_path):
    be = _be(tmp_path)
    repair(be)
    assert "def get_post(post_id: int)" in (be / "custom_routes.py").read_text()


def test_widening_still_applies(tmp_path):
    be = _be(tmp_path)
    repair(be)
    assert "def get_user(username: str)" in (be / "custom_routes.py").read_text()


def test_no_models_means_no_narrowing(tmp_path):
    be = _be(tmp_path, models=None)
    out = repair(be)
    src = (be / "custom_routes.py").read_text()
    assert "def get_post(post_id: str)" in src
    assert "def get_user(username: str)" in src
    assert out["fixed"] == 1
