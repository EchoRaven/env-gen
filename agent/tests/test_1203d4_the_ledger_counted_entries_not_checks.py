r"""#1203d4: the hold ledger counted gate entries the way #1008 stopped the log from counting them.

Two writers render the SAME `gate["failed_checks"]`, twenty lines apart in one file:

    orchestrator.py  #1008    -> the operator log line
    orchestrator.py  #1202wc  -> logs/delivery_hold.jsonl, the artifact a post-mortem reads
                                 to learn why a run never delivered

#1008 fixed the first and said why: r164 logged "6 failed check(s)" where all six entries were
`deliverability_ui_page_unwired` -- one check, six pages -- and "this number is what an
operator (and the orchestrator deciding whether to attempt delivery) reads as the app's
distance from green". The second writer was still counting entries.

MEASURED over every gate ledger on disk: **711 of 7995 records with failed checks (8.9%)
across 66 runs** carry a duplicate. Worst: googlemaps-r16, 16 entries / 7 distinct.
Most-duplicated: `deliverability_ui_page_unwired` 418, `deliverability_dead_nav_link` 156,
`deliverability_placeholder_stub_handler` 74, `deliverability_guard_tampering` 69.

r149's hold ledger line 5 reads `4 failed check(s): ...guard_tampering, ...guard_tampering,
...page_apis_understated, business_chain_failing` -- I read that line live, and that is what
prompted this.

The fix is one shared helper rather than a second dedupe, because #1202lf's rule is that
fixing one reader is worse than fixing none: a divergence that both sites can express is a
defect waiting to come back.
"""
import ast
import inspect
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent import orchestrator as O  # noqa: E402

_SRC = inspect.getsource(O)
_fn = O._distinct_checks_1203d4


# ---------------------------------------------------------------- the helper itself

def test_r149s_actual_line_now_reads_correctly():
    """r149's list, verbatim from logs/delivery_hold.jsonl line 5."""
    n, shown = _fn(["deliverability_guard_tampering", "deliverability_guard_tampering",
                    "deliverability_page_apis_understated", "business_chain_failing"])
    assert n == 3, n
    assert "deliverability_guard_tampering x2" in shown, shown
    assert "%d failed check(s): %s" % (n, ", ".join(shown)) == (
        "3 failed check(s): business_chain_failing, deliverability_guard_tampering x2, "
        "deliverability_page_apis_understated")


def test_googlemaps_r16s_worst_case():
    """16 entries, 7 distinct -- its hold said "16 failed check(s)"."""
    n, shown = _fn(["deliverability_ui_page_unwired"] * 10 + list("abcdef"))
    assert n == 7, n
    assert "deliverability_ui_page_unwired x10" in shown, shown


def test_r164s_case_the_one_1008_was_written_for():
    n, shown = _fn(["deliverability_ui_page_unwired"] * 6)
    assert (n, shown) == (1, ["deliverability_ui_page_unwired x6"])


def test_a_list_with_no_duplicates_is_untouched():
    """★ The invariant: 91% of records have no duplicate, and their line must not move."""
    n, shown = _fn(["business_chain_failing", "deliverability_dead_artifacts"])
    assert n == 2
    assert shown == ["business_chain_failing", "deliverability_dead_artifacts"]


def test_the_instance_count_is_kept_not_discarded():
    """One check failing on six pages is still six pages. The number moves out of the
    headline count; it does not disappear (#1008's own resolution)."""
    _, shown = _fn(["x", "x", "x"])
    assert shown == ["x x3"], shown


def test_none_and_empty_are_tolerated():
    """The hold writer passes `gate.get("failed_checks")` straight through, which can be
    absent -- the old code's `or []` must survive in the helper."""
    assert _fn(None) == (0, [])
    assert _fn([]) == (0, [])


def test_non_string_entries_are_coerced_not_crashed():
    """The old writer did `str(c)` for every entry; a check name has arrived as a non-string
    before, and the helper is the only place that guard now lives."""
    n, shown = _fn([1, 1, "1"])
    assert (n, shown) == (1, ["1 x3"]), shown


def test_names_are_sorted_so_two_runs_compare():
    _, shown = _fn(["z", "a", "m"])
    assert shown == ["a", "m", "z"], shown


# ---------------------------------------------------------------- the wiring

def _hold_stanza():
    """The hold-writing stanza, bounded by two LANDMARKS rather than a byte count.

    ★ #943's ratchet caught the first draft of this helper reaching backwards with
    `_SRC[i - 600:j]`: a fixed window breaks the moment a comment above it grows, which is
    exactly what this patch did to the lines above. Anchor on text that must be there."""
    i = _SRC.index("# #1203d4: count CHECKS, not entries")
    j = _SRC.index("return  # not deliverable yet", i)
    return _SRC[i:j]


def test_the_hold_writer_calls_the_helper():
    s = _hold_stanza()
    assert "_distinct_checks_1203d4(" in s, "the ledger still counts entries itself:\n" + s


def test_no_site_counts_the_raw_list_any_more():
    """★ The defect in one assertion: no `len(` of an un-deduped failed-checks list survives."""
    assert "len(_fc1202wc)" not in _SRC, "the raw entry count is still being reported"
    assert "_seen1008" not in _SRC, "#1008 kept its own private copy of the dedupe"


def test_both_writers_call_the_same_function():
    """★ #1032 (one fact, many emitters): pin that the log line and the ledger line come from
    ONE implementation, so a later edit to either cannot silently reintroduce the drift.
    Asserted by AST over call sites, not by text, so a rename shows up as a failure here."""
    tree = ast.parse(_SRC)
    callers = set()
    for node in ast.walk(tree):
        # ★ both writers live in `async def` methods -- AsyncFunctionDef is a
        # SEPARATE node type and a FunctionDef-only walk finds neither of them.
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for sub in ast.walk(node):
            if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
                    and sub.func.id == "_distinct_checks_1203d4"):
                callers.add(node.name)
    # Both writers sit in ONE method, ~400 lines apart -- which is exactly how they drifted:
    # #1008 fixed the top of `_maybe_framework_deliver` and the bottom kept counting entries.
    assert callers == {"_maybe_framework_deliver"}, sorted(callers)
    n_calls = sum(1 for node in ast.walk(tree)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                  and node.func.id == "_distinct_checks_1203d4")
    assert n_calls >= 2, "only %d call site(s); both writers must use it" % n_calls


def test_the_helper_explains_itself_to_the_next_reader():
    """#1202zz: a decision whose reason is not in the code gets re-litigated. The docstring
    must carry the measurement, so nobody re-derives 8.9% from the ledgers again."""
    doc = _fn.__doc__ or ""
    assert "8.9%" in doc and "7995" in doc, doc[:300]
