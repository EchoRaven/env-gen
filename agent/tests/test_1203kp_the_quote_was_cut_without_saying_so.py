"""#1203kp: the quoted earlier failure was cut at 80 characters with nothing to say so.

#1202oe tells a step that it is NOT the first failure in its chain and quotes what the earlier
step said. The quote was a bare `[:80]`, so a reader takes the parenthetical for the whole of
it — and the cut lands mid-word.

Found by the length-spike instrument, which is what a bare `[:N]` looks like from outside:
across the corpus's 300 such quotes the length histogram spikes at exactly 80 — 93 of them, 62
in the modern era — against 21, 46 and 22 for the shapes that fit. r175 quotes
`…save failed at step 'list_participant_conversation` (the step is `conversations`); r176
quotes `…the table is populated, so`, where the clause dropped is the actionable half.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import chain_executor as CE  # noqa: E402


def _chain(steps):
    return {"name": "c", "steps": steps}


def _run(monkeypatch, first_status, long_note):
    """Drive execute_chain so step 2 inherits #1202oe's quote of step 1."""
    calls = {"n": 0}

    def _fake(method, url, *, token=None, body=None, timeout=None, headers=None, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"status": first_status, "body_text": long_note, "error": None, "headers": {}}
        return {"status": 404, "body_text": '{"detail":"parent resource not found"}',
                "error": None, "headers": {}}

    monkeypatch.setattr(CE, "_http", _fake)
    out = CE.execute_chain("http://127.0.0.1:1", _chain([
        {"action": "first", "method": "POST", "path": "/api/a", "expect": [200, 201]},
        {"action": "second", "method": "POST", "path": "/api/b", "expect": [200, 201]},
    ]))
    notes = [str(s.get("note") or "") for s in (out.get("steps") or [])]
    return [n for n in notes if "NOT THE FIRST FAILURE" in n]


_LONG = '{"detail":"' + ("x" * 300) + '"}'
_SHORT = '{"detail":"short"}'


def test_a_cut_quote_says_it_was_cut_1203kp(monkeypatch):
    got = _run(monkeypatch, 500, _LONG)
    assert got, "the fixture must produce #1202oe's sentence"
    assert "…" in got[0], (
        "#1034: a quote the reader cannot tell is partial reads as the whole of what the "
        "earlier step said\n" + got[0])


def test_a_quote_that_fits_is_not_marked_1203kp(monkeypatch):
    got = _run(monkeypatch, 500, _SHORT)
    assert got, got
    quoted = got[0].split("failed earlier (", 1)[1].split("). Any", 1)[0]
    assert "…" not in quoted, ("a quote that fits must not claim a cut", quoted)
    assert "short" in quoted, quoted


def test_the_cut_is_at_eighty_and_the_budget_did_not_grow_1203kp(monkeypatch):
    """Only the cut is declared, not widened: this is a QUOTE inside another note (#1202vx),
    and the full text is on the earlier step's own record."""
    got = _run(monkeypatch, 500, _LONG)
    quoted = got[0].split("failed earlier (", 1)[1].split("). Any", 1)[0]
    assert len(quoted) == 81, (len(quoted), quoted[-20:])   # 80 + the marker
    assert quoted.endswith("…"), quoted[-20:]


def test_the_rest_of_the_sentence_is_untouched_1203kp(monkeypatch):
    got = _run(monkeypatch, 500, _LONG)
    assert "fix that one first and re-run before treating this step as a defect" in got[0]
    assert "`POST /api/a` failed earlier" in got[0], "it still names the step to look at"
