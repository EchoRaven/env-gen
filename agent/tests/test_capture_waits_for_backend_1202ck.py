"""#1202ck — the visual capture waits for the app to be able to ANSWER, not just to accept
a connection.

The readiness loop broke the moment the FRONTEND answered. `be_port` was resolved beside it
and never probed, so a capture could start while the backend was still coming up — the
frontend serves static files in seconds, the backend does not. Every page then renders its
empty state and the round scores as if the app were broken.

All three score collapses measured across r30/r34/r35 are the same race between the capture
and a compose recycle. Two surfaced as ERR_CONNECTION_REFUSED (#1202cc). r30's did not: its
log reads `docker up -d` at 14:42:03, then "#1189 navigation ... waited 12s for the origin
to come back (compose recycle)", then a round that went 0.42 -> 0.15. #1189 waits for the
origin to accept a connection, which is not the app being ready.

LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

VF = LLM / "multi_agent" / "runtime" / "visual_fidelity.py"


def _src():
    return VF.read_text(encoding="utf-8")


def test_the_capture_waits_for_the_backend():
    src = _src()
    assert "wait_backend_ready as _wbr1202ck" in src
    assert "_wbr1202ck(project_dir, timeout_s=90)" in src


def test_the_wait_happens_before_any_screen_is_captured():
    """#943: landmark anchors. It must sit after the port-resolution loop and before the
    token mint that precedes navigation — a wait placed after the captures would be inert."""
    src = _src()
    wait = src.index("_wbr1202ck(project_dir")
    assert src.index("could not resolve the app's OWN frontend") < wait
    assert wait < src.index("token = _mint_token(be_port")


def test_it_reuses_the_established_readiness_helper():
    """#555 established that HTTP liveness is necessary but NOT sufficient: FastAPI answers
    while Postgres is still starting, so the helper also clears a DB-touching probe. A
    hand-rolled GET here would reintroduce exactly that hole."""
    vr = (LLM / "multi_agent" / "runtime" / "validation_runner.py").read_text(encoding="utf-8")
    i = vr.index("def wait_backend_ready(")
    body = vr[i:vr.index("\ndef ", i + 10)]
    assert "_db_readiness_probe_ok" in body


def test_a_backend_that_never_comes_up_still_captures():
    """The capture must not become MORE likely to skip: if the backend never answers the
    round proceeds exactly as it does today, so this can only delay a capture that was
    going to be taken anyway."""
    src = _src()
    i = src.index("_wbr1202ck(project_dir")
    stanza = src[src.rindex("try:", 0, i):src.index("auth_measured = any", i)]
    assert "_LOG.warning" in stanza, "must use the module logger; `logger` is unbound here (#940)"
    assert "return" not in stanza, "a non-ready backend must not abort the round"


def test_the_wait_is_bounded():
    """An unbounded wait would hang the gate on a genuinely dead stack."""
    assert "timeout_s=90" in _src()


def test_the_guard_cannot_take_the_run_down():
    """Same rule as every other hook added this session."""
    src = _src()
    i = src.index("_wbr1202ck(project_dir")
    assert src.rindex("try:", 0, i) < i < src.index("except Exception:", i)
