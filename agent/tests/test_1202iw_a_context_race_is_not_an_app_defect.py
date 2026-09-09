"""#1202iw: the build-context tar race is the framework's own packaging step, not app code.

`docker build` streams the context directory into the daemon as a tar while the lanes are
still writing into that same directory. A file that changes size mid-stream truncates the
entry and kills the whole stream. 26 of the 423 failed builds in this corpus (6.1%) are this,
across tiktok and netflix, and the retry clears it every time.

Nothing said so. In r110 the verifier read the failure and filed `Docker frontend build fails
while packaging frontend assets` as a P0; it was still open at the delivery cut and is named
in the #743 line that kept the run from releasing. A lane cannot fix a race in the framework's
packaging -- it can only rewrite app code that was never wrong.
"""
import sys
import pathlib
import types
import logging

_AGENT = pathlib.Path(__file__).resolve().parents[1]
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

from env_generator.llm_generator.multi_agent.runtime import validation_runner as VR  # noqa: E402


_RACE = (
    'time="2026-09-09T16:04:57-05:00" level=error msg="Can\'t add file '
    '/run/app/frontend/vite.config.js to tar: archive/tar: missed writing 28161 bytes"\n'
    'time="2026-09-09T16:04:57-05:00" level=error msg="Can\'t close tar writer: '
    'archive/tar: missed writing 28161 bytes"\n'
    'Error response from daemon: Error processing tar file(exit status 1): unexpected EOF\n'
)

_REAL_APP_ERROR = (
    '#12 1.331 x Build failed in 1.33s\n'
    '#12 1.333 [vite]: Rollup failed to resolve import "lucide-react/icons/x" '
    'from "/app/src/App.jsx".\n'
)


def test_the_race_signature_is_recognised():
    assert VR._build_context_race_1202iw(_RACE)
    for line in ("Can't add file /x to tar: archive/tar: missed writing 12 bytes",
                 "Can't close tar writer: archive/tar: missed writing 12 bytes",
                 "Error processing tar file(exit status 1): unexpected EOF"):
        assert VR._build_context_race_1202iw(line), line


def test_a_genuine_app_failure_is_not_misclassified():
    """The whole value of the note is that it is TRUE. Marking a real Rollup failure as an
    infrastructure race would tell a lane to ignore the one thing it must fix -- strictly
    worse than the silence this replaces."""
    assert not VR._build_context_race_1202iw(_REAL_APP_ERROR)
    assert not VR._build_context_race_1202iw(
        "npm ERR! code ERESOLVE\nnpm ERR! ERESOLVE unable to resolve dependency tree")
    assert not VR._build_context_race_1202iw("")
    assert not VR._build_context_race_1202iw(None)


def _fake_capture(monkey_results):
    """Drive `_build_with_retry` through a scripted sequence of compose results."""
    seq = list(monkey_results)

    def _cap(compose_file, verb, cwd=None, timeout=None):
        rc, out = seq.pop(0)
        return types.SimpleNamespace(returncode=rc, stdout=out, stderr=""), False
    return _cap


def test_the_failure_detail_names_the_race(monkeypatch):
    """Every attempt races -> the returned detail must carry the classification, because that
    string is what reaches a reader."""
    monkeypatch.setattr(VR, "_compose_capture",
                        _fake_capture([(1, _RACE)] * (VR._BUILD_RETRIES + 1)))
    ok, detail = VR._build_with_retry(pathlib.Path("compose.yml"), pathlib.Path("."))
    assert ok is False
    assert "#1202iw" in detail, detail
    assert "NOT a defect in the application code" in detail, detail


def test_a_real_failure_detail_is_not_annotated(monkeypatch):
    monkeypatch.setattr(VR, "_compose_capture",
                        _fake_capture([(1, _REAL_APP_ERROR)] * (VR._BUILD_RETRIES + 1)))
    ok, detail = VR._build_with_retry(pathlib.Path("compose.yml"), pathlib.Path("."))
    assert ok is False
    assert "#1202iw" not in detail, detail
    assert "Rollup failed to resolve" in detail, detail


def test_a_recovered_race_says_so_out_loud(monkeypatch, caplog):
    """The r110 shape exactly: attempt 1 races, the retry succeeds. A lane that saw the failed
    attempt has no other way to learn the retry settled it."""
    monkeypatch.setattr(VR, "_compose_capture", _fake_capture([(1, _RACE), (0, "")]))
    monkeypatch.setattr(VR, "_note_build_ok_1046", lambda *a, **k: None)
    with caplog.at_level(logging.INFO, logger=VR._LOG.name):
        ok, detail = VR._build_with_retry(pathlib.Path("compose.yml"), pathlib.Path("."))
    assert ok is True and detail == ""
    assert any("#1202iw" in r.getMessage() for r in caplog.records), \
        [r.getMessage() for r in caplog.records]


def test_a_clean_first_build_stays_silent(monkeypatch, caplog):
    monkeypatch.setattr(VR, "_compose_capture", _fake_capture([(0, "")]))
    monkeypatch.setattr(VR, "_note_build_ok_1046", lambda *a, **k: None)
    with caplog.at_level(logging.INFO, logger=VR._LOG.name):
        ok, _ = VR._build_with_retry(pathlib.Path("compose.yml"), pathlib.Path("."))
    assert ok is True
    assert not any("#1202iw" in r.getMessage() for r in caplog.records)
