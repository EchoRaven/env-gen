import sys
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from utils.config import LLMConfig, LLMProvider
from utils.llm import AnthropicClient, Message


def _client() -> AnthropicClient:
    return AnthropicClient(LLMConfig(provider=LLMProvider.ANTHROPIC,
                                     model_name="claude-opus-4-7"))


class AnthropicMultimodalTests(unittest.TestCase):
    def test_system_message_extracted(self):
        system, chat = _client()._convert_messages_to_anthropic([
            Message.system("you are helpful"),
            Message.user("hi"),
        ])
        self.assertEqual(system, "you are helpful")
        self.assertEqual(len(chat), 1)
        self.assertEqual(chat[0]["role"], "user")

    def test_plain_text_user_message_passes_through(self):
        _system, chat = _client()._convert_messages_to_anthropic([
            Message.user("just text"),
        ])
        self.assertEqual(chat[0]["content"], "just text")

    def test_image_url_data_uri_converts_to_anthropic_image_block(self):
        # base64 for the bytes b"hello"
        b64 = "aGVsbG8="
        msg = Message.user_with_image(
            text="describe this",
            image_base64=b64,
            mime_type="image/png",
        )
        _system, chat = _client()._convert_messages_to_anthropic([msg])

        content = chat[0]["content"]
        self.assertIsInstance(content, list)

        text_blocks = [b for b in content if b.get("type") == "text"]
        image_blocks = [b for b in content if b.get("type") == "image"]

        self.assertEqual(text_blocks[0]["text"], "describe this")
        self.assertEqual(len(image_blocks), 1)
        source = image_blocks[0]["source"]
        self.assertEqual(source["type"], "base64")
        self.assertEqual(source["media_type"], "image/png")
        self.assertEqual(source["data"], b64)
        # No leftover OpenAI-style keys
        self.assertNotIn("image_url", image_blocks[0])

    def test_multimodal_two_images_preserves_order(self):
        msg = Message.user_multimodal([
            {"type": "text", "text": "reference:"},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,QQ=="}},
            {"type": "text", "text": "generated:"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,Qg=="}},
        ])
        _system, chat = _client()._convert_messages_to_anthropic([msg])
        content = chat[0]["content"]
        self.assertEqual([b["type"] for b in content],
                         ["text", "image", "text", "image"])
        self.assertEqual(content[1]["source"]["media_type"], "image/jpeg")
        self.assertEqual(content[3]["source"]["media_type"], "image/png")

    def test_http_image_url_converts_to_url_source(self):
        msg = Message.user_multimodal([
            {"type": "image_url", "image_url": {"url": "https://example.com/x.png"}},
        ])
        _system, chat = _client()._convert_messages_to_anthropic([msg])
        source = chat[0]["content"][0]["source"]
        self.assertEqual(source["type"], "url")
        self.assertEqual(source["url"], "https://example.com/x.png")


if __name__ == "__main__":
    unittest.main()
