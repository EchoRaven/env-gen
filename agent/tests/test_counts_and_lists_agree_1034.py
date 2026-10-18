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
#
# #1203jx: the second half of that heading was a CLAIM, not a check. `_CONVERTED` asserts
# `join_capped(` appears at least N times per module, which pins the conversions in place and
# can never notice a NEW site that says "12 files" and then lists 5. Same shape as #1203js's
# `_KNOWN`: a sentence promising a property no assertion implemented.
#
# The predicate is the HARM, not the shape. A truncating slice is everywhere (88 sites in the
# tree) and almost all of them are harmless -- `''.join(p[:1].upper() + p[1:])` capitalises,
# `' '.join(sys.argv[:6])` is a log line. What #1034 is about is a COUNT of the whole
# collection standing beside a CUT rendering of it in the SAME sentence, with nothing saying
# what was cut. Scoped that way the tree holds three, and two of them append their own "...":
#
#     commit_gate.py:144       {len(files)} file(s): {', '.join(files[:5])}{'...' if >5}   marked
#     hub_pulse.py:775         same shape                                                 marked
#     generator_memory.py      "Task created {len(x)} files: {', '.join(list(x)[:5])}"     UNMARKED
#
# The third is fixed (#1203jx), so the unmarked count is ZERO and this keeps it there. The
# whole llm_generator package is scanned, not `runtime/` -- the one real violation lived in
# `memory/`, which every earlier reach here excluded.
import ast as _ast1203jx

_MARKERS_1203JX = ("more not shown", "join_capped", "...", "\u2026", "more)", "and more")


def _own_nodes_1203jx(scope):
    """Nodes belonging to THIS scope, not descending into nested functions or classes.

    #1203jx: `ast.walk` has no notion of scope, so the module-level pass walked straight
    into every function body and attributed one function's truncated variable to another
    function's f-string. My own scope test caught it; the live tree would not have, because
    both halves rarely sit in the same module.
    """
    out, stack = [], list(_ast1203jx.iter_child_nodes(scope))
    while stack:
        n = stack.pop()
        if isinstance(n, (_ast1203jx.FunctionDef, _ast1203jx.AsyncFunctionDef,
                          _ast1203jx.ClassDef)):
            continue
        out.append(n)
        stack.extend(_ast1203jx.iter_child_nodes(n))
    return out


def _count_beside_cut_list_1203jx(tree, ignore_markers=False):
    """f-strings carrying BOTH len(<whole>) and a joined, truncated rendering, unmarked."""
    def _has_len(node):
        return any(isinstance(c, _ast1203jx.Call)
                   and getattr(c.func, "id", None) == "len"
                   for c in _ast1203jx.walk(node))

    def _joined_trunc(node):
        for c in _ast1203jx.walk(node):
            if not (isinstance(c, _ast1203jx.Call)
                    and isinstance(c.func, _ast1203jx.Attribute)
                    and c.func.attr == "join" and c.args):
                continue
            for sub in _ast1203jx.walk(c.args[0]):
                if (isinstance(sub, _ast1203jx.Subscript)
                        and isinstance(sub.slice, _ast1203jx.Slice)
                        and sub.slice.lower is None and sub.slice.upper is not None
                        and isinstance(sub.slice.upper, _ast1203jx.Constant)
                        and isinstance(sub.slice.upper.value, int)):
                    return True
        return False

    out = []
    # #1203jx: the harm comes in two shapes and the first version saw only one.
    #
    #   inline        f"{len(x)} file(s): {', '.join(x[:5])}"
    #   cross-stmt    s = ', '.join(x[:5])  ...  f"{len(x)} file(s): {s}"
    #
    # The second is not a corner case -- it is what the FIX looks like, so a ratchet blind to
    # it cannot protect the sites just repaired. `code_tools` carried three of them
    # ("Found 23 issues: <five of them>", returned to the agent that has to fix them) and
    # `remediation_dispatcher` one. A mutation that reverted a repaired site to the split form
    # survived the inline-only detector; that is how this was found.
    scopes = [x for x in _ast1203jx.walk(tree)
              if isinstance(x, (_ast1203jx.FunctionDef, _ast1203jx.AsyncFunctionDef))]
    scopes.append(tree)
    seen = set()
    for scope in scopes:
        cut_vars = {}
        for st in _own_nodes_1203jx(scope):
            if isinstance(st, _ast1203jx.Assign) and _joined_trunc(st.value):
                for t in st.targets:
                    if isinstance(t, _ast1203jx.Name):
                        cut_vars[t.id] = _ast1203jx.unparse(st)
        for n in _own_nodes_1203jx(scope):
            if not isinstance(n, _ast1203jx.JoinedStr) or not _has_len(n):
                continue
            txt = _ast1203jx.unparse(n)
            via = sorted({c.id for c in _ast1203jx.walk(n)
                          if isinstance(c, _ast1203jx.Name) and c.id in cut_vars})
            if not (_joined_trunc(n) or via):
                continue
            # The remainder may be declared where the list is BUILT, not where it is
            # interpolated, so both texts are consulted.
            whole = txt + "".join(cut_vars[v] for v in via)
            if not ignore_markers and any(m in whole for m in _MARKERS_1203JX):
                continue
            key = (getattr(n, "lineno", "?"), txt)
            if key in seen:
                continue
            seen.add(key)
            out.append((key[0], " ".join(txt.split())[:110]))
    return out


