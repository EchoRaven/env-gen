r"""#729: the contract stopped describing its own endpoints, by following instructions exactly.

The largest functional defect measured this session is that half the catalogue pages render the
same thing: `/movies`, `/shows`, `/games`, `/new` and `/browse/languages` all fetch bare
`/api/titles`. Four of the five identical-content route groups have that one cause (#728 explains
the fifth).

The frontend cannot fix it alone, because it has no contract basis for passing a filter. Tracing
back:

    r146   16 GET endpoints, 3 declare query params  (/api/titles {kind,genre,language,limit,
                                                      offset}, /api/titles/trending, /api/search)
    r147   17 GET endpoints, 1
    r148   16 GET endpoints, 0

**And the decline is not a regression — it is convergence.** The backend prompt's only guidance
on endpoint schemas was `schema with response_key`. It asks for `response_key` and says nothing
about request parameters, so a lane declaring exactly that is following instructions correctly;
r146's richer declaration was the lane exceeding them. 3 -> 1 -> 0 is drift toward what was
actually asked.

That distinction matters for whether a prompt change can work here. #664 measured that repeating
an ignored instruction does nothing — 30 mentions plus 76 escalations moved no behaviour. This is
the opposite case: the instruction is not ignored, it is incomplete, and the lane already does
what it says. Completing it is not the move #664 ruled out.

The backend meanwhile IMPLEMENTS the filters — r148's `list_titles` takes kind/genre/language and
its SQL carries `WHERE kind = :kind`. The contract is the only broken link in the chain.
"""
import re
from pathlib import Path

import pytest


def _prompt() -> str:
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf
    root = Path(vf.__file__).resolve().parents[1]
    return (root / "prompts" / "v3" / "backend_agent.j2").read_text(encoding="utf-8")


# --- the instruction is completed ---------------------------------------------------------------

def test_it_asks_for_request_parameters():
    p = _prompt()
    assert "schema.request naming every QUERY PARAMETER" in p


def test_it_shows_the_shape_including_the_optional_marker():
    p = _prompt()
    assert '\\"kind\\": \\"string?\\"' in p
    assert "`?` meaning optional" in p


def test_the_original_response_key_requirement_survives():
    """Completing an instruction must not drop the part that was already working."""
    assert "schema with response_key" in _prompt()


def test_it_states_the_consequence_not_just_the_rule():
    p = _prompt()
    assert "does not exist to anyone else" in p
    assert "render IDENTICAL content" in p


def test_it_carries_the_measurement():
    p = _prompt()
    assert "3 -> 1 -> 0" in p
    assert "Four of the five identical-content route groups" in p


def test_it_names_who_depends_on_the_declaration():
    p = _prompt()
    assert "the frontend, the contract audit and the remediation hints" in p


# --- the reasoning that separates this from #664 -------------------------------------------------

def test_the_docstring_distinguishes_incomplete_from_ignored():
    d = __doc__ or ""
    assert "it is incomplete" in d
    assert "not the move #664 ruled out" in d


def test_the_convergence_reading_is_recorded():
    d = __doc__ or ""
    assert "not a regression — it is convergence" in d


# --- the evidence, re-derivable from the runs on disk ---------------------------------------------

@pytest.mark.parametrize("run,expected", [
    ("netflix-web-r146", 3), ("netflix-web-r147", 1), ("netflix-web-r148", 0)])
def test_the_declining_counts_reproduce(run, expected):
    import json
    root = Path(__file__).resolve().parents[1] / "generated" / run / "shared" / "hubs"
    if not root.is_dir():
        pytest.skip(f"{run} not on disk")
    d = json.loads((root / "registryhub_endpoints.json").read_text())
    n = sum(1 for k, v in d.items()
            if not k.startswith("_") and isinstance(v, dict)
            and str(v.get("method")).upper() == "GET"
            and ((v.get("schema") or {}).get("request")))
    assert n == expected


def test_the_backend_still_implements_what_the_contract_omits():
    """If the code stopped filtering too, this would be a different problem."""
    import subprocess
    root = Path(__file__).resolve().parents[1] / "generated" / "netflix-web-r148"
    if not root.is_dir():
        pytest.skip("r148 not on disk")
    src = subprocess.run(["git", "-C", str(root), "show",
                          "release-v1.0.0:app/backend/custom_routes.py"],
                         capture_output=True, text=True).stdout
    assert "kind: Optional[str] = Query" in src or "WHERE kind = :kind" in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
