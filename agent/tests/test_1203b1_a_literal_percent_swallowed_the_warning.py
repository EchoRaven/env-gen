r"""#1203b1/b2: a `%` in prose silenced #739 entirely, and #739's task described a sibling.

FOUND LIVE. r143 logged a `Traceback` 25 minutes in. It was not a pipeline failure — it was
logging's own formatter:

    TypeError: not enough arguments for format string
    delivery_gate.py  Message: "#739 ui_smoke_pass=True rests on %d passing UI record(s)..."
                      Arguments: (9, 1, 'explore_grid_page, ...', 'fyp_feed_logged_out')

The message ends with "because blocking 45% of runs for absent evidence is a stop". `45% o` is
a FORMAT SPECIFIER to `%`-formatting — space-flag plus octal — so there were 5 placeholders
against 4 arguments. logging caught the TypeError, printed a traceback and DROPPED the record:
#739's diagnostic has never reached any log. Worse than "the fact only reaches a log" — it did
not reach one.

A swept AST scan of all 279 runtime modules found this to be the ONLY real instance. The two
other candidates were false positives of the scan: `%(components)d` is mapping-style formatting
with a dict argument, and one format string is built by concatenation with a variable that
carries its own `%r`.

#1203b2 is the other half, in the remediation text for the blocker that aborted r143.
"""
import ast
import inspect
import io
import logging
import os
import re
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import multi_agent.runtime.delivery_gate as DG  # noqa: E402
import multi_agent.runtime.remediation_dispatcher as RD  # noqa: E402

_SPEC = re.compile(r'%(?:\((\w+)\))?[-+ #0]*[0-9*]*(?:\.[0-9*]+)?[hlL]?([diouxXeEfFgGcrsa%])')


def _remediation_text(check_name):
    """The CONCATENATED description a lane actually receives, via AST.

    Matching the module SOURCE does not work: the sentence spans several adjacent string
    literals, so the raw text has quotes and newlines inside the phrase. The first version of
    these tests asserted on source and passed a mutation that cut the clause.
    """
    import ast as _ast
    tree = _ast.parse(inspect.getsource(RD))
    for node in _ast.walk(tree):
        if not isinstance(node, _ast.Dict):
            continue
        for k, v in zip(node.keys, node.values):
            if (isinstance(k, _ast.Constant) and k.value == check_name
                    and isinstance(v, _ast.Tuple) and len(v.elts) >= 3):
                return _ast.literal_eval(v.elts[2])
    raise AssertionError("no remediation entry for %r" % check_name)


def _logger_calls(mod):
    """Every logger call in a module with a literal format string and positional args."""
    out = []
    tree = ast.parse(inspect.getsource(mod))
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        if getattr(n.func, "attr", "") not in (
                "debug", "info", "warning", "error", "critical", "exception"):
            continue
        if not n.args or isinstance(n.args[0], ast.JoinedStr):
            continue
        parts = [c.value for c in ast.walk(n.args[0])
                 if isinstance(c, ast.Constant) and isinstance(c.value, str)]
        if not parts:
            continue
        # only literal-only format strings; a concatenation with a variable is unresolvable
        if any(not isinstance(c, (ast.Constant, ast.BinOp)) for c in ast.walk(n.args[0])
               if isinstance(c, (ast.Name, ast.Attribute))):
            continue
        if any(isinstance(c, (ast.Name, ast.Attribute)) for c in ast.walk(n.args[0])):
            continue
        out.append((n.lineno, "".join(parts), len(n.args) - 1))
    return out


def test_the_739_warning_can_actually_be_emitted():
    """★ The defect: the message must survive `%`-formatting with its real arguments."""
    hits = [(ln, f, na) for ln, f, na in _logger_calls(DG) if "#739 ui_smoke_pass=True" in f]
    assert hits, "the #739 warning is gone"
    ln, fmt, nargs = hits[0]
    specs = [m for m in _SPEC.finditer(fmt) if m.group(2) != "%"]
    assert len(specs) == nargs, (
        "delivery_gate.py:%d has %d placeholder(s) %r for %d argument(s) — logging will drop "
        "the record" % (ln, len(specs), [m.group(0) for m in specs], nargs))
    # and prove it by actually formatting it
    fmt % (9, 1, "a, b", "c")


def test_the_sentence_with_the_percent_survived():
    """Non-vacuity and the point of escaping rather than deleting: the prose is still there."""
    hits = [f for _, f, _ in _logger_calls(DG) if "#739 ui_smoke_pass=True" in f]
    rendered = hits[0] % (9, 1, "a", "b")
    assert "45% of runs" in rendered, rendered[-200:]


def test_no_logger_call_in_the_gate_has_a_stray_specifier():
    """The class, not just the instance — every literal-format logger call in this module."""
    bad = []
    for ln, fmt, nargs in _logger_calls(DG):
        specs = [m for m in _SPEC.finditer(fmt) if m.group(2) != "%"]
        if nargs and len(specs) != nargs:
            bad.append((ln, len(specs), nargs, [m.group(0) for m in specs][:6]))
    assert bad == [], bad


def test_the_understated_task_no_longer_states_the_sibling_condition():
    """★ #1203b2. `deliverability_all_page_apis_empty` owns the empty case; this text described
    it, so r143's lane saw a non-empty list and concluded the report did not apply."""
    text = _remediation_text("deliverability_page_apis_understated")
    assert "FEWER endpoints" in text, text[:400]
    assert "declares `apis_used: []`" not in text, (
        "the sibling's premise is back: " + text[:400])


def test_the_sibling_still_owns_the_empty_case():
    """Non-vacuity: the empty-list wording must still exist where it belongs."""
    text = _remediation_text("deliverability_all_page_apis_empty")
    assert "`apis_used: []`" in text, text[:400]


def test_the_understated_task_names_the_tool_and_the_omission_rule():
    """The lane re-registered 19 times without the field. The text has to say which call and
    that omitting it changes nothing."""
    text = _remediation_text("deliverability_page_apis_understated")
    assert "registryhub_register_ui_page" in text, text[:400]
    assert "apis_used" in text and "changes nothing" in text, text[:400]


def test_the_understated_task_covers_the_ghost_declaration_half():
    """r143's `signup` declared `POST /auth/signup`, which its own contract does not serve, while
    the source called `POST /auth/register`. 26 of 2274 corpus entries are such ghosts."""
    text = _remediation_text("deliverability_page_apis_understated")
    assert "DROP" in text, text[:400]
    # ★ FOUND BY MUTANT: asserting "no endpoint in the" and "serves" SEPARATELY passed when the
    # clause was cut, because "serves" also occurs elsewhere in the block. Pin the phrase, and
    # pin the tool that lets a lane check — without it "drop the ghosts" is not actionable.
    assert "no endpoint in the contract serves" in text, text[:400]
    assert "registryhub_list_endpoints" in text, text[:400]


def test_the_warning_emits_through_a_real_logger(caplog):
    """End to end: hand the real format string to a real logger and require the record OUT.
    A unit test on the string alone would not have caught that logging swallows the failure."""
    fmt = [f for _, f, _ in _logger_calls(DG) if "#739 ui_smoke_pass=True" in f][0]
    log = logging.getLogger("test_1203b1")
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(h)
    log.setLevel(logging.WARNING)
    try:
        log.warning(fmt, 9, 1, "explore_grid_page", "fyp_feed_logged_out")
    finally:
        log.removeHandler(h)
    out = buf.getvalue()
    assert "#739" in out, "the record was dropped: %r" % out
    assert "45% of runs" in out, out[-200:]