# runtime -> multi_agent -> llm_generator. One level higher is `env_generator`, which
# my first version used and which made the reach assertion below fail with the paths
# prefixed `llm_generator/` -- the test caught my own off-by-one.
_PKG_1203JX = os.path.abspath(os.path.join(_RUNTIME, "..", ".."))


def _scan_pkg_1203jx(ignore_markers=False):
    """Returns (findings, files_visited). The second value is not decoration.

    #1203jx: the first version returned findings alone, and the live answer is ZERO -- so a
    mutation that made the walk iterate `[]`, and another that narrowed the root back to
    `runtime/` (where the one real violation was NOT), both left every test green. A ceiling
    of zero is evidence only while the scan is known to have looked, and the REACH is part of
    the claim here because `memory/` is the package this ratchet used to exclude.
    """
    found, visited = [], []
    for dirpath, _dirs, files in os.walk(_PKG_1203JX):
        if os.sep + "tests" in dirpath:
            continue
        for fn in sorted(files):
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            try:
                # #1202eu: a handle per FILE, closed per file. This walk opens every .py in
                # the package, and a bare `open(...).read()` here is that ratchet's exact
                # subject -- it caught this on the first full run after I wrote it.
                with open(path, encoding="utf-8", errors="ignore") as _fh1203jx:
                    tree = _ast1203jx.parse(_fh1203jx.read())
            except Exception:
                continue
            visited.append(os.path.relpath(path, _PKG_1203JX))
            for lineno, txt in _count_beside_cut_list_1203jx(
                    tree, ignore_markers=ignore_markers):
                found.append("%s:%s  %s" % (fn, lineno, txt))
    return found, visited


def test_the_scan_looked_and_reached_memory_1203jx():
    """Non-vacuity AND reach, in one assertion each.

    The marked-site check is a positive control on the REAL tree: with markers ignored the
    detector must still find `commit_gate` and `hub_pulse`, which carry their own "...". If
    it finds neither, the zero above means "did not look".
    """
    _found, visited = _scan_pkg_1203jx()
    assert len(visited) >= 100, "the scan parsed only %d file(s); it did not look" % len(visited)
    for must in (os.path.join("memory", "generator_memory.py"),
                 os.path.join("multi_agent", "runtime", "delivery_gate.py")):
        assert must in visited, (
            "the scan does not reach %s — the only real violation this ratchet ever found "
            "lived in memory/, which a runtime-only root excludes" % must)
    marked, _v = _scan_pkg_1203jx(ignore_markers=True)
    names = {m.split(":")[0] for m in marked}
    assert {"commit_gate.py", "hub_pulse.py"} <= names, (
        "the detector no longer fires on the real tree's known count-beside-cut-list sites "
        "(markers ignored): %s" % sorted(names))


def test_the_detector_sees_an_unmarked_site_1203jx():
    """Positive control: zero below must mean "none left", not "the scan broke".

    Without this, every mutation of the predicate reads green, because the live answer is
    already zero -- the trap #1203js was built to close one level up.
    """
    src = ('x = [1, 2, 3]\n'
           'msg = f"{len(x)} thing(s): {chr(44).join(str(i) for i in x[:2])}"\n')
    hits = _count_beside_cut_list_1203jx(_ast1203jx.parse(src))
    assert hits, "the detector no longer recognises a count beside a cut list"


