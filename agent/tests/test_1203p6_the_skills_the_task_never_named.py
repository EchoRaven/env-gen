r"""#1203p6: the frontend lane's visual-remediation task never named the two skills about it.

The framework ships 12 bundled skills with every run and allowlists three for the frontend
lane (`agents_config.yaml`: ui-ux-review, ui-bootstrap, frontend-design). MEASURED over the
corpus: `skill_consulted` fires 23,617 times and those three are consulted **4 times each
across 104 runs**, while `verification-before-completion` is consulted 9,725 times and
`release-readiness` 9,064.

Two explanations were checked and both are wrong. It is not reachability -- all three are in
the lane's allowlist. It is not gating -- `_require_skill_consulted` guards only
release-readiness and api-contract-guard, and the most-consulted skill of all is guarded by
neither. What is left: nothing steers the choice, and **the three UI skills are named in 0 of
25,903 corpus task bodies**.

This body is the one place where that is clearly wrong: it is the frontend lane's instruction
after the VISUAL gate failed, and `frontend-design` opens with "env-gen FIRST: reference
fidelity outranks distinctiveness" while `ui-ux-review` says "a flow that renders but has no
empty/error state passes the smoke check yet is still a UX defect" -- #1203ny's finding in the
skill's own words. Iconography is meanwhile the weakest of the judge's seven dimensions
(mean 0.577; 67 of 251 PASSING screens below 0.50).

A POINTER, NOT A GATE: `preconditions.py` records what the wall costs ("release-readiness gate
blocked deliver_project forever") and #1202w6 wants a live run before a new one. A sentence
blocks nothing and is measurable -- if `skill_consulted` for these three does not move after
the next run, the pointer was not the lever.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf

_RESULTS = [
    {"name": "login", "route": "/login", "similarity": 0.50, "dimensions": {}},
    {"name": "feed", "route": "/feed", "similarity": 0.31, "dimensions": {}},
]


@pytest.fixture()
def body():
    return vf.remediation_text(
        {"min_similarity": 0.65, "summary": "s", "screens": _RESULTS}, None, set())


def test_it_names_the_two_skills_that_are_about_this_job(body):
    assert "frontend-design" in body, body[-400:]
    assert "ui-ux-review" in body, body[-400:]


def test_it_names_them_as_a_callable_tool_not_as_prose(body):
    """A skill the lane cannot see how to open is not a pointer. `get_skill` is the tool."""
    assert 'get_skill("frontend-design")' in body
    assert 'get_skill("ui-ux-review")' in body


def test_each_pointer_says_what_that_skill_is_for(body):
    """Two skills with no distinction is a coin flip, not guidance: one is about fidelity to
    the reference (what this gate scores) and the other about the states a screen can pass a
    smoke check without having.

    Asserted INSIDE the pointer's own segment. The first draft said `"fidelity" in body` and
    a mutation that removed the word from this sentence still passed -- the surrounding
    remediation body says "fidelity" elsewhere, so the assertion was being fed by its
    neighbours. Same trap as #1203p3's first criterion (it matched six warnings) and the
    comment-quoting one recorded three times over.
    """
    seg = body.split("Two skills are about this exact job", 1)[1]
    fd = seg.split("ui-ux-review", 1)[0]
    assert "fidelity" in fd, fd
    assert "empty" in seg and "error" in seg, seg


def test_it_says_nothing_else_will_point_there(body):
    """The measured fact is the reason this sentence exists: 0 of 25,903 task bodies name
    them. If that stops being true the sentence can go -- but it must say WHY it is here."""
    assert "nothing else in this task" in body


def test_the_pointer_comes_BEFORE_the_per_screen_notes(body):
    """The criterion this test started with was the opposite one, and it was wrong.

    It said the screens must come first (citing #680's ordering). Then the body was measured:
    over the corpus's 399 visual-gate remediation tasks the description is a MEDIAN 48,322
    characters (p90 60,527, max 70,225; 95% over 10k), and #605's comment names this very
    function as why task descriptions total 17 MB. A sentence meant to be READ cannot sit
    after 48k characters of per-screen notes.

    #1203jhb made the same call for the same reason, in its own words: "SHORT, AND BEFORE THE
    BITS, BECAUSE THE FIELD IS CAPPED." #680's concern was a long DEFERRAL LIST displacing the
    fix list, which is a different thing from two lines at the top.
    """
    assert body.index("Two skills are about this exact job") < body.index("## login")


def test_it_is_not_a_gate(body):
    """The body must not claim the lane is blocked on consulting them -- #1202w6 wants a live
    run before a wall, and `preconditions.py` records that a skill gate wedged delivery."""
    low = body.lower()
    for phrase in ("you must", "required before", "blocked until", "cannot finish"):
        assert phrase not in low.split("two skills are about this exact job")[-1], phrase


def test_a_clean_result_still_gets_the_pointer():
    """The visual gate only produces this body when something is below the bar, so there is no
    'clean' case to exclude -- but an empty screen list must not crash it."""
    out = vf.remediation_text({"min_similarity": 0.65, "summary": "s", "screens": []}, None, set())
    assert isinstance(out, str)
