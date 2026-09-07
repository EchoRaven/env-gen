r"""#1034: a printed COUNT beside a silently truncated list, twelve times over.

#1022b fixed two gate lines that said "5 P0 BUG task(s) ... <four titles>" with no marker.
Scanning `runtime/` for the same shape — text that prints a count AND joins a `[:N]`-truncated
list, with no "+N more" anywhere near it — found 12 by eye. ALL SITES ARE NOW CONVERTED, and
finishing them corrected the original list twice, in both directions:

    delivery_gate.py:1436       #1006 %d chain(s) framework-blocked, [:4]     agent-facing
    delivery_gate.py:1445       business_chain_failing, %d chain(s), [:8]     agent-facing
    delivery_gate.py:1700       route coverage missing declared endpoints, [:10]
    delivery_gate.py:1743       frontend calls unregistered endpoint(s), [:10]
    delivery_gate.py:1957       completeness oracle, %d gap(s), [:8]
    delivery_gate.py:2549       #1009 incomplete_required_tasks, %d x %s, [:6]
    design_prep.py:888          #643 %d section(s) nobody reads, [:8]
    frontend_audit.py:1231      #918 declares %d API(s), [:4]
    frontend_audit.py:1249      #909 declares %d component(s), [:6]
    frontend_scaffold.py:11590  #707 staged %d placeholder asset(s), [:8]
    heal_pipeline.py:2012       #1014 committing %d LANE-OWNED path(s), [:10]
    remediation_dispatcher.py:697/700  #1006 framework-defect detail, [:4] x2
    remediation_dispatcher.py:891      %s unwired page(s), [:200]
    visual_fidelity.py:2598     #715 %d route(s) the served frontend lacks, [:6]
    visual_fidelity.py:3145     #740 %d console error(s), [:4] AND [:4] nested
    visual_fidelity.py:3667     #893 %d screen(s) with a different verdict, [:4]

★ Two corrections the conversion forced, both of which say the eyeball scan is not the
instrument (see [[a-bare-name-search-is-never-a-locator]]):

  FALSE POSITIVE. `visual_fidelity.py:3993` "#713 %d screens with the SAME image, [:12]" is
  not truncated at all — its list is a full `", ".join(sorted(_names713))` and the `[:12]` I
  matched was `_h713[:12]`, an md5 PREFIX. A digit-slice regex cannot tell a list cap from a
  hash abbreviation.

  UNDERCOUNT, by 3.7x. The eyeball scan missed FIFTEEN. Five `delivery_gate` sites build the
  string with `+` concatenation instead of a `%s` arg; `visual_fidelity:3145` is really TWO
  nested caps (the distinct errors, and the screens each was seen on), each printed beside its
  own full count; and eight more only an AST sweep found:

    deliverability.py:595/599   %d critical UI flow(s) missing/failed, [:10]   agent-facing
    delivery_gate.py:2230       #1017 ui_evidence, [:12]  — see the count/list note below
    delivery_gate.py:2391       #774 lost ownership column(s), [:6]
    remediation_dispatcher.py:1441  "you have %d unfinished required task(s) (%s)", [:8]
    seed_audit.py:352           placeholder markers, [:5]
    validation_runner.py:1020/1023  business_endpoints_{implemented,correct_shape}, [:800]
    visual_fidelity.py:2886     #949 capture exceptions, [:3]

  `remediation_dispatcher:891` and `validation_runner:1020/1023` were worse than catalogued:
  the cut was on the JOINED STRING, so it could sever an item mid-word and read as a different
  page or endpoint. `validation_runner`'s two are the `run_validation` detail a lane reads to
  learn WHICH endpoints to implement — a silent cut there costs a repair round.

  `delivery_gate:2230` was not truncation at all but a COUNT/LIST MISMATCH: the count came
  from `failed_records` and the list from `pages_failed`, two different collections, so
  "N record(s): <list>" could never be read as "these are the N". It now prints both.

Bounding the list is right; an unbounded dump is worse. Saying nothing about the cut is the
defect: reading these across ticks means DIFFING the lists, and an item merely pushed past
position N reads as resolved. It misled me twice in one session.

★ Five of these are AGENT-facing `detail` strings, not operator logs — a lane reads
"3 chain(s) have NOT passed: <two names>", repairs what it was shown, and resubmits into the
same gate. That is the silent-truncation defect with a feedback loop attached.

`delivery_gate.py:1473` was already correct before this fix (`+N more`); it is the proof the
others are a deviation from this file's own practice rather than a house style.
"""
import pathlib
import ast
import glob
import inspect
import os
import re

import pytest

from env_generator.llm_generator.multi_agent.runtime.message_format import join_capped

