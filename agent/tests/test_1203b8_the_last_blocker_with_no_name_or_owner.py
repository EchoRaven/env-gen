r"""#1203b8: the last deliverability blocker with no name and no owner.

`#1202rl` found pages that render a hardcoded data module and never call the API, and gave the
gate a blocker for it — but no canonical TOKEN. `_deliverability_check_token` therefore drops it
into `deliverability_other:<first 80 chars>`, and `_GATE_OWNER` is an exact lookup, so a
composite key can never match. The check declines delivery and dispatches NOBODY: #1202tu's
measured failure mode (r132, 67 snapshots reading "NO remediation owner").

MEASURED over every record that reached the catch-all in production: 825 are mapped today
(`unscoped_owner_read` 734, `reserved_email_domain` 67, `operator_identity_leak` 12,
`auth_override` 6, `placeholder_route` 6) and 12 are not. All 12 are this one check, arriving
under THREE keys that differ only by the count — the drifting name the catch-all's own comment
says defeats the dispatcher's re-fire guard and storm control. r145 hit it live on four pages,
all importing `../lib/fallbackData`.
"""
import glob
import json
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import pytest  # noqa: E402

from multi_agent.runtime.delivery_gate import _deliverability_check_token as _token  # noqa: E402

_TOKEN = "deliverability_static_data_twin"

def _gate_owner():
    """`_GATE_OWNER` is a LOCAL of `dispatch_gate_level_checks`, so it cannot be imported.
    Read as a literal via AST — the same way this repo reads the owner table elsewhere, and
    the reason it is read rather than grepped: a regex over this dict reports entries that are
    only mentioned in a comment."""
    import ast
    import inspect
    import multi_agent.runtime.remediation_dispatcher as RD

    tree = ast.parse(inspect.getsource(RD))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", "") == "_GATE_OWNER" for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("_GATE_OWNER is gone")



# r145's own prose, and the two other spellings the corpus recorded
_PROSE = [
    "4 page/component(s) render a hardcoded data module WITHOUT asking the server: "
    "pages/ExploreGridPage.jsx renders from '../lib/fallbackData' and makes no API call",
    "1 page/component(s) render a hardcoded data module WITHOUT asking the server: "
    "components/CommentsPanel.jsx renders from '../lib/mockData' and makes no API call",
    "3 page/component(s) render a hardcoded data module WITHOUT asking the server: x; y; z",
]


@pytest.mark.parametrize("prose", _PROSE)
def test_every_spelling_gets_the_same_token(prose):
    """★ The point of a token: three counts, three different catch-all keys, ONE name. The
    dispatcher's re-fire guard is keyed on the name, so a drifting one defeats de-duplication
    as well as routing."""
    assert _token(prose) == _TOKEN, _token(prose)


def test_the_token_has_an_owner():
    """★ A token with no owner is the same wall with a tidier name — #1202tu's whole point."""
    owners = _gate_owner()
    assert _TOKEN in owners, sorted(owners)[:5]
    assignee, title, desc = owners[_TOKEN]
    assert assignee == "frontend", assignee
    assert title and len(title) < 120, title


def test_the_description_names_the_shape_and_the_repair():
    _, _, desc = _gate_owner()[_TOKEN]
    for frag in ("fallbackData", "never call the server", "apis_used", "DELETE"):
        assert frag in desc, "%r missing from the task description" % frag


def test_the_description_states_the_no_fallback_rule():
    """★ The user's standing rule, and the reason this blocker exists: a fallback that hides
    the absence of a request is worse than none. A lane told only "call the API" could keep the
    module as a fallback and the screen would still lie."""
    _, _, desc = _gate_owner()[_TOKEN]
    assert "hides the absence of a request" in desc, desc[-300:]
    assert "empty state" in desc, desc[-300:]


def test_it_is_not_a_masked_failure_and_says_so():
    """#1202qn owns masked failures; this is the opposite — no request at all. Conflating them
    sends the lane looking for a swallowed exception that does not exist."""
    _, _, desc = _gate_owner()[_TOKEN]
    assert "not a masked failure" in desc


def test_the_sibling_tokens_still_map():
    """The new branch sits in a long elif-chain; a misplaced one shadows its neighbours."""
    cases = {
        "1 served route(s) exist only to satisfy a framework check and would ship":
            "deliverability_parked_probe_route",
        "1 served file(s) carry the identity of the account that BUILT this env":
            "deliverability_operator_identity_leak",
        "4 registered ui_page(s) understate `apis_used` while their own source calls an API":
            "deliverability_page_apis_understated",
    }
    for prose, want in cases.items():
        assert _token(prose) == want, (prose[:40], _token(prose))


def test_an_unrelated_blocker_still_reaches_the_catch_all():
    """The catch-all is the right answer for something genuinely new — this must not start
    swallowing prose it does not understand."""
    assert _token("something nobody has ever reported before").startswith(
        "deliverability_other")


def test_no_deliverability_blocker_in_the_corpus_reaches_the_catch_all():
    """★ The claim this ticket makes, checked against the recorded runs rather than asserted:
    every record that fell into `deliverability_other:` now maps to a real token. Skipped where
    the corpus is not present, so the suite still runs on a clean checkout."""
    root = os.path.join(os.path.dirname(_AGENT), "generated")
    ledgers = glob.glob(os.path.join(root, "*", "logs", "delivery_gate.jsonl"))
    if not ledgers:
        pytest.skip("no run corpus in this checkout")
    unmapped = {}
    for p in ledgers:
        try:
            recs = [json.loads(x) for x in open(p, encoding="utf-8") if x.strip().startswith("{")]
        except Exception:
            continue
        for r in recs:
            for c in (r.get("failed_checks") or []):
                c = str(c)
                if not c.startswith("deliverability_other:"):
                    continue
                prose = c.split("deliverability_other:", 1)[1]
                if str(_token(prose)).startswith("deliverability_other"):
                    unmapped[prose[:78]] = unmapped.get(prose[:78], 0) + 1
    assert not unmapped, (
        "%d record(s) in %d form(s) still dispatch nobody:\n  "
        % (sum(unmapped.values()), len(unmapped))
        + "\n  ".join(sorted(unmapped)))
