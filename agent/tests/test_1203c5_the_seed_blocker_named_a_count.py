r"""#1203c5: the seed blocker names a COUNT, and the names sit in the dict beside it.

`compute_deliverability` builds `f"{seed['missing']} table(s) missing seed registration (Cutover
21 gate)"` while `_seed_summary`, twenty lines up, already carries

    # #1202ow: which tables, and why — the task body could only say "N table(s)".
    "flagged_tables": [{"table": ..., "reason": ...} …][:20]

#1202ow put the names there because a count is unactionable, and fixed the TASK BODY. The BLOCKER
PROSE — what the gate ledger records and the lane reads — stayed on the count. #1202lf's rule:
fixing one reader is worse than fixing none, because the fix looks done.

MEASURED over every gate ledger: 191 occurrences across 22 runs, a table named ZERO times,
spellings from "1 table(s)" to "13 table(s)". r146 is live proof, and the asymmetry inside ONE
record is the argument:

    deliverability_dead_artifacts  files:…/SignupPage.jsx, …/LoginModalPage.jsx
    business_chain_failing         [video_engagement_comments] POST /api/videos/44/comments → 400 …
    deliverability_missing_seed    3 table(s) missing seed registration (Cutover 21 gate)

★ The token is matched by the substring "missing seed" (`delivery_gate.py:3014`), verified to
still map after the change — a reworded blocker that stops mapping falls into the catch-all,
which is the defect #1203b8 had just finished clearing.
"""
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import multi_agent.runtime.deliverability as D  # noqa: E402
from multi_agent.runtime.delivery_gate import _deliverability_check_token as _token  # noqa: E402


def _blockers(monkeypatch, summary):
    """Run the seed branch with a controlled `_seed_summary` and collect what it appends."""
    import ast
    import inspect

    src = inspect.getsource(D.compute_deliverability)
    tree = ast.parse(src.lstrip())
    seg = None
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and "missing seed registration" in ast.dump(node):
            seg = node
            break
    assert seg is not None, "the seed blocker branch is gone"
    out = []
    env = {"seed": summary, "functionally_validated": False, "blockers": out,
           "join_capped": D.join_capped, "isinstance": isinstance, "dict": dict, "len": len,
           "str": str}
    exec(compile(ast.Module(body=[seg], type_ignores=[]), "<seed>", "exec"), env)
    return out


_THREE = {
    "missing": 3, "flagged": 4,
    "flagged_tables": [
        {"table": "videos", "reason": "missing_seed"},
        {"table": "comments", "reason": "missing_seed"},
        {"table": "sounds", "reason": "missing_seed"},
        {"table": "users", "reason": "low_row_count"},
    ],
}


def test_the_tables_are_named(monkeypatch):
    """★ r146's exact state: three missing, and the lane could not learn which."""
    b = _blockers(monkeypatch, _THREE)
    assert len(b) == 1, b
    for t in ("videos", "comments", "sounds"):
        assert t in b[0], b[0]


def test_the_reason_rides_along(monkeypatch):
    """`missing_seed` and `low_row_count` send a lane to different work, and `flagged_tables`
    already carries the distinction."""
    b = _blockers(monkeypatch, _THREE)
    assert "missing_seed" in b[0], b[0]


def test_only_the_missing_ones_are_named(monkeypatch):
    """★ The sibling blocker owns `low_row_count` (it maps to `deliverability_seed_quality`);
    naming it here would attribute it to the wrong check."""
    b = _blockers(monkeypatch, _THREE)
    assert "users" not in b[0], b[0]


def test_the_count_is_unchanged(monkeypatch):
    """Additive: the number the gate has always reported stays, and stays first."""
    b = _blockers(monkeypatch, _THREE)
    assert b[0].startswith("3 table(s) missing seed registration"), b[0]


def test_the_token_still_maps(monkeypatch):
    """★ The canonicaliser matches the substring "missing seed". A reworded blocker that stops
    mapping lands in `deliverability_other:<prose>`, which #1203b8 had just emptied."""
    b = _blockers(monkeypatch, _THREE)
    assert _token(b[0]) == "deliverability_missing_seed", _token(b[0])


def test_a_long_list_says_what_it_cut(monkeypatch):
    """#1034: a silently truncated list understates the work."""
    many = {"missing": 12, "flagged": 12,
            "flagged_tables": [{"table": "t%d" % i, "reason": "missing_seed"}
                               for i in range(12)]}
    b = _blockers(monkeypatch, many)
    assert "more" in b[0], b[0]
    assert b[0].startswith("12 table(s)"), b[0]


def test_no_names_available_reads_exactly_as_before(monkeypatch):
    """An older summary without `flagged_tables` (or one whose entries carry no table) must
    produce the original sentence byte for byte — no dangling colon."""
    for summary in ({"missing": 2, "flagged": 2},
                    {"missing": 2, "flagged": 2, "flagged_tables": []},
                    {"missing": 2, "flagged": 2,
                     "flagged_tables": [{"reason": "missing_seed"}]}):
        b = _blockers(monkeypatch, summary)
        assert b == ["2 table(s) missing seed registration (Cutover 21 gate)"], (summary, b)


def test_the_summary_still_carries_the_names():
    """★ The names only exist here because #1202ow put them in; if that is ever removed this
    blocker silently returns to a bare count, and this is where it shows."""
    import ast
    import inspect

    src = inspect.getsource(D._seed_summary)
    assert "flagged_tables" in src, "#1202ow's carry is gone"
    tree = ast.parse(src.lstrip())
    keys = {k.value for n in ast.walk(tree) if isinstance(n, ast.Dict)
            for k in n.keys if isinstance(k, ast.Constant)}
    assert {"missing", "flagged_tables"} <= keys, sorted(str(k) for k in keys)
