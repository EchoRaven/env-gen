"""FIX #140 — a Gemini request with NO tools sets function_calling mode=NONE.

Log-mining runs 50-62: every run's first ~90s hit a deterministic 9-18-retry
MALFORMED_FUNCTION_CALL cluster on tools=0 requests — the -customtools variant
attempts tool-call codegen even with no declared tools, and the re-roll retries
the same doomed prompt (13/13 runs, ~18min avg direct loss per run overall).
mode=NONE disables function calling for tool-less requests at the source.

ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "utils" / "llm.py").read_text()


def test_toolless_branch_sets_mode_none():
    # the branch exists, is gated on NOT google_tools, and sets NONE
    m = re.search(r"elif \(not google_tools.*?FunctionCallingConfigMode\.NONE",
                  SRC, re.DOTALL)
    assert m, "tool-less mode=NONE branch missing"
    assert "ENVGEN_GEMINI_FC_NONE" in m.group(0)


def test_sdk_supports_none_mode():
    from google.genai import types
    assert hasattr(types.FunctionCallingConfigMode, "NONE")


def test_tooled_branches_unchanged():
    # ANY (forced) and VALIDATED branches still present for tooled requests
    assert "FunctionCallingConfigMode.ANY" in SRC
    assert "FunctionCallingConfigMode.VALIDATED" in SRC


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
