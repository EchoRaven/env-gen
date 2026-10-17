r"""#1203mz: the projected read typed every `*_id` filter as int, whatever the column said.

`_declared_query_filters_1202os` had the column's declared type in hand and then overrode it
by name:

    out.append((name, "int" if ("int" in t or name.endswith("_id")) else "str"))

r190 paid for it. `comments.video_id` is `Column(String, ForeignKey("videos.id"))` in
models.py, `"video_id" text` in the DDL, and `"string references videos.id nullable"` in the
registry's table schema -- and the projected read came out

    def _projected_get_api_comments_6(video_id: int = Query(default=None), ...)

so FastAPI answered 422 to `?video_id=video-36` before any SQL ran. The lane found it and
wrote its own route around the framework, documenting the cause in custom_routes.py:

    The comments panel passes public video ids such as "video-36". The generic projected
    collection handler typed video_id as int in the current artifact, causing FastAPI to
    reject valid requests at validation time before the SQL layer sees them.

MEASURED over every delivered backend on disk: 4 projected params are typed int while their
model column is a string type, across 3 runs -- googlemaps-r16 (2, both PATH params, from
before `_param_column_type` existed), tiktok-web-r152 (`tenant_id`, Text) and tiktok-web-r190
(`video_id`, String/Text). Both modern instances are query filters, i.e. this line.

The policy is not invented here: `_param_column_type` in the same file already types PATH
params "by-construction from the schema -- never hardcodes names", falling back to the name
only when no model resolves. This makes the query side agree, and keeps the heuristic for the
case it was written for: a raw-SQL app whose models.py cannot be parsed leaves `types` empty.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
if str(LLM) not in sys.path:
    sys.path.insert(0, str(LLM))

from multi_agent.runtime.route_projector import (          # noqa: E402
    _declared_query_filters_1202os as filters,
    project_missing_routes,
)

# r190's shape: string ids everywhere, a text FK to them.
_MODELS_TEXT_ID = '''
from sqlalchemy import Column, Integer, String, Text, ForeignKey
from db import Base


class Video(Base):
    __tablename__ = "videos"
    id = Column(String, primary_key=True)
    category = Column(String)


class Comment(Base):
    __tablename__ = "comments"
    id = Column(String, primary_key=True)
    video_id = Column(String, ForeignKey("videos.id"))
    body = Column(String)
'''

# The same app with integer keys, which must keep coercing "123" -> 123.
_MODELS_INT_ID = _MODELS_TEXT_ID.replace(
    'id = Column(String, primary_key=True)\n    category',
    'id = Column(Integer, primary_key=True)\n    category').replace(
    'id = Column(String, primary_key=True)\n    video_id = Column(String',
    'id = Column(Integer, primary_key=True)\n    video_id = Column(Integer')

_ENDPOINT = [{"method": "GET", "path": "/api/comments",
              "schema": {"request": {"video_id": "str", "limit": "int"}}}]


def _project(tmp_path, models_src, endpoints=None):
    backend = tmp_path / "app" / "backend"
    backend.mkdir(parents=True)
    (backend / "models.py").write_text(models_src)
    (backend / "main.py").write_text(
        "from fastapi import Depends, FastAPI, Query\napp = FastAPI()\n")
    design = tmp_path / "design"
    design.mkdir()
    (design / "reference_spec.json").write_text(json.dumps(
        {"entities": [{"name": "videos", "visibility": "public"},
                      {"name": "comments", "visibility": "public"}]}))
    project_missing_routes(backend, endpoints or _ENDPOINT)
    return (backend / "main.py").read_text()


class TheColumnTypeDecides(unittest.TestCase):
    def test_r190s_string_column(self):
        self.assertEqual(filters({"video_id": "str"}, ["video_id"], {"video_id": "String"}),
                         [("video_id", "str")])

    def test_a_text_column(self):
        """r152's shape: `tenant_id` on a Text column."""
        self.assertEqual(filters({"tenant_id": "str"}, ["tenant_id"], {"tenant_id": "Text"}),
                         [("tenant_id", "str")])

    def test_an_integer_column_still_coerces(self):
        self.assertEqual(filters({"video_id": "int"}, ["video_id"], {"video_id": "Integer"}),
                         [("video_id", "int")])

    def test_the_wider_integer_spellings(self):
        for sa in ("BigInteger", "SmallInteger", "INTEGER"):
            with self.subTest(sa=sa):
                self.assertEqual(filters({"x_id": "int"}, ["x_id"], {"x_id": sa}),
                                 [("x_id", "int")])

    def test_a_uuid_column_is_not_an_int(self):
        self.assertEqual(filters({"video_id": "str"}, ["video_id"], {"video_id": "UUID"}),
                         [("video_id", "str")])


class TheNameHeuristicSurvivesWhereItIsAllThereIs(unittest.TestCase):
    def test_no_type_at_all_keeps_the_id_guess(self):
        """A raw-SQL app whose models.py the projector cannot parse."""
        self.assertEqual(filters({"video_id": "str"}, ["video_id"], {}),
                         [("video_id", "int")])

    def test_no_type_and_not_an_id_is_a_string(self):
        self.assertEqual(filters({"category": "str"}, ["category"], {}),
                         [("category", "str")])

    def test_an_empty_type_string_counts_as_unknown(self):
        self.assertEqual(filters({"video_id": "str"}, ["video_id"], {"video_id": ""}),
                         [("video_id", "int")])


class TheOtherRulesAreUntouched(unittest.TestCase):
    def test_pagination_is_not_a_filter(self):
        self.assertEqual(filters({"limit": "int", "offset": "int"}, ["limit"], {}), [])

    def test_a_field_that_is_not_a_column_is_not_served(self):
        self.assertEqual(filters({"q": "str"}, ["video_id"], {"q": "String"}), [])

    def test_a_non_mapping_schema(self):
        self.assertEqual(filters(None, ["video_id"], {"video_id": "String"}), [])


class TheProjectedSignatureSaysIt(unittest.TestCase):
    """End to end: the emitted handler is what FastAPI validates against."""

    def setUp(self):
        import tempfile
        self._d = tempfile.TemporaryDirectory()
        self.tmp = Path(self._d.name)
        self.addCleanup(self._d.cleanup)

    def test_a_text_id_is_projected_as_str(self):
        src = _project(self.tmp, _MODELS_TEXT_ID)
        self.assertIn("video_id: str = Query(default=None)", src)
        self.assertNotIn("video_id: int = Query(default=None)", src)

    def test_an_int_id_is_still_projected_as_int(self):
        src = _project(self.tmp, _MODELS_INT_ID)
        self.assertIn("video_id: int = Query(default=None)", src)

    def test_the_filter_is_still_applied(self):
        """#1202os's own claim -- the declared filter must reach the query."""
        src = _project(self.tmp, _MODELS_TEXT_ID)
        self.assertIn("if video_id is not None:", src)
        self.assertIn('getattr(Comment, "video_id") == video_id', src)


if __name__ == "__main__":
    unittest.main()
