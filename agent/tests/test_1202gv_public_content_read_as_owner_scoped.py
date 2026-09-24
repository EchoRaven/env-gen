"""#1202gv — the materials say a row is for everyone; the contract scopes it to its author.

`visibility` (#1202gd) answers exactly one question, in the compile instructions' own words:
"WHO IS A ROW FOR? ... `public` — every row is content PUBLISHED for all users to read ... A
reader who is not the author still sees the row, and seeing it is the point."

`owner_scoped_reads: True` makes the projected read `WHERE author_id = <caller>` — the reader
who is not the author sees NOTHING. The two statements are direct opposites, and today nothing
compares them. Measured on this machine, every run that carries a `visibility` declaration at
all has the contradiction: r98, r99 and r100 each declare `videos` and `comments` public while
the contract owner-scopes both.

The cost is paid three surfaces away. r100: the feed read returned `{"items": []}` to the
verifier's fresh actor, so `save: {videoId: "items.0.id"}` captured nothing, the id ladder
substituted an unrelated row, and 38 of 73 chain steps 404'd. r99 rode the same disagreement
into a 26-minute oscillation. Every existing reader of `visibility` — #1202gd's exemption,
#1202gt's wording, #1202gl's reassurance — is REACTIVE: each speaks only once some other
blocker has already fired, and r100 never tripped one, so nobody said anything at all.

NOT auth_required. "Any logged-in user sees every row" and "you must log in" are perfectly
compatible, and a check built on that pair would be a conflation (#647). Only the
owner-scoping pair is a contradiction of the declared semantics.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_audit import (  # noqa: E402
    public_content_scoped_away_1202gv)

_SPEC = {"entities": [
    {"name": "videos", "fields": ["id", "author_id"], "visibility": "public"},
    {"name": "comments", "fields": ["id", "video_id"], "visibility": "public"},
    {"name": "video_saves", "fields": ["id", "user_id"], "visibility": "owner"},
    {"name": "sounds", "fields": ["id", "name"]},
]}
_TABLES = {
    "videos": {"metadata": {"owner_scoped_reads": True}},
    "comments": {"metadata": {"owner_scoped_reads": True}},
    "video_saves": {"metadata": {"owner_scoped_reads": True}},
    "sounds": {"metadata": {}},
    "_meta": {"version": 3},
}


def test_it_names_the_tables_the_contract_scoped_away():
    out = public_content_scoped_away_1202gv(_SPEC, _TABLES)
    assert out == ["comments", "videos"], out


def test_an_owner_table_scoped_is_correct_and_silent():
    """`video_saves` is declared owner and scoped — that is the system working."""
    assert "video_saves" not in public_content_scoped_away_1202gv(_SPEC, _TABLES)


def test_a_table_with_no_declaration_is_never_second_guessed():
    """Absent `visibility` the materials said nothing; #1202gd's rule is to stay strict."""
    tables = {**_TABLES, "sounds": {"metadata": {"owner_scoped_reads": True}}}
    assert "sounds" not in public_content_scoped_away_1202gv(_SPEC, tables)


def test_public_and_unscoped_is_agreement_not_a_finding():
    tables = {**_TABLES, "videos": {"metadata": {"owner_scoped_reads": False}},
              "comments": {"metadata": {}}}
    assert public_content_scoped_away_1202gv(_SPEC, tables) == []


def test_auth_required_alone_is_not_the_contradiction():
    """#647 — 'every logged-in user sees every row' and 'you must log in' are compatible."""
    tables = {"videos": {"metadata": {"auth_required": True, "owner_scoped_reads": False}}}
    assert public_content_scoped_away_1202gv(_SPEC, tables) == []


def test_the_meta_row_is_not_a_table():
    """#1202gi: `_meta` rode into a required-flow list this way."""
    assert "_meta" not in public_content_scoped_away_1202gv(_SPEC, _TABLES)


def test_hostile_inputs_never_raise():
    for spec in (None, {}, {"entities": "nope"}, {"entities": [None, 3]}):
        assert public_content_scoped_away_1202gv(spec, _TABLES) == []
    for tables in (None, {}, {"videos": "nope"}):
        assert isinstance(public_content_scoped_away_1202gv(_SPEC, tables), list)


def test_the_finding_is_filed_where_the_contract_is_owned():
    """A mechanism nobody calls is this codebase's most repeated failure."""
    src = (LLM / "multi_agent" / "runtime" / "scaffolder.py").read_text(encoding="utf-8")
    assert "public_content_scoped_away_1202gv" in src, "the check has no caller"
    at = src.index("_gv = public_content_scoped_away_1202gv(")
    # #943: end on a landmark, not a byte offset.
    block = src[at:src.index("except Exception as _e1202gv:", at)]
    assert 'assignee="backend"' in block, (
        "the contract disagreement is not routed to the lane that owns the contract:\n%s"
        % block)
    # #782: assert the guard is APPLIED to this finding, not where its import is spelled.
    # `_sc1202az` is `state_changed_1202ad` under the local alias the block already uses.
    # #1202gv shipped INERT twice. The first cut sat inside `if _us1202az:` — the UNRELATED
    # underspecified-tables finding. The second sat inside `if _sc1202ad("backend_skeleton",
    # ...)`, which only fires when the SKELETON changed: the skeleton is projected before the
    # lane sets `owner_scoped_reads`, so the contradiction does not exist yet on the pass that
    # changes it, and by the time it exists the skeleton no longer changes. Both passed a test
    # that only asserted the call was PRESENT. Reachability is the property, so assert it
    # structurally: no `if` may stand between the function body and this call.
    import ast
    tree = ast.parse(src)
    line = next(n.lineno for n in ast.walk(tree)
                if isinstance(n, ast.Call)
                and getattr(n.func, "id", "") == "public_content_scoped_away_1202gv")

    def _guards(node, want, chain):
        for ch in ast.iter_child_nodes(node):
            if getattr(ch, "lineno", None) == want:
                return chain
            deeper = _guards(ch, want, chain + ([ch] if isinstance(ch, ast.If) else []))
            if deeper is not None:
                return deeper
        return None

    conds = _guards(tree, line, [])
    assert conds is not None, "could not locate the call in the AST"
    assert conds == [], (
        "the check is nested under %d condition(s), so it speaks only when they hold: %s"
        % (len(conds), [ast.unparse(c.test)[:60] for c in conds]))
    assert 'state_changed_1202ad' in src and '("task:public_content_scoped_away"' in src, (
        "#1202bn: files once per scaffold pass instead of once per changed finding — the "
        "scaffold ran 117 times in r32 and 55% of the corpus's cancelled tasks are duplicates")