def test_the_detector_accepts_a_declared_remainder_1203jx():
    """And the marked form must NOT be flagged, or the ceiling is unreachable by design."""
    # The marker has to survive `ast.unparse`, so it is a LITERAL here. My first fixture
    # built it with chr(46) * 3 to dodge the quoting, and unparse rendered the call rather
    # than the dots -- the test failed on the fixture, not on the detector.
    src = "\n".join([
        "x = [1, 2, 3]",
        "msg = f'{len(x)} thing(s): " + '{", ".join(str(i) for i in x[:2])}'
        + "{\"...\" if len(x) > 2 else \"\"}'",
    ]) + "\n"
    assert "..." in src, src
    assert _count_beside_cut_list_1203jx(_ast1203jx.parse(src)) == [], src


def test_the_detector_sees_the_cross_statement_shape_1203jx():
    """Positive control for the shape the FIX takes.

    Repairing a site moves the list-building out of the f-string, so an inline-only detector
    stops protecting exactly the code it just caused. The live count for this shape is zero
    (four sites were repaired), which is why it needs a fixture rather than a re-run.
    """
    src = ("def f(errors):\n"
           "    s = '; '.join(str(e) for e in errors[:5])\n"
           "    return f'Found {len(errors)} issues: {s}'\n")
    hits = _count_beside_cut_list_1203jx(_ast1203jx.parse(src))
    assert hits, "a count beside a list cut in an earlier statement is not seen"


def test_the_cross_statement_remainder_may_be_declared_at_the_build_1203jx():
    """The marker can sit where the list is BUILT, not where it is interpolated.

    The first version of this test used `join_capped(...)` in the assignment and passed
    VACUOUSLY: `join_capped` is a plain call, not `.join(`, so the shape was never detected
    and the `== []` held for the wrong reason. A mutation that dropped the build-site text
    from the marker check survived it. The assignment below carries a REAL truncating join,
    so the only thing keeping it off the list is the marker.
    """
    marked = ("def f(errors):\n"
              "    s = '; '.join(str(e) for e in errors[:5])"
              " + ' (+%d more not shown)' % (len(errors) - 5)\n"
              "    return f'Found {len(errors)} issues: {s}'\n")
    bare = ("def f(errors):\n"
            "    s = '; '.join(str(e) for e in errors[:5])\n"
            "    return f'Found {len(errors)} issues: {s}'\n")
    # Non-vacuity first: without the marker the SAME shape must be flagged, otherwise this
    # test would pass because nothing was detected rather than because the marker was found.
    assert _count_beside_cut_list_1203jx(_ast1203jx.parse(bare)), "the fixture is not detectable"
    assert _count_beside_cut_list_1203jx(_ast1203jx.parse(marked)) == []


def test_a_cut_variable_from_another_function_is_not_attributed_1203jx():
    """Scope matters: a same-named local elsewhere must not implicate this f-string."""
    src = ("def build(errors):\n"
           "    s = '; '.join(str(e) for e in errors[:5])\n"
           "    return s\n"
           "def report(errors, s):\n"
           "    return f'Found {len(errors)} issues: {s}'\n")
    hits = _count_beside_cut_list_1203jx(_ast1203jx.parse(src))
    assert all("report" not in h[1] for h in hits), hits
    assert len(hits) == 0, hits


def test_a_hash_prefix_is_not_a_cut_list_1203jx():
    """`hexdigest()[:8]` is a slice and not a truncated list; the first predicate flagged it."""
    src = 'msg = f"{h.hexdigest()[:8]}:{len(lines)}L"\n'
    assert _count_beside_cut_list_1203jx(_ast1203jx.parse(src)) == []


def test_no_count_stands_beside_an_unmarked_cut_list_1203jx():
    found, _visited = _scan_pkg_1203jx()
    assert found == [], (
        "a count of the whole collection stands beside a CUT rendering of it with nothing "
        "saying what was cut — use join_capped (#1034):\n  " + "\n  ".join(found))



_CONVERTED = {
    "deliverability.py": 2, "delivery_gate.py": 8, "design_prep.py": 1,
    "frontend_audit.py": 2, "frontend_scaffold.py": 1, "heal_pipeline.py": 1,
    "remediation_dispatcher.py": 4, "seed_audit.py": 1, "validation_runner.py": 2,
    "visual_fidelity.py": 5,
}


