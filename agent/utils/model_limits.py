"""Per-model maximum OUTPUT token limits.

These are the synchronous-API output (completion) caps for the model families
env-gen targets, verified against provider docs (May 2026):

- Anthropic: https://platform.claude.com/docs/en/about-claude/models/overview
- OpenAI:    https://developers.openai.com/api/docs/models
- Google:    https://ai.google.dev/gemini-api/docs/models

``max_tokens`` here means *output* tokens, not the context window. Setting it
above a model's cap makes the provider reject the request, so the values are
the documented ceilings (we want "as large as possible" without erroring).

Notes / caveats baked into the chosen values:
- Anthropic Opus 4.7/4.6 cap is 128k, but the non-streaming Messages API errors
  on very large outputs ("Streaming is required..."). The AnthropicClient
  switches to streaming above a threshold so these caps are usable.
- Claude 3.7 Sonnet and Opus batch-300k need beta headers we do not send, so
  3.7 is kept at its default 8k.
- Gemini defaults maxOutputTokens to 8192; callers must pass the value
  explicitly (env-gen does) to unlock the full cap.
"""

from __future__ import annotations

# Safe value supported as output by virtually every modern model.
SAFE_DEFAULT_MAX_OUTPUT = 8192

# Ordered (prefix, max_output_tokens). First matching prefix wins, so more
# specific prefixes MUST come before more general ones.
_MAX_OUTPUT_TABLE: list[tuple[str, int]] = [
    # --- Anthropic ---
    ("claude-opus-4-8", 128000),
    ("claude-opus-4-7", 128000),
    ("claude-opus-4-6", 128000),
    ("claude-opus-4-5", 64000),
    ("claude-opus-4-1", 32000),
    ("claude-opus-4", 32000),       # opus-4-0 / opus-4-20250514
    ("claude-sonnet-4", 64000),
    ("claude-haiku-4", 64000),
    ("claude-3-7", 8192),           # 64k only with beta header (not sent)
    ("claude-3-5", 8192),
    ("claude-3", 4096),
    # --- OpenAI ---
    ("gpt-5", 128000),              # gpt-5, gpt-5-mini, gpt-5.5, ...
    ("o1", 100000),
    ("o3", 100000),
    ("o4", 100000),
    ("gpt-4.1", 32768),
    ("gpt-4o", 16384),
    ("gpt-4-turbo", 4096),
    ("gpt-4", 8192),
    # --- Google Gemini ---
    ("gemini-3", 65536),
    ("gemini-2.5", 65536),
    ("gemini-2.0", 8192),
    ("gemini-1.5", 8192),
]


def resolve_max_output_tokens(model: str,
                              default: int = SAFE_DEFAULT_MAX_OUTPUT) -> int:
    """Return the max output tokens for ``model``.

    Matching is case-insensitive and prefix-based, so dated/point-release
    snapshots (``claude-opus-4-7``, ``gpt-4o-2024-11``) inherit their family's
    cap. OpenRouter-style ``vendor/model`` ids are handled by matching on the
    portion after the last ``/`` as well. Unknown models fall back to
    ``default``.
    """
    if not model:
        return default

    name = model.strip().lower()
    candidates = [name]
    if "/" in name:
        candidates.append(name.rsplit("/", 1)[1])

    for candidate in candidates:
        for prefix, limit in _MAX_OUTPUT_TABLE:
            if candidate.startswith(prefix):
                return limit

    return default


# --- Context WINDOW (input) per model family -------------------------------
# The model's documented INPUT context window (tokens). Used to size the live
# context manager / in-context memory to the model's RECOMMENDED WORKING LENGTH
# rather than a tiny hardcoded default — an agent on a large-context model (e.g.
# Gemini's ~1M) should USE that window, not truncate its history/memory to a small
# slice. Prefix-matched like the output table.
SAFE_DEFAULT_CONTEXT_WINDOW = 128000

# Documented INPUT context windows, verified against provider docs (June 2026).
# Specific prefixes MUST precede general ones (first match wins).
_CONTEXT_WINDOW_TABLE: list[tuple[str, int]] = [
    # --- Anthropic: 1M GA for Opus/Sonnet 4.6+ (claude.com/blog/1m-context-ga,
    #     Mar 2026, no price multiplier); earlier 4.x + Claude 3 are 200k.
    ("claude-5-fable", 200_000),    # Claude 5 Fable (MetaGen Vertex) — >=200k; conservative floor
    ("claude-5", 200_000),
    ("claude-opus-4-8", 1_000_000),
    ("claude-opus-4-7", 1_000_000),
    ("claude-opus-4-6", 1_000_000),
    ("claude-sonnet-4-6", 1_000_000),
    ("claude-opus-4", 200_000),
    ("claude-sonnet-4", 200_000),
    ("claude-haiku-4", 200_000),
    ("claude-3", 200_000),
    # --- OpenAI: GPT-5.5 ~1.05M; GPT-5/5.4 standard input 272k (1M is opt-in
    #     experimental, not assumed); GPT-4.1 1M; GPT-4o/4 128k.
    ("gpt-5.5", 1_050_000),
    ("gpt-5", 272_000),
    ("gpt-4.1", 1_047_576),
    ("o1", 200_000),
    ("o3", 200_000),
    ("o4", 200_000),
    ("gpt-4o", 128_000),
    ("gpt-4", 128_000),
    # --- Google Gemini: 3.x Pro = 1,000,000-token input window (ai.google.dev /
    #     Vertex docs; 64k output); 2.5/2.0/1.5 = 1,048,576.
    ("gemini-3", 1_000_000),
    ("gemini-2.5", 1_048_576),
    ("gemini-2.0", 1_048_576),
    ("gemini-1.5", 1_048_576),
]


def resolve_context_window(model: str,
                           default: int = SAFE_DEFAULT_CONTEXT_WINDOW) -> int:
    """Return the INPUT context window (tokens) for ``model`` (prefix match)."""
    if not model:
        return default
    name = model.strip().lower()
    candidates = [name]
    if "/" in name:
        candidates.append(name.rsplit("/", 1)[1])
    for candidate in candidates:
        for prefix, win in _CONTEXT_WINDOW_TABLE:
            if candidate.startswith(prefix):
                return win
    return default


def resolve_ctx_working_chars(model: str,
                              default: int = SAFE_DEFAULT_CONTEXT_WINDOW) -> int:
    """RECOMMENDED working char budget for the live context (accumulated history +
    in-context memory), from the model's window with response headroom: ~3.5
    chars/token x 0.7 of the window. Override via ENVGEN_CTX_WORKING_CHARS. A
    Gemini-class 1M-token model yields a ~2.5M-char budget (normal runs never
    truncated); a small model stays modest."""
    import os
    env = os.environ.get("ENVGEN_CTX_WORKING_CHARS")
    if env:
        try:
            return max(2000, int(env))
        except ValueError:
            pass
    return int(resolve_context_window(model, default) * 3.5 * 0.7)


__all__ = ["resolve_max_output_tokens", "SAFE_DEFAULT_MAX_OUTPUT",
           "resolve_context_window", "resolve_ctx_working_chars",
           "SAFE_DEFAULT_CONTEXT_WINDOW"]
