"""#256 — model-family lookup must survive a gateway's reordered model id.

The Llama compat gateway names Opus 4.7 ``claude-4-7-opus-vertex-genai`` — same tokens as
the table's ``claude-opus-4-7``, different ORDER. Prefix matching missed it, so the model
fell back to SAFE_DEFAULT_CONTEXT_WINDOW (128k) when its real window is 1M: an 8x
UNDER-estimate, on the exact axis that decides how much history we keep. Consequences are
silent and all information-destroying — observation masking fires on nearly every call and
truncates real history, and the condense gate reads the model as "pressured" and summarises
history that would have fit ~8x over.

The fix keeps the existing prefix fast-path (no behaviour change for normal ids) and only
adds a token-subset fallback for ids the prefix path cannot resolve, with the MOST SPECIFIC
entry winning so ``claude-opus-4-7`` beats the shorter ``claude-opus-4``.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.model_limits import (  # noqa: E402
    SAFE_DEFAULT_CONTEXT_WINDOW,
    resolve_context_window,
    resolve_ctx_working_chars,
    resolve_max_output_tokens,
)


def test_the_r53_case_gateway_reordered_opus_id():
    """claude-4-7-opus-vertex-genai must resolve as Opus 4.7, not as the default."""
    assert resolve_context_window("claude-4-7-opus-vertex-genai") == 1_000_000
    assert resolve_context_window("claude-4-7-opus-vertex-genai") != SAFE_DEFAULT_CONTEXT_WINDOW


def test_working_chars_follow_the_real_window():
    """~2.45M chars, not the 313.6k that made a 1M model look like a 128k one."""
    assert resolve_ctx_working_chars("claude-4-7-opus-vertex-genai") > 2_000_000


def test_most_specific_entry_wins_not_the_shortest():
    """claude-opus-4 (3 tokens) must not shadow claude-opus-4-7 (4 tokens)."""
    assert resolve_context_window("claude-4-7-opus-vertex-genai") == \
        resolve_context_window("claude-opus-4-7")


def test_other_gateway_permutations_resolve_too():
    for mid in ("claude-4-8-opus-vertex-genai", "claude-4-6-opus-anthropic",
                "opus-4-7-claude-vertex"):
        assert resolve_context_window(mid) == 1_000_000, mid


def test_ordinary_ids_are_unchanged():
    """The prefix fast-path must still decide these, byte for byte."""
    for mid, want in (("claude-opus-4-7", 1_000_000),
                      ("claude-opus-4-7-20260101", 1_000_000),
                      ("claude-sonnet-4-6", 1_000_000)):
        assert resolve_context_window(mid) == want, mid


def test_unknown_models_still_fall_back():
    assert resolve_context_window("totally-unknown-model-x") == SAFE_DEFAULT_CONTEXT_WINDOW
    assert resolve_context_window("") == SAFE_DEFAULT_CONTEXT_WINDOW


def test_no_false_positive_across_families():
    """A reordered id must not match a family whose tokens it does not all contain."""
    # 'claude-3' would be a false hit if matching were 'any token in common'
    assert resolve_context_window("claude-4-7-opus-vertex-genai") != \
        resolve_context_window("claude-3-5-sonnet")


def test_output_token_table_gets_the_same_treatment():
    """max_output must not silently fall back either — Vertex REQUIRES max_tokens."""
    assert resolve_max_output_tokens("claude-4-7-opus-vertex-genai") == \
        resolve_max_output_tokens("claude-opus-4-7")


def test_openrouter_vendor_prefix_still_works():
    assert resolve_context_window("anthropic/claude-opus-4-7") == 1_000_000