@pytest.mark.parametrize("mod,n", sorted(_CONVERTED.items()))
def test_each_module_uses_the_helper(mod, n):
    # #1203jx: closed, not because this leaks much -- it is one file per parametrised call,
    # ten in all, nowhere near the 1,593 handles #1202eu was written for -- but because it is
    # the ONLY inhabitant of that ratchet's blind spot. Its regex is
    # `open\([^)]*\)\.read\(\)`, which a nested call in the arguments hides
    # (`open(os.path.join(a, b), ...)`). Measured across every test file with a tree loop: one
    # site, this one. Widening the regex for a single non-harmful instance would be the
    # "same shape, different harm" mistake; emptying the blind spot costs three lines.
    with open(os.path.join(_RUNTIME, mod), encoding="utf-8") as _fh1203jx:
        src = _fh1203jx.read()
    got = src.count("join_capped(")
    assert got >= n, f"{mod}: expected >= {n} join_capped call(s), found {got}"


@pytest.mark.parametrize("mod", sorted(_CONVERTED))
def test_each_converted_module_still_imports(mod):
    """★ The seam that actually broke: the import insert landed above
    `from __future__ import annotations` and heal_pipeline stopped importing. Every module
    touched by this fix is executed, not grepped."""
    import importlib
    importlib.import_module(f"env_generator.llm_generator.multi_agent.runtime.{mod[:-3]}")


def _code_only_1202w3(line: str) -> str:
    """The line with any trailing/whole-line comment removed, quotes respected.

    Deliberately simple: a `#` inside a string literal is kept, everything from an unquoted
    `#` is dropped. That is enough to stop prose from answering a question about code.
    """
    out = []
    quote = None
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            out.append(ch)
            if ch == "\\":
                if i + 1 < len(line):
                    out.append(line[i + 1])
                    i += 2
                    continue
            elif ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
        i += 1
    return "".join(out)


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
            # #1202w3: the window is CODE, not commentary. The marker check reads the
            # surrounding eight lines, and a COMMENT that happens to contain "more" silenced
            # it -- found while fixing #1202w2, whose natural comment is `join_capped appends
            # the "+N more" this used to omit`. Writing that sentence blinded the guard to the
            # bare slice three lines below it. A cut declares itself to the READER OF THE
            # OUTPUT, and a comment is not output.
            window = " ".join(_code_only_1202w3(ln) for ln in lines[max(0, lineno - 4):lineno + 4])
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


def test_the_lint_helper_shows_no_list_when_it_cannot_cap_1203jx(monkeypatch):
    """`code_tools._jc1203jx`'s unreachable-helper branch, driven rather than assumed.

    #1203jx: three lint summaries there said "Found 23 issues: <five of them>" to the agent
    that has to fix them. The wrapper imports `join_capped` lazily because `message_format`
    lives two packages over, and its `except` must NOT re-implement the remainder rule -- a
    second owner would rot (#1032). It shows the count and NO list instead, because a list
    that is not rendered cannot be a cut one. Nothing in the suite reaches a failed import,
    so a mutation that made this branch render a cut list survived; this breaks the helper on
    purpose.

    #1203nc REWROTE WHAT THIS DRIVES, and the reason is the whole of #1203n6: the branch this
    test was breaking was the IMPORT, and an import that degrades into an apology is how
    "Found 52 issues: (details unavailable)" reached the backend lane on every run of r189,
    r190 and r191 -- 11 messages, 124 issues withheld. The import is now absolute and sits
    ABOVE the try, so an ImportError is loud. The `except` covers what it always should have:
    a failure INSIDE `join_capped`.
    """
    import importlib
    import sys
    from env_generator.llm_generator.tools import code_tools

    assert "more not shown" in code_tools._jc1203jx([str(i) for i in range(5)], 23, cap=5)

    # The module has to be reached by the name the WRAPPER imports. `multi_agent.runtime.
    # message_format` and `env_generator.llm_generator.multi_agent.runtime.message_format`
    # are two sys.modules entries holding two module objects -- the dual root #1203n6 is
    # about -- so patching the long one leaves the wrapper untouched. Measured by doing
    # exactly that: the apology never appeared.
    mf = importlib.import_module("multi_agent.runtime.message_format")

    # #1203jx's rule, driven: the helper fails, so show the count and NO list.
    def _boom(*a, **k):
        raise RuntimeError("join_capped exploded")

    monkeypatch.setattr(mf, "join_capped", _boom)
    out = code_tools._jc1203jx([str(i) for i in range(5)], 23, cap=5)
    assert out == "(details unavailable)", out
    assert "0; 1" not in out, "the fallback rendered a cut list: %r" % out

    # #1203nc's rule: an unreachable helper is NOT the same event, and must not be swallowed.
    monkeypatch.setitem(sys.modules, "multi_agent.runtime.message_format", None)
    with pytest.raises(ImportError):
        code_tools._jc1203jx([str(i) for i in range(5)], 23, cap=5)
