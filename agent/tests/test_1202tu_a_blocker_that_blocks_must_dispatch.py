r"""#1202tu: a check that can DECLINE delivery but mints no mappable name dispatches NOBODY.

MEASURED ON A LIVE RUN, not inferred. r132 (2026-09-24, tiktok design-input, gpt-5.5) spent
$139.64 over 13 ticks and 67 gate snapshots and went green ZERO times. One blocker sat in all
67:

    Delivery declined on gate check(s) with NO remediation owner
      ['deliverability_other:1 served file(s) carry addresses on a RESERVED documentation
        domain: backend/see']

Every one of the ten other failing checks was dispatched normally in the same run. The chain:

  1. `_deliverability_check_token` maps blocker PROSE to a check NAME through a chain of
     substring tests, and falls back to `deliverability_other:<first 80 chars>`.
  2. `_GATE_OWNER` is an EXACT-key lookup, so a composite key carrying prose can never match
     -- delivery_gate.py's own comment said so already.
  3. #1202rs (realism) and #1202ri/rj (operator identity) were added 09-23 WITHOUT a token,
     so both minted `deliverability_other:` and neither could ever be routed.

★ AND THE HARM WAS WORSE THAN "NOBODY WAS ASKED". The addresses were in `seed_data.py`, a
FRAMEWORK-owned file, emitted by `backend_skeleton`'s own seed fallback. The backend lane did
try, and reported honestly that it could not fix a file the framework rewrites. The framework
was declining its own delivery over content it wrote itself. #1202tu also fixes that emitter;
this file guards the ROUTING half.

WHY A RATCHET AND NOT TWO ENTRIES: #1202sw already swept "the last gate blocker that declines
with nobody dispatched", and two new ones grew back the very next day. Adding a check and
adding its owner mapping are separate acts, and nothing made the second follow the first.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.delivery_gate import _deliverability_check_token  # noqa: E402

RUNTIME = LLM_DIR / "multi_agent" / "runtime"
DELIVERABILITY = RUNTIME / "deliverability.py"

# Blockers whose check NAME is assigned at the emission site instead of through the prose
# token chain, so the `deliverability_other:` fallback never applies to them.
#
# This is a claim, not a waiver, and #1202ts is why it is written as one: an exemption list
# that states something falsifiable and is never re-checked is how three false entries
# survived in #1202cw's. So each entry names the check it is REALLY emitted as, and
# `test_every_named_elsewhere_claim_is_true` verifies that name exists and is classified.
_NAMED_ELSEWHERE_1202TU = {
    "Frontend kickoff `critical_flows[]` is present but every ent":
        "deliverability_critical_flows_invalid",
    "no successful RunHub run since session start (call run_start":
        "deliverability_no_successful_run",
    " critical visual review(s) need revision":
        "deliverability_critical_visuals_needs_revision",
}


def _owner_table():
    """`_GATE_OWNER` as built by the dispatcher, without running a delivery."""
    src = (RUNTIME / "remediation_dispatcher.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", "") == "_GATE_OWNER" for t in node.targets):
            return {k.value for k in node.value.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    raise AssertionError("_GATE_OWNER is gone")


def _lit_prefix(n):
    """The static leading text of a blocker expression, through the shapes these checks use."""
    if isinstance(n, ast.Constant) and isinstance(n.value, str):
        return n.value
    if isinstance(n, ast.JoinedStr):                       # f"..." -- take the literal head
        for v in n.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str) and len(v.value) > 20:
                return v.value
    if isinstance(n, ast.BinOp):                           # "..." % (...) / "..." + x
        return _lit_prefix(n.left)
    if isinstance(n, ast.Call):                            # "...".format(...) / helper(...)
        parts = ([n.func.value] if isinstance(n.func, ast.Attribute) else []) + list(n.args)
        for a in parts:
            got = _lit_prefix(a)
            if got:
                return got
    return None


def _blocker_prose_literals():
    """The static prose each deliverability check can emit.

    COVERAGE, stated rather than implied (#1202tb's rule): this reads the two shapes these
    checks actually use to raise a blocker -- a literal inside `return [...]` and one inside
    `.append(...)` -- through `%`-formatting, f-strings, concatenation and `.format`. It does
    NOT see prose assembled somewhere else and handed in as a variable. So it is a FLOOR: it
    cannot prove every blocker routes, only that these do. It found 7 real ones, which is the
    argument for keeping it.
    """
    tree = ast.parse(DELIVERABILITY.read_text(encoding="utf-8"))
    out = {}
    for node in ast.walk(tree):
        targets = None
        if isinstance(node, ast.Return) and isinstance(node.value, ast.List):
            targets = node.value.elts
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "append"):
            targets = node.args
        if not targets:
            continue
        for elt in targets:
            prose = _lit_prefix(elt)
            if prose and len(prose) > 30:
                out.setdefault(prose, node.lineno)
    return [(ln, p) for p, ln in out.items()]


def test_the_scan_sees_the_checks():
    """Non-vacuity: an extractor that quietly stopped working would report a clean tree."""
    lits = _blocker_prose_literals()
    # 17 at the time of writing; a floor well under it still catches an extractor that broke.
    assert len(lits) >= 14, f"only {len(lits)} blocker literals found — the AST walk drifted"
    assert len(_owner_table()) >= 20, "the owner table looks empty"


def test_the_two_r132_blockers_now_route():
    """The instance, pinned by consequence: these are the exact two r132 could not dispatch."""
    owners = _owner_table()
    for prose, expected in (
            ("3 served file(s) carry addresses on a RESERVED documentation domain: x.py (6). ",
             "deliverability_reserved_email_domain"),
            ("1 served file(s) carry the identity of the account that BUILT this env, and 1 ",
             "deliverability_operator_identity_leak")):
        got = _deliverability_check_token(prose)
        assert got == expected, (prose[:50], got)
        assert got in owners, f"{got} maps to no owner"


def test_no_blocker_prose_mints_an_unroutable_name():
    """The rule, not the instance: a check added tomorrow must be routable too."""
    owners = _owner_table()
    unroutable = []
    for lineno, prose in _blocker_prose_literals():
        if any(prose.startswith(k) or k in prose for k in _NAMED_ELSEWHERE_1202TU):
            continue
        name = _deliverability_check_token(prose)
        if name.startswith("deliverability_other:") or name not in owners:
            unroutable.append(f"deliverability.py:{lineno}: {prose[:60]!r} -> {name[:48]}")
    assert unroutable == [], (
        "these blockers can DECLINE delivery and dispatch nobody — the run declines every "
        "tick until the wall clock with no action that could clear it. Give each a token in "
        "_deliverability_check_token and an owner in _GATE_OWNER: %s" % unroutable)


def test_every_named_elsewhere_claim_is_true():
    """#1202ts's rule applied to this file's own exemptions: check the claim, don't believe it.

    A prose fragment is excused only because the gate emits it under a REAL check name. If
    that name is neither owned nor classified, the excuse is hiding an unroutable blocker.
    """
    owners = _owner_table()
    # A check counts as classified if it is OWNED, handled by a bespoke path
    # (`_COVERED_ELSEWHERE`), or deliberately exempt (#1202tb) -- the same three buckets
    # #1202tb's own sweep uses. Leaving _COVERED_ELSEWHERE out of this set is what made this
    # test's first run flag `deliverability_no_successful_run`, a check that fires 1946 times
    # across the corpus and is handled there.
    disp_src = (RUNTIME / "remediation_dispatcher.py").read_text(encoding="utf-8")
    covered = set(re.findall(r'"(deliverability_[a-z_]+)"',
                             disp_src.split("_COVERED_ELSEWHERE = {")[1].split("}")[0]))
    exempt_src = (ROOT / "tests"
                  / "test_1202tb_every_gate_check_is_classified.py").read_text(encoding="utf-8")
    classified = set(re.findall(r'"(deliverability_[a-z_]+)"', exempt_src)) | owners | covered
    bogus = [f"{frag[:40]!r} claims {name}" for frag, name in _NAMED_ELSEWHERE_1202TU.items()
             if name not in classified]
    assert bogus == [], (
        "these exemptions name a check that is neither owned nor classified anywhere, so the "
        "blocker they excuse may in fact dispatch nobody: %s" % bogus)
