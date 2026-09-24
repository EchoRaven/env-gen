"""#1202hq — #1202hm moved the exemption's switch and left the sentence that explains it.

tiktok-web-r106, live. The gate reported `unscoped owner read: GET /api/videos returns every
row of `videos` to ANY caller`, and the message it carried said:

    "publicness is decided in the CONTRACT (`auth_required=false`), and #1202gd's audit then
     exempts a public read the materials and the contract agree on"

That was true until #1202hm, which moved the corroborating signal off the endpoint's login
flag and onto the TABLE's `owner_scoped_reads` — precisely because the login flag answers a
different question. The sentence survived the change, so the framework was telling the lane
to operate a switch that no longer controls the outcome.

The lane did what it was told, twice: it made the read anonymous (the finding's wording
changed from "any authenticated caller" to "ANY caller"), the blocker stayed, and at 17:59:49
it set `owner_scoped_reads: True` on `videos` — which is the one action that re-imposes the
owner filter and empties the feed. #1202hf documents this exact conflation from the other
side; the message that should have prevented it was the one causing it.

So both halves are stated here: `auth_required` is "must you log in", `owner_scoped_reads` is
"do you see other people's rows", and for published rows the second must NOT be set.
"""
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _message_source():
    """The clause the lane reads, taken from the builder itself.

    Asserted on the source rather than on a driven finding: reproducing r106's exact shape
    needs an owner-scoped table whose read is nonetheless projected unfiltered, which is the
    contradictory state the lane put it in (`auth_required: false` + `owner_scoped_reads:
    true`) and not something the producers emit on their own — a hand-built stand-in for it
    produced no finding at all, which would have made every assertion here vacuous. The real
    r106 artifacts were used to confirm the rendered text; this pins it against regression.
    """
    import inspect
    from multi_agent.runtime import backend_audit
    src = inspect.getsource(backend_audit.unscoped_owner_read_findings)
    # LANDMARK anchors, not a byte window (#943): the first cut took `at + 3000` and cut the
    # clause in half, so two of these assertions failed against a message that already said
    # what they were checking for.
    return src[src.index("returns every row of"):src.index("except Exception as _e1202af")]


class TheUnscopedReadMessage(unittest.TestCase):
    def test_it_names_the_switch_that_actually_governs_row_visibility(self):
        msg = _message_source()
        self.assertIn("owner_scoped_reads", msg,
                      "the message never names the flag the exemption reads")

    def test_it_no_longer_claims_the_login_flag_decides_publicness(self):
        msg = _message_source()
        self.assertNotIn("`auth_required` is where it is decided", msg)
        self.assertNotIn("publicness is decided in the CONTRACT (`auth_required=false`)", msg)

    def test_it_separates_the_two_questions(self):
        """#1202hf's distinction, in the message that had been teaching the conflation."""
        msg = _message_source()
        self.assertIn("auth_required", msg)
        self.assertIn("log in", msg)
        self.assertIn("other people's rows", msg)

    def test_the_two_halves_of_one_message_point_at_the_same_switch(self):
        """The first correction left the other half of the SAME sentence naming
        `auth_required`, so one message pointed at two different switches two clauses apart."""
        msg = _message_source()
        self.assertEqual(msg.count("`auth_required` is where it is decided"), 0)


class TheAuthWedgeNote(unittest.TestCase):
    def test_its_exemption_promise_states_the_real_condition(self):
        """The wedge note tells a lane to set `auth_required=false` — correct, that IS the
        login question — and promises the unscoped-read audit will not then bite. After
        #1202hm that promise holds only while the table is not owner-scoped, so it has to
        say so or it becomes the next stale reassurance."""
        import inspect
        from multi_agent.runtime import deliverability as d
        src = inspect.getsource(d)
        at = src.index("_pub1202gl = (")
        # Landmark, not a byte count (#943) — the same mistake this file already made once
        # above, and a comment growing inside the clause is exactly what would break it.
        clause = src[at:src.index("def _flow_coverage_summary", at)]
        self.assertIn("owner_scoped_reads", clause,
                      "the promise still omits the condition it now depends on")


if __name__ == "__main__":
    unittest.main()
