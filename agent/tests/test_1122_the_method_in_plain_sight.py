"""#1122: the method was in the step, and the guard refused to look at it.

`normalize_steps` split `endpoint: "POST /x"` into method+path — but only when the step
supplied no `path` of its own. A step that gave BOTH was rejected for "lacks
method+path" with the method sitting in plain sight:

    {"endpoint": "POST /api/users/{}/follow",
     "path": "/api/users/${user_b_id}/follow", "auth": "token_a"}

That is the MORE precise authoring, not a mistake: `endpoint` names the contract entry
as RegistryHub holds it — and as #742 requires elsewhere, '<METHOD> <path>' — while
`path` is the concrete URL carrying its ${var} substitutions. The framework punished
the agent for using its own canonical format.

Replaying the 94 rejected chain registrations in the corpus through this function: 284
steps are genuinely rejected, and 272 of them — 96%, across 26 runs — are this and
nothing else. After the fix the same 94 registrations reject 12, all of which supply
neither endpoint nor path.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.chain_executor import normalize_steps


def _one(step):
    """normalize_steps PREPENDS a platform auth step (see its docstring), so the step
    under test is the last one, never norm[0]."""
    norm, errs = normalize_steps([step])
    return (norm[-1] if norm else None), errs


def test_the_corpus_shape_is_accepted():
    got, errs = _one({
        "endpoint": "POST /api/users/{}/follow",
        "path": "/api/users/${user_b_id}/follow",
        "expect": [200, 201],
        "auth": "token_a",
    })
    assert not errs, "the dominant corpus shape is still rejected: %r" % errs
    assert got["method"] == "POST", "the method was not taken from the endpoint"


def test_the_concrete_path_wins_over_the_contract_placeholder():
    """`{}` is the registered entry; `${user_b_id}` is the URL to actually hit."""
    got, errs = _one({
        "endpoint": "POST /api/users/{}/follow",
        "path": "/api/users/${user_b_id}/follow",
    })
    assert not errs
    assert got["path"] == "/api/users/${user_b_id}/follow", (
        "the endpoint's placeholder path overwrote the concrete one: %r" % got["path"]
    )


def test_a_step_without_a_path_still_takes_both_from_the_endpoint():
    """The pre-#1122 behaviour, unchanged."""
    got, errs = _one({"endpoint": "POST /auth/register", "expect": [200, 201]})
    assert not errs
    assert got["method"] == "POST" and got["path"] == "/auth/register"


def test_an_explicit_method_is_never_overridden():
    """setdefault, not assignment — the step's own method is authoritative."""
    got, errs = _one({"method": "PUT", "endpoint": "POST /x", "path": "/y"})
    assert not errs
    assert got["method"] == "PUT" and got["path"] == "/y"


def test_an_endpoint_that_is_only_a_path_still_needs_a_method():
    _got, errs = _one({"endpoint": "/api/notes"})
    assert errs, "a step with no method anywhere must still be refused"
    assert "lacks method+path" in errs[0]


def test_a_step_with_neither_is_still_refused():
    """The 12 the corpus still rejects after the fix."""
    _got, errs = _one({"expect": [200]})
    assert errs and "lacks method+path" in errs[0]


def test_an_endpoint_only_path_is_not_mistaken_for_a_method():
    """'/api/notes' must never become method='/api/notes'."""
    got, errs = _one({"endpoint": "/api/notes", "method": "GET"})
    assert not errs
    assert got["method"] == "GET" and got["path"] == "/api/notes"


@pytest.mark.parametrize("verb", ["GET", "POST", "PUT", "PATCH", "DELETE"])
def test_every_verb_is_derived(verb):
    got, errs = _one({"endpoint": "%s /api/notes/{}" % verb, "path": "/api/notes/${id}"})
    assert not errs
    assert got["method"] == verb