_RUNTIME = os.path.dirname(inspect.getfile(
    __import__("env_generator.llm_generator.multi_agent.runtime.message_format",
               fromlist=["x"])))


# --- the helper --------------------------------------------------------------------------

def test_a_truncated_list_declares_the_remainder():
    assert join_capped(list("abcdefgh"), 20) == "a; b; c; d; e; f (+14 more not shown)"


def test_an_untruncated_list_gains_no_noise():
    assert join_capped(["a", "b", "c"], 3) == "a; b; c"


def test_total_defaults_to_the_list_length():
    assert join_capped(["a", "b"]) == "a; b"


def test_the_cap_is_adjustable():
    assert join_capped(list("abcdef"), 6, cap=2) == "a; b (+4 more not shown)"


def test_the_separator_is_adjustable():
    assert join_capped(["a", "b"], 2, sep=", ") == "a, b"


@pytest.mark.parametrize("items,total", [
    (None, None), ([], 0), (["a"], "junk"), (["a"], None), (None, 5),
])
def test_it_never_raises(items, total):
    """Every caller is a logging path — a formatting slip must not break a gate or a run."""
    assert isinstance(join_capped(items, total), str)


def test_a_count_larger_than_the_list_still_reports_honestly():
    """The caller's count is authoritative: it is what the reader is being shown."""
    assert join_capped(["a"], 9) == "a (+8 more not shown)"


def test_a_count_smaller_than_the_list_does_not_invent_a_negative():
    assert join_capped(list("abc"), 1) == "a; b; c"


# --- the two converted sites -----------------------------------------------------------------

def test_the_1009_line_uses_it():
    from env_generator.llm_generator.multi_agent.runtime import delivery_gate as dg
    src = inspect.getsource(dg)
    assert "join_capped(_names, len(_names))" in src
    assert '"; ".join(_names[:6])' not in src


def test_the_1014_line_uses_it():
    from env_generator.llm_generator.multi_agent.runtime import heal_pipeline as hp
    src = inspect.getsource(hp)
    assert "join_capped(_hits, len(_hits), cap=10)" in src
    assert '"; ".join(_hits[:10])' not in src


def test_both_modules_still_import():
    """★ The seam that actually broke: the import insert landed above
    `from __future__ import annotations` and heal_pipeline stopped importing."""
    import importlib
    for m in ("delivery_gate", "heal_pipeline", "message_format"):
        importlib.import_module(
            f"env_generator.llm_generator.multi_agent.runtime.{m}")


def test_future_imports_stay_first_everywhere_in_runtime():
    """Generalised from that breakage: a `__future__` import must be the first statement."""
    bad = []
    for f in sorted(glob.glob(os.path.join(_RUNTIME, "*.py"))):
        try:
            tree = ast.parse(pathlib.Path(f).read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            bad.append(f"{os.path.basename(f)}: does not parse")
            continue
        body = [n for n in tree.body if not isinstance(n, ast.Expr)]
        for i, n in enumerate(body):
            if isinstance(n, ast.ImportFrom) and n.module == "__future__" and i != 0:
                bad.append(f"{os.path.basename(f)}: __future__ import is statement {i}")
    assert bad == [], bad


# --- every site is converted, and no new one may appear ----------------------------------

_CONVERTED = {
    "deliverability.py": 2, "delivery_gate.py": 8, "design_prep.py": 1,
    "frontend_audit.py": 2, "frontend_scaffold.py": 1, "heal_pipeline.py": 1,
    "remediation_dispatcher.py": 4, "seed_audit.py": 1, "validation_runner.py": 2,
    "visual_fidelity.py": 5,
}


@pytest.mark.parametrize("mod,n", sorted(_CONVERTED.items()))
def test_each_module_uses_the_helper(mod, n):
    src = open(os.path.join(_RUNTIME, mod), encoding="utf-8").read()
    got = src.count("join_capped(")
    assert got >= n, f"{mod}: expected >= {n} join_capped call(s), found {got}"


@pytest.mark.parametrize("mod", sorted(_CONVERTED))
def test_each_converted_module_still_imports(mod):
    """★ The seam that actually broke: the import insert landed above
    `from __future__ import annotations` and heal_pipeline stopped importing. Every module
    touched by this fix is executed, not grepped."""
    import importlib
    importlib.import_module(f"env_generator.llm_generator.multi_agent.runtime.{mod[:-3]}")


def _joins_of_a_sliced_list(path):
    """`.join(...)` calls whose argument is cut by a constant-upper slice.

    Anchored on AST shape, not on a digit regex — the regex version produced a false positive
    on an md5 prefix (`_h713[:12]`) and missed every `+`-concatenated site.
    """
    try:
        tree = ast.parse(pathlib.Path(path).read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return []
    def _capped(node):
        return (isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice)
                and isinstance(node.slice.upper, ast.Constant)
                and isinstance(node.slice.upper.value, int))

    out = []
    for node in ast.walk(tree):
        # `"; ".join(xs)[:200]` — the cut is on the join's RESULT, so it can sever an item
        # mid-word. This was remediation_dispatcher:891.
        if _capped(node) and isinstance(node.value, ast.Call) \
                and isinstance(node.value.func, ast.Attribute) \
                and node.value.func.attr == "join":
            out.append((node.lineno, ast.unparse(node)[:90]))
            continue
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "join" and node.args):
            continue
        arg = node.args[0]
        # The cap must be on WHAT IS JOINED: the argument itself, or the iterable of a
        # comprehension. A slice inside the ELEMENT expression is text abbreviation
        # (`p[:1].upper()`, an md5 prefix) — 32 false positives when this was `ast.walk`.
        targets = [arg]
        if isinstance(arg, (ast.GeneratorExp, ast.ListComp)):
            targets = [g.iter for g in arg.generators]
        if any(_capped(t) for t in targets):
            out.append((node.lineno, ast.unparse(node)[:90]))
    return out


