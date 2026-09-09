"""#1202hu — the lane was told to clear a flag that a merge-upsert cannot clear.

tiktok-web-r106 spent its whole budget oscillating on one table. The framework told it, twice
over and correctly, that `videos` is published content and must not be `owner_scoped_reads`.
The lane re-registered the table repeatedly — `_updated_by=backend` at 19:18:24, 19:21:00 —
and the flag stayed `True` every time.

`register_table` merges: `{**existing.metadata, **new_metadata}`. Re-registering a table
WITHOUT the key therefore preserves the old value. Proven against a real HubRegistry below.
So "make it not owner_scoped_reads", executed the obvious way, is a no-op that reports
success: the record's timestamp moves, the value does not. The neighbouring `comments` table
looks clean only because nothing ever set it.

The flag is one-way by construction — settable, not clearable — unless the caller knows to
pass `False` explicitly. Neither lane-facing message said so, so both now do: the unscoped-read
finding (#1202hq's clause) and the public-content task body (#1202hf's). Grepped for every
place that instructs a lane about this flag before writing, because a single corrected emitter
is what #1202hq itself got wrong.

Diagnosing it took reversing my own conclusion twice: first "the lane cannot converge", then
"the message never reached it". The lane had the right instruction and was following it — the
instruction was not executable as written.
"""
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class TheMergeSemantics(unittest.TestCase):
    """The fact the messages have to describe. Asserted against the real hub, so a future
    change to `register_table` makes this fail rather than making the advice silently wrong."""

    def test_omitting_the_key_preserves_the_old_value(self):
        """#1202io note: the second registration used to pass `visibility="public"` as its
        "some other field" — which is now the one value that does NOT merge inertly, because
        `public` and `owner_scoped_reads` are direct opposites and the write boundary refuses
        to store both (r109: the lane wrote the pair and the audit reported seven phantom
        leaks against a projector that had correctly stopped filtering).

        The merge semantics this test guards are unchanged — omitting a key still preserves
        it — so the fixture moves to a field that carries no verdict about row visibility.
        `#1202hu`'s advice ("pass owner_scoped_reads=False EXPLICITLY") also stands: it is
        still the only way to clear the flag on a table the materials say nothing about.
        """
        from multi_agent.runtime.hub_registry import HubRegistry
        with tempfile.TemporaryDirectory() as d:
            sh = HubRegistry(Path(d)).schema_hub
            sh.register_table(name="videos", schema={"columns": [{"name": "id"}]},
                              provider="backend", agent="backend", owner_scoped_reads=True)
            sh.register_table(name="videos", schema={"columns": [{"name": "id"}]},
                              provider="backend", agent="backend", note="unrelated")
            md = (sh.get_table("videos") or {}).get("metadata") or {}
            self.assertIs(md.get("owner_scoped_reads"), True,
                          "if this ever stops merging, the advice below must change too")

    def test_a_materials_public_verdict_is_the_one_field_that_does_clear_it(self):
        """#1202io: the contradiction is refused where it is written, so the lane no longer
        has to win a fight it kept re-losing (r107: cleared six times, restored each time)."""
        from multi_agent.runtime.hub_registry import HubRegistry
        with tempfile.TemporaryDirectory() as d:
            sh = HubRegistry(Path(d)).schema_hub
            sh.register_table(name="videos", schema={"columns": [{"name": "id"}]},
                              provider="backend", agent="backend", owner_scoped_reads=True)
            sh.register_table(name="videos", schema={"columns": [{"name": "id"}]},
                              provider="backend", agent="backend", visibility="public")
            md = (sh.get_table("videos") or {}).get("metadata") or {}
            self.assertIs(md.get("owner_scoped_reads"), False)

    def test_an_explicit_false_is_what_clears_it(self):
        from multi_agent.runtime.hub_registry import HubRegistry
        with tempfile.TemporaryDirectory() as d:
            sh = HubRegistry(Path(d)).schema_hub
            sh.register_table(name="videos", schema={"columns": [{"name": "id"}]},
                              provider="backend", agent="backend", owner_scoped_reads=True)
            sh.register_table(name="videos", schema={"columns": [{"name": "id"}]},
                              provider="backend", agent="backend", owner_scoped_reads=False)
            md = (sh.get_table("videos") or {}).get("metadata") or {}
            self.assertIs(md.get("owner_scoped_reads"), False)


def _finding_clause():
    import inspect
    from multi_agent.runtime import backend_audit
    src = inspect.getsource(backend_audit.unscoped_owner_read_findings)
    return src[src.index("returns every row of"):src.index("except Exception as _e1202af")]


def _task_body():
    import inspect
    from multi_agent.runtime import scaffolder
    return inspect.getsource(scaffolder._public_content_task_body_1202hf)


class BothMessagesSayHowToActuallyDoIt(unittest.TestCase):
    def test_the_unscoped_read_finding_does(self):
        c = _finding_clause()
        self.assertIn("owner_scoped_reads=False", c,
                      "the finding says to clear the flag but not how:\n" + c[-600:])

    def test_the_public_content_task_does(self):
        b = _task_body()
        self.assertIn("owner_scoped_reads=False", b,
                      "the task says to clear the flag but not how:\n" + b[-600:])

    def test_both_explain_why_omitting_it_is_not_enough(self):
        """Without the reason, "pass False" reads as a style note and gets dropped."""
        for text in (_finding_clause(), _task_body()):
            low = text.lower()
            self.assertTrue("merge" in low or "merges" in low,
                            "nothing says re-registering without the key keeps the old value")


if __name__ == "__main__":
    unittest.main()
