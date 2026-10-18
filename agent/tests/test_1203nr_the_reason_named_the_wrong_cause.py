r"""#1203nr: "tried services database/db/postgres" blamed name resolution ~2,111 times.

When the seed audit cannot reach the database it falls back to a status filter that examines
0 tables in 145 of 147 runs, and `_not_measured_1039` exists so that degradation is not
silent. Its dominant reason read

    no database container resolved from <compose> (tried services database/db/postgres)

and that sentence is wrong twice over:

  * IT BLAMES NAME RESOLUTION. MEASURED over the corpus's 104 compose files that declare a
    postgres-image service, the service is called `database` in **104 of 104** -- always a
    name this resolver probes. So the real situation in every corpus case is "the service IS
    declared and docker returned no container", i.e. the stack is down at that moment, which
    `_not_measured_1039`'s own comment already describes and which is a TIMING state.
  * IT IS STALE WITH RESPECT TO ITS OWN CODE. `#1202x` narrowed the probe to the services the
    file DECLARES, precisely so the other two names stop being tried. The sentence kept
    advertising the blind sweep #1202x removed.

AND THE COST IS MEASURABLE, because I paid it: reading that line while mining, I went and
measured compose service names across the whole corpus looking for one outside the three.
There is none. That is #883's family arriving sideways -- not an empty default read as clean,
but a stated cause read as the cause.

Corpus-wide the line appears ~2,111 times in 38 runs (netflix-r37 241, googlemaps-r16 171,
netflix-r41 168, and 17 in r190, the newest long run).

★ THE UNIT TEST CAUGHT A DEAD BRANCH IN MY OWN FIX. The first draft had `if not _probed` for
"the file declares no database service", and the `or [...]` fallback below refills that list,
so the branch could never fire and a no-database compose file got the stack-is-down sentence.
The flag is now computed from the DECLARED set instead.
"""
import inspect
import tempfile
import unittest
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime import container_runtime as CR
from env_generator.llm_generator.multi_agent.runtime import seed_audit as SA

# 104 of 104 real compose files carry a header line before `services:`; a synthetic file that
# starts with `services:` exercises a parser path the corpus does not have (#647).
_PG = ("version: '3.8'\nservices:\n  database:\n    image: postgres:16\n"
       "  api:\n    image: node:20\n")
_NO_DB = ("version: '3.8'\nservices:\n  api:\n    image: node:20\n"
          "  cache:\n    image: redis:7\n")


def _compose(text):
    d = tempfile.mkdtemp()
    p = Path(d) / "docker-compose.yml"
    p.write_text(text, encoding="utf-8")
    return p


class _Patched(unittest.TestCase):
    def setUp(self):
        self._real = CR.container_id

    def tearDown(self):
        CR.container_id = self._real


class TheStackBeingDownSaysSo(_Patched):
    """The corpus's actual case: `database` declared, docker returns nothing."""

    def setUp(self):
        super().setUp()
        CR.container_id = lambda *a, **k: ""

    def test_it_says_the_service_IS_declared(self):
        why = SA._db_container_why_1203nr(_compose(_PG), 5)[1]
        self.assertIn("IS declared", why)

    def test_it_names_the_cause_as_a_timing_state(self):
        why = SA._db_container_why_1203nr(_compose(_PG), 5)[1]
        self.assertIn("stack is", why)
        self.assertIn("DOWN", why)
        self.assertIn("timing state", why)

    def test_it_no_longer_blames_name_resolution(self):
        why = SA._db_container_why_1203nr(_compose(_PG), 5)[1]
        self.assertNotIn("tried services", why)

    def test_it_names_only_the_service_the_file_declares(self):
        """#1202x narrowed the probe; the sentence has to narrow with it."""
        why = SA._db_container_why_1203nr(_compose(_PG), 5)[1]
        self.assertIn("database", why)
        self.assertNotIn("database/db/postgres", why)


class AComposeWithNoDatabaseServiceIsItsOwnCase(_Patched):
    """The branch that was DEAD in the first draft."""

    def setUp(self):
        super().setUp()
        CR.container_id = lambda *a, **k: ""

    def test_it_says_the_file_declares_none(self):
        why = SA._db_container_why_1203nr(_compose(_NO_DB), 5)[1]
        self.assertIn("declares NO database service", why)

    def test_it_lists_what_the_file_does_declare(self):
        why = SA._db_container_why_1203nr(_compose(_NO_DB), 5)[1]
        self.assertIn("api", why)
        self.assertIn("cache", why)

    def test_it_does_not_claim_the_stack_is_merely_down(self):
        """The two situations have different owners -- a missing service is a scaffolding
        question, a stopped stack is a re-read-later."""
        why = SA._db_container_why_1203nr(_compose(_NO_DB), 5)[1]
        self.assertNotIn("DOWN at this moment", why)

    def test_it_says_the_probed_names_were_a_fallback(self):
        why = SA._db_container_why_1203nr(_compose(_NO_DB), 5)[1]
        self.assertIn("fallback", why)


