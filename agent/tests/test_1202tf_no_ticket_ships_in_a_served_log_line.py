r"""#1202tf: a framework ticket must not ship inside the delivered app's own log messages.

`#1202te` closed the JS comment leak and recorded the Python half as a separate decision.
This is that decision.

The tags sit in RUNTIME strings -- `logger.warning("#1202ki restored %d FRAMEWORK route(s)…")`
-- so the scrub cannot take them: `#1202mi`'s contract is that it never rewrites code, and a
log format string is code. That contract stands untouched. What changes is the TEMPLATE: the
skeleton simply stops writing the ticket into the message.

WHAT THE TAGS COST: they ship in the delivered environment. Whoever runs the env reads
`#1202ki restored 3 FRAMEWORK route(s)` in the container log -- a number that means nothing to
them and names our internal history, which is the standing rule against internal tags in
generated output.

THE JUSTIFICATION FOR KEEPING THEM DID NOT HOLD. `#1202mi`'s own test says of this exact case:
*"Load bearing: … detectors read these back out of a run's logs."* Checked rather than
trusted, because a comment is not evidence:

    readers of these strings anywhere in the package     0
    corpus run logs containing "#1166 restored"          0  (likewise #1202ki, #807)

The sibling half of that claim IS real and is preserved: `test_1166_dropped_routes_…` asserts
the restore announces itself. That is a property of the ANNOUNCEMENT, not of the ticket, so it
is re-anchored on the message and now forbids the tag.

WHY THIS ASSERTS ON THE RENDERED ARTIFACT, not on the template: a first version scanned
`backend_skeleton.py` for message-shaped lines and produced six false positives -- the
framework's OWN logging during projection, and emitted COMMENTS the scrub already handles at
write time. Heuristics over a template cannot tell those apart; the rendered file can, because
it is the thing that ships. Rendering also parses, and that caught a real break: removing
`(FIX #130)` from a `print(...)` line took the closing paren with it, and every delivered
`seed_data.py` would have been a SyntaxError. The scrub's own "could not parse" warning is
what surfaced it.

★ The census needed two corrections before it was right, both worth keeping: a bare
`#\d{3,4}` reported 1,074 "leaks" in .css that were hex colours, then `#666`/`#333` inside an
HTML template string in main.py. Position, not pattern, tells a ticket from a colour -- which
is exactly what `#1202mi`'s own test says.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.backend_skeleton import (  # noqa: E402
    render_seed_data, render_skeleton_main)
from multi_agent.runtime.provenance_scrub import scrub_provenance_1202mi as scrub  # noqa: E402

SKELETON = LLM_DIR / "multi_agent" / "runtime" / "backend_skeleton.py"

# A ticket reference, not a colour. `#1202xx` and `FIX #N` are unambiguous; a bare `#NNN`
# counts only in prose (a letter or a possessive follows), which is how a message reads and a
# hex colour does not.
_TICKET = re.compile(
    r"#1202[a-z]{2}\b|\b(?:FIX|PROPOSAL)[ -]?#\d{1,4}\b|#\d{3,4}(?=['\"]?s\b|\s+[a-z])")

_TABLES = {"videos": {"columns": [{"name": "id", "type": "integer", "primary_key": True},
                                  {"name": "title", "type": "string"}]}}
_ENDPOINTS = [{"id": "e1", "method": "GET", "path": "/api/videos", "status": "implemented"}]


def _rendered():
    """The two files the skeleton writes, as they reach disk -- rendered, then scrubbed."""
    return {"main.py": scrub(render_skeleton_main(_ENDPOINTS, _TABLES), "main.py"),
            "seed_data.py": scrub(render_seed_data(_TABLES), "seed_data.py")}


@pytest.mark.parametrize("name", ["main.py", "seed_data.py"])
def test_the_delivered_file_parses(name):
    """Rendering is only a check if the result is real Python. Removing `(FIX #130)` from a
    `print(...)` once took its closing paren with it, and this is what noticed."""
    src = _rendered()[name]
    try:
        ast.parse(src)
    except SyntaxError as exc:
        raise AssertionError(f"{name} does not parse: {exc.msg} at line {exc.lineno}: "
                             f"{src.splitlines()[(exc.lineno or 1) - 1][:120]}")


@pytest.mark.parametrize("name", ["main.py", "seed_data.py"])
def test_no_ticket_reaches_the_delivered_file(name):
    src = _rendered()[name]
    offenders = [(i, l.strip()[:110]) for i, l in enumerate(src.split("\n"), 1)
                 if _TICKET.search(l)]
    assert offenders == [], (
        f"{name} ships framework tickets. A COMMENT should have been scrubbed at write time "
        f"(check #1202mi could parse the file); a LOG MESSAGE must lose the reference in the "
        f"template and keep its sentence: {offenders}")


def test_the_messages_themselves_survived():
    """Non-vacuity, and the property the tickets were standing in for: each repair still
    announces what it did."""
    main = _rendered()["main.py"]
    for phrase in ("restored %d lane route(s)", "restored %d FRAMEWORK route(s)"):
        assert phrase in main, phrase
    seed = _rendered()["seed_data.py"]
    for phrase in ("pruned %d of %d %s row(s)",
                   "fingerprint matched but a seed-provided table is EMPTY"):
        assert phrase in seed, phrase


def test_the_framework_keeps_its_own_provenance():
    """Not 'fixed' by deleting our history: the tickets stay in the comments around the code,
    which is where the next reader of the skeleton needs them."""
    src = SKELETON.read_text(encoding="utf-8")
    for ticket in ("#1166", "#1202ki", "#1202db", "#807", "#528"):
        assert ticket in src, f"{ticket} vanished from the framework's own source"


def test_the_census_pattern_does_not_call_a_colour_a_ticket():
    """The mistake this file made twice before it was right."""
    assert not _TICKET.search("    label {{ color:#333; }}")
    assert not _TICKET.search('BRAND = "#528"')
    assert not _TICKET.search('return {"colour": "#111"}')
    assert _TICKET.search("so #528's ordering guarantee holds")
    assert _TICKET.search('"#1202ki restored %d route(s)"')
    assert _TICKET.search("re-seeding (FIX #130)")
