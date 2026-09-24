r"""#1201 ratchet: a guard that can switch a mechanism off must not be added silently.

The dominant defect class this session was a mechanism wired and never reached, and the thing
that made all three instances invisible was the same: `try: from .x import mechanism_NNN ...
except Exception: pass`. The import is guarded because it can genuinely fail — a circular
import, a hub that is not there — and when it does, the mechanism is simply absent for the
whole run while the log stays clean. #1200's leak signal was one `except` away from exactly
that.

The fourteen that exist are NOT converted here, and the reason had to be earned rather than
asserted. The first version of this docstring said "their markers all appear in the corpus, so
they are running" — which was not evidence: none of these mechanisms logs from inside its own
body, so the corpus hits were the CALLING comment's text, not proof that anything ran. Checked
properly instead, by importing each guarded symbol the way the run does: all ten distinct
imports resolve under the run's PYTHONPATH (`note_finish_637` needs `agent/` on the path as a
real run has it; it resolves there). The guards protect against an import that does not
currently fail, so the mechanisms behind them run, and rewriting fourteen live call sites to
prove a point is not worth the risk.

What this pins is the direction: a NEW one has to say so, via `warn_once_1201`, one line.

Detected by shape, not by name: a `try:` whose body imports a symbol ending in a ticket number
and whose handler body is exactly `pass`. A guard that reports (contains `warn_once_1201`) is
not counted, which is the whole point — the ratchet is satisfied by fixing, not by hiding.
"""

import re
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent / "env_generator" / "llm_generator"
sys.path.insert(0, str(ROOT))

# Measured 2026-09-01. Lower it when one is converted; never raise it.
_BASELINE_1201 = 14


def _silent_mechanism_guards():
    found = []
    for p in sorted(ROOT.rglob("*.py")):
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        for i, line in enumerate(lines):
            if line.strip() != "try:":
                continue
            indent = len(line) - len(line.lstrip())
            body, silent = [], False
            # Landmark, not a byte window (#943): the block ends at the first line that
            # dedents back to the `try`.
            for j in range(i + 1, min(i + 80, len(lines))):
                cur = lines[j]
                if cur.strip() and len(cur) - len(cur.lstrip()) <= indent:
                    silent = (cur.strip().startswith("except")
                              and j + 1 < len(lines) and lines[j + 1].strip() == "pass")
                    break
                body.append(cur)
            if not silent:
                continue
            blob = "\n".join(body)
            if "warn_once_1201" in blob:
                continue                      # it reports — that is the fix, not a violation
            m = re.search(r"from\s+\.[\w.]*\s+import\s+(\w*_\d{3,4})\b", blob)
            if m:
                found.append(f"{p.relative_to(ROOT)}:{i + 1} {m.group(1)}")
    return found


def test_the_count_does_not_grow():
    found = _silent_mechanism_guards()
    assert len(found) <= _BASELINE_1201, (
        "a new mechanism import is guarded by a silent `pass` — when that import fails the "
        "mechanism is OFF for the whole run and nothing says so. Add "
        "`warn_once_1201(site, what, exc)` to the handler.\n  "
        + "\n  ".join(sorted(set(found) - set(_KNOWN))))


# The fourteen as measured, so a swap (one converted, one added) cannot pass unnoticed.
_KNOWN = [
    "multi_agent/agents/runtime/tooling.py:1206 note_finish_637",
    "multi_agent/orchestrator.py:1556 record_stage_894",
    "multi_agent/orchestrator.py:3379 record_stage_894",
    "multi_agent/runtime/backend_skeleton.py:2084 _structurally_private_resource_633",
    "multi_agent/runtime/completeness_audit.py:702 _gate_absent_792",
    "multi_agent/runtime/database_scaffold.py:1521 require_stage_output_891",
    "multi_agent/runtime/deliverability.py:308 crossed_page_endpoints_728",
    "multi_agent/runtime/frontend_audit.py:1058 _swallowed_790",
    "multi_agent/runtime/heal_pipeline.py:1064 identical_projected_bodies_1156",
    "multi_agent/runtime/remediation_dispatcher.py:40 _swallowed_790",
    "multi_agent/runtime/scaffolder.py:346 require_stage_input_891",
    "multi_agent/runtime/scaffolder.py:467 register_mandated_ui_components_1090",
    "multi_agent/runtime/visual_fidelity.py:2518 require_stage_input_891",
    "multi_agent/runtime/visual_fidelity.py:3541 _screen_is_player_449",
]


def test_this_sessions_own_guards_report():
    """The four added this session are the reason the ratchet exists; none may be in the
    silent set."""
    silent = " ".join(_silent_mechanism_guards())
    for name in ("_lane_owner_scoped_read_tables_1200",
                 "reconcile_ui_page_apis_1199"):
        assert name not in silent, name
