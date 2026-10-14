r"""#614: a 405 on a DECLARED endpoint is a timing verdict, not a missing feature.

`POST /api/continue-watching -> 405 missing` is the second-largest API failure family in the
test-user reports (8 runs, incl. the recent r141/r143). A long static hunt found the endpoint
DECLARED in the contract and EMITTED in `main.py` at column 0 — an apparent impossibility.

The resolution was a timestamp, not a code path: **in every one of the 8 runs, `main.py` was
written 8 to 108 MINUTES AFTER the report**. The file inspected was never the one that served the
smoke. And in r131 / r120 / r114 / r101 the verification chains later got **201** on the very
same call.

So the verdict was correct when written and stale by the time anything read it — yet it lands in
the failure ledger as a missing feature and is never re-evaluated. That is the #597 staleness
class, one layer up.

The note says so rather than silently reclassifying: `missing` still fails the step, and a
genuinely undeclared endpoint reads exactly as it did before.

#1203kh EXTENDED IT TO 404, on #614's own standard rather than around it. #614 scoped the
note to 405 and said why: "for 404s there is no chain evidence, and the timestamp on its own
cannot carry the claim" — and its control is what kills the timestamp argument, since
`main.py` is newer than the report in 96% of runs REGARDLESS of verdict. That reasoning still
holds, so the extension does not lean on timestamps either.

The chain evidence #614 asked for now exists and is unanimous. Every `missing` entry in the
modern era's final test-user reports is a 404 on a DECLARED endpoint, and for all 7 — r187
and r184 `POST /api/videos`, r176 `PATCH` and `DELETE /api/feed/post-card/{post_id}`, r171
`PUT /api/messages/conversations/{id}`, r168 `GET /api/comments/{comment_id}`, r165 `POST
/api/live-streams` — the verification chains later got 200/201 on the very same method+path.
That is the same proof shape #614 used for its own case (r131/r120/r114/r101).

An UNDECLARED 404 still reads exactly as it did before, which is the half of #614's sentence
that does not change.
"""
import inspect
import re

import pytest

from env_generator.llm_generator.multi_agent.runtime import test_user_validation as v


@pytest.fixture(scope="module")
def src():
    return inspect.getsource(v._api_test_user)


# --- the predicate ---------------------------------------------------------------------------

def test_the_contract_check_is_param_name_agnostic(src):
    """A recorded `/api/x/{id}` must match a declared `/api/x/{item_id}` — the same
    normalisation PROPOSAL #1/#29 uses elsewhere."""
    assert 'sub(r"\\{[^}]*\\}", "{}"' in src


def test_the_method_must_match_too(src):
    i = src.index("def _declared_endpoint")
    window = src[i:i + 700]
    assert 'str(ep.get("method") or "GET").upper() != want_m' in window


def test_a_malformed_contract_entry_is_skipped(src):
    i = src.index("def _declared_endpoint")
    assert "isinstance(ep, Mapping)" in src[i:i + 700]


# --- where the note is attached -----------------------------------------------------------------

def test_only_a_404_or_405_on_a_DECLARED_endpoint_gets_the_note():
    """Asked of the AST: the literal this used to pin went stale the moment #1203kh widened
    the status set, which is #943's point about anchoring on source text."""
    import ast
    tree = ast.parse(inspect.getsource(v).lstrip())
    guards = [n for n in ast.walk(tree) if isinstance(n, ast.If)
              and "_declared_endpoint(method, path)" in ast.unparse(n.test)]
    assert len(guards) == 1, [ast.unparse(g.test) for g in guards]
    cond = ast.unparse(guards[0].test)
    assert "status in (404, 405)" in cond, cond
    assert "_declared_endpoint" in cond, (
        "the note may only attach to an endpoint the CONTRACT has — an undeclared 404 is the "
        "honest 'never built' case and keeps its old meaning")


def test_an_UNDECLARED_404_is_untouched(src):
    """#614's surviving half: the note is gated on the contract, so a 404 on an endpoint
    nobody declared reads exactly as it did before #1203kh."""
    i = src.index("_declared_endpoint(method, path):")
    block = src[i:src.index("elif check:", i)]
    assert "_declared_endpoint" in src[:i + 40]
    assert "NOTE: this endpoint IS in the contract" in block, block[:200]


def test_the_step_still_FAILS(src):
    """#614 explains the verdict; it must not soften it into a pass."""
    i = src.index("_declared_endpoint(method, path):")
    block = src[i:src.index("elif check:", i)]
    assert "ok = True" not in block and 'kind = "ok"' not in block


def test_the_kind_is_not_silently_reclassified(src):
    i = src.index("_declared_endpoint(method, path):")
    block = src[i:src.index("elif check:", i)]
    assert "kind =" not in block


def test_the_note_is_appended_not_replaced(src):
    i = src.index("_declared_endpoint(method, path):")
    assert '(note + " | ") if note else ""' in src[i:i + 400]


def test_the_note_tells_the_reader_what_to_do(src):
    flat = " ".join(src.replace('"', " ").split())
    i = flat.index("this endpoint IS in the contract")
    window = flat[i:i + 420]
    assert "projected handler had not been emitted" in window
    assert "Re-check against the CURRENT backend" in window


# --- the evidence ----------------------------------------------------------------------------------

def test_the_CHAINS_are_named_as_the_evidence_not_the_timestamps(src):
    """A later control showed `main.py` is newer than the report in 96% of runs regardless of
    verdict, so the timestamp gap proves nothing on its own — the 201s do."""
    flat = " ".join(src.replace("#", " ").split())
    assert "THE EVIDENCE IS THE CHAINS" in flat
    assert "r131/r120/r114/r101" in flat and "201" in flat
    assert "96% of runs REGARDLESS of verdict" in flat


def test_the_scope_is_405_only_and_says_why(src):
    flat = " ".join(src.replace("#", " ").split())
    assert "NOT extended to 404" in flat
    assert "no chain evidence" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
