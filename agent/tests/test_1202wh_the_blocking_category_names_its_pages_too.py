"""#1202wh: the UI-evidence category that BLOCKS must name its pages, like the one that doesn't.

`_ui_evidence_breadth_739` returns `pages_failed` alongside `failed_records`, and the gate
verdict carried only the count. Two lines below it, `unreachable` -- the category that is
reported and never blocks (#1154) -- carried both its count AND `pages_unreachable`.

So a run directory could answer "4 UI records failed" and nothing else, while the harmless
sibling answered which. `validation_ui_evidence_failed` is the second most frequent blocker
over r135 and r136 (135 of ~390 gate evaluations) and `unreachable_records` was 0 in every
one of them -- the failures were real, and not one is diagnosable after the run.

Same defect as #1202wc, one category further in: a blocker that records a number and not an
instance cannot be investigated once the run is over.
"""
import ast
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

_GATE = os.path.join(_AGENT, "env_generator", "llm_generator", "multi_agent", "runtime",
                     "delivery_gate.py")


def _read(path):
    with open(path, encoding="utf-8") as fh:      # #1202eu
        return fh.read()


def _verdict_keys():
    """Every string key the gate verdict dict is built with, located structurally.

    Asserted over the AST rather than by matching the literal `"ui_evidence_failed_pages":`
    in the file: a key that appears in a comment, a docstring or an unrelated dict would
    satisfy a text search without ever reaching the verdict a run writes down.
    """
    tree = ast.parse(_read(_GATE))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = {k.value for k in node.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        if "ui_evidence_failed_records" in keys and "ui_evidence_unreachable_pages" in keys:
            return keys
    return set()


def test_the_verdict_dict_is_found():
    keys = _verdict_keys()
    assert keys, "the gate verdict carrying the ui-evidence counts was not located"


def test_the_failing_pages_travel_with_their_count():
    keys = _verdict_keys()
    assert "ui_evidence_failed_pages" in keys, (
        "the blocking category records only a number: %s"
        % sorted(k for k in keys if k.startswith("ui_evidence")))


def test_both_categories_are_symmetric():
    """★ The asymmetry was the tell: the harmless one named its pages, the blocker did not."""
    keys = _verdict_keys()
    for cat in ("failed", "unreachable"):
        assert "ui_evidence_%s_records" % cat in keys, cat
        assert "ui_evidence_%s_pages" % cat in keys, (
            "`%s` carries a count with no instances while its sibling carries both" % cat)


def test_the_source_of_the_names_already_provides_them():
    """`pages_failed` is not new data -- breadth_739 has returned it all along."""
    tree = ast.parse(_read(_GATE))
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == "_ui_evidence_breadth_739"), None)
    assert fn is not None, "_ui_evidence_breadth_739 not found"
    returned = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            returned |= {k.value for k in node.value.keys
                         if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    assert {"pages_failed", "failed_records"} <= returned, sorted(returned)
