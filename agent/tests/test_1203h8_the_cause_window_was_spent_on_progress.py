r"""#1203h8: no compose failure in the corpus matched an error marker, so all 119 fell to the tail.

`_salient_error` returns the lines matching `_ERR_MARKERS`, and the TAIL of the text
when nothing matches. A compose tail is container-progress chatter.

MEASURED over every `compose up FAILED` record in the corpus -- 119 of them, across
44 logs -- NOT ONE matched any existing marker. 66% of those windows' characters
(24219 of 36612) are lines like ` Container app-database-1  Started`, and in 25 the
causal line survived only as a fragment: the operator-facing log read `Error respo`
and nothing more. The three dominant causes are

    48  Error response from daemon: driver failed programming external connectivity
        on endpoint X: Bind for 0.0.0.0:P failed: port is already allocated
    22  failed to create network X: Error response from daemon: could not find an
        available, non-overlapping IPv4 address pool among the defaults
     7  Error response from daemon: No such container: <id>        (the #1202hn race)

and none of them says `error:` WITH the colon the marker list wants. `denied`,
`not found` and `cannot find` do not reach them either -- compose says `No such
container` and `could not find`, one word off each.

★ THE SAME GAP, THIRD TIME. #1119b added `oci runtime` because "OCI runtime create
failed ... error loading seccomp filter" matched nothing; #1202iv added the bundler
shapes for the same reason. The lesson that keeps not sticking is that the marker
list is a list of TOOL dialects, so every tool whose output reaches this function
needs its own entry -- and compose is the one tool every run uses.

Projected before landing: 83 of the 119 windows become the one causal line.
Over-match checked against every container-progress line in the corpus: 0 hits.
The remaining 36 cannot be helped here -- 30 of them arrive already truncated
mid-word from upstream, which is a separate, still-open measurement.
"""
import os
import sys

import pytest

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.framework_validation import (  # noqa: E402
    _ERR_MARKERS, _salient_error)

_PROGRESS = """time="2026-09-29T02:56:47-05:00" level=warning msg="the attribute `version` is obsolete"
 Network app_default  Creating
 Network app_default  Created
 Container app-database-1  Creating
 Container app-database-1  Created
 Container app-database-1  Starting
 Container app-database-1  Started
 Container app-database-1  Waiting
 Container app-database-1  Healthy
 Container app-backend-1  Starting
 Container app-backend-1  Started
 Container app-frontend-1  Starting"""

# Verbatim shapes from the corpus, each the LAST line of a real compose stderr.
PORT_CLASH = ("Error response from daemon: driver failed programming external "
              "connectivity on endpoint app-frontend-1: Bind for 0.0.0.0:3000 "
              "failed: port is already allocated")
POOL = ("failed to create network netflix-local-r37_default: Error response from "
        "daemon: could not find an available, non-overlapping IPv4 address pool "
        "among the defaults to assign to the network")
RACE = ("Error response from daemon: No such container: "
        "61e645a4e9066784027d509b0ae1d7dc78fadc2fbf40c09fd720225a5adb796c")
DEPENDENCY = ("dependency failed to start: container tiktok-web-r166-database-1 "
              "exited (1)")


@pytest.mark.parametrize("cause", [PORT_CLASH, POOL, RACE, DEPENDENCY],
                         ids=["port_clash", "address_pool", "hn_race", "dependency"])
def test_the_causal_line_survives_the_progress_chatter(cause):
    """★ The whole ticket: 12 lines of progress in, one causal line out."""
    out = _salient_error(_PROGRESS + "\n" + cause, cap=500)
    assert cause[:60] in out, out
    assert "Container app-database-1" not in out, out
    assert "Creating" not in out, out


@pytest.mark.parametrize("cause", [PORT_CLASH, POOL, RACE, DEPENDENCY],
                         ids=["port_clash", "address_pool", "hn_race", "dependency"])
def test_each_shape_matches_a_marker_at_all(cause):
    """Stated at the marker level too, because the behaviour above would also pass
    if the cause merely happened to be the tail. These must be HITS."""
    assert any(m in cause.lower() for m in _ERR_MARKERS), cause


def test_the_port_number_reaches_the_reader():
    """A port clash whose port is cut is not actionable: the operator's next move is
    to find who holds that port."""
    out = _salient_error(_PROGRESS + "\n" + PORT_CLASH, cap=500)
    assert "0.0.0.0:3000" in out, out
    assert "already allocated" in out, out


def test_the_container_id_reaches_the_reader():
    """The #1202hn race names the container that vanished; without the id you cannot
    tell it from a container the run never created."""
    out = _salient_error(_PROGRESS + "\n" + RACE, cap=500)
    assert "61e645a4e9066784027d509b0ae1d7dc78fadc2f" in out, out


def test_a_progress_line_alone_is_never_promoted_to_a_cause():
    """★ THE OVER-MATCH GUARD. The new markers must not fire on the chatter itself,
    or the fix becomes the defect with extra steps. With no causal line present the
    extractor must fall through to its tail, not claim a hit."""
    for line in _PROGRESS.splitlines():
        assert not any(m in line.lower() for m in _ERR_MARKERS), line


