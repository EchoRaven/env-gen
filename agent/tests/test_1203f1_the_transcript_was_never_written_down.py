r"""#1203f1: the build transcript that would have named the file was never written down.

`#1129` made this report carry the error instead of the epilogue, and said why: "the compile
error itself — the Vite/rollup/tsc diagnostic naming the file and the symbol — goes to STDOUT".
`_salient_error` delivers exactly that whenever some line matches an error marker. When none
does, it falls back to `text[-cap:]`, and for a build whose output ENDS in a stack trace that
tail is the frames.

★ r154, live: `docker build FAILED (attempt 2/2)` reported `x Build failed in 2.63s` — which
`_is_void_hit_1202iv` correctly classifies as content-free, so the selector took the tail, and
the tail was 20 rollup frames beginning mid-word (`t FunctionScope.findVariable`). `Maximum call
stack`, `RangeError`, `error during build` and `ERROR:` appear ZERO times anywhere in that run's
log — whatever rollup said above its frames was never written down at all.

This deliberately does NOT change the selection window. Changing a window requires evidence of
what the window missed, and that evidence is precisely what was gone; I said so and left it. What
it changes is that the evidence EXISTS: the whole transcript goes to `logs/`, the same move
`#1203c9` makes for the browser walk's raw answer ("its words are kept ... so the walk is not
lost"). The next build failure is then diagnosable without re-running anything — including the
window question itself.
"""
import inspect
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime import validation_runner as VR  # noqa: E402


def _stanza():
    """Landmarks, comments stripped — a source assertion that cannot tell code from the comment
    about it keeps catching the comment (#1203e6, and again in #1203f0)."""
    import textwrap
    src = inspect.getsource(VR)
    i = src.rindex("\n", 0, src.index("_saved_1203f1 = ")) + 1    # ★ line START, not the symbol
    j = src.index("transcript tail:", i)
    j = src.rindex("\n", 0, src.rindex("_LOG.warning", i, j)) + 1
    body = "\n".join(ln for ln in src[i:j].split("\n") if not ln.lstrip().startswith("#"))
    return textwrap.dedent(body)


def test_the_whole_transcript_is_written(tmp_path):
    """★ The defect in one assertion, run through the shipped expression on a real directory."""
    docker = tmp_path / "docker"
    docker.mkdir()
    full = ("Service frontend  Building\n" + "    at CallExpression.bind (rollup.js:1)\n" * 40
            + "x Build failed in 2.63s")
    ns = {"cwd": str(docker), "_verb": "build", "_full": full}
    # #1203fe moved the filename construction into `VR._transcript_path_1203fe`, so the
    # stanza now CALLS it. A stanza exec'd in isolation must be given what it calls, or the
    # `except Exception: pass` inside it swallows a NameError and the test sees "no file
    # written" for the wrong reason.
    ns["_transcript_path_1203fe"] = VR._transcript_path_1203fe
    exec(compile(_stanza(), "<f1>", "exec"), ns)
    saved = tmp_path / "logs" / "compose_build_failure_1203f1.log"
    assert saved.is_file(), list((tmp_path).rglob("*"))
    assert saved.read_text() == full
    assert "FULL transcript" in ns["_saved_1203f1"]
    assert str(saved) in ns["_saved_1203f1"]


def test_the_note_names_the_size_so_a_reader_knows_it_is_complete(tmp_path):
    docker = tmp_path / "docker"; docker.mkdir()
    ns = {"cwd": str(docker), "_verb": "build", "_full": "x" * 1234}
    # #1203fe moved the filename construction into `VR._transcript_path_1203fe`, so the
    # stanza now CALLS it. A stanza exec'd in isolation must be given what it calls, or the
    # `except Exception: pass` inside it swallows a NameError and the test sees "no file
    # written" for the wrong reason.
    ns["_transcript_path_1203fe"] = VR._transcript_path_1203fe
    exec(compile(_stanza(), "<f1>", "exec"), ns)
    assert "1234 chars" in ns["_saved_1203f1"], ns["_saved_1203f1"]


