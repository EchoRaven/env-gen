r"""#1202ui: routes the app SERVES that no gate examines were reported only to a logger.

`unregistered_routes_1202h` finds routes the backend serves that the contract never declared,
and its own warning states the cost precisely: "no gate sees them -- not auth, not
owner-scoping, not coverage." In an environment built to measure what an agent can do, an
endpoint no gate examines is not a reporting nicety.

It wrote a `logger.warning` and nothing else. #947's rule is that a measurement existing only
in a log line is not a measurement, and the run log is not kept -- the same gap that made
#1202tk necessary after 41 of 77 runs went green and never shipped with no record of why.

MEASURED across the corpus logs: 15 runs carry this warning, up to 7 routes in one of them.
r134 raised it on five REAL business routes -- `GET /api/feed/for-you`,
`GET/POST /api/videos/{}/comments`, `POST/DELETE /api/videos/{}/like` -- not the debug
scaffolding (`/api/debug_routes2`, `/api/admin/fix`) the warning's own example names.

DELIBERATELY NOT A GATE. Whether an unregistered route should block delivery is a separate
decision with real risk both ways: auto-registering lets a lane bypass the contract, and
blocking halts runs where the lane legitimately added a route. What it cannot be is invisible
once the run is over.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.scaffolder import (  # noqa: E402
    record_unregistered_routes_1202ui as record,
)

SCAFFOLDER = LLM_DIR / "multi_agent" / "runtime" / "scaffolder.py"


def _rows(d):
    p = Path(d) / "logs" / "unregistered_routes_1202h.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_the_finding_lands_on_disk():
    d = Path(tempfile.mkdtemp())
    assert record(d, ["GET /api/feed/for-you", "POST /api/videos/{}/like"]) is True
    rows = _rows(d)
    assert len(rows) == 1 and rows[0]["count"] == 2
    assert "GET /api/feed/for-you" in rows[0]["routes"]
    assert rows[0]["at"] > 0


def test_it_appends_rather_than_overwrites():
    """A run raises this on several ticks; the artifact is a history, not a snapshot."""
    d = Path(tempfile.mkdtemp())
    record(d, ["a"])
    record(d, ["a", "b"])
    assert [r["count"] for r in _rows(d)] == [1, 2]


def test_it_can_never_break_the_scaffold():
    """Scaffolding must not die because an advisory write failed."""
    assert record("/proc/nonexistent/nope", ["x"]) is False
    assert record(None, None) is False


def test_the_warning_site_actually_records():
    """★ Reachability. The point of #1202ui is that the EXISTING warning now persists, so a
    version where the call is dropped but the helper survives must fail."""
    src = SCAFFOLDER.read_text(encoding="utf-8")
    i = src.index("#1202h %d route(s) are SERVED but never registered")
    j = src.index("except Exception as _e1202h", i)
    assert "record_unregistered_routes_1202ui(" in src[i:j], \
        "the warning still reports the finding without persisting it"


def test_it_does_not_quietly_become_a_gate():
    """The decision this fix deliberately does NOT make. If someone later wants unregistered
    routes to block, that is its own ticket with its own evidence -- not a side effect here."""
    src = SCAFFOLDER.read_text(encoding="utf-8")
    i = src.index("def record_unregistered_routes_1202ui")
    j = src.index("\ndef ", i + 10)
    body = src[i:j]
    assert "failed_checks" not in body, body[:200]
