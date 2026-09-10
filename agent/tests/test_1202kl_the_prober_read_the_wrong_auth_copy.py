"""#1202kl: the prober called a correct 401 a failure, in 74% of the ones it saw.

`auth_required` lives in up to three places on an endpoint record — top level, `schema`, and
`metadata` — and the framework settled that question long ago: `_stated_auth_1202hi` is the ONE
reader, schema first, because that is what `register_endpoint(schema=...)` writes. #1202ga is
the cost of not using it (the projector read the mirror for six rounds while the backend lane
kept correctly fixing the contract), and #1202ih is the same lesson on the validator.

RunHub's prober never got the memo. `plan_probe` and the `classify_probe_result` call site both
read `endpoint["auth_required"]` raw:

    auth_required = bool(endpoint.get("auth_required"))          # probes.plan_probe
    auth_required=bool(ep.get("auth_required")),                 # runhub/service.py

Measured over the 153 corpus runs: 1628 of 4270 endpoint records (38%), in 128 runs, disagree
between that read and `_stated_auth_1202hi` — nearly all of them `naive=False` where the
contract says `True`.

The consequence is in `classify_probe_result`:

    if status_code in (401, 403) and auth_required:
        return ProbeOutcome(verdict="pass", note="auth-protected as expected")

With the wrong copy that branch does not fire, and a correct denial falls through to the P2
catch-all as `fail: "unexpected status 401"`. In the probe ledgers: **125 such records marked
fail**, against 43 correctly passed — wrong 74% of the time it saw a 401, across 13 runs.

`plan_probe` has the same read for a different purpose (skip an auth-required write rather than
probe it without a token), so both move together.

The reader is resolved at the CALL SITE and handed in — `probes.py` stays a leaf module with no
import of the projector, and there is one resolution rather than two that can drift.

WHAT IS VERIFIED: a contract-protected endpoint's 401 is accepted however the record spells
`auth_required`; a contract-PUBLIC endpoint's 401 stays a failure; an auth-required write is
skipped rather than probed tokenless; and the raw-read fallback is unchanged when nothing is
passed.

WHAT IS NOT, and this was checked rather than assumed: that it gives the framework a detector
for the #1202kh shape. The first draft of this claimed exactly that — "a contract-PUBLIC route
answering 401 is now a recorded failure" — and it is false. `plan_probe` skips any endpoint
whose `status != "defined"`, and across the corpus 3913 of 4270 records are `implemented`
against 308 `defined`; the number of contract-public GET /api/ endpoints sitting at `defined`
where the prober could see them is **zero**, in zero runs. So this repairs the false failures
the wrong reader produces and adds no new detection. The blanket-middleware denial stays
undetected here; #1202kh fixes it at the source instead.

Nor does any run's outcome change: these probes feed RunHub's record and the deliverability
blocker's evidence, so a false `fail` is noise in the diagnosis, not automatically a blocked cut.
"""
import sys
import pathlib

