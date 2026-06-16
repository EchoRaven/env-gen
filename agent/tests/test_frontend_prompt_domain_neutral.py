"""frontend prompt few-shots must be DOMAIN-NEUTRAL — no instagram/social shape.

Root cause (generality sweep 2026-06-15): the kickoff worked example was a
"hello-world social feed" (login + home_feed + StoriesRow/PostCard + /api/posts)
and the authoritative FINAL PROTOCOL one-liner declared
`id='home_feed', route='/feed', components=['StoriesRow','PostCard']`. The prompt
itself states the FINAL PROTOCOL block "overrides anything above", so EVERY
frontend lane was primed toward a social shape regardless of the target app —
directly undermining the goal of generating ANY app. The few-shots were
rewritten to a neutral task-tracker shape (login + task_list + TaskCard +
/api/tasks) plus an explicit "derive from THIS app" note.

This guards against regressing to a domain-specific (social) few-shot. NOTE:
`data.posts` is intentionally STILL present in the NEGATIVE-example lessons
("NEVER read data.posts/data.games") which teach domain-agnostic envelope
reading — those are allowed and asserted preserved; the declaration-SHAPING
tokens are what must stay out.
"""

from __future__ import annotations

from pathlib import Path

PROMPT = (
    Path(__file__).resolve().parents[1]
    / "env_generator" / "llm_generator" / "multi_agent" / "prompts" / "v3"
    / "frontend_agent.j2"
)

# Tokens that PRIME a specific (social) domain in the worked examples /
# typed-declaration few-shots. A literal-minded model copies these verbatim.
_SOCIAL_DECLARATION_TOKENS = (
    "home_feed",
    "StoriesRow",
    "PostCard",
    "PostsPage",
    "social feed",
    "list of posts",
    "compose a post",
    "compose new post",
)


def _text() -> str:
    return PROMPT.read_text(encoding="utf-8")


def test_no_social_declaration_tokens_in_few_shots():
    text = _text()
    offenders = [t for t in _SOCIAL_DECLARATION_TOKENS if t in text]
    assert not offenders, (
        f"frontend prompt few-shots regressed to a social-shaped domain: {offenders}. "
        "Worked examples must stay domain-neutral (task-tracker) so the lane derives "
        "pages/components from THIS app, not a hardcoded social shape."
    )


def test_kickoff_example_is_domain_neutral_task_tracker():
    text = _text()
    # the rewritten neutral worked-example markers
    assert "task-tracker" in text or "task_list" in text
    # the explicit neutrality note added to the 1-shot label
    assert "DOMAIN-NEUTRAL" in text


def test_final_protocol_uses_placeholders_not_a_domain_shape():
    text = _text()
    i = text.rfind("FINAL PROTOCOL")
    assert i != -1, "FINAL PROTOCOL block not found"
    block = text[i:i + 1400]
    # the authoritative override example must show placeholders, never a concrete
    # social page/component pair
    assert "<page_id>" in block and "/<route>" in block, \
        "FINAL PROTOCOL ui_page example must use placeholders, not a domain page"
    assert "home_feed" not in block and "StoriesRow" not in block


def test_negative_envelope_lesson_preserved():
    # The domain-AGNOSTIC lesson (don't read a domain-named key) must remain — it
    # teaches generality and must not be collateral-damaged by the neutralization.
    low = _text().lower()
    assert "never read" in low
    assert "data.posts" in low  # kept ONLY as a "don't do this" example
