"""#1203hw: a bare `validation:<kind>` failure names its page in metadata, not in its name.

#1202fq's rule is "supersede by the PAGE, not by the spelling", and it rekeys a record via
`metadata.url`. #1203f9 canonicalises the flow segment of a three-part name. A record whose
NAME has no page segment at all defeats both: it keys as the bare `validation:<kind>`, a key
no per-page pass can ever match, so #757's retirement is unreachable for it.

r180, live and to the minute. `validation:ui_smoke` recorded FAILURE at 14:52:37:

    summary  "/friends route failed UI smoke because rendered avatar assets returned 404."
    metadata {"check": "ui_smoke", "route": "/friends"}
    no `url` anywhere on the record

The verifier walked /friends, found it clean, and recorded `validation:ui_smoke:/friends`
SUCCESS at 15:01:35. Two keys, so the pass retired nothing: the gate named /friends for
another eight evaluations over 18.5 minutes and dispatched a SECOND remediation, which
re-walked the same page and wrote "zero console/network errors" again. #757 names this
outcome exactly -- "that is not a gate, it is a latch".

The page was in hand the whole time: the labelling code already reads `metadata.route`,
which is how /friends reached `pages_failed` at all. The fact reached the label, not the key.

Reach, measured both ways. On disk, 9 runs hold a bare failure record whose metadata names a
page and 1 (r180) also holds a later pass for that page+kind -- an undercount by
construction, since `check_main_validation:ui_smoke` is ONE store slot each write overwrites.
From the logs, which do see intermediate states: 16 gate evaluations across 2 runs (r117 8,
r180 8) name a page already recorded success with no failure since.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.delivery_gate import _ui_evidence_breadth_739  # noqa: E402


def _rec(name, status, at, **meta):
    return {"name": name, "status": status, "recorded_at": at,
            "metadata": dict(meta)}


def _failed(records, **kw):
    return _ui_evidence_breadth_739(records, **kw)["pages_failed"]


class TheR180Latch(unittest.TestCase):

    #: the two records off r180's disk, with their real names, statuses and times.
    BARE_FAIL = _rec("validation:ui_smoke", "failed", 1791748357.78,
                     check="ui_smoke", route="/friends")
    PAGE_PASS = _rec("validation:ui_smoke:/friends", "success", 1791748867.0,
                     check="ui_smoke", flow="/friends",
                     url="http://localhost:8059/friends")

    def test_the_later_pass_retires_the_bare_failure(self):
        self.assertEqual(_failed([self.BARE_FAIL, self.PAGE_PASS]), [])

    def test_the_bare_failure_alone_still_blocks(self):
        """The fix must not make a real failure disappear -- only let a pass answer it."""
        self.assertEqual(_failed([self.BARE_FAIL]), ["/friends"])

    def test_an_earlier_pass_does_not_retire_a_later_failure(self):
        """Direction matters: a page that passed and then broke is still broken."""
        stale_pass = dict(self.PAGE_PASS, recorded_at=1791748000.0)
        self.assertEqual(_failed([self.BARE_FAIL, stale_pass]), ["/friends"])

    def test_the_order_is_unchanged_by_input_order(self):
        for order in ([self.BARE_FAIL, self.PAGE_PASS], [self.PAGE_PASS, self.BARE_FAIL]):
            self.assertEqual(_failed(order), [], order)


class ItStaysNarrow(unittest.TestCase):

    def test_a_bare_record_with_no_page_in_metadata_is_untouched(self):
        """Nothing to key by: the previous behaviour, exactly."""
        bare = _rec("validation:ui_smoke", "failed", 10.0, check="ui_smoke")
        page_pass = _rec("validation:ui_smoke:/friends", "success", 20.0, flow="/friends")
        self.assertEqual(_failed([bare, page_pass]), ["ui_smoke"])

    def test_nothing_is_not_a_page_named_nothing(self):
        """★ The LABEL cannot show this and the first version of this file checked only the
        label, so dropping the `if <page>` guard survived a mutation round: with no guard the
        key becomes `validation:<kind>:None`, which claims a page called "None". These two
        records both have no page -- one leaves `route` out, one sets it to the literal
        string -- and they must stay DISTINCT, which only the key decides."""
        no_page = _rec("validation:ui_smoke", "failed", 10.0, check="ui_smoke")
        literally_none = _rec("validation:ui_smoke", "failed", 20.0,
                              check="ui_smoke", route="None")
        self.assertEqual(_failed([no_page, literally_none]), ["None", "ui_smoke"])

    def test_the_kind_stays_in_the_key(self):
        """`ui_smoke` must not merge into `ui_flow` -- the rule the key already carried."""
        bare = _rec("validation:ui_smoke", "failed", 10.0, check="ui_smoke", route="/x")
        other_kind = _rec("validation:ui_flow:/x", "success", 20.0, flow="/x")
        self.assertEqual(_failed([bare, other_kind]), ["/x"])

    def test_a_record_that_names_its_own_flow_keeps_its_own_key(self):
        """Only a name with NO page segment is rekeyed; a three-part name is left alone even
        when its metadata disagrees with it."""
        named = _rec("validation:ui_flow:alpha", "failed", 10.0, flow="alpha", route="beta")
        beta_pass = _rec("validation:ui_flow:beta", "success", 20.0, flow="beta")
        self.assertEqual(_failed([named, beta_pass]), ["alpha"])

    def test_two_bare_failures_for_different_pages_both_survive(self):
        """The bare name is ONE key for every page, so before this they overwrote each other
        and the gate reported a single one."""
        a = _rec("validation:ui_smoke", "failed", 10.0, check="ui_smoke", route="/a")
        b = _rec("validation:ui_smoke", "failed", 20.0, check="ui_smoke", route="/b")
        self.assertEqual(_failed([a, b]), ["/a", "/b"])


class ItRunsBeforeTheFlowKeyCanonicaliser(unittest.TestCase):
    """#1203f9 canonicalises the flow segment (`friends_page` -> `friends`,
    `view-fyp-feed` -> `view_fyp_feed`). The rekey has to happen FIRST, or the segment it
    adds never gets canonicalised and still fails to match the pass."""

    def test_a_page_spelled_with_the_page_suffix_still_matches(self):
        bare = _rec("validation:ui_smoke", "failed", 10.0,
                    check="ui_smoke", route="friends_page")
        page_pass = _rec("validation:ui_smoke:friends", "success", 20.0, flow="friends")
        self.assertEqual(_failed([bare, page_pass]), [])

    def test_a_hyphenated_page_still_matches(self):
        bare = _rec("validation:ui_smoke", "failed", 10.0,
                    check="ui_smoke", route="view-fyp-feed")
        page_pass = _rec("validation:ui_smoke:view_fyp_feed", "success", 20.0,
                         flow="view_fyp_feed")
        self.assertEqual(_failed([bare, page_pass]), [])


class TheMetadataFieldsItAccepts(unittest.TestCase):

    def test_route_page_and_flow_all_name_the_page(self):
        for field in ("route", "page", "flow"):
            bare = _rec("validation:ui_smoke", "failed", 10.0,
                        **{"check": "ui_smoke", field: "/friends"})
            page_pass = _rec("validation:ui_smoke:/friends", "success", 20.0,
                             flow="/friends")
            self.assertEqual(_failed([bare, page_pass]), [], field)

    def test_junk_metadata_cannot_raise(self):
        for meta in (None, {"route": None}, {"route": ""}, {"route": 0}):
            r = {"name": "validation:ui_smoke", "status": "failed",
                 "recorded_at": 10.0, "metadata": meta}
            self.assertIsInstance(_ui_evidence_breadth_739([r])["pages_failed"], list)


if __name__ == "__main__":
    unittest.main()
