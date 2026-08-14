r"""#682: a 404 said "title not found" and never said WHAT was not found.

From the first live run after this session's fixes. r145 aborted after 75 minutes with
`business_chain_failing`, and the reason was three chains stuck red — two of them posting
`title_id: 'movie-1003596'` and getting `404 {"detail":"title not found"}`.

That id is real. It is an ASSET id from design_system.json. Three id vocabularies were in play:

    design/dataset/titles.json   integers      [1, 2, 3]
    app/backend/seed_data.json   strings       ['tv-stranger-signals', ...]   <- what is seeded
    design_system.json assets    'movie-1003596'                              <- what was sent

and the registered contract could not have disambiguated it: the schema says `title_id: 'str'`.
The step's own request body held the answer, and the broken line never quoted it.

In the corpus the same shape is POST /api/my-list -> "referenced resource not found" x26, the
largest single broken-assertion class after the denial probes.

NOT a registration-time rule. I measured hardcoded `*_id` literals across the 3492 stored chains
before writing anything:

    chains WITH a hardcoded FK literal     5% failing   (392 of them PASS)
    chains WITHOUT one                     5% failing

Identical. Rejecting them at registration would have cost real work and caught nothing — the
value only becomes wrong once the server says so, which is exactly where this hint lives.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.chain_executor import (
    _unknown_id_hint_682 as hint,
)


# --- it fires where it should -----------------------------------------------------------------

def test_it_names_the_field_and_the_value():
    out = hint(404, {"title_id": "movie-1003596"}, "title not found")
    assert "title_id='movie-1003596'" in out


def test_it_says_no_such_row_exists():
    assert "no such row exists" in hint(404, {"title_id": "x"}, "title not found")


def test_it_explains_why_a_literal_is_a_guess():
    """The actual r145 cause: dataset, seed and asset names disagree."""
    out = hint(404, {"title_id": "x"}, "title not found")
    assert "dataset, the seed and the staged ASSET names" in out


def test_it_gives_the_remedy():
    out = hint(404, {"title_id": "x"}, "title not found")
    assert "`save` an id from the response" in out


def test_it_also_fires_on_the_corpus_wording():
    """POST /api/my-list -> 'referenced resource not found', x26 in the corpus."""
    assert hint(404, {"title_id": "x"}, "referenced resource not found")


def test_several_ids_are_all_named():
    out = hint(404, {"title_id": "a", "profile_id": "b"}, "not found")
    assert "title_id='a'" in out and "profile_id='b'" in out


# --- it stays quiet everywhere else -------------------------------------------------------------

@pytest.mark.parametrize("status", [200, 201, 401, 409, 500, None])
def test_only_400_403_and_404_qualify(status):
    assert hint(status, {"title_id": "x"}, "title not found") == ""


# --- #682c: a 400 that spells out the accepted values (r145's third stuck chain) ------------------

def test_an_enum_400_quotes_the_allowed_set():
    out = hint(400, {"value": "like"}, "value must be up|down|love")
    assert "[up|down|love]" in out


def test_the_enum_400_names_what_was_sent():
    assert "you sent 'like'" in hint(400, {"value": "like"}, "value must be up|down|love")


def test_it_says_the_enum_is_missing_from_the_contract():
    """The whole reason the author could not have known: 1 of 4013 schemas declares one."""
    out = hint(400, {"value": "like"}, "value must be up|down|love")
    assert "NOT in the registered schema" in out


def test_it_says_a_same_name_re_registration_replaces_a_failing_chain():
    """Nothing had ever told the verifier this, and the chain sat red for 75 minutes."""
    out = hint(400, {"value": "like"}, "value must be up|down|love")
    assert "SAME name replaces it while it is failing" in out


def test_a_400_without_an_allowed_set_stays_quiet():
    assert hint(400, {"value": "like"}, "bad request") == ""


def test_a_two_value_enum_is_recognised():
    assert "[up|down]" in hint(400, {"value": "x"}, "value must be up|down")


def test_a_prose_400_mentioning_must_be_but_no_set_is_ignored():
    assert hint(400, {"value": "x"}, "value must be a string") == ""


# --- #682b: the ownership 403, r145's most frequent business_chain failure (15 of them) -----------

def test_an_ownership_403_names_the_id():
    out = hint(403, {"profile_id": 7}, "profile_id does not belong to the caller")
    assert "profile_id=7" in out


def test_the_403_says_the_refusal_is_correct():
    """An ownership denial is right; implying the server is wrong would send the lane astray."""
    out = hint(403, {"profile_id": 7}, "does not belong to the caller")
    assert "The refusal is CORRECT" in out
    assert "the step is what is wrong" in out


def test_the_403_offers_both_legitimate_repairs():
    out = hint(403, {"profile_id": 7}, "not owned")
    assert "Create the resource as THIS actor" in out
    assert "expects 403 alone" in out


def test_the_403_does_not_reuse_the_missing_row_wording():
    out = hint(403, {"profile_id": 7}, "does not belong to the caller")
    assert "no such row exists" not in out


def test_a_403_that_is_not_about_ownership_stays_quiet():
    assert hint(403, {"profile_id": 7}, "forbidden") == ""


def test_a_404_that_is_not_about_a_missing_row_is_ignored():
    """A routing 404 is a different defect and must not get id advice."""
    assert hint(404, {"title_id": "x"}, "Not Found: no route for POST /api/nope") != ""  # 'not found'
    assert hint(404, {"title_id": "x"}, "gateway timeout") == ""


def test_a_body_with_no_id_field_adds_nothing():
    assert hint(404, {"value": "up", "name": "x"}, "title not found") == ""


def test_an_unresolved_variable_is_not_reported_as_a_literal():
    """`${tid}` failing is #188's unresolved-variable case, which already has its own line."""
    assert hint(404, {"title_id": "${tid}"}, "title not found") == ""


def test_an_empty_value_is_skipped():
    assert hint(404, {"title_id": "   "}, "title not found") == ""


def test_nested_values_are_skipped():
    assert hint(404, {"title_id": {"a": 1}}, "title not found") == ""


# --- it must never break the report -----------------------------------------------------------

@pytest.mark.parametrize("body", [None, "x", 42, [], ("a",)])
def test_a_non_mapping_body_is_safe(body):
    assert hint(404, body, "title not found") == ""


def test_a_missing_note_is_safe():
    assert hint(404, {"title_id": "x"}, None) == ""


def test_it_is_deterministic():
    b = {"title_id": "x"}
    assert hint(404, b, "not found") == hint(404, b, "not found")


# --- wiring + provenance ------------------------------------------------------------------------

def test_the_executor_appends_it_to_the_note():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import chain_executor as ce
    src = inspect.getsource(ce)
    assert "note = note + _unknown_id_hint_682(status, body, note)" in src


def test_it_runs_before_the_entry_is_built():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import chain_executor as ce
    src = inspect.getsource(ce)
    i = src.index("_unknown_id_hint_682(status, body, note)")
    assert src.index('entry = {"action"', i) > i


def test_the_live_run_evidence_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import chain_executor as ce
    flat = " ".join(inspect.getsource(ce).replace("#", " ").split())
    assert "r145 died on exactly this" in flat
    assert "movie-1003596" in flat


def test_the_rejected_registration_rule_is_recorded():
    """A future reader will propose rejecting hardcoded ids; the measurement must be there."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import chain_executor as ce
    flat = " ".join(inspect.getsource(ce).replace("#", " ").split())
    assert "they fail at 5%" in flat
    assert "392 PASSING chains" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
