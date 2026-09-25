r"""#1202uh: the ledger named the squad 12 times and could not say what it was waiting on.

#1202tk records WHICH of the fourteen holds stopped a release after a clear gate. r133 is the
first run that produced that ledger, and it answered the question the corpus could not:

    gate_failed_checks         95
    squad_inflight              9  \
    squad_launched_background   2   |  12 of the 13 post-gate holds
    squad_defects               1  /
    fresh_smoke                 1

So the squad is where a green gate actually waits. Every one of those 12 rows carried an EMPTY
`detail`, and every one sat at milestone 1.0.0 -- the ledger could say the squad held the
release and could not say what was in flight, for how long, or how many defects were open.

That is exactly the gap #1202to closed for the visual gate one day earlier, and the reason is
the same: #1202tk's own call sites pass a name and nothing else, so the holds that turned out
to matter most are the ones carrying no numbers.

The counters come from state the orchestrator already has at each site -- attempts, seconds
deferred, open P0 count -- so nothing new is computed and nothing can fail. As with every
advisory line here, an unreadable value degrades to "?" rather than taking a delivery with it.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import ast
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.orchestrator import _squad_detail_1202uh as detail  # noqa: E402

ORCH = LLM_DIR / "multi_agent" / "orchestrator.py"
SQUAD_HOLDS = ("squad_wait", "squad_stack_unanswered", "squad_launched_background",
               "squad_inflight", "squad_not_ready", "squad_defects")


def test_it_reports_the_counters_the_ledger_was_missing():
    orch = types.SimpleNamespace(_tu_squad_attempts=3,
                                 _tu_squad_deferred_since=time.time() - 120,
                                 _tu_squad_open_p0=["a", "b"])
    out = detail(orch)
    assert "attempts=3" in out, out
    assert "defects=2" in out, out
    secs = int(out.split("deferred_s=")[1].split()[0])
    assert 110 <= secs <= 130, out


def test_it_degrades_rather_than_raising():
    """An advisory line may never be the reason a delivery fails."""
    assert detail(types.SimpleNamespace()) is not None
    assert detail(None) is not None
    assert detail(types.SimpleNamespace(_tu_squad_deferred_since="nonsense")) is not None


def test_every_squad_hold_site_passes_the_detail():
    """The rule, not the instance: a seventh squad hold added tomorrow must carry it too.

    Parsed rather than grepped -- #1202to's ratchets broke when a call was reformatted across
    lines, and the lesson there was to pin the property, not the layout.
    """
    tree = ast.parse(ORCH.read_text(encoding="utf-8"))
    bare = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_note_delivery_hold_1202tk"):
            continue
        if len(node.args) < 2 or not isinstance(node.args[1], ast.Constant):
            continue
        name = node.args[1].value
        if not str(name).startswith("squad"):
            continue
        if len(node.args) < 3:
            bare.append(f"orchestrator.py:{node.lineno}: {name}")
    assert bare == [], (
        "these squad holds record a name and no counters, which is the state r133 measured "
        "as 12 of 13 post-gate holds: %s" % bare)


def test_the_squad_holds_are_all_still_there():
    """Non-vacuity: if the names changed, the test above would pass by finding nothing."""
    src = ORCH.read_text(encoding="utf-8")
    missing = [h for h in SQUAD_HOLDS if f'"{h}"' not in src]
    assert missing == [], missing
