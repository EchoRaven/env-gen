"""#1202iv: a build-failure report that says only THAT it failed suppresses the one that
says WHY.

`_salient_error`'s own contract is "if none match, returns the TAIL (never the misleading
prefix)". A content-free hit is worse than no hit at all, because it takes the `if hits:`
branch and the tail never runs. Vite prints `x Build failed in 1.33s` and puts the cause on
the lines around it; `build failed` is an error marker, so the summary won.

Measured across every run log in this tree: 73 of 642 failure reports (11.4%) carried a tail
that was entirely such a line. r110 dispatched three of them to the frontend lane as the
reason its build was broken.
"""
import sys
import pathlib

_AGENT = pathlib.Path(__file__).resolve().parents[1]
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

from env_generator.llm_generator.multi_agent.runtime.framework_validation import (  # noqa: E402
    _salient_error, _is_void_hit_1202iv)


# Shaped after the real thing: buildkit step prefixes, vite's ANSI-coloured summary, and the
# cause on the line AFTER it.
_VITE = (
    '#12 [frontend build 5/6] RUN npm run build\n'
    '#12 1.203 vite v5.4.10 building for production...\n'
    '#12 1.298 transforming...\n'
    '#12 1.331 \x1b[91mx\x1b[39m Build failed in 1.33s\n'
    '#12 1.332 error during build:\n'
    '#12 1.333 [vite]: Rollup failed to resolve import "lucide-react/icons/x" '
    'from "/app/src/App.jsx".\n'
)

_ONLY_SUMMARY = (
    'vite v5.4.10 building for production...\n'
    'transforming...\n'
    '\x1b[91mx\x1b[39m Build failed in 1.33s\n'
)


def test_the_bundler_cause_reaches_the_report():
    """`failed to solve` (BuildKit) was a marker and `failed to resolve` (Rollup) was not --
    one letter apart, different tools. The frontend cause matched nothing."""
    out = _salient_error(_VITE, cap=400)
    assert "Rollup failed to resolve" in out, out
    assert "lucide-react/icons/x" in out, out


def test_a_summary_only_hit_does_not_suppress_the_tail():
    """The regression this ticket is about: with only content-free hits the function must
    behave as if nothing matched, which its docstring already says means "return the tail"."""
    out = _salient_error(_ONLY_SUMMARY, cap=400)
    assert out.strip() != "x Build failed in 1.33s"
    assert "building for production" in out, out


def test_a_real_hit_alongside_a_summary_still_wins():
    """The guard fires only when EVERY hit is content-free. One real line must keep the
    marker path -- otherwise the fix trades a bad report for a noisy one."""
    out = _salient_error(_ONLY_SUMMARY + 'ERROR: The symbol "Link" has already been declared\n',
                         cap=400)
    assert 'symbol "Link"' in out, out
    assert "building for production" not in out, out


def test_which_lines_count_as_content_free():
    for void in ('x Build failed in 1.33s', '\x1b[91mx\x1b[39m Build failed in 825ms',
                 'error during build:', 'exit code: 1', 'exited with code 137',
                 'The command ... returned a non-zero code: 1', 'Build failed'):
        assert _is_void_hit_1202iv(void), void
    for real in ('ERROR: The symbol "Link" has already been declared',
                 '[vite]: Rollup failed to resolve import "x" from "y".',
                 'npm ERR! code ERESOLVE',
                 'ERROR: process "/bin/sh -c npm run build" did not complete '
                 'successfully: exit code: 1'):
        assert not _is_void_hit_1202iv(real), real


def test_the_postgres_pairing_still_works():
    """#973's STATEMENT pairing shares this function; #1202iv must not disturb it."""
    out = _salient_error(
        'ERROR:  syntax error at or near ")" at character 41\n'
        'STATEMENT:  CREATE TABLE IF NOT EXISTS "titles" ()\n', cap=400)
    assert "STATEMENT" in out, out
    assert "titles" in out, out


def test_an_empty_transcript_is_still_empty():
    assert _salient_error("") == ""
    assert _salient_error(None) == ""
