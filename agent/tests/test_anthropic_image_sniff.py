"""Anthropic image media-type is sniffed from bytes, not the (often-lying) data-URI header."""
import base64
from utils.llm import AnthropicClient

def _durl(header_mime, raw): return f"data:{header_mime};base64," + base64.b64encode(raw).decode()

def _mt(header_mime, raw):
    blocks = AnthropicClient._convert_content_to_anthropic(
        [{"type": "image_url", "image_url": {"url": _durl(header_mime, raw)}}])
    return blocks[0]["source"]["media_type"]

def test_jpeg_mislabeled_png_is_corrected():
    assert _mt("image/png", b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00"*20) == "image/jpeg"

def test_png_stays_png():
    assert _mt("image/png", b"\x89PNG\r\n\x1a\n" + b"\x00"*20) == "image/png"

def test_gif_detected():
    assert _mt("image/png", b"GIF89a" + b"\x00"*20) == "image/gif"

def test_webp_detected():
    assert _mt("image/png", b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00"*8) == "image/webp"
