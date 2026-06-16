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


__all__ = ["resolve_max_output_tokens", "SAFE_DEFAULT_MAX_OUTPUT"]
