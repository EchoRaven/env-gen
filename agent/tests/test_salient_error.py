"""FIX #182 — the STUCK-ABORT "Real blocker" message (framework_validation.py _root_detail) built
the diagnostic from check.detail[:400], a blind PREFIX slice of the docker build log. For a
docker_up failure that prefix is the backend build's cached steps — meaningless fragments (image
hashes, a chopped 'ghcr.io'->'cr.io') — while the ACTUAL error (e.g. a frontend Vite
'LoginPage' has already been declared) is deeper/at the end. gmtiktok aborted with
"Real blocker: docker_up: cr.io/astral-sh/uv" and red-herring'd the debugger toward a nonexistent
wrong-registry bug. _salient_error surfaces the real ERROR line(s) instead, falling back to the
TAIL (not the prefix) when no marker matches. Pure; LOCAL-ONLY.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.framework_validation import _salient_error  # noqa: E402


def test_surfaces_real_error_not_the_cached_build_prefix():
    # the exact gmtiktok shape: cached backend build prefix, real frontend error at the end.
    detail = ("Sending build context to Docker daemon 50kB\n"
              "Step 1/10 : FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim\n"
              " ---> 785c56f403d0\n"
              "Step 2/10 : WORKDIR /app\n ---> Using cache\n"
              "Step 4/10 : RUN uv pip install\n ---> Using cache\n"
              "error: 'LoginPage' has already been declared in src/App.jsx\n"
              "build failed")
    out = _salient_error(detail)
    assert "LoginPage" in out and "has already been declared" in out
    assert "cr.io" not in out and "ghcr.io" not in out  # the red-herring prefix is gone


def test_falls_back_to_tail_not_prefix_when_no_marker():
    detail = "Step 1/10 : FROM ghcr.io/astral\n" + ("filler cached step line\n" * 40) + "the container never became healthy"
    out = _salient_error(detail)
    assert "never became healthy" in out    # real failure lives at the tail
    assert "FROM ghcr.io" not in out         # NOT the misleading prefix


def test_handles_escaped_newlines():
    detail = "Step 1 : FROM ghcr.io/x\\n ---> abc\\nerror: something broke in the build"
    out = _salient_error(detail)
    assert "something broke" in out


def test_empty_and_none():
    assert _salient_error("") == ""
    assert _salient_error(None) == ""


def test_caps_length():
    assert len(_salient_error("error: " + "x" * 5000)) <= 400


def test_surfaces_postgres_relation_not_exist_over_build_banner():
    # #212 (r15): docker_up failed at DB INIT, but the blind prefix slice showed
    # only the build-context banner ("Sending build context to Docker daemon …"),
    # hiding the real cause and sending the frontend chasing a phantom api.js
    # build error for 20min. The salient extractor must surface the postgres
    # ERROR line (matched via the 'error:' marker) instead of the banner.
    detail = (
        "Sending build context to Docker daemon  158MB\n"
        "Step 1/8 : FROM postgres:16\n"
        ' db-1  | 2026-07-18 20:05 UTC [1] ERROR:  relation "sounds" does not exist\n'
        " db-1  | STATEMENT:  CREATE TABLE videos ( sound_id INTEGER REFERENCES sounds(id) )"
    )
    out = _salient_error(detail)
    assert 'relation "sounds" does not exist' in out
    assert "Sending build context" not in out
