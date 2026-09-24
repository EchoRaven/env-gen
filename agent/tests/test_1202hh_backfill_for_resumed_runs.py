"""#1202hh (backfill half) — a run whose ledger predates the stamp must still get the fact.

The producer half runs in `finalize_kickoff`. A RESUME skips kickoff entirely, so r103 --
the run that proved the defect -- would resume with a ledger carrying only
`owner_scoped_reads` and the whole fix would be inert for it. Every existing run on this
machine is in that state.

So the scaffolder backfills the in-memory table dict at skeleton-write time, exactly where it
already unions the probed `owner_scoped_reads` signals (a stamp on the local dict, no hub
write and no event). Backfill only: a ledger that already carries the declaration is left
alone, so the kickoff stamp stays authoritative.
"""
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.backend_skeleton import _apply_spec_visibility_1202hh


def _tables():
    return {
        "videos": {"name": "videos", "schema": {"columns": []},
                   "metadata": {"owner_scoped_reads": False}},
        "video_likes": {"name": "video_likes", "schema": {"columns": []},
                        "metadata": {"owner_scoped_reads": True}},
    }


class BackfillTests(unittest.TestCase):
    def _spec(self, tmp, entities):
        import json
        (tmp / "design").mkdir(parents=True, exist_ok=True)
        (tmp / "shared").mkdir(parents=True, exist_ok=True)
        (tmp / "design" / "reference_spec.json").write_text(
            json.dumps({"entities": entities}), encoding="utf-8")
        return tmp / "shared"

    def test_backfills_a_ledger_written_before_1202hh(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            shared = self._spec(Path(d), [{"name": "videos", "visibility": "public"},
                                          {"name": "video_likes", "visibility": "owner"}])
            tables = _tables()
            _apply_spec_visibility_1202hh(tables, shared.parent)
            self.assertEqual(tables["videos"]["metadata"]["visibility"], "public")
            self.assertEqual(tables["video_likes"]["metadata"]["visibility"], "owner")
            # the flag it must not disturb
            self.assertIs(tables["video_likes"]["metadata"]["owner_scoped_reads"], True)

    def test_existing_declaration_is_authoritative(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            shared = self._spec(Path(d), [{"name": "videos", "visibility": "owner"}])
            tables = _tables()
            tables["videos"]["metadata"]["visibility"] = "public"
            _apply_spec_visibility_1202hh(tables, shared.parent)
            self.assertEqual(tables["videos"]["metadata"]["visibility"], "public")

    def test_no_spec_leaves_the_dict_untouched(self):
        import copy
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "shared").mkdir(parents=True)
            tables = _tables()
            before = copy.deepcopy(tables)
            _apply_spec_visibility_1202hh(tables, Path(d) / "shared")
            self.assertEqual(tables, before)


if __name__ == "__main__":
    unittest.main()
