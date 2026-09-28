"""Model token pricing.

This module held `SystemMetrics` until #1202wm removed it; what remains is the pricing
table and the note below explaining why.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Pricing table
# ---------------------------------------------------------------------------
# Prices are USD per 1K tokens (cost calc divides token count by 1000).
TOKEN_PRICING: dict = {
    "gpt-4o": {"input": 0.0025, "output": 0.01},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "claude-3-opus": {"input": 0.015, "output": 0.075},
    "claude-3-sonnet": {"input": 0.003, "output": 0.015},
    "claude-3.5-sonnet": {"input": 0.003, "output": 0.015},
    # Claude 4.x family (2026 list prices: $15/$75, $3/$15, $1/$5 per 1M tokens)
    "claude-opus-4-7":     {"input": 0.015,  "output": 0.075},
    "claude-opus-4-6":     {"input": 0.015,  "output": 0.075},
    "claude-sonnet-4-6":   {"input": 0.003,  "output": 0.015},
    "claude-haiku-4-5":    {"input": 0.001,  "output": 0.005},
    # GPT-5 family (2026 list prices: $5/$20, $1/$4 per 1M tokens)
    "gpt-5":               {"input": 0.005,  "output": 0.020},
    "gpt-5-mini":          {"input": 0.001,  "output": 0.004},
    "default": {"input": 0.005, "output": 0.015},
}

# #1202wm: `SystemMetrics` lived here and was removed -- the orchestrator constructed it on
# every run and never called it, all six of its methods had zero production references, and
# its three stores appear in 0 of the corpus's 176 run directories. Per-tool wall clock is
# now recorded by #1202wl; USD spend has always been run_budget's (it carries
# `usd_before_this_run` across resumes, which SystemMetrics never did).
#
# TOKEN_PRICING stays. Its only production reader WAS that class, so nothing consumes it
# today -- the live cost path takes USD from the LLM layer, not from a table here. It is
# kept rather than deleted with the class because test_token_pricing.py exists to keep this
# table current (Cutover 18), and removing someone's deliberately-maintained pricing data on
# the strength of "nothing imports it this week" is a judgement about intent I should not
# make silently. Flagged here instead: if this is still unread, delete it on purpose.
