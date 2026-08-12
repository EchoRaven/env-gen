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

def test_only_a_405_on_a_DECLARED_endpoint_gets_the_note(src):
    assert "if status == 405 and _declared_endpoint(method, path):" in src


def test_a_404_is_untouched(src):
    """404 is the honest 'never declared / never built' case and keeps its old meaning."""
    i = src.index("if status == 405 and _declared_endpoint")
    assert "404" not in src[i:src.index("elif check:", i)]


def test_the_step_still_FAILS(src):
    """#614 explains the verdict; it must not soften it into a pass."""
    i = src.index("if status == 405 and _declared_endpoint")
    block = src[i:src.index("elif check:", i)]
    assert "ok = True" not in block and 'kind = "ok"' not in block


def test_the_kind_is_not_silently_reclassified(src):
    i = src.index("if status == 405 and _declared_endpoint")
    block = src[i:src.index("elif check:", i)]
    assert "kind =" not in block


def test_the_note_is_appended_not_replaced(src):
    i = src.index("if status == 405 and _declared_endpoint")
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
