"""#1153: the two remaining detectors whose silence was indistinguishable.

A sweep of every detector-named function in the framework found 27 sites that
answer a raised exception with a falsy value.  Most are deliberate and stay:
`missing_required_args_634` documents "a signature that cannot be inspected
yields [] -- never guess"; `player_chrome_missing` returns None and [] to mean
two different things and its caller distinguishes them; `_shape_violation`'s
guard wraps only `json.loads`.  Two were not deliberate:

  * `dead_nav_link_blockers` wraps the WHOLE scan, so one unreadable JSX file
    turns every remaining page into "no dead nav links" and the gate passes.
  * `_stale_open_p0_evidence_1023` sits in delivery_gate, which has owned
    `_swallowed_790` since r148 and calls it 9 times -- but not here.

Neither changes behaviour: both stay permissive.  They just stop being silent.
"""
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime import delivery_gate as dg
from env_generator.llm_generator.multi_agent.runtime import frontend_audit as fa


def _fn_body(mod, name):
    """Anchor on the def, stop at the next top-level def (#943)."""
    src = Path(mod.__file__).read_text(encoding="utf-8")
    i = src.index("def %s(" % name)
    return src[i:src.index("\ndef ", i + 1)]


def test_dead_nav_scan_reports_when_it_cannot_run():
    b = _fn_body(fa, "dead_nav_link_blockers")
    assert "_swallowed_790" in b
    assert "except Exception as _exc_1153:" in b
    assert "#1153" in b


def test_dead_nav_scan_stays_permissive():
    """Failing closed here would let one unreadable file wedge every release."""
    b = _fn_body(fa, "dead_nav_link_blockers")
    i = b.index("_exc_1153")
    handler = b[i:b.index("return []", i) + len("return []")]
    assert handler.rstrip().endswith("return []"), "must still answer permissively"
    assert "raise" not in handler


def test_the_gate_reporter_is_used_in_its_own_file():
    b = _fn_body(dg, "_stale_open_p0_evidence_1023")
    assert "_swallowed_790(" in b and "#1153" in b
    assert "except Exception as _exc_1153:" in b


def test_the_report_names_which_answer_it_defaulted_to():
    """#790's whole value is saying WHAT the gate assumed, not just that it broke."""
    for mod, fn in ((fa, "dead_nav_link_blockers"),
                    (dg, "_stale_open_p0_evidence_1023")):
        b = _fn_body(mod, fn)
        i = b.index("_swallowed_790(")
        call = b[i:b.index("return", i)]      # stop at the answer it defaults to
        assert "=" in call, "%s: the defaulting_to argument must state the answer" % fn


def test_the_deliberate_ones_were_left_alone():
    """A sweep that rewrites deliberate guards is worse than no sweep."""
    from env_generator.llm_generator.multi_agent.agents.runtime import tooling
    b = _fn_body(tooling, "missing_required_args_634")
    assert "never guess" in b
    assert "_swallowed" not in b
