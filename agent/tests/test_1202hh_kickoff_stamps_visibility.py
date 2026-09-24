"""#1202hh (producer half) — the declaration has to be ON THE TABLE RECORD.

The projector-side exemption is worth nothing if the fact never reaches the ledger. In r103
the reference spec declared `videos`/`comments` public, and the registered table metadata
carried exactly one key: `owner_scoped_reads`. Every downstream reader was therefore blind,
and `backend_audit` was the only component that ever knew — because it re-opens the spec
file itself.

`try_synthesize` ALREADY reads `entities[].visibility` (#1202ha, to keep the read-visibility
backstop off published tables). It computes the set, uses it for the roadmap, and drops it.
So this stamps the same fact onto the table record at registration, from the same reader.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "env_generator" / "llm_generator"), str(Path(__file__).resolve().parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_kickoff_run_kickoff import ATTENDEES, _all_clean_decisions, _mock_hubs

from multi_agent.runtime.kickoff.run_kickoff import finalize_kickoff, try_synthesize


def _register_calls(entities):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "shared").mkdir(parents=True)
        (root / "design").mkdir(parents=True)
        (root / "design" / "reference_spec.json").write_text(
            json.dumps({"entities": entities}), encoding="utf-8")
        hubs = _mock_hubs(decisions=_all_clean_decisions())
        hubs.base_dir = str(root)          # production: HubRegistry(output_dir).base_dir IS the run root
        handle = {"meeting_id": "page_meeting_1", "milestone_index": 1,
                  "expected_attendees": ATTENDEES}
        synthesis = try_synthesize(hubs, handle)
        assert synthesis["status"] == "ready", synthesis
        finalize_kickoff(hubs, handle, synthesis)
        return {c.kwargs.get("name"): c.kwargs
                for c in hubs.schema_hub.register_table.call_args_list}


class KickoffStampsVisibility(unittest.TestCase):
    def test_declared_entity_is_stamped(self):
        calls = _register_calls([{"name": "posts", "visibility": "public"}])
        self.assertIn("posts", calls, calls)
        self.assertEqual(calls["posts"].get("visibility"), "public", calls["posts"])

    def test_owner_declaration_is_carried_verbatim(self):
        """Not just the public verdict — the audit and #1202hh both key off the WORD, and a
        table stamped `owner` is the evidence that the spec was read at all."""
        calls = _register_calls([{"name": "posts", "visibility": "owner"}])
        self.assertEqual(calls["posts"].get("visibility"), "owner", calls["posts"])

    def test_undeclared_entity_is_not_stamped(self):
        """Corpus specs carry no `visibility`; those runs must register exactly as before."""
        calls = _register_calls([{"name": "posts"}])
        self.assertNotIn("visibility", calls["posts"], calls["posts"])

    def test_missing_spec_registers_as_before(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "shared").mkdir(parents=True)
            hubs = _mock_hubs(decisions=_all_clean_decisions())
            hubs.base_dir = str(root)          # production: HubRegistry(output_dir).base_dir IS the run root
            handle = {"meeting_id": "page_meeting_1", "milestone_index": 1,
                      "expected_attendees": ATTENDEES}
            synthesis = try_synthesize(hubs, handle)
            finalize_kickoff(hubs, handle, synthesis)
            kw = hubs.schema_hub.register_table.call_args_list[0].kwargs
            self.assertNotIn("visibility", kw, kw)


if __name__ == "__main__":
    unittest.main()


class TheContractTheReadersDependOn(unittest.TestCase):
    def test_hub_registry_base_dir_is_the_run_root(self):
        """The readers resolve `<base_dir>/design/reference_spec.json`. #1202ha's comment said
        `hubs.base_dir` is `<project>/shared` and the first draft of #1202hh/#1202hk copied
        that, so both stamps resolved `generated/design/...` and silently found nothing — on
        a live run (tiktok-web-r104) the registered `users` had 6 columns and no table carried
        `visibility`, while the spec on disk had all 11 fields and 8 declarations. The unit
        tests passed throughout because they hand-built `base_dir` as `<tmp>/shared`, a shape
        production never produces. This pins the real contract instead.
        """
        import tempfile
        from multi_agent.runtime.hub_registry import HubRegistry
        with tempfile.TemporaryDirectory() as t:
            reg = HubRegistry(Path(t))
            self.assertEqual(Path(str(reg.base_dir)).resolve(), Path(t).resolve())
