r"""#1203fn: the read-only-table blocker told the lane about netflix's columns.

`completeness_state_entity_no_write` hard-blocks delivery, and this is the whole paragraph the
backend lane receives (r106's task_7acf88068b, verbatim):

    The `completeness_state_entity_no_write` delivery-gate check FAILED.
    a state-bearing table (it has mutable columns like progress_seconds / status / value) has
    a GET but NO POST/PUT/PATCH — the feature can be READ and never WRITTEN ...

It names no table. `progress_seconds / status / value` are netflix Continue-Watching columns,
so in a tiktok run they point at nothing. 26 tasks across 26 corpus runs carry that text and
name no entity; the owning agent is told a table exists and sent to find it. The urgent message
that accompanies it says "Re-read the task body (it names the failing instance)" -- which for
this check was not true.

The instance is computed twice over before the dispatch. `check_state_entity_no_write` builds a
per-entity `detail` AND a `suggested_fix`, and the gate publishes both under its `completeness`
key. r160, live at 10:28:53:

    {"check_id": "completeness_state_entity_no_write", "entity": "creators",
     "missing_verb": "POST/PUT/PATCH",
     "detail": "state-bearing table `creators` (mutable column(s): verified,
      followers_count, following_count, likes_count) has a GET but NO POST/PUT..."}

and `blocker_prose` for that gate record is EMPTY, so nothing carried it across.

This is #798/#799/#982's own fix applied to the row they left out -- each of those added a
`_extra` helper to this same table for the same reason -- and it is #1203fg's division again: a
constant paragraph standing where a computed fact belongs.

LOCAL-ONLY (agent/tests/ gitignored).
"""
from __future__ import annotations

import ast
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime import remediation_dispatcher as RD  # noqa: E402

SRC = LLM_DIR / "multi_agent" / "runtime" / "remediation_dispatcher.py"

# r160's own `creators` record, trimmed to the columns the classifier reads.
CREATORS = {
    "id": "creators", "name": "creators", "status": "implemented", "provider": "backend",
    "schema": {"columns": [
        {"name": "id", "type": "integer primary key", "primary_key": True},
        {"name": "user_id", "type": "integer references users.id", "references": "users(id)"},
        {"name": "username", "type": "string unique", "unique": True},
        {"name": "display_name", "type": "string"},
        {"name": "avatar_url", "type": "string"},
        {"name": "bio", "type": "text"},
        {"name": "verified", "type": "boolean"},
        {"name": "followers_count", "type": "integer"},
        {"name": "following_count", "type": "integer"},
        {"name": "likes_count", "type": "integer"},
    ]},
}
GET_ONLY = {"GET /api/creators": {"method": "GET", "path": "/api/creators",
                                  "status": "implemented"}}
WITH_WRITE = dict(GET_ONLY)
WITH_WRITE["POST /api/creators"] = {"method": "POST", "path": "/api/creators",
                                    "status": "implemented"}


def _orch(tables, endpoints, *, boom=None):
    class _RH:
        def get_endpoints(self):
            if boom == "endpoints":
                raise RuntimeError("hub down")
            return endpoints

    class _SH:
        def list_tables(self):
            if boom == "tables":
                raise RuntimeError("hub down")
            return tables
    return types.SimpleNamespace(
        hubs=types.SimpleNamespace(registryhub=_RH(), schema_hub=_SH()))


