import sys
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))

from utils.model_limits import resolve_max_output_tokens


class ModelLimitsTests(unittest.TestCase):
    def test_opus_4_7_gets_128k(self):
        self.assertEqual(resolve_max_output_tokens("claude-opus-4-7"), 128000)

    def test_opus_4_6_gets_128k(self):
        self.assertEqual(resolve_max_output_tokens("claude-opus-4-6"), 128000)

    def test_opus_4_1_gets_32k(self):
        self.assertEqual(resolve_max_output_tokens("claude-opus-4-1-20250805"), 32000)

    def test_sonnet_4_gets_64k(self):
        self.assertEqual(resolve_max_output_tokens("claude-sonnet-4-6"), 64000)
        self.assertEqual(resolve_max_output_tokens("claude-sonnet-4-20250514"), 64000)

    def test_haiku_4_5_gets_64k(self):
        self.assertEqual(resolve_max_output_tokens("claude-haiku-4-5"), 64000)

    def test_claude_3_7_safe_8k(self):
        self.assertEqual(resolve_max_output_tokens("claude-3-7-sonnet-20250219"), 8192)

    def test_claude_3_5_gets_8k(self):
        self.assertEqual(resolve_max_output_tokens("claude-3-5-sonnet-20241022"), 8192)

    def test_claude_3_gets_4k(self):
        self.assertEqual(resolve_max_output_tokens("claude-3-opus-20240229"), 4096)

    def test_gpt5_family_gets_128k(self):
        self.assertEqual(resolve_max_output_tokens("gpt-5"), 128000)
        self.assertEqual(resolve_max_output_tokens("gpt-5-mini"), 128000)
        self.assertEqual(resolve_max_output_tokens("gpt-5.5"), 128000)

    def test_o_series_gets_100k(self):
        self.assertEqual(resolve_max_output_tokens("o1"), 100000)
        self.assertEqual(resolve_max_output_tokens("o3"), 100000)
        self.assertEqual(resolve_max_output_tokens("o4-mini"), 100000)

    def test_gpt_4_1_gets_32768(self):
        self.assertEqual(resolve_max_output_tokens("gpt-4.1"), 32768)
        self.assertEqual(resolve_max_output_tokens("gpt-4.1-mini"), 32768)

    def test_gpt_4o_gets_16384(self):
        self.assertEqual(resolve_max_output_tokens("gpt-4o"), 16384)
        self.assertEqual(resolve_max_output_tokens("gpt-4o-mini"), 16384)

    def test_gpt_4_turbo_and_gpt_4(self):
        self.assertEqual(resolve_max_output_tokens("gpt-4-turbo"), 4096)
        self.assertEqual(resolve_max_output_tokens("gpt-4"), 8192)

    def test_gemini_3_and_2_5_get_65536(self):
        self.assertEqual(resolve_max_output_tokens("gemini-3-pro-preview"), 65536)
        self.assertEqual(resolve_max_output_tokens("gemini-2.5-pro"), 65536)
        self.assertEqual(resolve_max_output_tokens("gemini-2.5-flash"), 65536)

    def test_gemini_2_0_and_1_5_get_8192(self):
        self.assertEqual(resolve_max_output_tokens("gemini-2.0-flash"), 8192)
        self.assertEqual(resolve_max_output_tokens("gemini-1.5-pro"), 8192)

    def test_unknown_model_uses_safe_fallback(self):
        self.assertEqual(resolve_max_output_tokens("some-future-model"), 8192)

    def test_custom_default_honored(self):
        self.assertEqual(resolve_max_output_tokens("mystery", default=4096), 4096)

    def test_openrouter_vendor_prefixed_names_resolve(self):
        # OpenRouter ids look like "vendor/model"
        self.assertEqual(resolve_max_output_tokens("anthropic/claude-opus-4-7"), 128000)
        self.assertEqual(resolve_max_output_tokens("openai/gpt-5"), 128000)
        self.assertEqual(resolve_max_output_tokens("google/gemini-2.5-pro"), 65536)

    def test_case_insensitive(self):
        self.assertEqual(resolve_max_output_tokens("GPT-4o"), 16384)


if __name__ == "__main__":
    unittest.main()
