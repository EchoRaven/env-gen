"""#1202lv — the wrong-target notice told a refused probe that something answered.

GROUND TRUTH (tiktok-web-r121 resume #3, live):

    11:21:58  #1134b run ports published for the wrong-target notice: 8000,3001,8081
    11:33:59  [backend] test_api POST http://localhost:8082/oauth/register
              → Request failed: [Errno 111] Connection refused
    11:41:35  [backend] test_api GET  http://localhost:8082/health      (again)

8082 is that run's CONTAINER-internal API port — its compose says `API_PORT: 8082` and
`ports: - "3001:8082"` — which is precisely why a lane reading the compose file picks it up.
From the host the answer was 3001.

#1134 DID fire (verified by calling it with that run's published ports: it returns a notice
for :8082 and none for :3001/:8081, and `_with_notices_1116` renders notices into the text
the caller sees). What it said was wrong: "Whatever answered is a DIFFERENT service on this
host" — nothing answered. #949 settled that a mis-attribution is worse than silence, because
it sends the reader somewhere real to look for something that never happened.

★ What this is NOT: a second port resolver. The first draft of this fix parsed the compose
file again to name the host port — a mechanism #1134 already implements, wired at
orchestrator.py's `#1134b`. #665/#1136's lesson is that the copy drifts, and #1136 WAS that
drift. Deleted before commit; only the wording is changed here.
"""
import inspect

import pytest

from env_generator.llm_generator.tools import runtime_tools as rt

PORTS = "8000,3001,8081"


@pytest.fixture(autouse=True)
def _ports(monkeypatch):
    monkeypatch.setenv("ENVGEN_RUN_HTTP_PORTS", PORTS)


def test_a_refusal_does_not_claim_anything_answered():
    n = rt.foreign_target_notice_1134("http://localhost:8082/oauth/register", answered=False)
    assert n, "the notice must still fire — the port is still wrong"
    assert "Whatever answered" not in n
    assert "nothing is listening" in n
    assert "1202lv" in n


def test_a_refusal_explains_why_the_port_looked_right():
    """The compose file legitimately shows the container port; say so, or the lane keeps
    reading it as evidence the service is down (r121 probed :8082 twice)."""
    n = rt.foreign_target_notice_1134("http://localhost:8082/health", answered=False)
    assert "CONTAINER-internal" in n
    assert "3001:8082" in n, "a concrete mapping, not an abstraction"
    assert "not evidence the service is down" in n


def test_an_answered_probe_keeps_the_original_sentence():
    """★ Non-regression: #1134's whole point is that a REPLY from a stranger is not evidence
    about this product."""
    n = rt.foreign_target_notice_1134("http://localhost:8082/health", answered=True)
    assert "Whatever answered is a DIFFERENT service" in n
    assert "do not file it as a defect" in n


def test_both_wordings_name_the_right_targets():
    for answered in (True, False):
        n = rt.foreign_target_notice_1134("http://localhost:8082/health", answered=answered)
        for p in ("3001", "8000", "8081"):
            assert p in n
        assert "localhost:3001" in n


def test_the_run_s_own_ports_are_still_silent():
    for url in ("http://localhost:3001/health", "http://localhost:8081/",
                "http://localhost:8000/"):
        assert rt.foreign_target_notice_1134(url, answered=False) == ""
        assert rt.foreign_target_notice_1134(url, answered=True) == ""


def test_default_stays_answered_for_existing_callers():
    a = rt.foreign_target_notice_1134("http://localhost:8082/health")
    b = rt.foreign_target_notice_1134("http://localhost:8082/health", answered=True)
    assert a == b


def test_an_unset_allowlist_says_nothing(monkeypatch):
    """Unknown must never become a claim — #1134's own rule."""
    monkeypatch.delenv("ENVGEN_RUN_HTTP_PORTS", raising=False)
    assert rt.foreign_target_notice_1134("http://localhost:8082/x", answered=False) == ""


def test_the_caller_derives_answered_from_the_result():
    """★ Reachability: only the result knows. An HTTP error still carries a status; a
    transport failure carries none."""
    src = inspect.getsource(rt.TestAPITool.execute)
    assert "answered=" in src, "the notice is still told nothing about what happened"
    assert "_answered_1202lv" in src
    assert 'data.get("status")' in src, (
        "an HTTP 500 from a stranger DID answer — deriving this from success alone would "
        "call it a refusal")


def test_no_second_port_resolver_was_added():
    """#665/#1136: the copy drifts. #1134's allowlist is the one source."""
    src = inspect.getsource(rt)
    assert "_published_port_hint_1202lv" not in src
    # Assert on PARSING, not on mentions: both surviving occurrences of the filename are
    # prose inside agent-facing messages, which is the point of naming it. The first draft of
    # this assertion counted mentions and failed for the right module for the wrong reason.
    assert "yaml.safe_load" not in src, "runtime_tools must not parse compose itself"
    assert '"docker" / "docker-compose.yml"' not in src
    assert 'docker/docker-compose.yml"' not in src.replace(
        "docker/docker-compose.yml — read them", "")
