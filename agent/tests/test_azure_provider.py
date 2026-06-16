import os
import sys
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))

from utils.config import LLMConfig, LLMProvider
from utils.llm import OpenAIClient


def _azure_cfg(**kw):
    base = dict(provider=LLMProvider.AZURE, model_name="my-gpt4o-deployment",
                api_key="k", api_base="https://res.openai.azure.com")
    base.update(kw)
    return LLMConfig(**base)


class AzureProviderTests(unittest.TestCase):
    def setUp(self):
        for var in ("AZURE_OPENAI_API_VERSION",):
            os.environ.pop(var, None)

    def tearDown(self):
        os.environ.pop("AZURE_OPENAI_API_VERSION", None)

    def test_is_azure_true_only_for_azure(self):
        self.assertTrue(OpenAIClient(_azure_cfg())._is_azure())
        self.assertFalse(OpenAIClient(
            LLMConfig(provider=LLMProvider.OPENAI, model_name="gpt-4o"))._is_azure())

    def test_api_version_default(self):
        client = OpenAIClient(_azure_cfg())
        self.assertEqual(client._resolve_api_version(),
                         OpenAIClient.AZURE_DEFAULT_API_VERSION)

    def test_api_version_from_extra_params(self):
        client = OpenAIClient(_azure_cfg(extra_params={"api_version": "2025-01-01"}))
        self.assertEqual(client._resolve_api_version(), "2025-01-01")

    def test_api_version_from_env(self):
        os.environ["AZURE_OPENAI_API_VERSION"] = "2024-12-01"
        client = OpenAIClient(_azure_cfg())
        self.assertEqual(client._resolve_api_version(), "2024-12-01")

    def test_get_client_builds_azure_client(self):
        from openai import AsyncAzureOpenAI
        client = OpenAIClient(_azure_cfg())._get_client()
        self.assertIsInstance(client, AsyncAzureOpenAI)

    def test_get_client_builds_plain_openai_for_non_azure(self):
        from openai import AsyncOpenAI, AsyncAzureOpenAI
        client = OpenAIClient(
            LLMConfig(provider=LLMProvider.OPENAI, model_name="gpt-4o",
                      api_key="k"))._get_client()
        self.assertIsInstance(client, AsyncOpenAI)
        self.assertNotIsInstance(client, AsyncAzureOpenAI)


if __name__ == "__main__":
    unittest.main()
