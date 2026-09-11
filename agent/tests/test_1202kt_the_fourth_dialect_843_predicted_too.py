"""#1202kt: the fourth spec dialect — inline, mid-sentence, semicolon separated.

#843 taught three table dialects and its own note said the list would grow. #1202kb added the
square-bracket form. All three are LINE-shaped: `_DESC_TABLE_RE` requires a bullet at the start
of a line. tiktok-r115 and r116 write the data model INLINE:

    DATA MODEL:
    Full model ships in milestone 1 and remains available here: users[id, username,
    display_name, avatar_url, ...]; videos[id, author_id, video_url, ...]; comments[...]

No bullet, no line start, prose in front. The bulleted regex matched nothing, so both slices
yielded ZERO tables while plainly declaring eleven and thirteen. #843's ratchet caught it:
"2 slice(s) from the last 30 days DECLARE a data model the parser cannot read:
['tiktok-web-r115', 'tiktok-web-r116']".

WHAT IS VERIFIED: the inline form parses; the three older dialects still parse; a slice written
in both forms keeps the bulleted parse; and the plausibility filter still rejects prose.

WHAT IS NOT: that this is the last dialect. It is the fourth, found the same way as the third —
by a ratchet, on real slices. Measured after the fix: 159 of 159 marked slices in the corpus
yield tables (was 157), across 38 distinct table names with nothing implausible among them.
"""
import sys
import pathlib

_AGENT = pathlib.Path(__file__).resolve().parents[1]
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

from env_generator.llm_generator.multi_agent.runtime.kickoff.run_kickoff import (  # noqa: E402
    extract_contract_from_description as extract)


def _names(text):
    return sorted(t["name"] for t in (extract(text).get("tables") or []))


def test_r115s_inline_dialect_parses():
    """★ The case, in r115's own shape."""
    s = ("DATA MODEL:\n"
         "Full model ships in milestone 1 and remains available here: "
         "users[id, username, display_name, avatar_url]; "
         "videos[id, author_id, video_url, caption]; "
         "comments[id, video_id, user_id, text]")
    assert _names(s) == ["comments", "users", "videos"]


def test_the_bulleted_dialects_still_parse():
    """★ Non-regression on the three #843/#1202kb already taught."""
    for s in ("TABLES:\n- users: id, email, name\n- posts: id, user_id, body",
              "TABLES:\n- users (id, email, name)\n- posts (id, user_id, body)",
              "TABLES:\n- users [id, email, name]\n- posts [id, user_id, body]"):
        assert _names(s) == ["posts", "users"], s


def test_a_slice_in_BOTH_forms_keeps_the_bulleted_parse():
    """The bulleted declaration is the more explicit one; the inline pass may only ADD."""
    s = ("TABLES:\n- users: id, email, name\n"
         "Also available here: posts[id, user_id, body]")
    assert _names(s) == ["posts", "users"]


def test_prose_in_brackets_is_still_rejected():
    """★ The safety of matching anywhere: the >=2-columns-and-an-id filter is what keeps an
    English phrase from becoming a table, and it is unchanged."""
    for s in ("DATA MODEL:\nsee the notes[appendix a, appendix b] for details",
              "DATA MODEL:\nthe feed[most recent first] is the landing view",
              "DATA MODEL:\narray[0] holds the first row"):
        assert _names(s) == [], s


def test_a_single_column_bracket_is_not_a_table():
    assert _names("DATA MODEL:\nusers[id]") == []


def test_a_bracket_without_an_id_is_not_a_table():
    assert _names("DATA MODEL:\nusers[email, name, bio]") == []


def test_the_inline_pattern_runs_after_the_bulleted_one():
    """★ Order matters for de-duplication: `seen_t` keeps the FIRST parse of a name."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime.kickoff import run_kickoff as RK
    src = inspect.getsource(RK.extract_contract_from_description)
    assert src.index("_DESC_TABLE_RE.finditer") < src.index("_DESC_TABLE_INLINE_RE_1202KT")


def test_every_marked_slice_in_the_corpus_now_parses():
    """★ The corpus-wide statement, which is what #843's ratchet actually guards."""
    import json
    import re
    import pytest
    gen = _AGENT.parent / "generated"
    if not gen.is_dir():
        pytest.skip("no corpus")
    mark = re.compile(r"(?im)^\s*(TABLES?\s*:|DATA MODEL\s*:|table:\s*\w)")
    empty = []
    total = 0
    for f in sorted(gen.glob("*/shared/hubs/milestones.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows = d if isinstance(d, list) else [
            v for k, v in d.items() if k != "_meta" and isinstance(v, dict)]
        for m in rows:
            s = str(m.get("description_slice") or "")
            if not (s.strip() and mark.search(s)):
                continue
            total += 1
            if not (extract(s).get("tables") or []):
                empty.append(f.parts[-4])
    if total < 50:
        pytest.skip("corpus too small")
    assert not empty, f"{len(set(empty))} run(s) declare a data model that still will not parse: {sorted(set(empty))[:6]}"
