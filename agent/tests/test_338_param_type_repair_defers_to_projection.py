"""#338: #106's PK-type guess must not overwrite #119's projected signature.

Two framework passes rewrite the SAME annotation in app/backend/custom_routes.py
with opposite rules:

  * #119 `repair_custom_routes_param_types_vs_projection` aligns each param to
    the PROJECTED signature in framework-owned main.py (the authoritative
    contract), in both directions.
  * #106 `repair_custom_routes_param_types` forces `str` -> `int` for any route
    whose resource segment maps to an integer-PK table.

#106's classifier takes `res = segs[first_param_idx - 1]` — the segment just
before the first path param — and assumes that param is that table's PK. That
is false for a NATURAL KEY: on `/api/users/{username}/follow` it reads `users`,
finds `users.id` is `Column(Integer, primary_key=True)`, and rewrites
`username: str` -> `username: int`, which 422s on every real username.

That is not hypothetical. r92's generated repo contains the flip and the lane
having to undo it:

    35022b3 merge agent/backend -> integration
    -    username: int
    +    username: str

So the delivered app is correct only because the lane spent work reverting a
bug the framework introduced. #106 fired 99 times in r92, #119 39 times.

They also disagree about WHICH tree wins: heal_pipeline runs #119 then #106, so
#106 wins the heal tick — but #119 has two entry points #106 does not
(validation_runner right before `docker compose up --build`, and docker_tools),
so the IMAGE THAT GETS VALIDATED can carry #119's annotation while the
committed integration tree carries #106's.

Fix: #106 defers to the projection. Where main.py already projects a route,
#119's answer is authoritative and #106 can only corrupt it. Where a route has
NO projected counterpart, #106 is the only signal and still applies — so the
instagram run-23 wedge it was written for (`posts.id = '20'::VARCHAR` -> 500 on
every by-id read) stays fixed.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

MODELS = '''from sqlalchemy import Column, Integer, Text
from .database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(Text)

class Post(Base):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True)
'''

# main.py projects the follow route with the TRUTH (username is a natural key,
# so the projection types it str) and does NOT project the by-id post read.
MAIN = '''from fastapi import FastAPI
app = FastAPI()

@app.post("/api/users/{username}/follow")
def _projected_follow(username: str):
    return {"item": {}}
'''

CUSTOM = '''from fastapi import APIRouter
router = APIRouter()

@router.post("/api/users/{username}/follow")
def toggle_follow(username: str):
    return {"item": {}}

@router.get("/api/posts/{id}")
def get_post(id: str):
    return {"item": {}}
'''


def _tree(tmp):
    be = Path(tmp) / "backend"
    be.mkdir()
    (be / "models.py").write_text(MODELS)
    (be / "main.py").write_text(MAIN)
    (be / "custom_routes.py").write_text(CUSTOM)
    return be


def _repair(be):
    from multi_agent.runtime.backend_scaffold import repair_custom_routes_param_types
    return repair_custom_routes_param_types(be)


class ProjectedRoutesAreLeftToFix119(unittest.TestCase):

    def test_natural_key_param_is_not_forced_to_int(self):
        """The r92 regression, exactly."""
        with TemporaryDirectory() as tmp:
            be = _tree(tmp)
            _repair(be)
            src = (be / "custom_routes.py").read_text()
            self.assertIn("def toggle_follow(username: str)", src)
            self.assertNotIn("username: int", src)

    def test_repair_is_idempotent_on_a_projected_route(self):
        with TemporaryDirectory() as tmp:
            be = _tree(tmp)
            _repair(be)
            first = (be / "custom_routes.py").read_text()
            _repair(be)
            self.assertEqual(first, (be / "custom_routes.py").read_text())


class UnprojectedRoutesStillGetTheRun23Fix(unittest.TestCase):
    """#106 must keep working where it is the only signal."""

    def test_by_id_param_on_an_int_pk_table_is_still_corrected(self):
        with TemporaryDirectory() as tmp:
            be = _tree(tmp)
            _repair(be)
            src = (be / "custom_routes.py").read_text()
            # /api/posts/{id} has no projected counterpart in main.py
            self.assertIn("def get_post(id: int)", src)

    def test_it_reports_the_fix_count(self):
        with TemporaryDirectory() as tmp:
            be = _tree(tmp)
            out = _repair(be)
            self.assertEqual(out.get("fixed"), 1)


class NoMainPyStillFixesTheWedgeButNotTheNaturalKey(unittest.TestCase):
    """★ #1104 changed this contract deliberately; this test pinned the old one.

    #338 fixed the natural-key flip by DEFERRING wherever main.py projects the route.
    With no projection there was nothing to defer to, so the flip still happened — and
    this case asserted it, under the name "unchanged behaviour".

    But the flip is wrong on its own terms, as this module's own docstring says: it
    "422s on every real username", and r92's delivered app is correct only because the
    lane reverted it by hand. #1104 asks the PARAM's own column instead of the
    resource's PK, which settles it with no projection needed — and is also what makes
    the repair converge, since #1104's reverse pass would otherwise rewrite `username`
    back to str on the very next tick.

    The run-23 wedge #106 exists for is untouched: `posts.id` really is an integer, so
    `id: str` is still flipped.
    """

    def test_the_by_id_wedge_is_still_repaired_without_main_py(self):
        with TemporaryDirectory() as tmp:
            be = _tree(tmp)
            (be / "main.py").unlink()
            _repair(be)
            src = (be / "custom_routes.py").read_text()
            self.assertIn("def get_post(id: int)", src)

    def test_the_natural_key_is_no_longer_flipped_without_main_py(self):
        with TemporaryDirectory() as tmp:
            be = _tree(tmp)
            (be / "main.py").unlink()
            _repair(be)
            src = (be / "custom_routes.py").read_text()
            self.assertIn("username: str", src)
            self.assertNotIn("username: int", src)


if __name__ == "__main__":
    unittest.main()
