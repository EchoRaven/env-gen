r"""#1203iw: the note named a mechanism that is absent in 71 of the 73 cases it described.

Both probes answered "no /auth request was seen" with:

    submit sent NO /auth request — the form is not wired to the API
    (button has no handler / submit does nothing)

#612 wrote the rule that breaks, in this same file: "REPORT THE OBSERVATION, NOT A GUESS AT
ITS CAUSE … the causal clause was an inference the harness had no basis for, and it is
load-bearing: it lands in the failure ledger and sends the frontend lane to re-wire a form
that is already wired." It removed the claim from the other branches after checking the
SERVER side — `POST /auth/login` answered 200 in all 12 runs it had — and kept it in this
branch, because "no request was seen" looked like evidence for it.

The PAGE side disagrees. Counting every run that emitted this note against its own frontend
source:

    73 runs emitted it; 71 have BOTH a submit handler and an auth call in a file whose
      name is auth-like  (loose predicate — any auth-ish file with a handler — 73 of 73)
    172 of the corpus's 173 runs have a submit handler on an auth page at all, and the
      single run that has none never emitted this note

Two reasons "no request seen" happens with the form wired landed the same day: #1203it (the
listeners watched `/auth/` while instagram-core-r176 logged in through `/oauth/authorize`)
and #1203iu (nothing listened for the page throwing).

DEMOTED, NOT DELETED. "the form is not wired to the API" stays, as the last of three numbered
checks: #612, #1203a6, #1203b6 and #1203g1 all LOCATE this branch by that phrase, and a form
that really has no handler still reads correctly at (3). What goes is the parenthetical that
asserted a mechanism.
"""
import ast
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import test_user_runner as tur
from env_generator.llm_generator.multi_agent.runtime import test_user_validation as tuv

VSRC = inspect.getsource(tuv)
USRC = inspect.getsource(tur)

CHECKS = ("was the submit disabled",
          "does the handler reach its api call",
          "whether the form is not wired to the API at all")


def _runner_note():
    """The ladder's own output for the no-request case — a pure function (#1203g1)."""
    return tur.auth_note_1203g1(ok_auth=False, token=None, navigated=False, landed=False,
                                path="/login", url="http://localhost:8000/login",
                                auth_status=[])


def _validation_note():
    """The sibling's branch text, read off the chain it is assigned in."""
    for node in ast.walk(ast.parse(VSRC)):
        if not isinstance(node, ast.If):
            continue
        for stmt in node.body:
            if (isinstance(stmt, ast.Assign)
                    and getattr(stmt.targets[0], "id", "") == "_note"
                    and "not wired to the API" in ast.unparse(stmt.value)):
                return ast.unparse(stmt.value)
    raise AssertionError("the unwired branch is gone from test_user_validation")


# --- the mechanism claim is gone, from both -----------------------------------------------------

# Parametrised by NAME, not by source: passing the module text makes pytest put a slab of it
# into the test id, and a failure then reads as a random line of `test_user_runner`.
@pytest.mark.parametrize("name", ["test_user_validation", "test_user_runner"])
def test_neither_module_asserts_the_mechanism(name):
    """Not even in a comment: a stale comment quoting it let one of #1203iu's assertions pass
    on its author's prose rather than on the code."""
    src = VSRC if name == "test_user_validation" else USRC
    assert "button has no handler" not in src, name
    assert "submit does nothing" not in src, name


def test_the_runners_note_no_longer_asserts_a_cause():
    note = _runner_note()
    assert "button has no handler" not in note, note
    assert "submit sent NO /auth request" in note, note


# --- what it says instead -----------------------------------------------------------------------

@pytest.mark.parametrize("check", CHECKS)
def test_the_runners_note_carries_every_check(check):
    assert check in _runner_note(), check


@pytest.mark.parametrize("check", CHECKS)
def test_the_validation_note_carries_every_check(check):
    assert check in _validation_note(), check


def test_the_two_readings_agree_check_by_check():
    """One rule, two emitters, and #1203g1 forbids sharing the string (every ladder phrase
    must be BUILT INSIDE `auth_note_1203g1`). A test is the drift guard instead (#1032)."""
    runner, validation = _runner_note(), _validation_note()
    for check in CHECKS:
        assert check in runner and check in validation, check
    assert runner.index(CHECKS[0]) < runner.index(CHECKS[1]) < runner.index(CHECKS[2])
    assert (validation.index(CHECKS[0]) < validation.index(CHECKS[1])
            < validation.index(CHECKS[2]))


def test_the_unwired_claim_is_the_last_check_not_the_headline():
    """A reader acts on the first thing a note says."""
    for note in (_runner_note(), _validation_note()):
        assert note.index("no call to the auth surface") < note.index("not wired to the API")


def test_the_observation_still_leads():
    for note in (_runner_note(), _validation_note()):
        assert note.lstrip().lower().startswith(("submit sent no /auth request",
                                                 '"submit sent no /auth request',
                                                 "'submit sent no /auth request",
                                                 "f'submit sent no /auth request"))


# --- what four other tickets depend on ----------------------------------------------------------

def test_the_phrase_those_tickets_locate_the_branch_by_survives():
    """#612 counts it (exactly one ladder note), #1203a6 asserts non-vacuity, #1203b6 finds
    the branch by it, #1203g1 requires it to live inside the ladder function. Deleting it
    would have been a fix that broke four tickets' tests to remove one clause."""
    assert "not wired to the API" in _runner_note()
    assert "not wired to the API" in _validation_note()


def test_it_is_still_exactly_one_ladder_note_that_says_it():
    """#612's invariant, re-asserted here so this ticket cannot be the one that breaks it."""
    tree = ast.parse(USRC)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "auth_note_1203g1")
    notes = [ast.unparse(n.value) for n in ast.walk(fn)
             if isinstance(n, ast.Return) and n.value is not None]
    assert sum("not wired to the API" in n for n in notes) == 1, notes


# --- provenance ---------------------------------------------------------------------------------

def test_the_page_side_census_is_recorded():
    flat = " ".join(VSRC.replace("#", " ").split())
    assert "71 of 73" in flat
    assert "172" in flat and "173" in flat


def test_612s_rule_is_named_where_it_is_applied():
    flat = " ".join(VSRC.replace("#", " ").split())
    assert "REPORT THE OBSERVATION, NOT A GUESS AT ITS CAUSE" in flat


def test_why_it_was_demoted_rather_than_deleted_is_recorded():
    flat = " ".join(VSRC.replace("#", " ").split())
    assert "DEMOTED, NOT DELETED" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
