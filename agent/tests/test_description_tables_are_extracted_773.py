r"""#773: the description's table lines were never extracted — `tables` was always empty.

`extract_contract_from_description` returns `{endpoints, tables}`. The endpoints regex works; the
table regex expected `- NAME: cols` while every description writes `- table: NAME: cols`. With no
optional prefix, group(1) captured the literal word "table", group(2) became
`users: id, email, ...`, its first column parsed as `users:` — not an identifier — and the whole
extraction yielded ZERO tables.

r150's own milestone slice, before the fix:

    - table: my_list: id, profile_id, title_id
    - table: ratings: id, profile_id, title_id, value
    - table: continue_watching: id, profile_id, title_id, progress_seconds

    extract_contract_from_description(slice)  ->  endpoints: 17,  tables: 0

The consumer is `_derive_missing_essential_sections`, which salvages a stalled BACKEND lane and
whose docstring says *"the milestone slice already LISTS the endpoints/tables ... so extract
them"*. It could never have salvaged a schema — only endpoints — and nothing said so, because
`tables: []` is indistinguishable from "the spec declared no tables".

**Why it matters beyond the salvage path.** r150 shipped `my_list`, `ratings` and
`continue_watching` all keyed on **`user_id`**, while its spec says `profile_id` and states the
one privacy requirement in the whole task: *"Each profile sees only its own My List, ratings and
Continue Watching."* DDL, RegistryHub contract and handlers all agree with each other and all
disagree with the spec, so every consistency check passes. Comparing the two is a separate step —
this fix is its prerequisite, and on its own it catches nothing.
"""
import json
import pathlib

import pytest

from env_generator.llm_generator.multi_agent.runtime.kickoff.run_kickoff import (
    extract_contract_from_description as extract)


# --- both forms ------------------------------------------------------------------------------

def test_the_form_every_description_actually_writes():
    r = extract("- table: users: id, email, name\n- table: ratings: id, profile_id, value")
    assert [t["name"] for t in r["tables"]] == ["users", "ratings"]


def test_the_form_it_already_accepted_still_works():
    """The old shape must not regress — the prefix is optional, not required."""
    r = extract("- users: id, email\n- ratings: id, value")
    assert [t["name"] for t in r["tables"]] == ["users", "ratings"]


def test_the_columns_survive():
    r = extract("- table: continue_watching: id, profile_id, title_id, progress_seconds")
    assert [c["name"] for c in r["tables"][0]["columns"]] == [
        "id", "profile_id", "title_id", "progress_seconds"]


def test_a_starred_bullet_works_too():
    assert extract("* table: genres: id, name")["tables"][0]["name"] == "genres"


@pytest.mark.parametrize("line", [
    "- table: users(id, email)",          # parenthesised, the third shape in the wild
    "- Endpoints: POST /auth/login",      # a prose heading, not a table
])
def test_it_does_not_invent_tables_from_prose(line):
    names = [t["name"] for t in extract(line)["tables"]]
    assert "table" not in names, "the literal word `table` must never become a table name"


def test_endpoints_are_untouched():
    r = extract("- POST /auth/login\n- table: users: id, email")
    assert len(r["endpoints"]) == 1 and len(r["tables"]) == 1


# --- against the real artifact ------------------------------------------------------------------

def _r150_slice():
    p = (pathlib.Path(__file__).resolve().parents[1] / "generated" / "netflix-web-r150"
         / "shared" / "hubs" / "milestones.json")
    if not p.exists():
        pytest.skip("r150 artifacts not present")
    rows = [x for x in json.loads(p.read_text()).values() if isinstance(x, dict)]
    for r in rows:
        if "continue_watching" in str(r.get("description_slice", "")):
            return r["description_slice"]
    pytest.skip("no slice with the table declarations")


def test_r150s_real_slice_now_yields_its_tables():
    r = extract(_r150_slice())
    by = {t["name"]: [c["name"] for c in t["columns"]] for t in r["tables"]}
    assert len(r["tables"]) >= 9, by
    assert "profile_id" in by["continue_watching"]
    assert "profile_id" in by["ratings"]
    assert "profile_id" in by["my_list"]


def test_the_endpoint_count_is_unchanged_on_the_real_slice():
    """Non-vacuity for the regression risk: endpoints were already working, 17 of them."""
    assert len(extract(_r150_slice())["endpoints"]) == 17


# --- provenance -----------------------------------------------------------------------------------

def test_the_diagnosis_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime.kickoff import run_kickoff
    src = inspect.getsource(run_kickoff)
    i = src.index("#773:")
    blk = " ".join(l.strip().lstrip("#").strip() for l in src[i:src.index("_DESC_TABLE_RE = re.compile", i)].split("\n"))
    assert "group(1) captured the literal word" in blk
    assert "endpoints: 17, tables: 0" in blk


def test_it_records_that_the_fix_alone_catches_nothing():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime.kickoff import run_kickoff
    src = inspect.getsource(run_kickoff)
    i = src.index("#773:")
    blk = " ".join(l.strip().lstrip("#").strip() for l in src[i:src.index("_DESC_TABLE_RE = re.compile", i)].split("\n"))
    assert "could never have salvaged a schema" in blk


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
