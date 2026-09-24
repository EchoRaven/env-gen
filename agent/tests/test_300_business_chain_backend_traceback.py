"""#300 — a business_chain 5xx failure must surface the backend traceback.

r81 M2 STUCK (95min, NO-CONVERGENCE ABORT): POST /api/comments/{id}/replies → 500.
business_endpoints_reachable failures attach the backend docker-logs traceback
(custom_routes.py:NNN — the real error), but business_chain failures showed only
the HTTP body ("Internal Server Error") — so the backend lane fixing the chain
500 was blind and never converged (while feed_for_you's md5 bug, surfaced WITH a
traceback via endpoints_reachable, got fixed). Attach the salient backend
traceback to business_chain 5xx failures too.
"""
import sys
from pathlib import Path
THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS.parent / "env_generator" / "llm_generator"))
from multi_agent.runtime.validation_runner import (  # noqa: E402
    _chain_broken_has_5xx, _business_chain_detail,
)


def test_has_5xx_on_500_step():
    assert _chain_broken_has_5xx(
        ["POST /api/comments/2/replies → 500 (expected [200, 201]; Internal Server Error)"]) is True


def test_has_5xx_on_internal_server_error_text():
    assert _chain_broken_has_5xx(["some step: Internal Server Error"]) is True


def test_has_5xx_false_on_404():
    assert _chain_broken_has_5xx(
        ["POST /api/comments/11/replies → 404 (expected [200, 201]; parent not found)"]) is False


def test_has_5xx_false_on_empty():
    assert _chain_broken_has_5xx([]) is False
    assert _chain_broken_has_5xx(None) is False


def test_detail_attaches_traceback_when_present():
    d = _business_chain_detail(
        ["POST /api/comments/2/replies → 500 (Internal Server Error)"],
        "custom_routes.py:1256 in post_reply — psycopg.errors.NotNullViolation")
    assert "backend traceback: custom_routes.py:1256 in post_reply" in d
    assert "replies → 500" in d


def test_detail_no_traceback_when_absent():
    d = _business_chain_detail(["POST /api/x → 500 (Internal Server Error)"], "")
    assert "backend traceback:" not in d
    assert "→ 500" in d


def test_detail_bounded_length():
    d = _business_chain_detail(["x" * 2000], "y" * 2000)
    assert len(d) <= 800