class TheTableIsNamed(unittest.TestCase):
    def test_it_names_the_entity_and_its_real_mutable_columns(self):
        out = RD._state_entities_missing_write_1203fn(_orch({"creators": CREATORS}, GET_ONLY))
        self.assertEqual(len(out), 1, out)
        line = out[0]
        self.assertIn("`creators`", line)
        for col in ("verified", "followers_count", "following_count", "likes_count"):
            self.assertIn(col, line, line)
        # and NOT the other domain's example columns
        for foreign in ("progress_seconds", "value"):
            self.assertNotIn(foreign, line)

    def test_a_table_that_already_has_a_write_is_not_named(self):
        """Negative control: the remediation must not name a table whose write exists, or the
        lane is sent to add an endpoint that is already there."""
        out = RD._state_entities_missing_write_1203fn(_orch({"creators": CREATORS}, WITH_WRITE))
        self.assertEqual(out, [])

    def test_no_tables_means_nothing_to_say(self):
        self.assertEqual(RD._state_entities_missing_write_1203fn(_orch({}, {})), [])

    def test_a_hub_fault_degrades_to_todays_generic_text(self):
        """[] means the lane gets the paragraph it got before this existed -- never an
        exception, which would take the whole dispatch with it."""
        for boom in ("tables", "endpoints"):
            self.assertEqual(
                RD._state_entities_missing_write_1203fn(
                    _orch({"creators": CREATORS}, GET_ONLY, boom=boom)), [], boom)
        self.assertEqual(RD._state_entities_missing_write_1203fn(None), [])
        self.assertEqual(RD._state_entities_missing_write_1203fn(
            types.SimpleNamespace()), [])

    def test_the_list_is_capped(self):
        """#1034's sibling rule at the other end: a P0 body is read by an agent with a context
        budget, so the list is bounded.

        Each table needs its OWN GET: `state_entities_missing_write` flags
        readable-but-not-writable, so a fixture with no endpoints produces zero entities and
        this assertion passes against anything. The first version did exactly that and the
        cap-removal mutation stayed green -- an empty counter-example, not a cap."""
        tables = {}
        endpoints = {}
        for i in range(9):
            t = dict(CREATORS)
            t["name"] = t["id"] = f"creators{i}"
            tables[f"creators{i}"] = t
            endpoints[f"GET /api/creators{i}"] = {
                "method": "GET", "path": f"/api/creators{i}", "status": "implemented"}
        # the fixture itself must be non-vacuous: more entities than the cap
        from multi_agent.runtime.completeness_audit import state_entities_missing_write
        self.assertGreater(len(state_entities_missing_write(tables, endpoints)), 6)
        out = RD._state_entities_missing_write_1203fn(_orch(tables, endpoints))
        self.assertEqual(len(out), 6, len(out))

    def test_it_uses_the_shipped_classifier_not_a_second_copy(self):
        """#1032/#906: the names the lane is given must be produced by the same function that
        blocked it, or the two can disagree and the lane chases a table the gate never flagged."""
        src = SRC.read_text(encoding="utf-8")
        i = src.find("def _state_entities_missing_write_1203fn")
        self.assertGreater(i, 0)
        body = src[i:src.find("\ndef ", i + 10)]
        self.assertIn("from .completeness_audit import state_entities_missing_write", body)


class TheDispatchCarriesIt(unittest.TestCase):
    def _fn(self):
        tree = ast.parse(SRC.read_text(encoding="utf-8"))
        best = None
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            calls = [n for n in ast.walk(node)
                     if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                     and n.func.id == "_state_entities_missing_write_1203fn"]
            if calls and (best is None or node.end_lineno - node.lineno
                          < best.end_lineno - best.lineno):
                best = node
        self.assertIsNotNone(best, "nothing calls the helper")
        return best

    def test_the_branch_is_keyed_on_this_check_name(self):
        fn = self._fn()
        calls = [n for n in ast.walk(fn)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == "_state_entities_missing_write_1203fn"]
        guards = [n for n in ast.walk(fn) if isinstance(n, ast.If)
                  and any(c is calls[0] for c in ast.walk(n))]
        self.assertTrue(guards)
        tests = " | ".join(ast.dump(g.test) for g in guards)
        self.assertIn("completeness_state_entity_no_write", tests)

    def test_it_feeds_both_the_body_and_the_instance_list(self):
        """`_extra` is what the lane READS; `_inst` is what the title names (#1202ss). A fix
        that set only one of them would leave half the dispatch generic."""
        fn = self._fn()
        assigned = {t.id for n in ast.walk(fn) if isinstance(n, ast.Assign)
                    for t in n.targets if isinstance(t, ast.Name)}
        self.assertIn("_extra", assigned)
        self.assertIn("_inst", assigned)
        # both must be fed from THIS helper's result, not from something else in the chain
        src = SRC.read_text(encoding="utf-8")
        i = src.find("_sew1203fn = _state_entities_missing_write_1203fn(orch)")
        self.assertGreater(i, 0, "the helper's result is not bound in the dispatch")
        window = src[i:src.find("\n                elif ", i) if src.find(
            "\n                elif ", i) > 0 else i + 600]
        self.assertIn("_inst = list(_sew1203fn)", window)
        self.assertIn("_extra", window)
        self.assertIn("_sew1203fn)", window)


if __name__ == "__main__":
    unittest.main()
