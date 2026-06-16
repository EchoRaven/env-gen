"""TOKEN_PRICING must include current model families (Cutover 18)."""

import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from tools.system_tools import TOKEN_PRICING  # noqa: E402


REQUIRED_MODELS = (
    "claude-opus-4-7",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
    "gpt-5",
)


class TokenPricingTests(unittest.TestCase):
    def test_modern_models_present(self) -> None:
        for model in REQUIRED_MODELS:
            # Allow substring match — handles "claude-opus-4-7" vs "claude-opus-4-7-20260513"
            self.assertTrue(any(model in k.lower() for k in TOKEN_PRICING),
                              f"TOKEN_PRICING missing entry for {model!r}; "
                              f"keys: {sorted(TOKEN_PRICING)}")

    def test_each_entry_has_input_and_output_price(self) -> None:
        for model, prices in TOKEN_PRICING.items():
            if model == "default":
                continue
            self.assertIn("input", prices,
                            f"{model} missing 'input' price")
            self.assertIn("output", prices,
                            f"{model} missing 'output' price")
            self.assertGreater(prices["input"], 0.0)
            self.assertGreater(prices["output"], 0.0)


if __name__ == "__main__":
    unittest.main()
