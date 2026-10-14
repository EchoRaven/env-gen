r"""#1203jj: the isolation gate is parked behind a trigger nobody can evaluate.

`business_chain_isolation` requires at least one NEGATIVE assertion in the authored
verification chains — a step expecting 401/403 — because endpoint COVERAGE proves only
that every route was hit, and "a backend returning dummy 2xx for every route would clear
it (V29: 11 dummy no-op routes shipped)". It is env-gated, default-off, "until the drive
fix is validated end-to-end, then enable by default".

★ `drive fix` appears in no other file in this tree, so no reader can tell whether the
precondition has been met. A park is only honest when its trigger is checkable: #1203ib's
park states one I could measure ("one run where a host-caused browser failure reaches a
FINAL gate verdict") and the answer was zero. This one sends the next reader after a
referent that is not there — so the measurement now lives beside it instead.

★★ Measured with the gate's OWN predicate (`expect` ∩ {401, 403}) over every modern run
with chains (64): **63 already have at least one denial-asserting chain.** The exception is
tiktok-web-r131 — 17 chains, zero denial steps — which is exactly the happy-path sweep the
gate exists to catch, so it is a true positive. Enabling would change nothing in 63 of 64
runs and route the 64th to the verifier rather than dead-ending.

It is still NOT flipped: that is a delivery-path behaviour change, and this session's one
such change (#1203jd) is itself unverified live. These tests exist so the flip cannot
happen quietly — `test_the_gate_is_still_parked` goes red the moment the default changes,
which sends whoever changed it to the number above.
"""
import ast
import glob
import inspect
import json
import os
import pathlib
import sys

import pytest

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import multi_agent.runtime.delivery_gate as DG  # noqa: E402

_DENIAL = {401, 403}


def _isolation_block():
    """The `if ENVGEN_ISOLATION_GATE ...:` node, located by the variable it reads."""
    tree = ast.parse(inspect.getsource(DG))
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and "ENVGEN_ISOLATION_GATE" in ast.dump(node.test):
            return node
    raise AssertionError("the isolation gate block is gone")


def _park_comment_1203jj(src):
    """The #1203jj comment block, as text.

    Landmark-anchored (#943): start at the line carrying the marker, stop at the first line
    that is not a comment. No byte count, so rewording the park cannot move what this reads.

    ★ The first attempt walked UP from the `ENVGEN_ISOLATION_GATE` read instead, and
    stopped dead on the `import os as _os` that sits between the comment and the branch —
    returning an almost empty window. A landmark has to be the thing you want, not a thing
    near it.
    """
    lines = src.splitlines()
    start = next(n for n, l in enumerate(lines)
                 if "#1203jj" in l and l.strip().startswith("#"))
    out = []
    for l in lines[start:]:
        if not l.strip().startswith("#"):
            break
        out.append(l)
    return "\n".join(out)


def test_the_gate_is_still_parked():
    """★ THE RATCHET. Flipping the default is the decision the measurement above is FOR,
    and it must not happen in a session that cannot watch a run. If this is red because you
    enabled it deliberately with a run in flight, update the comment and this test
    together."""
    node = _isolation_block()
    defaults = [c.value for c in ast.walk(node.test)
                if isinstance(c, ast.Constant) and isinstance(c.value, str)]
    assert "0" in defaults, (
        "ENVGEN_ISOLATION_GATE no longer defaults to off: %s — read #1203jj's measurement "
        "before leaving it on" % defaults)


