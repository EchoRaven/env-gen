r"""#1203ol: a file path is not an agent, and one got an inbox.

r171 registered 14 endpoints with `provider: "app/backend/custom_routes.py"` — the backend lane
passed its FILE where the agent id goes — and registryhub emits to the provider. The result is
an inbox keyed `app/backend/custom_routes.py` holding 108 events (task_created 40,
bug_state_changed 38, endpoint_schema_changed 30), 93 of them `high` and 15 `urgent`, and EVERY
one carries `delivered: false, read: false`. No agent answers to that name.

MEASURED: 1 of 104 runs, and 14 of 3,442 endpoint registrations carry a path-shaped provider —
rare, with total harm per occurrence. The same field confusion is #1203oj's defect one hub over
(a consumer record whose `agent` held a frontend file), so it is a shape the lanes reach for.

★ ONLY THE PATH-SHAPED CASE, and the wider measurement is why. "Inboxes whose key never acted
as an agent in that run" gives 10,628 events across 82 runs — but that instrument is
confounded: the top names are `design_analyst_1` (1825), `knowledge` (1439) and the browser
test-users, which ARE real agents that simply never create a task or write a comment, and
10,525 of those events are `normal`. A path cannot be an agent; that is the whole guard.

★ AND THE FIRST DRAFT'S ANNOUNCEMENT WAS DEAD. `eventhub.py` has no module-level
`message_format` import, so the bare `warn_once_1201(...)` would have raised NameError straight
into the `except Exception: pass` beside it — the trap this session has paid for three times.
That is why `test_it_announces_the_drop` asserts the announcement FIRES rather than only that
the recipient disappeared.
"""
import unittest

from env_generator.llm_generator.multi_agent.runtime import eventhub as EH
from env_generator.llm_generator.multi_agent.runtime.eventhub import (
    _looks_like_a_path_1203ol as looks_like_path,
)


class APathIsRecognised(unittest.TestCase):
    def test_r171s_own_value(self):
        self.assertTrue(looks_like_path("app/backend/custom_routes.py"))

    def test_a_bare_source_filename(self):
        for p in ("custom_routes.py", "api.js", "App.jsx", "models.PY", "conf.yaml"):
            with self.subTest(path=p):
                self.assertTrue(looks_like_path(p))

    def test_a_windows_separator(self):
        self.assertTrue(looks_like_path(r"app\backend\custom_routes.py"))

    def test_a_separator_alone_is_enough(self):
        """★ r171's value has BOTH a separator and a `.py`, so the extension branch covered
        for the separator branch and mutation OL5 read MISSED. A directory-shaped recipient
        has no extension to fall back on."""
        for p in ("app/frontend/src", "app/backend/", "src/components", r"app\backend"):
            with self.subTest(path=p):
                self.assertTrue(looks_like_path(p))

    def test_every_agent_id_shape_in_the_corpus_is_left_alone(self):
        """The 29-agent inbox set: core lanes, squad ids, the analyst."""
        for a in ("backend", "frontend", "verifier", "orchestrator", "debugger", "knowledge",
                  "design_analyst_1", "api_test_user_1_api_smoke",
                  "browser_test_user_7_page_live_discover_page",
                  "mcp_test_user_2_mcp_surface", "orchestrator-monitor", "oauth"):
            with self.subTest(agent=a):
                self.assertFalse(looks_like_path(a))

    def test_hostile_input_never_raises(self):
        for r in (None, "", 7, object()):
            with self.subTest(r=repr(r)[:16]):
                self.assertFalse(looks_like_path(r))


