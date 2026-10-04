r"""#1203e6: the log cut the front off a string that was already a tail, throwing away the cause.

`RunHub` reports a failed `compose up` as:

    _cause1119 = _salient_stderr_1119(_stderr748)      # -> _salient_error(stderr, cap=500)
    _logger.warning("... Cause: %s", run_id, rc, _cause1119[:400] or "...")

`_salient_error` returns the last few MARKER-matching lines, and when nothing matches a marker
it returns `text[-cap:]` — "never the misleading prefix", as #182 put it. The caller then sliced
`[:400]` off the front of that tail, undoing it.

`Error response from daemon:` does not contain the marker `error:` (there is no colon straight
after "error"), so a compose failure reported that way takes exactly the tail path and is exactly
the case the second slice destroys.

★ Live, twice within one hour of r152: the operator-facing line read `Cause: d` and
`Cause: 1  Creating` — compose progress lines — while the `compose_stderr` field stored beside it
(capped once at 500, never re-sliced) ended with

    "...You have to remove (or rename) that container to be able to reuse that name."
    "Error response from daemon: No such container: e702cb63e4c78e78268f95c297fe2e34..."

The log named a container being created; the cause was a stale container from another run, with
146 containers from other runs on the host at the time.

The fix is one string with one cap and no second slice, so the class cannot return here.

And because the causes were visible at last, two of them turned out to match none of
`_COMPOSE_FATAL_1202DC`'s host-fault tokens. Measured over all 498 `compose_stderr` records on
disk: `No such container` appears in 26, across 25 DIFFERENT runs; the name clash in 1. Both are
docker's own bookkeeping — a name held by a run nobody cleaned up, or a container that vanished
mid-operation — and no lane edit reaches either.
"""
import inspect
import os
import re
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.framework_validation import _salient_error  # noqa: E402
from multi_agent.runtime.hubs.runhub import service as SV  # noqa: E402
from multi_agent.runtime.visual_fidelity import _host_fatal_1202de  # noqa: E402

# r152's two stored causes, verbatim from its runhub_runs.json (truncated heads and all).
R152_NAME_CLASH = (
    'd\n Container tiktok-web-r152-database-1  Creating\n'
    + ' Container tiktok-web-r152-backend-1  Creating\n' * 12
    + ' Container tiktok-web-r152-frontend-1  Creating\n'
    + 'Error response from daemon: Conflict. The container name "/tiktok-web-r152-backend-1" is '
      'already in use by container "fb861e2316bc7d7b430c66dc206cebfdcff3c90fc464574174c3b8de87b8'
      'cab0". You have to remove (or rename) that container to be able to reuse that name.')
R152_NO_SUCH = (
    '1  Creating\n Container tiktok-web-r152-frontend-1  Created\n'
    + ' Container tiktok-web-r152-database-1  Starting\n' * 12
    + ' Container tiktok-web-r152-frontend-1  Starting\n'
      'Error response from daemon: No such container: '
      'e702cb63e4c78e78268f95c297fe2e3484a395c148b1f572fed7b9f397759d60')


# ---------------------------------------------------------------- the slice

def _log_stanza(code_only=True):
    """Bounded by two landmarks (#943), and with comment lines STRIPPED.

    ★ The first draft of this helper returned the raw slice, and then failed — because the patch's
    own comment quotes the expression it removed (`this was _cause1119[:400]`). A source assertion
    that cannot tell code from the comment explaining it will keep catching the explanation; same
    shape as #1202w3, where a comment written about a ratchet blinded that ratchet."""
    src = inspect.getsource(SV)
    i = src.index('"compose up FAILED for run %s (rc=%s)')
    j = src.index('self._emit("run_completed"', i)
    body = src[i:j]
    if not code_only:
        return body
    return "\n".join(ln for ln in body.split("\n") if not ln.lstrip().startswith("#"))


def test_the_cause_is_not_sliced_from_the_front():
    """★ The defect in one assertion."""
    s = _log_stanza()
    assert "_cause1119[:400]" not in s, "the tail is being re-cut from the front:\n" + s
    assert re.search(r"_cause1119 or ", s), s


