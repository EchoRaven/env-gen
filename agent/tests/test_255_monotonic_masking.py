"""#255 — observation masking must be PREFIX-STABLE, or it destroys the prompt cache.

Measured on r51 (Gemini, 164 min): 5739 LLM calls, 456.7M prompt tokens vs 0.9M
completion — the run's entire cost is prompt, and only 59.9% of it was cache-served.

``_mask_old_observations`` masks everything before ``cutoff = n - keep_recent``. That
cutoff advances on EVERY step, so on every step the messages that just crossed it flip
from full text to truncated text. A prompt cache is keyed on the longest common PREFIX,
so a byte that changes at position ``cutoff`` invalidates the cache from there on —
every step, forever. Quantising the cutoff down to a block boundary makes the masked set
byte-identical for BLOCK consecutive steps, so the prefix survives.

This was latent on Gemini (working window 2.45M chars, so masking never fired at all)
and becomes constant on Claude/opus-4.7 (313.6k chars — r51's mean prompt was ~318k
chars, i.e. over the line on essentially every call). It is also strictly information-
PRESERVING: a quantised cutoff is <= the exact one, so fewer messages get truncated.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.llm import Message, _mask_old_observations  # noqa: E402

BIG = "x" * 40_000          # far over max_old (6000) so it is a masking candidate
# Quantisation and the budget floor are SEPARATE properties, so they are probed
# separately: model=None exercises pure prefix-stability (no budget escalation),
# and the floor test below uses a real small-window model.
MODEL = "claude-4-7-opus-vertex-genai"   # working window 313.6k chars -> masking fires


def _history(n):
    msgs = [Message(role="system", content="SYS")]
    msgs.append(Message(role="user", content="TASK"))
    for i in range(n):
        msgs.append(Message(role="assistant", content=f"step{i} " + BIG))
    return msgs


def _texts(msgs):
    return [getattr(m, "content", "") for m in msgs]


def _common_prefix_len(a, b):
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def test_masking_actually_fires_for_a_small_window_model():
    """Guard the premise: if this stops firing the rest of the file proves nothing."""
    out = _mask_old_observations(_history(40), model=None)
    assert any("older output truncated" in t for t in _texts(out))


def test_prefix_is_stable_across_consecutive_steps():
    """The regression: one appended message must not rewrite older ones."""
    unstable = 0
    for n in range(40, 60):
        a = _texts(_mask_old_observations(_history(n), model=None))
        b = _texts(_mask_old_observations(_history(n + 1), model=None))
        # every message that exists in both must be identical up to the shared length
        if _common_prefix_len(a, b) < len(a) - 2:
            unstable += 1
    assert unstable <= 4, (
        f"{unstable}/20 consecutive steps rewrote the shared prefix — with a block of "
        "16 at most 20/16 ≈ 2 boundary crossings may do so")


def test_quantised_cutoff_never_masks_more_than_the_exact_one():
    """Information-preserving: masking a SUPERSET would be a regression."""
    for n in (40, 47, 63, 100):
        out = _texts(_mask_old_observations(_history(n), model=None))
        masked = sum(1 for t in out if "older output truncated" in t)
        assert masked <= max(0, (n + 2) - 8), (n, masked)


def test_recent_messages_are_never_masked():
    out = _texts(_mask_old_observations(_history(50), model=None))
    for t in out[-8:]:
        assert "older output truncated" not in t


def test_system_and_first_task_survive_intact():
    out = _texts(_mask_old_observations(_history(60), model=None))
    assert out[0] == "SYS" and out[1] == "TASK"


def test_large_window_model_still_keeps_everything():
    """Gemini's 2.45M window must stay untouched — no new truncation."""
    out = _texts(_mask_old_observations(_history(30),
                                        model="gemini-3.1-pro-preview-customtools"))
    assert not any("older output truncated" in t for t in out)


def test_still_gets_under_budget_when_quantising_is_not_enough():
    """Safety floor: prefix stability must never let the prompt overflow. With a very
    long history the exact cutoff has to win."""
    from utils.model_limits import resolve_ctx_working_chars
    budget = resolve_ctx_working_chars(MODEL)
    out = _mask_old_observations(_history(400), model=MODEL)
    total = sum(len(getattr(m, "content", "")) for m in out
                if isinstance(getattr(m, "content", None), str))
    assert total <= budget, f"{total} > {budget}: masking failed to bound the prompt"


def test_non_string_content_is_left_alone():
    msgs = [Message(role="system", content="SYS"), Message(role="user", content="TASK")]
    msgs += [Message(role="user", content=[{"type": "text", "text": "img"}])
             for _ in range(40)]
    out = _mask_old_observations(msgs, model=None)
    assert all(isinstance(getattr(m, "content", None), (str, list)) for m in out)