class _Hub(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self._tmp = tempfile.TemporaryDirectory()
        try:
            self.hub = EH.EventHub(hub_dir=Path(self._tmp.name))
        except TypeError:
            self.hub = EH.EventHub(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def _publish(self, recipients):
        return self.hub.publish_event(
            source_hub="registryhub", event_type="endpoint_schema_changed",
            payload={"id": "POST /api/videos/{}/like"}, recipients=list(recipients),
            priority="urgent", caller="registryhub")

    def _inbox_keys(self):
        return {k for k in (self.hub._inboxes.value() or {})
                if k != "_meta" and not str(k).startswith(("version", "last_"))}


class TheFileNeverGetsAnInbox(_Hub):
    def test_the_path_recipient_is_dropped(self):
        ev = self._publish(["backend", "app/backend/custom_routes.py"])
        self.assertEqual(ev.get("recipients"), ["backend"], ev)

    def test_no_inbox_is_created_for_it(self):
        self._publish(["backend", "app/backend/custom_routes.py"])
        self.assertNotIn("app/backend/custom_routes.py", self._inbox_keys())

    def test_the_real_recipients_are_unaffected(self):
        """A dropped path must not cost the event its legitimate readers."""
        ev = self._publish(["backend", "frontend", "app/backend/custom_routes.py"])
        self.assertEqual(ev.get("recipients"), ["backend", "frontend"], ev)
        self.assertTrue({"backend", "frontend"} <= self._inbox_keys())

    def test_an_all_path_recipient_list_still_publishes(self):
        """The event is recorded even when nobody can receive it -- dropping the recipient is
        not the same as refusing the publish."""
        ev = self._publish(["app/backend/custom_routes.py"])
        self.assertEqual(ev.get("recipients"), [])
        self.assertTrue(ev.get("event_id") or ev.get("id"), ev)

    def test_it_announces_the_drop(self):
        """★ #883 and the dead-import trap: the drop must be SAID, and the announcement has to
        actually fire -- `eventhub.py` has no module-level `message_format` import, so a bare
        call would have raised NameError into the `except` beside it."""
        import env_generator.llm_generator.multi_agent.runtime.message_format as MF
        said = []
        orig = MF.warn_once_1201
        MF.warn_once_1201 = lambda *a, **k: said.append(a)
        try:
            self._publish(["backend", "app/backend/custom_routes.py"])
        finally:
            MF.warn_once_1201 = orig
        self.assertTrue(said, "the recipient was dropped in silence")
        joined = " ".join(str(x) for x in said[0])
        self.assertIn("#1203ol", joined)
        self.assertIn("app/backend/custom_routes.py", joined)

    def test_a_clean_publish_says_nothing(self):
        import env_generator.llm_generator.multi_agent.runtime.message_format as MF
        said = []
        orig = MF.warn_once_1201
        MF.warn_once_1201 = lambda *a, **k: said.append(a)
        try:
            self._publish(["backend", "frontend"])
        finally:
            MF.warn_once_1201 = orig
        self.assertEqual(said, [])


class WhatTheCorpusSays(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        cls.corpus = Path(__file__).resolve().parents[2] / "generated"
        if not cls.corpus.is_dir():
            raise unittest.SkipTest("no generated/ corpus on this machine")

    def test_r171_is_the_measured_case(self):
        import json
        f = self.corpus / "tiktok-web-r171" / "shared" / "hubs" / "eventhub_inboxes.json"
        if not f.is_file():
            self.skipTest("r171 has no inbox store on this disk")
        d = json.load(open(f, errors="ignore"))
        box = d.get("app/backend/custom_routes.py")
        self.assertIsNotNone(box, "r171's dead letterbox is gone; re-measure this ticket")
        items = (box or {}).get("items") or {}
        self.assertEqual(len(items), 108)
        self.assertTrue(all(not e.get("delivered") for e in items.values()
                            if isinstance(e, dict)),
                        "something in the dead letterbox was delivered after all")

    def test_no_other_run_has_a_path_keyed_inbox(self):
        """Scope, as an assertion: if a second run appears, the guard's 1-run evidence has
        grown and the comment should say so."""
        import json
        hits = []
        for f in sorted(self.corpus.glob("*/shared/hubs/eventhub_inboxes.json")):
            try:
                d = json.load(open(f, errors="ignore"))
            except Exception:
                continue
            for k in d:
                if k == "_meta" or str(k).startswith(("version", "last_")):
                    continue
                if looks_like_path(k):
                    hits.append((f.parts[-4], str(k)))
        self.assertEqual([h[0] for h in hits], ["tiktok-web-r171"], hits)


if __name__ == "__main__":
    unittest.main()
