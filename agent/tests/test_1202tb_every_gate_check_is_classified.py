r"""#1202tb: every check the gate can emit is owned, covered elsewhere, or exempt ON PURPOSE.

`dispatch_gate_level_checks` looks its owner up with `_GATE_OWNER.get(name)`. A name in
neither that table nor `_COVERED_ELSEWHERE` blocks delivery and dispatches nobody — the
failure `#1040`, `#1202ou` and `#1202lf` each fixed one instance of. `_GATE_OWNER`'s own
docstring states the intent: *"Any failing check NOT routed here AND not bespoke-covered is
LOGGED so it never silently dead-ends"*, and *"Conservative: ambiguous / relaxed /
framework-deterministic checks are logged, not mis-routed."*

**This file exists because I checked that the wrong way.** `#1202sw` replayed every
`failed_checks` entry in the corpus against the tables and concluded one class was left. That
only covers names the corpus HAPPENED TO HIT. Enumerating what the gate CAN emit — the
literal `failed_checks.append("…")` sites plus every `return "…"` in
`_deliverability_check_token` — finds fourteen unowned names, not one. A detector added after
the last corpus run is invisible to a corpus replay by construction, which is exactly when a
new dead-end would be introduced.

Measured over all 77 `logs/delivery_gate.jsonl` ledgers, which is why none of the fourteen is
an emergency and why routing them blind would be the wrong move:

    13 of 14 have NEVER fired.
    `no_implemented_endpoints` fires 23x across 6 runs and is TERMINAL IN NONE — it is the
    "nothing registered yet" shape, true early (r121/r122 tick 0-3) and transient when it
    reappears mid-run (r125 tick 452, r124 tick 110). Filing a P0 for a condition that
    always clears is noise, and #647 wants a measured reason before a constant is tuned.

So the exemptions below are decisions, each with its reason, rather than silence. The point of
the ratchet is the NEXT detector: it must be classified when it is added, by someone who knows
what it means, instead of joining an unowned set nobody enumerates.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime import delivery_gate as dg  # noqa: E402
from multi_agent.runtime import remediation_dispatcher as rd  # noqa: E402

# Each entry is a DECISION with its reason. Removing a name from here without giving it an
# owner is what this ratchet is for.
_EXEMPT_1202TB = {
    # "nothing is registered yet" — true at tick 0 of every run, and transient whenever it
    # returns. Never terminal in 77 ledgers. A lane cannot act on "you have not written it
    # yet" any sooner than it already is.
    "no_endpoints_in_hub": "pre-implementation state; never terminal",
    "no_implemented_endpoints": "pre-implementation state; 23 fires / 6 runs, terminal in 0",
    "no_implemented_tables": "pre-implementation state; never fired",
    "no_pages_in_hub": "pre-implementation state; never fired",
    "no_tables_in_hub": "pre-implementation state; never fired",
    "backend_code_missing": "pre-implementation state; never fired",
    # framework-internal: the gate reporting on its own machinery. There is no lane that can
    # repair the gate's own fault, and #790/#792 already surface these as errors.
    "deliverability_compute_failed": "the aggregator itself faulted — framework, not a lane",
    "validation_retry_pending": "the framework's own retry is in flight; waiting is correct",
    # framework-deterministic: the projector owns the output, so a lane told to fix it would
    # edit generated code the next projection overwrites (#1202cw's whole class).
    "semantic_projection_errors": "projector output; a lane cannot own it",
    "semantic_hub_drift": "framework reconciliation; a lane cannot own it",
    # ambiguous owner, and never observed. Routing on a guess is what _GATE_OWNER's docstring
    # refuses; each needs one real firing to show what it looks like first.
    "deliverability_critical_flows_invalid": "materials/spec shape; owner ambiguous, never fired",
    "deliverability_critical_visuals_needs_revision": "visual gate has its own attempt loop; never fired",
    "deliverability_failed_endpoint_probes": "probe failure may be the stack, not the code; never fired",
    "deliverability_failed_mcp_probes": "same, for the MCP surface; never fired",
}


def _emitted_check_names():
    """Every check name the gate can put into `failed_checks`, read from the source."""
    names = set()
    tree = ast.parse(inspect.getsource(dg))
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "append"
                and getattr(n.func.value, "id", "") in ("failed_checks",
                                                        "deliverability_failed_checks")):
            for a in n.args:
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    names.add(a.value)
    token_src = ast.parse(inspect.getsource(dg._deliverability_check_token))
    for n in ast.walk(token_src):
        if isinstance(n, ast.Return) and isinstance(n.value, ast.Constant) \
                and isinstance(n.value.value, str):
            names.add(n.value.value)
    return names


def _tables():
    owned, elsewhere = set(), set()
    tree = ast.parse(inspect.getsource(rd))
    for n in ast.walk(tree):
        if not isinstance(n, ast.Assign):
            continue
        targets = [getattr(t, "id", "") for t in n.targets]
        if "_GATE_OWNER" in targets:
            owned = {k.value for k in n.value.keys}
        if "_COVERED_ELSEWHERE" in targets:
            elsewhere = set(ast.literal_eval(n.value))
    return owned, elsewhere


def test_the_enumeration_finds_the_tables_and_the_names():
    """A ratchet that silently enumerates nothing passes forever."""
    names = _emitted_check_names()
    owned, elsewhere = _tables()
    assert len(names) >= 30, "the check-name scan stopped finding names — re-anchor it"
    assert len(owned) >= 25 and len(elsewhere) >= 8, "the owner tables were not found"


def test_every_emitted_check_is_owned_covered_or_exempt():
    names = _emitted_check_names()
    owned, elsewhere = _tables()
    unclassified = sorted(n for n in names
                          if n not in owned and n not in elsewhere and n not in _EXEMPT_1202TB)
    assert unclassified == [], (
        "these gate checks block delivery and dispatch nobody. Give each an owner in "
        "_GATE_OWNER, list it in _COVERED_ELSEWHERE if a bespoke path already handles it, or "
        "add it to _EXEMPT_1202TB WITH THE REASON: %s" % unclassified)


def test_no_exemption_is_stale():
    """If a name later gains an owner, the exemption must go — otherwise this list becomes a
    place where a routed check can quietly be un-routed again."""
    owned, elsewhere = _tables()
    stale = sorted(n for n in _EXEMPT_1202TB if n in owned or n in elsewhere)
    assert stale == [], "these are exempt AND routed; drop the exemption: %s" % stale


def test_no_exemption_names_a_check_the_gate_cannot_emit():
    """The dual: a renamed check leaves its exemption behind, covering nothing."""
    names = _emitted_check_names()
    orphan = sorted(n for n in _EXEMPT_1202TB if n not in names)
    assert orphan == [], "these exemptions name checks the gate no longer emits: %s" % orphan


def test_every_exemption_carries_a_reason():
    empty = sorted(k for k, v in _EXEMPT_1202TB.items() if not str(v).strip())
    assert empty == [], "an exemption without a reason is silence with extra steps: %s" % empty
