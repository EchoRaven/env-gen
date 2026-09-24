"""FIX #282 — the framework's IntegrityError→REST mapping DISCARDS the real cause (tiktok r67, live).

#82 maps a DB integrity error onto the status the chains expect (FK 23503 → 404, unique
23505 → 409). Correct as a STATUS mapping — but the handler returns a fixed prose detail and
**logs nothing**, so which constraint/table/column actually failed is destroyed.

r67 (live) died on it. `POST /api/videos/1/like` → `404 {"detail":"referenced resource not
found"}` while `GET /api/videos/1` → **200** — the video demonstrably EXISTS. The real failure
was an FK violation on the OTHER column (the lane's `_get_or_create_profile` id not being a row
in the table `likes.user_id` references). The lane could not see that: nothing in the response,
nothing in `docker logs` (verified by hand — the grep for foreign key/IntegrityError/23503 on
the live container returned EMPTY). So "referenced resource not found" on an existing video is
not merely unactionable, it is actively MISLEADING — it points at the video. The run burned 7
post-cap cycles with no lane progress → FAIL-FAST abort.

Fix: log the ORIGINAL error (pgcode/sqlstate + driver text + request path) at ERROR before
translating. The HTTP response body is deliberately UNCHANGED — no contract change, no DB
internals leaked to API clients — the diagnosis goes to the server log the lane can read.
ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import multi_agent.runtime.backend_scaffold as bs  # noqa: E402

SRC = bs._INTEGRITY_HANDLER


def test_handler_still_maps_the_three_statuses():
    """#82's status mapping must survive untouched — chains depend on it."""
    assert "23503" in SRC and "404" in SRC
    assert "23505" in SRC and "409" in SRC
    assert "400" in SRC


def test_response_detail_prose_is_unchanged():
    """No contract change: the API body stays exactly what it was."""
    assert '"referenced resource not found"' in SRC
    assert '"duplicate resource"' in SRC
    assert '"integrity constraint violated"' in SRC


def test_original_error_is_logged_before_translating():
    """The r67 gap: the real cause must reach a log the lane can read."""
    low = SRC.lower()
    assert "logging" in low or "logger" in low, "handler must obtain a logger"
    # the driver's own message carries the constraint/table/column — it must be emitted
    assert "_orig" in SRC
    assert any(tok in low for tok in (".error(", ".exception(")), \
        "the original integrity error must be logged at ERROR level"


def test_log_line_carries_code_and_path():
    """A bare 'integrity error' log would repeat the r67 mistake — it must name the
    sqlstate/pgcode AND the request path so the lane knows WHICH call failed."""
    assert "code" in SRC
    assert "request" in SRC and ("url" in SRC.lower() or "path" in SRC.lower())


def test_logging_failure_can_never_break_the_response():
    """Diagnosis is best-effort: a broken logger must not turn a mapped 404 into a 500."""
    seg = SRC[SRC.find("_orig = "):]
    assert "try:" in seg and "except Exception:" in seg, \
        "the logging must be wrapped so it cannot raise into the handler"


def test_handler_still_compiles():
    compile(SRC, "<integrity_handler>", "exec")
