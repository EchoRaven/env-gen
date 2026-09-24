import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))

from utils.config import LLMConfig, LLMProvider
from utils.llm import AnthropicClient


def _client(**cfg) -> AnthropicClient:
    return AnthropicClient(LLMConfig(provider=LLMProvider.ANTHROPIC,
                                     model_name="claude-opus-4-7", **cfg))


def _fake_message():
    """Mimic the anthropic SDK Message shape (same for create() and
    stream().get_final_message())."""
    text_block = SimpleNamespace(type="text", text="hello world")
    tool_block = SimpleNamespace(type="tool_use", id="tu_1",
                                 name="do_thing", input={"x": 1})
    usage = SimpleNamespace(input_tokens=12, output_tokens=34)
    return SimpleNamespace(content=[text_block, tool_block],
                           model="claude-opus-4-7",
                           stop_reason="end_turn", usage=usage)


class AnthropicStreamDecisionTests(unittest.TestCase):
    def test_small_max_tokens_does_not_stream(self):
        self.assertFalse(_client()._should_stream(8192))

    def test_large_max_tokens_streams(self):
        self.assertTrue(_client()._should_stream(128000))

    def test_threshold_is_boundary(self):
        c = _client()
        self.assertFalse(c._should_stream(c.STREAMING_MAX_TOKENS_THRESHOLD))
        self.assertTrue(c._should_stream(c.STREAMING_MAX_TOKENS_THRESHOLD + 1))


class AnthropicParseResponseTests(unittest.TestCase):
    def test_parses_text_content(self):
        resp = _client()._parse_response(_fake_message(), latency=1.5)
        self.assertEqual(resp.content, "hello world")
        self.assertEqual(resp.model, "claude-opus-4-7")
        self.assertEqual(resp.finish_reason, "end_turn")

    def test_parses_tool_use_into_tool_calls(self):
        resp = _client()._parse_response(_fake_message(), latency=0.0)
        self.assertIsNotNone(resp.tool_calls)
        self.assertEqual(len(resp.tool_calls), 1)
        tc = resp.tool_calls[0]
        self.assertEqual(tc["id"], "tu_1")
        self.assertEqual(tc["function"]["name"], "do_thing")
        # arguments serialized as JSON string
        self.assertEqual(tc["function"]["arguments"], '{"x": 1}')

    def test_usage_mapped(self):
        resp = _client()._parse_response(_fake_message(), latency=0.0)
        self.assertEqual(resp.usage["prompt_tokens"], 12)
        self.assertEqual(resp.usage["completion_tokens"], 34)
        self.assertEqual(resp.usage["total_tokens"], 46)


if __name__ == "__main__":
    unittest.main()
