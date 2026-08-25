"""#1099 — the invariant that would have caught #1096, #1097 and #1098 before a run did.

Three defects in a row came from the same shape: a decision computed independently by the two
handler emitters, drifting without anything noticing.

    #1096  _class_name called separately by render_models and _models_meta — both collapsed
           `messages` and `message` to `Message`, agreeing on being wrong, so models.py
           compiled and main.py referenced a name that existed. 500 only at request time.
    #1097  route_projector applied #320 (an explicit `auth_required: false` drops the owner
           filter); backend_skeleton did not.
    #1098  route_projector applied #271 (`auth = … or _owner_scoped`, without which #633's
           structural-privacy flag cannot take effect); backend_skeleton did not — so the
           same contract yielded a protected handler from one emitter and an unauthenticated
           dump of every user's rows from the other.

#885 already guards constants that share a NAME, and its own measurement records that scanning
by VALUE is the wrong axis (41 candidates, 1 finding). None of these three was a constant: they
were decision SEQUENCES at two call sites, which nothing compared. This does compare them —
render the same contract through both paths and assert the decisions that matter come out the
same.

`route_projector.project_missing_routes` appends to a backend on DISK, so path B renders a
skeleton with the endpoint withheld and lets the projector fill it in; path A renders the same
contract with the endpoint present. What is compared is not the generated text — the two
emitters legitimately differ in naming and ordering — but the two decisions that carried every
one of these defects: does the handler take an actor, and does it filter to that actor's rows.
"""
from __future__ import annotations

import re
import shutil
import sys
import unittest
from pathlib import Path
from tempfile import mkdtemp

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_skeleton import write_backend_skeleton  # noqa: E402
from multi_agent.runtime.route_projector import project_missing_routes  # noqa: E402

_PRIVATE = {
    "my_list": {"schema": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "user_id", "type": "integer", "references": "users.id"},
        {"name": "title_id", "type": "integer", "references": "titles.id"}]},
        "metadata": {"owner_scoped_reads": True}},
    "titles": {"schema": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "name", "type": "text"}]}},
}


def _decisions(main_src: str, path: str):
    """(takes an actor, filters to that actor) for the handler serving ``path``."""
    m = re.search(r'@(?:app|router)\.get\("%s"\)\s*\ndef \w+\(([^\n]*)\):\n(.*?)(?=\n@|\Z)'
                  % re.escape(path), main_src, re.S)
    if not m:
        return None
    sig, body = m.group(1), m.group(2)[:900]
    return ("get_current_user" in sig, "_fw_owner_val(" in body)


class _Rendered:
    """The same contract, through each emitter."""

    def __init__(self, ep, tables, scoped):
        self.a = Path(mkdtemp(prefix="emitA_"))
        self.b = Path(mkdtemp(prefix="emitB_"))
        write_backend_skeleton(self.a, [ep], tables)                 # A: skeleton renders it
        write_backend_skeleton(self.b, [], tables)                   # B: withheld …
        project_missing_routes(self.b / "app" / "backend", [ep],     # … projector fills it in
                               owner_scoped_tables=scoped)

    def read(self, path):
        return (_decisions((self.a / "app" / "backend" / "main.py").read_text(), path),
                _decisions((self.b / "app" / "backend" / "main.py").read_text(), path))

    def close(self):
        shutil.rmtree(self.a, ignore_errors=True)
        shutil.rmtree(self.b, ignore_errors=True)


class BothEmittersMakeTheSameDecision(unittest.TestCase):

    def _check(self, ep, tables=None, scoped=("my_list",), expect=None):
        r = _Rendered(ep, tables or _PRIVATE, set(scoped))
        try:
            a, b = r.read(ep["path"])
            self.assertIsNotNone(a, "skeleton did not project the endpoint")
            self.assertIsNotNone(b, "route_projector did not project the endpoint")
            self.assertEqual(a, b, f"emitters disagree on {ep['path']}: skeleton={a} projector={b}")
            if expect is not None:
                self.assertEqual(a, expect)
        finally:
            r.close()

    def test_1098s_case_a_private_table_the_contract_calls_public(self):
        """#633 says private, the contract says public. Neither emitter may publish it."""
        self._check({"method": "GET", "path": "/api/my-list", "auth_required": False},
                    expect=(True, True))

    def test_1097s_case_an_explicitly_public_read_on_a_scoped_table(self):
        self._check({"method": "GET", "path": "/api/titles", "auth_required": False},
                    expect=(False, False))

    def test_an_unstated_read_on_a_scoped_table(self):
        self._check({"method": "GET", "path": "/api/my-list"})

    def test_a_plain_read_on_an_unscoped_table(self):
        self._check({"method": "GET", "path": "/api/titles"}, scoped=())


if __name__ == "__main__":
    unittest.main()
