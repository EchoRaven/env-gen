r"""#1202uf: #739's warning told the reader nothing was blocking, while #752 was blocking.

`ui_smoke_pass` is existential (#287): one passing UI record satisfies the whole UI
requirement and a failing one is never consulted. r148 read True off landing + login while
the SPA crashed on 12 of 14 pages, and released v1.0.0. #739 exists to say so.

Its closing sentence was "Reported, not enforced - the matrix that would consume it is itself
skipped (#671)." That was true when it was written and is NOT true now. #752 (user-approved)
split the two cases on measured frequencies:

    contradicted (passing AND failing records)   6 of 148 runs   ->  4%, a gate
    missing (no UI evidence at all)             67 of 148 runs   -> 45%, a halt

and made the CONTRADICTION block unconditionally, without #671's matrix. MEASURED in r133:
`validation_ui_evidence_failed` entered `failed_checks` in 45 of 268 gate snapshots, so the
block is live and demonstrable.

WHY A STALE LOG LINE IS WORTH A TICKET: this is the class where a comment's absolute claim is
a falsifiable hypothesis. Anyone reading r133's log saw a warning stating the release was NOT
held on this, standing next to a gate ledger where it plainly was -- and the natural
conclusion, that nothing is enforcing UI breadth, is the opposite of the truth. A diagnostic
that misdescribes the system is worse than no diagnostic.

The MISSING half genuinely does stay unenforced, and the corrected text now says which half is
which instead of collapsing them.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

GATE = LLM_DIR / "multi_agent" / "runtime" / "delivery_gate.py"


def _warning_text():
    src = GATE.read_text(encoding="utf-8")
    i = src.index('"#739 ui_smoke_pass=True rests on')
    return src[i:src.index('", ', i) + 1]


def test_the_warning_does_not_claim_the_contradiction_is_unenforced():
    """The bug: it said 'Reported, not enforced' about a case #752 blocks."""
    text = _warning_text()
    assert "Reported, not enforced" not in text, text


def test_the_warning_names_which_half_is_enforced():
    text = _warning_text()
    assert "#752" in text and "validation_ui_evidence_failed" in text
    assert "MISSING" in text, "the half that genuinely stays unenforced must still be named"


def test_the_block_it_describes_really_exists():
    """★ Verify the claim rather than trust it -- the mistake being corrected was a sentence
    nobody re-checked. The gate must actually raise on a failing record."""
    import ast
    tree = ast.parse(GATE.read_text(encoding="utf-8"))
    # #943: no fixed byte window. The first version read `src[i:i + 4000]`, which is exactly
    # what that ratchet forbids -- it silently reaches into the next branch as soon as a
    # comment grows. The If NODE has real boundaries, so use them.
    guarded = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        if "_breadth739" not in ast.unparse(node.test):
            continue
        if "failed_records" not in ast.unparse(node.test):
            continue
        body = " ".join(ast.unparse(st) for st in node.body)
        guarded.append("validation_ui_evidence_failed" in body)
    assert guarded, "the `failed_records` branch #752 added is gone"
    assert any(guarded), \
        "the warning now claims #752 blocks; no failed_records branch raises the check"


def test_the_existential_finding_itself_is_still_stated():
    """#739's actual content must survive the correction: one page certifying the whole UI,
    and the r148 case that proved the cost."""
    text = _warning_text()
    assert "existential" in text and "r148" in text
    assert "12 of 14" in text


def test_no_other_gate_warning_claims_to_be_unenforced_while_blocking():
    """The rule, not the instance: a warning that names a check which DOES reach
    failed_checks may not also describe itself as merely reported."""
    src = GATE.read_text(encoding="utf-8")
    bad = []
    for m in re.finditer(r'"([^"]{80,900}?)"', src, re.S):
        blob = m.group(1)
        if "not enforced" not in blob.lower():
            continue
        named = re.findall(r"(deliverability_[a-z_]+|validation_[a-z_]+)", blob)
        for check in named:
            if f'"{check}"' in src and "failed_checks" in src:
                bad.append(f"{check}: {blob[:70]}")
    assert bad == [], (
        "these warnings describe a check as unenforced while the gate raises it: %s" % bad)