def test_the_park_states_a_trigger_that_can_be_evaluated():
    """A park's whole value is that the next reader can decide. The original trigger ("the
    drive fix") names nothing in the tree; the replacement is a number and a named
    exception, both re-derivable."""
    src = inspect.getsource(DG)
    # ★ The first version was `src[max(0, i - 2600):i]`. #943's ratchet did not catch it —
    # its pattern sees the forward `[i:i + N]` form and not the backward one — but the rule
    # is the same and the drift is the same, so this anchors on the block instead. The
    # blind spot is recorded in #1203jn's commit rather than silently relied on.
    window = _park_comment_1203jj(src)
    assert "#1203jj" in window, "the measurement is no longer beside the park"
    assert "63" in window and "tiktok-web-r131" in window, (
        "the park no longer carries a re-derivable number and the run it came from")
    # ★ `"drive fix" in window` is NOT a pin: the #1203jj paragraph QUOTES the trigger in
    # order to explain it, so deleting the original line left the phrase present and this
    # assertion green. Documenting a defect by quoting it makes your own quote a false
    # positive for any test that greps for it. Anchored on the original COMMENT LINE, which
    # the explanation does not reproduce (#943: a landmark, not a position).
    assert "\n    # drive fix is validated end-to-end, then enable by default." in src, (
        "the unevaluable trigger line was deleted rather than answered — keep it, so a "
        "reader who goes looking for it finds the explanation instead of nothing")


def test_the_gate_reads_the_key_the_chains_actually_write():
    """★ WITHOUT THIS THE GATE INVERTS SILENTLY. It looks for `expect` on a step. If the
    step shape ever changes, the predicate finds no denial anywhere and — once enabled —
    blocks EVERY run instead of none. Pinned against the key, not against a fixture."""
    node = _isolation_block()
    keys = [c.value for c in ast.walk(node)
            if isinstance(c, ast.Constant) and isinstance(c.value, str)]
    assert "expect" in keys, (
        "the isolation check no longer reads `expect`: %s" % sorted(set(keys))[:12])
    codes = {c.value for c in ast.walk(node)
             if isinstance(c, ast.Constant) and isinstance(c.value, int)}
    assert _DENIAL <= codes, "the denial codes changed: %s" % sorted(codes)


_CHAIN_FILES = sorted(glob.glob(os.path.join(
    os.path.dirname(_AGENT), "generated", "*", "shared", "hubs",
    "registryhub_verification_chains.json")))


@pytest.mark.skipif(not _CHAIN_FILES, reason="no generated/ corpus in this checkout")
def test_the_predicate_finds_denials_in_the_real_corpus():
    """★ THE NUMBER, re-derived rather than trusted. A fixture can agree with a predicate
    that agrees with nothing real (#1203d6), and the whole park decision rests on "63 of 64
    runs already satisfy this". Asserts the weaker, stable half: the predicate matches real
    chains at all, in most runs."""
    withs = total = 0
    for p in _CHAIN_FILES:
        try:
            hub = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        chains = [v for k, v in hub.items()
                  if k != "_meta" and isinstance(v, dict) and v.get("steps")
                  and v.get("name") != "_framework_coverage"]
        if not chains:
            continue
        total += 1
        for c in chains:
            hit = False
            for st in (c.get("steps") or []):
                exp = st.get("expect") if isinstance(st, dict) else None
                codes = ({int(x) for x in exp if str(x).isdigit()}
                         if isinstance(exp, (list, tuple))
                         else ({int(str(exp))} if str(exp).strip().isdigit() else set()))
                if codes & _DENIAL:
                    hit = True
                    break
            if hit:
                withs += 1
                break
    assert total, "no run in generated/ has authored chains"
    assert withs, (
        "the gate's predicate matched NO denial step in any of the %d runs with chains — "
        "either the step shape changed or the predicate is wrong, and enabling the gate "
        "would block every run" % total)
    assert withs / total > 0.5, (
        "only %d of %d runs carry a denial assertion; the park's premise (63 of 64) no "
        "longer holds, so re-measure before deciding" % (withs, total))


def test_a_failure_is_routed_and_actionable():
    """A gate that blocks without naming the next action is a dead end — the thing
    `blocker_prose` and #1203jg exist to prevent. This one returns its own detail."""
    node = _isolation_block()
    texts = [c.value for c in ast.walk(node)
             if isinstance(c, ast.Constant) and isinstance(c.value, str)]
    blob = " ".join(texts)
    assert "business_chain_isolation" in blob, blob[:200]
    assert "MUST be refused" in blob and "run_validation" in blob, (
        "the isolation blocker no longer tells the verifier what to author: %s" % blob[:300])
