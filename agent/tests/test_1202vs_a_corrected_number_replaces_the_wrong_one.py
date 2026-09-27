"""#1202vs: a corrected number replaces the one it corrects — it does not sit beside it.

The #743 P0 message read:

    Corpus: 90 of 129 runs end this way and 15 of them released
    (#755-corrected; 86 runs, not 90), so this is reported rather than blocking

Both counts in one sentence, the stale one in the position the reader trusts. The operator
who acts on this cannot tell which corpus this run is being judged against, and the sibling
message eight lines above gets it right — it states the corrected numbers and explains the
correction — so the two read as if they disagree about the same corpus.

The guard is structural rather than a spelling check on that one string: any message that
ends up carrying "…, not <other number>)" is the same mistake, appending the fix instead of
applying it.
"""
import ast
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import delivery_gate as _dg   # noqa: E402

_RUNTIME = pathlib.Path(_dg.__file__).parent
# Two conditions together, because either alone is ordinary prose: the text says it is
# CORRECTING something, and it also carries "…, not <number>)" — the superseded value,
# re-asserted in the same breath. "it answers 401, not 404)" is a contrast between two real
# outcomes and matches only the second half, which is why the second half alone will not do.
_CORRECTION = re.compile(r"correct(ed|ion|s)\b", re.I)
_SUPERSEDED_NUM = re.compile(r",\s*not\s+\d+\s*\)")


def _supersedes_its_own_number(text: str) -> bool:
    return bool(_CORRECTION.search(text) and _SUPERSEDED_NUM.search(text))


def _string_constants(path: pathlib.Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node


def test_the_p0_message_states_one_corpus_count():
    """Read by AST, so re-wrapping the literal cannot move this guard (#943)."""
    tree = ast.parse(pathlib.Path(_dg.__file__).read_text(encoding="utf-8"))
    msgs = [ast.literal_eval(n)
            for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and "P0 BUG task(s) are still open at the delivery cut" in n.value]
    # implicit concatenation folds to one constant, so there is exactly one
    assert len(msgs) == 1, f"expected one #743 P0 message, found {len(msgs)}"
    msg = msgs[0]
    assert "86 of 129" in msg, "the corrected count must be the one the reader sees first"
    assert "not 90" not in msg, "the superseded count must not be re-asserted beside it"


def test_no_runtime_message_carries_a_number_it_supersedes():
    """A ratchet, not a spelling check: the next append-instead-of-apply fails here."""
    offenders = []
    for py in sorted(_RUNTIME.glob("*.py")):
        for node in _string_constants(py):
            if _supersedes_its_own_number(node.value):
                offenders.append(f"{py.name}:{node.lineno} {node.value.strip()[:90]}")
    assert not offenders, (
        "these strings state a number and then tell the reader it is wrong, instead of "
        "replacing it:\n  " + "\n  ".join(offenders))


def test_the_detector_sees_the_shape_it_is_meant_to_catch():
    """Planted control — a guard that matches nothing proves nothing (#1202kx's lesson
    about empty counter-examples)."""
    assert _supersedes_its_own_number(
        "Corpus: 90 of 129 runs (#755-corrected; 86 runs, not 90), so")
    assert not _supersedes_its_own_number(
        "Corpus: 86 of 129 runs (#755 corrected an earlier count of 90), so")
    # a contrast between two real outcomes, not a superseded value
    assert not _supersedes_its_own_number("it answers 401, not 404).")
    # a correction that carries no stale number is fine
    assert not _supersedes_its_own_number("#755 corrected this count after a recount.")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