def test_the_deprecation_warning_is_still_not_a_cause():
    """#1119 measured 17 compose failures of one run all reporting `the attribute
    version is obsolete` -- a warning, not an error. It must not come back as a hit."""
    warn = ('time="2026-09-29T02:56:47-05:00" level=warning '
            'msg="the attribute `version` is obsolete"')
    assert not any(m in warn.lower() for m in _ERR_MARKERS), warn


def test_an_unrecognised_failure_still_yields_its_tail():
    """The fallback is unchanged: a shape nobody has taught this function yet must
    still hand over the end of the text rather than nothing."""
    out = _salient_error(_PROGRESS + "\nsomething nobody has seen before", cap=500)
    assert "something nobody has seen before" in out, out


# ------------------------------------------------------------------- #1203hb
# The companion #1203h8 made necessary. The hits branch joined `hits[-3:]` and handed
# the result to `_clip_keeping_guidance_1202df`, which -- absent a framework remediation
# clause -- keeps the FRONT. Three ~180-character compose errors (one per service, which
# is exactly what a port clash across database/backend/frontend produces) overflow a 500
# cap, and the cut lands inside the LAST hit: the one that localizes the fault.
#
# That is the mechanism behind 25 of the corpus's 119 records ending mid-word, 24 of them
# at the literal `Error respo`. I spent an hour on an upstream truncation that does not
# exist -- ComposeResult, _coerce and _default_runner pass subprocess stderr whole, and
# the logger has no cap (longest multi-line record in the same file: 2121 chars, no
# clustering). #1203h8 moves 83 more records onto this path, so it had to be fixed with it.
from multi_agent.runtime.framework_validation import (  # noqa: E402
    _join_hits_to_fit_1203hb)

_LONG = ("Error response from daemon: driver failed programming external connectivity on "
         "endpoint app-%s-1 " + "x" * 200 +
         ": Bind for 0.0.0.0:3000 failed: port is already allocated")


def test_the_most_causal_line_survives_whole_when_the_join_overflows():
    """★ THE defect: the end of the LAST hit is what names the port and the verdict."""
    stderr = "\n".join([" Container app-database-1  Creating"]
                       + [_LONG % t for t in ("database", "backend", "frontend")])
    out = _salient_error(stderr, cap=500)
    assert "port is already allocated" in out, out[-120:]
    assert out.rstrip().endswith("allocated"), out[-80:]


def test_an_earlier_hit_is_dropped_rather_than_the_last_one_cut():
    """`hits[-3:]` already says the last ones matter most; a whole cause beats three
    fragments. The earliest of the three is what goes."""
    hits = ["aaaa" * 40, "bbbb" * 40, "cccc" * 40]
    out = _join_hits_to_fit_1203hb(hits, cap=400)
    assert out.endswith("cccc"), out[-20:]
    assert "aaaa" not in out, out[:40]


def test_a_join_that_already_fits_is_untouched():
    """★ The no-op guarantee: the overwhelming majority of inputs produce a short join,
    and this change must not reword any of them."""
    hits = ["first cause", "second cause", "third cause"]
    assert _join_hits_to_fit_1203hb(hits, cap=500) == "first cause | second cause | third cause"


def test_a_single_over_long_hit_is_left_to_the_existing_clip():
    """★ SCOPE. #1202df owns what happens to one over-cap line -- netflix-r43's remedy is
    appended past the cap and that function keeps both ends. This must not reach into it."""
    out = _join_hits_to_fit_1203hb(["z" * 900], cap=500)
    assert out == "z" * 900, len(out)


def test_only_hits_are_dropped_never_truncated():
    """Whatever survives is a whole line, so a reader never sees half a message."""
    hits = ["x" * 300, "y" * 300]
    out = _join_hits_to_fit_1203hb(hits, cap=400)
    assert out in ("y" * 300,), out[:20]


def test_a_nonsense_cap_does_not_crash_the_reporter():
    """This runs on the failure path, where raising would replace a diagnosis with a
    traceback about the diagnosis."""
    assert _join_hits_to_fit_1203hb(["a", "b"], cap=None) == "a | b"
    assert _join_hits_to_fit_1203hb(["a", "b"], cap="nope") == "a | b"


def test_a_postgres_offset_keeps_both_halves_and_widens_instead():
    """★ THE REGRESSION #1203hb CAUSED AND THE SUITE CAUGHT. #973 pairs `ERROR:` with the
    `STATEMENT:` line that follows it, and the ERROR half is the one carrying
    `at character N` -- which #987 reads to widen the cap. The first version of
    `_join_hits_to_fit_1203hb` fitted FIRST and dropped the earliest hit, so the ERROR
    half went, the offset went with it, the cap never widened, and the output was 200
    characters of CREATE TABLE naming a position nobody could see.

    So "the last hit is the most causal" is true for compose and false here, and an
    offset now means #1203hb stands aside entirely."""
    stmt = 'STATEMENT:  CREATE TABLE IF NOT EXISTS "titles" ( ' + '"pad" TEXT, ' * 40 + ")"
    detail = ('ERROR:  syntax error at or near "?" at character 255\n' + stmt)
    out = _salient_error(detail, cap=200)
    assert "at character 255" in out, out[:120]
    assert "CREATE TABLE" in out, out
    assert len(out) > 255, (len(out), "the cap did not widen to the reported offset")
