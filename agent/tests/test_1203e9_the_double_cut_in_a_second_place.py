r"""#1203e9: #1203e6's double-cut, in a second place, made more frequent by #1203e6 itself.

`remediation_dispatcher` replaces `detail` with `_salient_978(detail, cap=600)` — the selector
that returns the last marker-matching lines, or `text[-cap:]` when nothing matches ("never the
misleading prefix", #182) — and then its host-fault log line printed `str(detail)[:200]`, cutting
the FRONT off that tail.

★ r154, live: the line read `Detail: nfusion"`, a mid-word fragment, while the cause itself was
printed correctly beside it through `%r`.

MEASURED over the run logs on disk: 14 of these lines exist. 13 are readable — r149's
`no space left on device` matches a marker, so the selector returns whole lines and the front 200
of them starts at a sentence. One is mangled, and it is exactly the token class #1203e6 ADDED:
`Error response from daemon: Conflict. The container name ... is already in use` contains no
`error:` marker (there is no colon straight after "error"), so it takes the tail branch. #1203e6
also added `No such container`, which appears in 26 records across 25 runs and will take the same
branch. My own patch made this more frequent — the same shape as #1203d6 exposing #1203e0.

The fallback is the TAIL, not the head, so even a total failure of the selector cannot put the
front-cut back.
"""
import inspect
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.remediation_dispatcher import (  # noqa: E402
    _salient_200_1203e9, docker_up_host_fault_1202de)

# r154's actual compose stderr shape, padded past 600 so the selector's tail branch engages.
R154 = (" Container tiktok-web-r154-database-1  Creating\n" * 14
        + 'Error response from daemon: Conflict. The container name '
          '"/tiktok-web-r154-backend-1" is already in use by container "a1b2c3". You have to '
          'remove (or rename) that container to be able to reuse that name.')


def test_r154s_cause_survives_instead_of_a_fragment():
    """★ The defect in one assertion."""
    out = _salient_200_1203e9(R154)
    assert "remove (or rename)" in out or "already in use" in out, out


# An unrecognised shape: #1203h8 taught the extractor compose's own error vocabulary, so
# R154 above now matches a marker and its cause LEADS the output. The counter-proof moves
# to a shape nobody has taught it yet, because that is where the double cut still bites.
R154_UNTAUGHT = (" Container tiktok-web-r154-database-1  Creating\n" * 14
                 + "the daemon said something no marker covers, and what localizes it is at "
                   "the very end: stale-handle-0x5f3a")


def test_the_old_front_cut_would_still_lose_an_untaught_cause():
    """★ The counter-proof, re-pointed by #1203h8 — and on a fixture long enough to matter."""
    assert len(R154_UNTAUGHT) > 600, len(R154_UNTAUGHT)
    import importlib
    fv = importlib.import_module("multi_agent.runtime.framework_validation")
    current = fv._salient_error(R154_UNTAUGHT, cap=600)
    assert "stale-handle-0x5f3a" in current, current[-80:]
    assert "stale-handle-0x5f3a" not in current[:200], current[:200][-80:]


def test_r154s_cause_now_leads_the_output():
    """★ #1203h8: the r154 shape no longer depends on the tail surviving, because
    `error response from daemon` is a marker now. Its cause leads, so even the pre-#1203e9
    front cut would keep it — which is the hazard removed rather than guarded."""
    import importlib
    fv = importlib.import_module("multi_agent.runtime.framework_validation")
    out = fv._salient_error(R154, cap=600)
    assert "remove (or rename)" in out, out
    assert "Creating" not in out, out


def test_a_marker_matching_detail_is_unchanged_in_spirit():
    """r149's 13 readable lines must stay readable: a disk-full message matches a marker, so the
    selector returns whole lines."""
    out = _salient_200_1203e9(
        "initdb: error: could not create directory: No space left on device")
    assert "No space left on device" in out, out


def test_the_fallback_is_the_tail_not_the_head():
    """If the selector itself were unavailable, the front-cut must not come back."""
    src = inspect.getsource(_salient_200_1203e9)
    assert "d[-200:]" in src, src
    assert "d[:200]" not in src, src


def test_empty_and_non_string_inputs():
    assert _salient_200_1203e9(None) == ""
    assert _salient_200_1203e9("") == ""
    assert isinstance(_salient_200_1203e9(12345), str)


def test_the_output_is_bounded():
    out = _salient_200_1203e9("x" * 5000)
    assert len(out) <= 220, len(out)      # the selector may widen slightly for #987's offsets


def test_the_host_fault_classifier_still_recognises_r154s_cause():
    """The pairing this line prints: #1203e6's token beside #1203e9's detail."""
    assert docker_up_host_fault_1202de(R154) == "You have to remove (or rename) that container"


# ---------------------------------------------------------------- wiring

def _log_stanza():
    """Landmarks, comments stripped (#1203e6's lesson: a source assertion that cannot tell code
    from the comment explaining it keeps catching the explanation)."""
    import multi_agent.runtime.remediation_dispatcher as RD
    src = inspect.getsource(RD)
    i = src.index("#1202de HOST FAULT (not a lane bug)")
    j = src.index("continue", i)
    body = src[i:j]
    return "\n".join(ln for ln in body.split("\n") if not ln.lstrip().startswith("#"))


def test_the_log_line_no_longer_front_cuts():
    s = _log_stanza()
    assert "str(detail)[:200]" not in s, s
    assert "_salient_200_1203e9(detail)" in s, s


def test_the_cause_token_is_still_printed_beside_it():
    """The token is what makes the line actionable; the detail is supplementary."""
    assert "_hf1202de" in _log_stanza()
