"""#1202gw — #1202gs shipped dead: `compose logs` prefixes every line, the fixture did not.

`_last_exception_1202gs` anchors its frame regex on `^\\s*File "` and matches the exception on
`line.strip()`. Both hold for `docker logs <container>`, which is where the fixture in
test_1202gs came from. Production reads `docker compose logs`, which prefixes EVERY line with
the service and replica:

    backend-1  | Traceback (most recent call last):
    backend-1  |   File "/usr/local/lib/python3.11/site-packages/uvicorn/...", line 416, in run_asgi

so nothing matched and the helper returned "" for every 5xx. Caught on r100 live: two chain
steps recorded `PUT /api/sounds/10 -> 500` with no `server_traceback`, while the container log
read back through the framework's own code path was 10231 bytes and contained `Traceback`.

Fifth time this session that a fixture supplying a shape production never produces let a
broken fix pass its own tests. The lines below are captured verbatim from that live read.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.chain_executor import _last_exception_1202gs  # noqa: E402

# Verbatim from `compose -f generated/tiktok-web-r100/docker/docker-compose.yml logs backend`.
_COMPOSE_LOG = '''backend-1  | INFO:     172.18.0.1:52134 - "PUT /api/sounds/10 HTTP/1.1" 500 Internal Server Error
backend-1  | ERROR:    Exception in ASGI application
backend-1  | Traceback (most recent call last):
backend-1  |   File "/usr/local/lib/python3.11/site-packages/uvicorn/protocols/http/h11_impl.py", line 416, in run_asgi
backend-1  |     result = await app(  # type: ignore[func-returns-value]
backend-1  |              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
backend-1  |   File "/app/main.py", line 812, in _projected_put_api_sounds_id_31
backend-1  |     setattr(obj, k, v)
backend-1  | AttributeError: can't set attribute 'video_count'
backend-1  | INFO:     127.0.0.1:41000 - "GET /health HTTP/1.1" 200 OK
'''

# The unprefixed form must keep working — a plain `docker logs` read is still valid input.
_PLAIN_LOG = "\n".join(l.split("|", 1)[1][1:] if "|" in l else l
                       for l in _COMPOSE_LOG.strip().split("\n"))


def test_the_compose_prefix_does_not_hide_the_exception():
    out = _last_exception_1202gs(_COMPOSE_LOG)
    assert "AttributeError: can't set attribute 'video_count'" in out, (
        "the compose stream prefix still swallows the whole traceback: %r" % out)


def test_the_app_frame_survives_the_prefix():
    out = _last_exception_1202gs(_COMPOSE_LOG)
    assert "/app/main.py" in out and "812" in out, out
    assert "uvicorn" not in out and "site-packages" not in out, (
        "library frames crowd out the line the lane can act on: %s" % out)


def test_the_prefix_itself_is_not_carried_into_the_note():
    out = _last_exception_1202gs(_COMPOSE_LOG)
    assert "backend-1" not in out and "|" not in out, (
        "the note repeats the log plumbing back at the reader: %s" % out)


def test_the_unprefixed_form_still_works():
    """#1202gs's original input shape must not regress."""
    out = _last_exception_1202gs(_PLAIN_LOG)
    assert "AttributeError: can't set attribute 'video_count'" in out, out
    assert "/app/main.py" in out, out


def test_a_pipe_inside_a_message_is_not_mistaken_for_a_prefix():
    log = ('backend-1  | Traceback (most recent call last):\n'
           'backend-1  |   File "/app/main.py", line 5, in f\n'
           'backend-1  | ValueError: bad value: a|b\n')
    out = _last_exception_1202gs(log)
    assert "a|b" in out, "the value's own pipe was eaten as plumbing: %s" % out


def test_health_chatter_after_the_traceback_is_still_ignored():
    assert "GET /health" not in _last_exception_1202gs(_COMPOSE_LOG)
