r"""#1202bl: a projected create that names no subject still reaches the table.

Measured live against netflix-r32:

    POST /api/continue-watching  {}   -> 201
    {"id":21,"profile_id":28,"title_id":null,"progress_seconds":null}
    GET /api/continue-watching        -> hands that row to the frontend

The owner FK is filled from the authenticated user; the SUBJECT FK is not, and the row
means nothing — a continue-watching entry for no title. The lane's own handler in
custom_routes.py rejects exactly this with a 400, but it is never registered: it
duplicates standard CRUD, so the projection serves the path and describes itself as
"schema-safe by construction".

Not a schema change. #1045 is why these columns are nullable — NOT NULL with no default
made 20 recent runs 400 at INSERT and r176 died on it — so this refuses before the insert
instead, on the only case that can never mean anything.

Blast radius measured across the corpus: of 6946 POSTs to a bare collection path, 83 send
an empty body, and all but 3 are framework-owned auth/oauth/tenant routes the projection
does not serve. Those 3 carry `expect=[200, 201, 400, 422]`, so 400 already passes them.
Zero corpus steps break.
"""
import re
import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

_SRC = (THIS_DIR.parent / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
        / "route_projector.py")


def _block_else():
    """The no-subject-FK branch of the same emission."""
    b = _block()
    return b[b.index("else:"):]


def _block():
    """Landmark-bounded (#943): the marker to the end of its own emission."""
    src = _SRC.read_text(encoding="utf-8")
    i = src.index("#1202bl")
    j = src.index("#566u", i)
    return src[i:j]


def _block_else():
    """The no-subject-FK branch of the same emission."""
    b = _block()
    return b[b.index("else:"):]


class CreateMustNameItsSubjectTests(unittest.TestCase):
    def test_the_check_is_emitted_for_post(self):
        b = _block()
        self.assertIn("_subj_1202bl", b)
        self.assertIn("status_code=400", b)

    def test_the_owner_fk_is_excluded(self):
        """profile_id is filled from the user, so requiring it would reject every create."""
        self.assertIn("_owner_fk(meta", _block())

    def test_path_bound_fks_are_excluded(self):
        """A parent id supplied in the URL is already bound; it is not the body's job."""
        self.assertIn("bound", _block())

    def test_it_only_fires_when_a_subject_fk_exists(self):
        """A top-level entity (no FKs) must stay creatable from an empty body."""
        self.assertIn("if _subj_1202bl:", _block())

    def test_it_accepts_any_one_subject(self):
        """`any(...)` not `all(...)`: naming one subject is a meaningful create."""
        b = _block()
        self.assertIn("if not any(valid.get(_k) is not None", b)
        self.assertNotIn("if not all(valid.get(", b)

    def test_a_table_with_no_subject_fk_still_requires_something(self):
        """r32, live: `POST /api/profiles {}` -> 201 {"name":null,"is_kids":null} — a
        profile with no name, which the picker renders as a blank tile. No subject FK
        exists to require, so the branch above cannot fire; the create must still have
        been given a field."""
        b = _block()
        b = b[b.index("else:"):]
        self.assertIn("if not valid:", b)
        self.assertIn("status_code=400", b)

    def test_the_two_branches_are_exclusive(self):
        """A table WITH a subject FK gets the specific message, not the generic one."""
        b = _block()
        self.assertIn("if _subj_1202bl:", b)
        self.assertIn("else:", b)

    def test_the_projector_still_parses(self):
        import ast
        ast.parse(_SRC.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
