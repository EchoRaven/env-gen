import sys
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))

from utils.config import LLMConfig, LLMProvider
from utils.llm import AnthropicClient


def _client() -> AnthropicClient:
    return AnthropicClient(LLMConfig(provider=LLMProvider.ANTHROPIC,
                                     model_name="claude-haiku-4-5"))


OPENAI_TOOL = {
    "type": "function",
    "function": {
        "name": "get_current_weather",
        "description": "Get the current weather for a city.",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
}


class AnthropicToolConversionTests(unittest.TestCase):
    def test_openai_function_tool_converted(self):
        out = _client()._convert_tools_to_anthropic([OPENAI_TOOL])
        self.assertEqual(len(out), 1)
        t = out[0]
        self.assertEqual(t["name"], "get_current_weather")
        self.assertEqual(t["description"], "Get the current weather for a city.")
        self.assertEqual(t["input_schema"], OPENAI_TOOL["function"]["parameters"])
        # Must NOT carry the OpenAI-style wrapper keys.
        self.assertNotIn("type", t)
        self.assertNotIn("function", t)
        self.assertNotIn("parameters", t)

    def test_missing_description_defaults_empty(self):
        tool = {"type": "function", "function": {"name": "ping", "parameters": {"type": "object"}}}
        out = _client()._convert_tools_to_anthropic([tool])
        self.assertEqual(out[0]["description"], "")

    def test_missing_parameters_defaults_object_schema(self):
        tool = {"type": "function", "function": {"name": "noargs"}}
        out = _client()._convert_tools_to_anthropic([tool])
        self.assertEqual(out[0]["input_schema"], {"type": "object", "properties": {}})

    def test_already_anthropic_tool_passthrough(self):
        native = {"name": "x", "description": "d", "input_schema": {"type": "object"}}
        out = _client()._convert_tools_to_anthropic([native])
        self.assertEqual(out[0], native)

    def test_none_returns_none(self):
        self.assertIsNone(_client()._convert_tools_to_anthropic(None))


class _FakeStatusError(Exception):
    def __init__(self, message, status_code):
        super().__init__(message)
        self.status_code = status_code


class RateLimitClassificationTests(unittest.TestCase):
    def test_400_with_exceeded_word_is_not_rate_limit(self):
        err = _FakeStatusError("invalid_request_error: tag does not match expected", 400)
        self.assertFalse(_client()._is_rate_limit_error(err))

    def test_400_is_not_rate_limit_even_with_quota_word(self):
        err = _FakeStatusError("some quota wording", 400)
        self.assertFalse(_client()._is_rate_limit_error(err))

    def test_429_is_rate_limit(self):
        err = _FakeStatusError("Too Many Requests", 429)
        self.assertTrue(_client()._is_rate_limit_error(err))

    def test_plain_message_rate_limit_without_status(self):
        self.assertTrue(_client()._is_rate_limit_error(Exception("rate limit reached")))


if __name__ == "__main__":
    unittest.main()
