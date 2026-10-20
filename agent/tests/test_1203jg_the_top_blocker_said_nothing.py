r"""#1203jg: #1202wi gave five checks their instances and skipped the biggest one.

`blocker_prose` is how a failed gate check tells a lane WHAT it is about: the orchestrator
copies it to `_gate_blocker_prose_983` and the remediation dispatcher reads it per check
name. #1202wi added `_note1202wi` for exactly that and wired `contract_alignment_failed`,
`verification_checklist_not_ready`, `unresolved_failed_tasks`,
`incomplete_required_tasks`, `business_response_key_noncanonical` and the
`business_chain_*` reasons.

★ By #1202wi's OWN measurement the largest class was `validation_ui_evidence_failed` at
1001 occurrences — against business_chain_failing's 368 — and that is the one it left out.

Measured now, over every modern run whose FINAL gate record carries a failed check:
`validation_ui_evidence_failed` holds the final gate in 13 of the 63 runs with a ledger,
more than any other check, and in 13 of 13 it carries NO prose. Six (r128–r137) could not
even name a page; `ui_evidence_failed_pages` fixed that from r154 on, so r170 says
`['login_page','signup_page']` — but never WHY, and the why is what decides whether a lane
has anything to fix. Both of r170's records say the page RENDERED and name an anonymous
401 on `/api/auth/me`, which is the correct answer from a guarded endpoint (#1203jf), not
a defect.

★★ The helper is tested against the records the corpus REALLY holds, because the only way
a lookup like this fails is by matching nothing — and a prose builder that matches nothing
is a fix that looks landed and never fires.
"""
import json
import os
import pathlib
import sys

import pytest

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.delivery_gate import (  # noqa: E402
    _ui_evidence_prose_1203jg as _prose)

# r170's own records, verbatim from its `codehub_checks.json`, trimmed to the fields the
# builder reads. Its FINAL gate record is
# `ui_evidence_failed_pages=['login_page','signup_page']` with no prose at all.
_R170 = [
    {"name": "validation:ui_flow:login_page", "status": "failure",
     "evidence": {"summary": "login_page flow failed: /api/auth/me produced a 401 "
                             "console/network error during the flow.",
                  "execution_mode": "manual"}},
    {"name": "validation:ui_flow:signup_page", "status": "failure",
     "evidence": {"summary": "/api/auth/me returned 401 during logged-out signup flow.",
                  "execution_mode": "manual"}},
    {"name": "validation:api_smoke", "status": "success", "evidence": {"summary": "fine"}},
]
_BREADTH = {"pages_failed": ["login_page", "signup_page"], "failed_records": 2}


def test_it_names_the_page_and_the_reason():
    """★ THE TICKET. The gate already had the page names; what the lane never got is why."""
    out = _prose(_R170, _BREADTH)
    assert "login_page" in out and "signup_page" in out, out
    assert "401" in out, "the reason did not reach the prose: %r" % out
    assert "auth/me" in out, out
    # #1203pr: the record count still LEADS the sentence; what follows it now also
    # states how many pages those records are spread over, because the two are
    # different collections. Asserted without the punctuation that used to follow.
    assert out.startswith("2 failed UI record(s)"), out
    assert "on 2 page(s)" in out, out


def test_a_page_the_records_do_not_mention_still_contributes_its_name():
    """Never emptier than the page list it replaces: an unmatched page must not vanish, or
    the prose would under-report what failed."""
    out = _prose(_R170, {"pages_failed": ["login_page", "mystery_page"],
                         "failed_records": 2})
    assert "mystery_page" in out, out
    assert "no summary recorded" in out, out


def test_a_passing_record_is_not_quoted():
    """It must read the FAILING record. Quoting a success would describe the opposite of
    the verdict."""
    out = _prose([{"name": "validation:ui_flow:login_page", "status": "success",
                   "evidence": {"summary": "all good"}}],
                 {"pages_failed": ["login_page"], "failed_records": 1})
    assert "all good" not in out, out
    assert "no summary recorded" in out, out


def test_the_page_can_be_carried_in_metadata_instead_of_the_name():
    """`_ui_evidence_breadth_739` documents that writers name a page inconsistently; r181's
    ui_smoke records carry it in `metadata.page`."""
    recs = [{"name": "validation:ui_smoke", "status": "failure",
             "evidence": {"summary": "Rerun /explore rendered but AppShell GET "
                                     "/api/auth/me returned 401",
                          "metadata": {"page": "explore_grid_page"}}}]
    out = _prose(recs, {"pages_failed": ["explore_grid_page"], "failed_records": 1})
    assert "401" in out, out


def test_nothing_to_say_is_said_as_nothing():
    """An empty page list must not produce a sentence — a prose line that names no instance
    is the defect #1202wi exists to remove, not a smaller version of it."""
    assert _prose(_R170, {"pages_failed": [], "failed_records": 0}) == ""
    assert _prose(_R170, None) == ""


def test_it_survives_junk_records():
    """`validation_results` comes off disk; prose is never the verdict (#1202wi's rule)."""
    assert "login_page" in _prose([None, 7, "x"] + _R170, _BREADTH)
    assert _prose(None, _BREADTH)


def test_the_gate_notes_it_under_the_right_check_name():
    """The prose only reaches a lane if it is filed under the name the dispatcher looks up.
    Asserted structurally, next to the `failed_checks.append` it explains."""
    import ast
    import inspect
    import multi_agent.runtime.delivery_gate as DG
    tree = ast.parse(inspect.getsource(DG))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and (getattr(n.func, "id", "") == "_note1202wi")
             and n.args and isinstance(n.args[0], ast.Constant)
             and n.args[0].value == "validation_ui_evidence_failed"]
    assert calls, ("the gate never files prose under validation_ui_evidence_failed — "
                   "#1202wi's five-of-six miss is back")
    builders = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                and getattr(n.func, "id", "") == "_ui_evidence_prose_1203jg"]
    assert builders, "the prose builder is no longer called by the gate"


_R170_HUB = (pathlib.Path(_AGENT).parent / "generated" / "tiktok-web-r170"
             / "shared" / "hubs" / "codehub_checks.json")


@pytest.mark.skipif(not _R170_HUB.exists(),
                    reason="r170's records are not in this checkout's generated/")
def test_it_fires_on_the_run_that_motivated_it():
    """★ THE ONLY TEST THAT PROVES THE LOOKUP MATCHES ANYTHING. A hand-written fixture can
    agree with a predicate that agrees with nothing real — #1203d6's rule, a fixture value
    the system never produces. This reads r170's own file."""
    with open(_R170_HUB, encoding="utf-8") as fh:
        hub = json.load(fh)
    recs = [v for k, v in hub.items() if k != "_meta" and isinstance(v, dict)]
    out = _prose(recs, {"pages_failed": ["login_page", "signup_page"], "failed_records": 2})
    assert "401" in out and "login_page" in out, out
    assert "no summary recorded" not in out, (
        "the lookup matched neither of r170's two records: %r" % out)
