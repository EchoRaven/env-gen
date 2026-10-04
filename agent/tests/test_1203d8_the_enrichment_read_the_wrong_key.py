r"""#1203d8: #612's enrichment read a page-shaped key off a step-shaped dict, so it never ran.

`run_browser_test_user` records its steps through one helper:

    def step(name: str, ok: bool, note: str = "") -> None:
        report["steps"].append({"step": name, "ok": bool(ok), "note": note[:200]})

#612 then tried to find one of those steps and widen its note:

    for _s in report.get("steps") or []:
        if isinstance(_s, dict) and str(_s.get("name", "")).startswith(
                "auth flow stores a token"):

`str({}.get("name", ""))` is `""`, and `"".startswith("auth flow stores a token")` is False, so
the loop matched nothing on every iteration of every run: **the branch was dead by
construction**, no data required to show it. `name` IS the right key on a PAGE dict -- four
other reads in that file are pages and pages carry it -- which is how it survived review.

What the dead note said: the SAME credentials DO authenticate over the API (#504), so a
form-drive auth failure is neither a backend nor a credential fault. It feeds
`browser_ui_unusable`, which by FIX #152 is a HARD gate that NEVER escape-releases; r146's 1.1.0
was held there six times and died. The one sentence that would have narrowed the frontend's work
reached nobody.

★ Honest about the evidence: I could not corroborate this from run artifacts, because
`run_browser_test_user`'s report is never written to disk -- the positive control (searching the
corpus for `step()`'s own wording) returns 0 files, so the corpus cannot speak to it either way.
The proof here is the writer/reader key disagreement, which is decidable from source alone.
"""
import ast
import inspect
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime import test_user_runner as TUR  # noqa: E402

_SRC = inspect.getsource(TUR)
_TREE = ast.parse(_SRC)


def _step_writer_keys():
    """Every key the one writer of `report["steps"]` actually stores, read through AST so a
    reformat cannot fool this (#1202vq: an AST relation test that names no literal)."""
    keys = set()
    for node in ast.walk(_TREE):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "append"):
            continue
        tgt = node.func.value
        if not (isinstance(tgt, ast.Subscript) and isinstance(tgt.slice, ast.Constant)
                and tgt.slice.value == "steps"):
            continue
        for arg in node.args:
            if isinstance(arg, ast.Dict):
                keys |= {k.value for k in arg.keys
                         if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    return keys


def _enrichment_read_keys():
    """The keys #612's loop reads off those dicts, located by the literal it compares against
    rather than by a line number (#943)."""
    out = set()
    for node in ast.walk(_TREE):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "startswith" and node.args):
            continue
        a = node.args[0]
        if not (isinstance(a, ast.Constant) and isinstance(a.value, str)
                and a.value.startswith("auth flow stores a token")):
            continue
        for sub in ast.walk(node.func.value):
            if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr == "get" and sub.args
                    and isinstance(sub.args[0], ast.Constant)):
                out.add(sub.args[0].value)
    return out


def test_the_writer_stores_step_not_name():
    """Ground truth: there is one writer and these are its keys."""
    assert _step_writer_keys() == {"step", "ok", "note"}, _step_writer_keys()


def test_the_enrichment_reads_a_key_the_writer_stores():
    """★ The defect in one assertion, and the ratchet: writer and reader must agree. Naming
    neither key keeps this true after a future rename of either side."""
    read = _enrichment_read_keys()
    assert read, "the #612 enrichment is gone — if that was deliberate, delete this test too"
    written = _step_writer_keys()
    assert read <= written, (
        "#612 reads %s off a dict that only ever carries %s, so the branch can never match"
        % (sorted(read - written), sorted(written)))


def test_the_dead_branch_is_dead_by_construction_not_by_data():
    """The pre-#1203d8 expression, evaluated on the writer's own record shape: no run data is
    needed to see that it cannot match."""
    record = {"step": "auth flow stores a token + navigates into the app", "ok": False,
              "note": "/auth returned [401]"}
    assert str(record.get("name", "")).startswith("auth flow stores a token") is False
    assert str(record.get("step", "")).startswith("auth flow stores a token") is True


def test_the_note_actually_reaches_the_record():
    """End to end on the shipped expression: run #612's loop over a real-shaped report and
    assert the note was widened. Exercises the source, not a replica."""
    i = _SRC.index('for _s in report.get("steps") or []:')
    j = _SRC.index("break", i) + len("break")
    import textwrap
    block = textwrap.dedent(_SRC[i:j])
    report = {"steps": [
        {"step": "open the app", "ok": True, "note": ""},
        {"step": "auth flow stores a token + navigates into the app", "ok": False,
         "note": "/auth returned [401] but token=False"},
    ]}
    ns = {"report": report}
    exec(compile(block, "<enrichment>", "exec"), ns)
    note = report["steps"][1]["note"]
    assert "SAME creds DO authenticate over" in note, note
    assert report["steps"][0]["note"] == "", "it widened the wrong step"


def test_only_the_matching_step_is_widened():
    """A report with no auth step must come back untouched."""
    i = _SRC.index('for _s in report.get("steps") or []:')
    j = _SRC.index("break", i) + len("break")
    import textwrap
    report = {"steps": [{"step": "open the app", "ok": True, "note": "fine"}]}
    exec(compile(textwrap.dedent(_SRC[i:j]), "<enrichment>", "exec"), {"report": report})
    assert report["steps"][0]["note"] == "fine"


def test_a_page_dict_is_where_name_belongs():
    """Why this survived review: `name` is correct on the OTHER dict shape in this file, so the
    expression reads as idiomatic. Pin that pages really do carry it, so a later reader does not
    'fix' the page reads by analogy with this one."""
    pages = [n for n in ast.walk(_TREE)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "get" and n.args
             and isinstance(n.args[0], ast.Constant) and n.args[0].value == "name"]
    assert len(pages) >= 4, len(pages)
