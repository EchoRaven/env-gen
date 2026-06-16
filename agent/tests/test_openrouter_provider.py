import sys
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from utils.config import LLMConfig, LLMProvider
from utils.llm import OpenAIClient, create_llm_client


class OpenRouterProviderTests(unittest.TestCase):
    def test_provider_enum_has_openrouter(self):
        self.assertEqual(LLMProvider.OPENROUTER.value, "openrouter")

    def test_factory_routes_openrouter_to_openai_client(self):
        client = create_llm_client(
            LLMConfig(provider=LLMProvider.OPENROUTER, model_name="x"))
        self.assertIsInstance(client, OpenAIClient)

    def test_openrouter_defaults_base_url(self):
        client = OpenAIClient(
            LLMConfig(provider=LLMProvider.OPENROUTER, model_name="x"))
        self.assertEqual(client._resolve_base_url(),
                         "https://openrouter.ai/api/v1")

    def test_explicit_api_base_overrides_openrouter_default(self):
        client = OpenAIClient(LLMConfig(
            provider=LLMProvider.OPENROUTER, model_name="x",
            api_base="https://gateway.internal/v1"))
        self.assertEqual(client._resolve_base_url(),
                         "https://gateway.internal/v1")

    def test_plain_openai_has_no_default_base_url(self):
        client = OpenAIClient(
            LLMConfig(provider=LLMProvider.OPENAI, model_name="gpt-4o"))
        self.assertIsNone(client._resolve_base_url())

    def test_explicit_api_base_used_for_plain_openai(self):
        client = OpenAIClient(LLMConfig(
            provider=LLMProvider.OPENAI, model_name="gpt-4o",
            api_base="https://my-proxy/v1"))
        self.assertEqual(client._resolve_base_url(), "https://my-proxy/v1")


if __name__ == "__main__":
    unittest.main()