def _capped_lists(with_count):
    """Capped lists in runtime/, split by whether a COUNT is printed beside the cut.

    That split is the defect boundary, not a convenience: "5 chain(s) failed: <two names>"
    is a contradiction the reader can act on wrongly, while a bounded list with no claimed
    total is merely brief.
    """
    out = []
    for f in sorted(glob.glob(os.path.join(_RUNTIME, "*.py"))):
        lines = pathlib.Path(f).read_text(encoding="utf-8", errors="ignore").splitlines()
        for lineno, text in _joins_of_a_sliced_list(f):
            window = " ".join(lines[max(0, lineno - 4):lineno + 4])
            if "more" in window or "…" in window or "..." in window:
                continue  # the cut declares itself
            counted = "len(" in window or "%d" in window or "count" in window.lower()
            if counted is with_count:
                out.append(f"{os.path.basename(f)}:{lineno}: {text}")
    return out


def test_no_count_sits_beside_a_silent_truncation():
    """★ #1034 itself, enforced. The eyeball scan that opened this found 12; the AST scan
    finds the real population, and eight sites were missing from my list entirely
    (deliverability x2, delivery_gate x2, remediation_dispatcher, seed_audit,
    validation_runner x2, visual_fidelity)."""
    offenders = _capped_lists(with_count=True)
    assert offenders == [], (
        f"{len(offenders)} count(s) printed beside a silent cut:\n" + "\n".join(offenders))


def test_the_lesser_class_is_bounded_and_recorded():
    """A capped list with NO count printed: it reads as complete but claims no total, so it
    cannot contradict itself across ticks. Not converted — recorded, and held at its current
    size so the class cannot quietly grow into the one above."""
    rest = _capped_lists(with_count=False)
    assert len(rest) <= 32, (
        f"{len(rest)} uncounted capped lists (was 30); a new one should either declare its "
        "cut or use join_capped:\n" + "\n".join(rest))


def test_the_guard_would_catch_a_regression():
    """★ Plant the defect and demand the finding — an unwatched check reports 'clean'.
    The pre-fix r172 expression must be flagged, and the fixed one must not."""
    import tempfile
    def scan(code):
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
            fh.write(code)
        return _joins_of_a_sliced_list(fh.name)

    assert scan('logger.warning("%d x: %s", len(v), "; ".join(v[:4]))'), \
        "the pre-fix shape must be flagged"
    assert scan('logger.warning("%d: %s", len(v), "; ".join(str(b) for b in v)[:200])'), \
        "a cut on the JOINED STRING can sever an item mid-word — it must be flagged too"
    assert scan('x = ", ".join(str(u["s"]) for u in items[:4])'), \
        "a cap on a comprehension's ITERABLE is a list cap"
    assert not scan('logger.warning("%d x: %s", len(v), join_capped(v, len(v)))'), \
        "the fixed shape must be clean"
    assert not scan('logger.warning("md5 %s: %s", h[:12], ", ".join(sorted(names)))'), \
        "an md5 prefix beside a FULL list is not this defect (the r174 false positive)"
    assert not scan('x = "".join(p[:1].upper() + p[1:] for p in parts)'), \
        "★ a slice in the ELEMENT expression is text abbreviation, not a list cap"


def test_the_two_scan_corrections_are_recorded():
    d = " ".join((__doc__ or "").split())
    assert "FALSE POSITIVE" in d and "_h713[:12]" in d
    assert "UNDERCOUNT" in d and "concatenation" in d


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
