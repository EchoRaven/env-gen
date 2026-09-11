"""#1202kr: #1202kh can make a verifier chain fail, and the blocker said nothing about it.

#1202kh made the blanket auth middleware honour `auth_required`, so a GET the contract states
public now answers 200 where the blanket rule used to answer 401. That is the framework's
documented authority chain — #320 declares the public surface, #1202ga picks the schema copy,
and #1202ih already ruled that "probing a contract-public read for a 401 is the wedge this
replaced". But a verifier chain asserting a denial on such a route used to PASS, for a reason
that had nothing to do with the contract, and now fails — and `business_chain_failing` blocks
delivery on any one failing chain, with a message that says only "re-author the broken step or
fix the endpoint".

CHECKED, NOT PREDICTED. Rendering main.py from the corpus's real ledgers with the current code,
15 runs contain a chain step expecting ONLY 401/403 on a GET that lands in the emitted
`_FW_PUBLIC_API_1202KH` — netflix-r13 `/api/profiles`, tiktok-r103 `/api/messages`,
tiktok-r110 `/api/live`. In tiktok-r117, the one run actually executed with #1202kh, the count
is 0, so the risk is real but has not yet materialised.

THE CONTRADICTION IS NOT RESOLVED, deliberately. One of the two is wrong and the ledgers cannot
say which: `owner_scoped_reads` is noisy (netflix-r13 carries it on `titles`, a public
catalogue), the materials' `visibility` is silent in exactly these cases, and
`schema.response.tables` is empty on every one of them. #1202gd already settled that no
structural rule separates a published feed from a private list. Guessing would either re-wall
the logged-out surface or publish a per-user read; #1202ht refuses the same guess for the same
reason. So this names the disagreement and both repairs, and changes no verdict.

WHAT IS VERIFIED: it fires on a route the guard ACTUALLY opened, stays silent when the route
was not opened, names both repair directions, and never widens the expectation on the verifier's
behalf.

WHAT IS NOT: that it tells you which side is wrong. It cannot, and it says so in the message.
"""
import sys
import pathlib

_AGENT = pathlib.Path(__file__).resolve().parents[1]
_LLM = _AGENT / "env_generator" / "llm_generator"
for _p in (str(_LLM), str(_AGENT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import json          # noqa: E402
import types         # noqa: E402

from multi_agent.runtime.delivery_gate import (               # noqa: E402
    _contract_denial_contradictions_1202kr as contradictions,
)

_R = pathlib.Path("/data/common/haibotong/forgingground-gen/generated")


def _hubs(tmp, opened):
    be = tmp / "app" / "backend"
    be.mkdir(parents=True, exist_ok=True)
    lit = "_FW_PUBLIC_API_1202KH = [\n" + "".join(
        "    (%r, %r),\n" % (m, p) for m, p in opened) + "]\n"
    (be / "main.py").write_text(lit, encoding="utf-8")
    return types.SimpleNamespace(base_dir=str(tmp))


def _chain(name, path, expect, status="failing"):
    return {"name": name, "status": status,
            "steps": [{"method": "GET", "path": path, "expect": expect}]}


def test_it_fires_when_the_guard_opened_the_route(tmp_path):
    """★ The case: the chain demands a denial from a route #1202kh opened."""
    hubs = _hubs(tmp_path, [("GET", "/api/messages")])
    out = contradictions(None, [_chain("messages_private", "/api/messages", [401])], hubs)
    assert "CONTRACT/CHAIN CONTRADICTION" in out
    assert "/api/messages" in out


def test_it_is_silent_when_the_route_was_not_opened(tmp_path):
    """★ The false positive I shipped first and caught: r117's `/api/notifications` is
    contract-public but was NOT opened (owner-scoped table forced an actor), so the guard still
    denies it and the chain demanding 401 is CORRECT. Telling the verifier to widen that step
    would have suppressed a real auth check."""
    hubs = _hubs(tmp_path, [("GET", "/api/videos/feed")])
    out = contradictions(None, [_chain("notif", "/api/notifications", [401])], hubs)
    assert out == ""


def test_r117s_real_ledger_reports_nothing():
    """★ The true negative, on real data: r117 ran WITH #1202kh and has no contradiction."""
    d = _R / "tiktok-web-r117"
    if not (d / "app" / "backend" / "main.py").exists():
        import pytest
        pytest.skip("r117 not present")
    C = json.loads((d / "shared" / "hubs" / "registryhub_verification_chains.json").read_text())
    authored = [c for k, c in C.items() if k != "_meta" and isinstance(c, dict)]
    assert contradictions(None, authored, types.SimpleNamespace(base_dir=str(d))) == ""


def test_a_step_that_also_accepts_200_is_not_a_contradiction(tmp_path):
    """A chain tolerating both outcomes is not asserting a denial."""
    hubs = _hubs(tmp_path, [("GET", "/api/messages")])
    assert contradictions(None, [_chain("m", "/api/messages", [200, 401])], hubs) == ""


def test_a_passing_chain_is_not_reported(tmp_path):
    """Only a chain that is actually blocking delivery is worth a sentence."""
    hubs = _hubs(tmp_path, [("GET", "/api/messages")])
    assert contradictions(
        None, [_chain("m", "/api/messages", [401], status="passing")], hubs) == ""


def test_it_names_BOTH_repairs_and_refuses_to_pick(tmp_path):
    """★ The whole point. It must not tell the verifier to just widen the expectation — that
    would ship an unauthenticated read of private rows if the CONTRACT is the wrong side."""
    hubs = _hubs(tmp_path, [("GET", "/api/messages")])
    out = contradictions(None, [_chain("m", "/api/messages", [401])], hubs).lower()
    assert "fix the contract" in out
    assert "do not just widen" in out
    assert "cannot tell which" in out


def test_a_missing_main_py_is_silent(tmp_path):
    """Fail-safe: a run without the literal (anything before #1202kh) reports nothing."""
    assert contradictions(None, [_chain("m", "/api/x", [401])],
                          types.SimpleNamespace(base_dir=str(tmp_path))) == ""


def test_it_is_appended_to_a_blocker_that_already_fires():
    """★ Scope: it must not create a new blocker, only annotate one. The call site sits inside
    the existing business_chain_failing return."""
    import inspect
    from multi_agent.runtime import delivery_gate as DG
    src = inspect.getsource(DG)
    i = src.index('"reason": "business_chain_failing"')
    j = src.index("_contract_denial_contradictions_1202kr(rh, authored, hubs)", i)
    assert j - i < 700, "the annotation must attach to the business_chain_failing return"
