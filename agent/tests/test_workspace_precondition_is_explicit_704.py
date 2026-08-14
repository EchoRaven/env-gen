r"""#704: the guard "inconsistency" is correct layering — so state the contract, don't add guards.

I reported that `verification_tools.py` both guards `self.workspace` in one place and dereferences
it unguarded elsewhere, and called the inconsistency real. It is real as a description and
misleading as a diagnosis. Mapping every method that touches `self.workspace`:

    CompareScreenshotsTool.execute            guarded      _find_image_pairs        NOT
    VerifyAPIContractTool.execute             guarded      _extract_backend_routes  NOT
    GenerateAPISpecTool.execute               guarded      _extract_frontend_calls  NOT
    WaitForAPISpecTool.execute                guarded      _extract_spec_endpoints  NOT

Every guarded method is a public `execute`; every unguarded one is a private helper called from
inside it, after the guard. The one out-of-band caller — `verification_tools.py:1149`, which
builds a `VerifyAPIContractTool` to reuse route extraction — guards at :1145 before constructing
it. **Every path in reaches a helper only after a guard, so the crash is not reachable.**

Adding redundant guards would therefore fix nothing. What the implicitness costs is a reader who
cannot tell "safe by layering" from "missed a check", so the contract is stated instead:
`_require_workspace_704` turns an AttributeError-from-nowhere into a named error saying which
method needs a workspace and who is expected to guard. No reachable behaviour changes.

I ALSO claimed it would clear the checker's ~20 `NoneType has no attribute` reports on these
methods, and measurement says it does not: identical query, before and after, 95 reports and
1,244 errors overall. A call to a raising function does not narrow a type — pyrefly needs an
inline `is None`, a `NoReturn` path, or these bodies to use the returned value instead of
`self.workspace`, which means rewriting eight dereferences in `_find_image_pairs` alone. Not done:
a real edit for a cosmetic gain. The claim is recorded as failed rather than quietly dropped.
"""
import inspect
import re

import pytest

from env_generator.llm_generator.tools import verification_tools as vt


HELPERS = ("_find_image_pairs", "_extract_backend_routes",
           "_extract_frontend_calls", "_extract_spec_endpoints")


# --- the contract holds -----------------------------------------------------------------------

class _NoWorkspace:
    workspace = None


class _WithWorkspace:
    workspace = object()


def test_it_raises_a_named_error_without_a_workspace():
    with pytest.raises(RuntimeError) as e:
        vt._require_workspace_704(_NoWorkspace(), "_find_image_pairs")
    assert "_NoWorkspace._find_image_pairs requires a workspace" in str(e.value)


def test_the_error_says_the_caller_should_guard():
    with pytest.raises(RuntimeError) as e:
        vt._require_workspace_704(_NoWorkspace(), "m")
    assert "its caller must guard" in str(e.value)


def test_it_returns_the_workspace_when_present():
    ws = _WithWorkspace()
    assert vt._require_workspace_704(ws, "m") is ws.workspace


def test_a_missing_attribute_is_treated_as_absent():
    class _Bare:
        pass
    with pytest.raises(RuntimeError):
        vt._require_workspace_704(_Bare(), "m")


# --- every helper states it --------------------------------------------------------------------

@pytest.mark.parametrize("name", HELPERS)
def test_each_helper_declares_the_precondition(name):
    src = inspect.getsource(getattr(vt.CompareScreenshotsTool, name, None)
                            or getattr(vt.VerifyAPIContractTool, name))
    assert f'_require_workspace_704(self, "{name}")' in src


@pytest.mark.parametrize("name", HELPERS)
def test_the_declaration_is_the_first_statement(name):
    fn = getattr(vt.CompareScreenshotsTool, name, None) or getattr(vt.VerifyAPIContractTool, name)
    body = [l.strip() for l in inspect.getsource(fn).split("\n")
            if l.strip() and not l.strip().startswith(("def ", "@"))]
    body = [l for l in body if not l.startswith('"""') and not l.endswith('"""')]
    assert body and body[0].startswith("_require_workspace_704"), body[:2]


# --- the real guards are untouched ----------------------------------------------------------------

@pytest.mark.parametrize("tool", ["CompareScreenshotsTool", "VerifyAPIContractTool",
                                  "GenerateAPISpecTool", "WaitForAPISpecTool"])
def test_every_public_execute_still_guards(tool):
    src = inspect.getsource(getattr(vt, tool).execute)
    assert re.search(r"if\s+not\s+self\.workspace|self\.workspace\s+is\s+None", src), tool


def test_the_out_of_band_caller_still_guards():
    """verification_tools.py:1145 guards before constructing the verifier at :1149."""
    src = inspect.getsource(vt)
    i = src.index("verifier = VerifyAPIContractTool(workspace=self.workspace)")
    before = src[max(0, src.rfind("def ", 0, i)):i]
    assert "if not self.workspace:" in before


def test_no_redundant_guard_was_added_to_the_helpers():
    """The point of the finding is that these do NOT need one."""
    for name in HELPERS:
        fn = getattr(vt.CompareScreenshotsTool, name, None) or getattr(vt.VerifyAPIContractTool, name)
        src = inspect.getsource(fn)
        assert "if not self.workspace" not in src, name


# --- provenance -------------------------------------------------------------------------------------

def test_the_layering_is_recorded_as_correct():
    d = " ".join((vt._require_workspace_704.__doc__ or "").split())
    assert "CORRECT layering rather than an oversight" in d
    assert "the crash is not reachable" in d


def test_the_out_of_band_caller_is_named_in_the_docstring():
    d = " ".join((vt._require_workspace_704.__doc__ or "").split())
    assert "1149" in d and "1145" in d


def test_the_failed_claim_is_recorded_as_failed():
    """I claimed this would clear the checker reports. Measurement says it does not."""
    d = " ".join((vt._require_workspace_704.__doc__ or "").split())
    assert "NOT what I first claimed" in d
    assert "95 of them and 1,244 errors overall" in d
    assert "a claim, not a result" in d


def test_it_says_nothing_reachable_changes():
    d = " ".join((vt._require_workspace_704.__doc__ or "").split())
    assert "without changing any reachable behaviour" in d


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