def test_the_fallback_message_survives():
    """An empty stderr must still say what to check."""
    assert "compose produced no stderr" in _log_stanza()


def test_only_one_cap_remains_on_the_logged_value():
    """One string, one cap: the LOGGED line must not re-cap what the selector already sized.
    (The stored `compose_stderr=` field keeps its own `[:500]`, which equals the selector's cap
    and so removes nothing — that one is a belt, not a second opinion.) Comments stripped, for
    the reason `_log_stanza` explains."""
    assert not re.findall(r"_cause1119\[:\d+\]", _log_stanza()), _log_stanza()


# ---------------------------------------------------------------- what the slice was hiding

def test_r152s_name_clash_cause_survives_the_selector():
    """★ End to end on the shipped selector: the cause must be in what gets logged."""
    out = _salient_error(R152_NAME_CLASH, cap=500)
    assert "You have to remove (or rename)" in out, out[-200:]


def test_r152s_no_such_container_cause_survives_the_selector():
    out = _salient_error(R152_NO_SUCH, cap=500)
    assert "No such container" in out, out[-200:]


def test_a_front_slice_would_have_lost_both():
    """★ The counter-proof stated rather than assumed: the pre-#1203e6 expression on the same
    two inputs keeps neither cause. r152's stored field was exactly 500 characters, so the real
    stderr was at least that long — the fixtures are padded to match, because on a SHORT stderr
    the old slice happened to be harmless and would have proved nothing (#1202lq)."""
    for text in (R152_NAME_CLASH, R152_NO_SUCH):
        assert len(text) >= 500, (len(text), "fixture too short to reproduce the truncation")
        old = _salient_error(text, cap=500)[:400]
        assert "You have to remove" not in old and "No such container" not in old, old[-120:]


def test_error_response_from_daemon_is_not_a_marker_hit():
    """Why these take the tail path at all: the marker is `error:`, with a colon."""
    assert "error:" not in "Error response from daemon: Conflict.".lower()


# ---------------------------------------------------------------- the two host faults

def test_the_name_clash_is_a_host_fault():
    """★ 1 record on disk, and the one that cost r152 a boot."""
    assert _host_fatal_1202de(R152_NAME_CLASH) == "You have to remove (or rename) that container"


def test_no_such_container_is_a_host_fault():
    """★ 26 records across 25 different runs, previously matching no token."""
    assert _host_fatal_1202de(R152_NO_SUCH) == "No such container"


def test_the_tokens_that_were_already_there_still_match():
    """The five pre-existing signatures must be untouched."""
    for text, want in (("Error: port is already allocated", "port is already allocated"),
                       ("could not find an available, non-overlapping address pool",
                        "address pool"),
                       ("initdb: no space left on device", "no space left on device"),
                       ("bind: address already in use", "bind: address already in use"),
                       ("Cannot connect to the Docker daemon at unix:///var/run/docker.sock",
                        "Cannot connect to the Docker daemon")):
        assert _host_fatal_1202de(text) == want, (text, _host_fatal_1202de(text))


def test_an_application_build_failure_is_still_not_a_host_fault():
    """★ The invariant #1202dc was built for: a real build error must not be excused."""
    for text in ("[vite:esbuild] Transform failed: /app/src/components/TenantPicker.jsx:15:0: "
                 'ERROR: Unexpected "}"',
                 "the attribute `version` is obsolete, it will be ignored",
                 "npm ERR! code ELIFECYCLE"):
        assert _host_fatal_1202de(text) == "", (text, _host_fatal_1202de(text))


def test_every_token_carries_a_why():
    """#1202dc's list is (token, why) pairs; a token with no explanation would reach an operator
    as a bare string."""
    from multi_agent.runtime.visual_fidelity import _COMPOSE_FATAL_1202DC
    for token, why in _COMPOSE_FATAL_1202DC:
        assert token and isinstance(why, str) and len(why) > 20, (token, why)