_AGENT = pathlib.Path(__file__).resolve().parents[1]
_LLM = _AGENT / "env_generator" / "llm_generator"
for _p in (str(_LLM), str(_AGENT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import inspect                                                        # noqa: E402

from multi_agent.runtime.hubs.runhub.probes import (                  # noqa: E402
    ProbeSkip,
    classify_probe_result,
    plan_probe,
)
from multi_agent.runtime.route_projector import _stated_auth_1202hi   # noqa: E402


# r97's shape, the one #1202ga was written for: the lane fixed `schema`, the stale `metadata`
# mirror still says True. Here it is the other way round and just as wrong for the prober.
SCHEMA_SAYS_AUTH = {
    "method": "GET", "path": "/api/saved-lists", "status": "defined",
    "schema": {"auth_required": True, "request": {}, "response": {}},
    "metadata": {},
}
SCHEMA_SAYS_PUBLIC = {
    "method": "GET", "path": "/api/videos/feed", "status": "defined",
    "schema": {"auth_required": False, "request": {}, "response": {}},
    "metadata": {},
}


def test_the_premise_the_raw_key_disagrees_with_the_framework_reader():
    """★ Validate the premise before the fix (the standing rule): these records really do
    read differently through the two accessors, or the whole finding is imaginary."""
    assert bool(SCHEMA_SAYS_AUTH.get("auth_required")) is False
    assert _stated_auth_1202hi(SCHEMA_SAYS_AUTH) is True


def test_a_correct_401_is_accepted_when_the_contract_requires_auth():
    """★ The 125 false failures."""
    out = classify_probe_result(401, "", auth_required=_stated_auth_1202hi(SCHEMA_SAYS_AUTH))
    assert out.verdict == "pass" and "auth-protected" in (out.note or "")


def test_a_401_on_a_contract_PUBLIC_endpoint_is_still_a_failure():
    """★ Scope, the other direction: the fix must not turn into "accept every 401". A public
    route that denies is still a failure HERE.

    Not a detector for #1202kh, though — see the module docstring. The prober only visits
    `status == "defined"` endpoints, and no contract-public GET in the corpus is ever in that
    state, so this branch does not fire on the real defect. It pins the classifier's shape,
    nothing more."""
    out = classify_probe_result(401, "", auth_required=_stated_auth_1202hi(SCHEMA_SAYS_PUBLIC))
    assert out.verdict == "fail", "a contract-public route that 401s must not be excused"


def test_an_auth_required_write_is_skipped_rather_than_probed_tokenless():
    """`plan_probe`'s own comment: a write that needs auth is skipped, because probing it with
    no token only ever produces a 401 nobody can act on."""
    ep = dict(SCHEMA_SAYS_AUTH, method="POST")
    got = plan_probe(ep, base_url="http://x", auth_required=_stated_auth_1202hi(ep))
    assert isinstance(got, ProbeSkip) and got.reason == "auth_required"


def test_a_public_write_is_still_probed():
    """Scope: the skip must follow the contract, not the method."""
    ep = dict(SCHEMA_SAYS_PUBLIC, method="POST")
    got = plan_probe(ep, base_url="http://x", auth_required=_stated_auth_1202hi(ep))
    assert not isinstance(got, ProbeSkip)


def test_the_raw_read_is_unchanged_when_nothing_is_passed():
    """★ Fail-safe: `probes.py` is a leaf module and every existing caller passes nothing."""
    ep = {"method": "POST", "path": "/api/x", "status": "defined", "auth_required": True}
    assert isinstance(plan_probe(ep, base_url="http://x"), ProbeSkip)
    ep2 = dict(ep, auth_required=False)
    assert not isinstance(plan_probe(ep2, base_url="http://x"), ProbeSkip)


def test_probes_py_does_not_import_the_projector():
    """The resolution happens at the CALL SITE. Importing the projector from this leaf module
    would drag the whole runtime into RunHub and invite a cycle."""
    import ast
    src = inspect.getsource(sys.modules["multi_agent.runtime.hubs.runhub.probes"])
    # IMPORTS, read from the tree — the module's docstring names the resolver on purpose, to
    # say where the value comes from, and a substring check would forbid explaining itself.
    imported = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    assert not any("route_projector" in m or "_stated_auth" in m for m in imported), (
        f"probes.py must stay a leaf module: {sorted(imported)}")


def test_the_service_resolves_it_once_and_hands_it_to_both():
    """★ Reachability, and one derivation: the call site must resolve through the framework's
    reader and pass the SAME value to plan and classify. Two reads is how #1202ga happened."""
    import ast
    from multi_agent.runtime.hubs.runhub import service as SVC
    tree = ast.parse(inspect.getsource(SVC))

    # (1) the PRIMARY assignment resolves through the framework's reader. A source span that
    # started at `plan_probe(` missed this line entirely -- the first counter-proof swapped the
    # resolver for the raw key and all 8 tests still passed, which is the vacuous-counter-proof
    # trap. Assert the assignment itself.
    def _calls(node):
        return {c.func.id for c in ast.walk(node)
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}

    assigns = [n for n in ast.walk(tree)
               if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == "_auth_1202kl" for t in n.targets)]
    assert assigns, "`_auth_1202kl` is not assigned anywhere"
    # The value is wrapped (`bool(_stated_auth_1202hi(ep))`), so look through the subtree
    # rather than at the outermost call — which is `bool`.
    primary = [n for n in assigns if "_stated_auth_1202hi" in _calls(n.value)]
    assert primary, (
        "`_auth_1202kl` must be assigned from `_stated_auth_1202hi(ep)` -- reading "
        "`ep['auth_required']` is the defect")

    # (2) and the ONE resolved value reaches BOTH consumers.
    for fname in ("plan_probe", "classify_probe_result"):
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == fname]
        assert calls, f"{fname} is no longer called"
        assert any(any(kw.arg == "auth_required"
                       and isinstance(kw.value, ast.Name)
                       and kw.value.id == "_auth_1202kl" for kw in c.keywords)
                   for c in calls), (
            f"{fname} must receive the SAME resolved value; two reads is how #1202ga happened")
