r"""#1202ae: a detector that crashed must not read as a detector that found nothing.

Self-review of this session's own additions, using the rule the session spent its time
enforcing on other people's code. Sixteen of my new functions swallow an exception and return
a default; the question #883 asks is which DIRECTION that default fails in.

Most fail safely — toward doing more or saying more:

    state_changed_1202ad  -> True    always report
    _driver_is_live_1198  -> False   treat as dead, rebuild
    recover_for_retry     -> False   claim no recovery

Seven fail the other way, toward "nothing found", and three of those had no announcement at
all. The gate wrappers do call `_gate_absent_792`, but they only see the inner function's
RETURN VALUE — so a crash inside produced `[]`, the wrapper reported clean, and the
announcement never fired:

    auth_override_findings_1202s   a SECURITY gate returning "no bypass"
    _widens_auth_1202s             "not provisioning" -> nothing blocked
    unregistered_routes_1202h      "no undeclared routes"
    unstaged_asset_refs_1202j      "no missing assets"

That is exactly the shape this session kept finding elsewhere — #1201's warn-once exists
because of it, #1039's live row count died of it, the seed audit reported clean while
examining zero tables — and I wrote it into a security gate two days ago.

They now announce through `warn_once_1201` and still return their safe default, so behaviour
is unchanged and the silence is gone.
"""

import logging
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime import message_format as mf  # noqa: E402
from multi_agent.runtime.backend_audit import auth_override_findings_1202s  # noqa: E402
from multi_agent.runtime.backend_skeleton import unregistered_routes_1202h  # noqa: E402
from multi_agent.runtime.frontend_scaffold import unstaged_asset_refs_1202j  # noqa: E402


def _fresh():
    mf._WARNED_1201.clear()


def test_the_auth_gate_says_so_when_it_cannot_run(caplog):
    _fresh()
    with caplog.at_level(logging.WARNING):
        out = auth_override_findings_1202s(object())      # not a path -> raises inside
    assert out == []                                       # safe default preserved
    assert "1202s" in caplog.text
    assert "NOT known clean" in caplog.text


def test_the_route_scan_says_so(caplog):
    _fresh()
    with caplog.at_level(logging.WARNING):
        assert unregistered_routes_1202h(object(), object()) == []
    assert "NOT known declared" in caplog.text


def test_the_asset_scan_says_so(caplog):
    _fresh()
    with caplog.at_level(logging.WARNING):
        assert unstaged_asset_refs_1202j(object(), object()) == []
    assert "NOT known staged" in caplog.text


def test_a_healthy_run_stays_silent(tmp_path, caplog):
    """The announcement is for failure only — a clean tree must not warn."""
    _fresh()
    b = tmp_path / "backend"
    b.mkdir()
    (b / "custom_routes.py").write_text("x = 1\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        assert auth_override_findings_1202s(b) == []
    assert "1202s" not in caplog.text


def test_it_is_said_once_not_every_call(caplog):
    """warn_once_1201 semantics: a mechanism that is down stays down; one line is enough."""
    _fresh()
    with caplog.at_level(logging.WARNING):
        for _ in range(5):
            auth_override_findings_1202s(object())
    assert caplog.text.count("1202s") == 1