class AProbeThatRaisedIsItsOwnCase(_Patched):
    def test_it_reports_the_exception(self):
        def boom(*a, **k):
            raise RuntimeError("docker daemon unreachable")
        CR.container_id = boom
        why = SA._db_container_why_1203nr(_compose(_PG), 5)[1]
        self.assertIn("raised", why)
        self.assertIn("docker daemon unreachable", why)

    def test_it_does_not_claim_the_stack_is_down(self):
        def boom(*a, **k):
            raise RuntimeError("docker daemon unreachable")
        CR.container_id = boom
        self.assertNotIn("DOWN at this moment",
                         SA._db_container_why_1203nr(_compose(_PG), 5)[1])


class SuccessIsUnchanged(_Patched):
    def test_the_id_comes_back_with_no_reason(self):
        CR.container_id = lambda *a, **k: "abc123"
        cid, why = SA._db_container_why_1203nr(_compose(_PG), 5)
        self.assertEqual(cid, "abc123")
        self.assertEqual(why, "")

    def test_the_old_signature_still_returns_a_bare_id(self):
        """Four other callers read only the id, including verification_isolation."""
        CR.container_id = lambda *a, **k: "abc123"
        self.assertEqual(SA._db_container_1039(_compose(_PG), 5), "abc123")

    def test_the_old_signature_returns_a_string_on_failure(self):
        CR.container_id = lambda *a, **k: ""
        got = SA._db_container_1039(_compose(_PG), 5)
        self.assertEqual(got, "")
        self.assertIsInstance(got, str)


class TheCallerPrintsTheReason(unittest.TestCase):
    def test_the_stale_sentence_is_gone_from_the_emitted_string(self):
        """Read the emitted literals, not the source: this fix's own comment quotes the
        sentence it removed, so a source grep would be fed by the explanation."""
        import ast
        tree = ast.parse(inspect.getsource(SA))
        docs = set()
        for n in ast.walk(tree):
            b = getattr(n, "body", None)
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.ClassDef)) and b and isinstance(b[0], ast.Expr) \
                    and isinstance(b[0].value, ast.Constant):
                docs.add(id(b[0].value))
        emitted = [n.value for n in ast.walk(tree)
                   if isinstance(n, ast.Constant) and isinstance(n.value, str)
                   and id(n) not in docs]
        self.assertFalse([s for s in emitted if "tried services" in s],
                         "the stale cause is still emitted somewhere")
        self.assertTrue([s for s in emitted if "no database container from" in s],
                        "the caller no longer prints a reason at all")

    def test_the_source_still_quotes_the_old_sentence_in_a_comment(self):
        """Non-vacuity for the assertion above: if the explanation were gone, a source grep
        would pass for the wrong reason and the test would prove nothing."""
        self.assertIn("tried services database/db/postgres", inspect.getsource(SA))


class WhatTheCorpusSays(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = Path(__file__).resolve().parents[2] / "generated"
        if not cls.corpus.is_dir():
            raise unittest.SkipTest("no generated/ corpus on this machine")

    def test_every_compose_declares_a_probed_database_service(self):
        """The measurement the correction rests on: the name was never the problem."""
        import re
        bad, seen = [], 0
        for f in sorted(self.corpus.glob("*/docker/docker-compose.yml")):
            txt = f.read_text(encoding="utf-8", errors="ignore")
            if "services:" not in txt:
                continue
            body = txt.split("services:", 1)[1]
            cur, pg = None, []
            for line in body.splitlines():
                m = re.match(r"^  ([A-Za-z0-9_.-]+):\s*$", line)
                if m:
                    cur = m.group(1)
                    continue
                if cur and re.search(r"image:\s*\S*(postgres|pgvector|timescale)", line, re.I):
                    pg.append(cur)
            if not pg:
                continue
            seen += 1
            if not any(p in ("database", "db", "postgres") for p in pg):
                bad.append((f.parts[-3], pg))
        if not seen:
            self.skipTest("no compose file with a postgres service on this disk")
        self.assertEqual(bad, [], "a run names its database service outside the probed set, "
                                 "so the OLD sentence would have been right for it")

    def test_the_parser_reads_every_real_compose_file(self):
        """`_compose_services_1202x` returning {} means "do not narrow", which would put the
        three-name fallback back in play for real runs."""
        empty, seen = [], 0
        for f in sorted(self.corpus.glob("*/docker/docker-compose.yml")):
            seen += 1
            if not SA._compose_services_1202x(f):
                empty.append(f.parts[-3])
        if not seen:
            self.skipTest("no compose files on this disk")
        self.assertEqual(empty, [])


if __name__ == "__main__":
    unittest.main()