def test_an_empty_transcript_writes_nothing(tmp_path):
    """"the command produced no output" is already reported by the tail; an empty file would only
    add a false trail."""
    docker = tmp_path / "docker"; docker.mkdir()
    ns = {"cwd": str(docker), "_verb": "build", "_full": ""}
    # #1203fe moved the filename construction into `VR._transcript_path_1203fe`, so the
    # stanza now CALLS it. A stanza exec'd in isolation must be given what it calls, or the
    # `except Exception: pass` inside it swallows a NameError and the test sees "no file
    # written" for the wrong reason.
    ns["_transcript_path_1203fe"] = VR._transcript_path_1203fe
    exec(compile(_stanza(), "<f1>", "exec"), ns)
    assert ns["_saved_1203f1"] == ""
    assert not (tmp_path / "logs").exists()


def test_an_unwritable_destination_does_not_break_the_report(tmp_path):
    """★ The invariant: the save is best-effort. A failed save must not also lose the tail — the
    whole point of #1129 was that this line carries the error."""
    ns = {"cwd": "/proc/one/does/not/mkdir/here/docker", "_verb": "build", "_full": "boom"}
    # #1203fe moved the filename construction into `VR._transcript_path_1203fe`, so the
    # stanza now CALLS it. A stanza exec'd in isolation must be given what it calls, or the
    # `except Exception: pass` inside it swallows a NameError and the test sees "no file
    # written" for the wrong reason.
    ns["_transcript_path_1203fe"] = VR._transcript_path_1203fe
    exec(compile(_stanza(), "<f1>", "exec"), ns)
    assert ns["_saved_1203f1"] == ""


def test_the_verb_is_in_the_filename(tmp_path):
    """`up` and `build` fail for different reasons; one file each keeps both diagnosable."""
    docker = tmp_path / "docker"; docker.mkdir()
    for verb in ("build", "up"):
        ns = {"cwd": str(docker), "_verb": verb, "_full": "cause-of-%s" % verb}
        # #1203fe moved the filename construction into `VR._transcript_path_1203fe`.
        ns["_transcript_path_1203fe"] = VR._transcript_path_1203fe
        exec(compile(_stanza(), "<f1>", "exec"), ns)
    logs = tmp_path / "logs"
    assert (logs / "compose_build_failure_1203f1.log").read_text() == "cause-of-build"
    assert (logs / "compose_up_failure_1203f1.log").read_text() == "cause-of-up"


def test_a_missing_verb_still_produces_a_file(tmp_path):
    docker = tmp_path / "docker"; docker.mkdir()
    ns = {"cwd": str(docker), "_verb": None, "_full": "x"}
    # #1203fe moved the filename construction into `VR._transcript_path_1203fe`, so the
    # stanza now CALLS it. A stanza exec'd in isolation must be given what it calls, or the
    # `except Exception: pass` inside it swallows a NameError and the test sees "no file
    # written" for the wrong reason.
    ns["_transcript_path_1203fe"] = VR._transcript_path_1203fe
    exec(compile(_stanza(), "<f1>", "exec"), ns)
    assert (tmp_path / "logs" / "compose_cmd_failure_1203f1.log").is_file()


# ---------------------------------------------------------------- the selection is untouched

def test_the_selection_window_is_unchanged():
    """★ Stated and pinned: this patch does not touch `_salient_error`'s cap or the fallback. The
    r154 question — does rollup's message sit above its frames and outside 900 chars — is still
    open, and #1203f1 is what will make it answerable."""
    src = inspect.getsource(VR)
    assert "_se_1129(_full, cap=900) or _full[-600:]" in src, "the selection moved"


def test_the_tail_still_reaches_the_log():
    s = _stanza()
    src = inspect.getsource(VR)
    i = src.index("_saved_1203f1 = ")
    j = src.index("\n\n", src.index("transcript tail:", i))
    log = "\n".join(ln for ln in src[i:j].split("\n") if not ln.lstrip().startswith("#"))
    assert "_tail or" in log, log
    assert "_saved_1203f1" in log, log
