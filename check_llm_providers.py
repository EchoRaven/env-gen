#!/usr/bin/env python3
"""
Smoke-test the env-gen LLM clients against real provider APIs.

Exercises the code paths changed recently:
  - multimodal image conversion (OpenAI image_url -> per-provider format)
  - OpenRouter routing + base_url
  - Anthropic streaming-accumulate path for large max_tokens
  - per-model max-output-token resolution

Run it in an environment where your API keys are exported. Providers whose
key is not set are skipped. Azure is included but skipped unless you set
AZURE_OPENAI_API_KEY + AZURE_OPENAI_ENDPOINT (+ optionally AZURE_OPENAI_API_VERSION).

    python check_llm_providers.py

Requires the SDKs the clients use: openai, anthropic, google-genai.
Override the model per provider with env vars (see DEFAULT_MODELS below), e.g.
    TEST_ANTHROPIC_MODEL=claude-sonnet-4-6 python check_llm_providers.py
"""
import asyncio
import os
import struct
import sys
import zlib
from pathlib import Path

# --- make env-gen's utils importable -----------------------------------------
ROOT = Path(__file__).resolve().parent
AGENT = ROOT / "agent"
for p in (AGENT, AGENT / "env_generator" / "llm_generator"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from utils.config import LLMConfig, LLMProvider          # noqa: E402
from utils.llm import create_llm_client, Message          # noqa: E402
from utils.model_limits import resolve_max_output_tokens  # noqa: E402


# --- a dependency-free solid-color PNG (so the image test needs no files) -----
def make_solid_png(w: int, h: int, rgb=(220, 20, 20)) -> bytes:
    def chunk(typ: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + typ + data +
                struct.pack(">I", zlib.crc32(typ + data) & 0xffffffff))

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)   # 8-bit RGB
    row = b"\x00" + bytes(rgb) * w                        # filter byte + pixels
    idat = zlib.compress(row * h, 9)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


import base64  # noqa: E402

RED_PNG_B64 = base64.b64encode(make_solid_png(64, 64, (220, 20, 20))).decode()

WEATHER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_current_weather",
        "description": "Get the current weather for a given city.",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string", "description": "City name"}},
            "required": ["city"],
        },
    },
}

DEFAULT_MODELS = {
    LLMProvider.OPENAI:     ("TEST_OPENAI_MODEL",     "gpt-4o"),
    LLMProvider.OPENROUTER: ("TEST_OPENROUTER_MODEL", "openai/gpt-4o-mini"),
    LLMProvider.ANTHROPIC:  ("TEST_ANTHROPIC_MODEL",  "claude-haiku-4-5"),
    LLMProvider.GOOGLE:     ("TEST_GOOGLE_MODEL",     "gemini-2.5-flash"),
    LLMProvider.AZURE:      ("TEST_AZURE_DEPLOYMENT", "gpt-4o"),  # deployment name
}

PROVIDERS = [
    ("OpenAI",     LLMProvider.OPENAI,     ["OPENAI_API_KEY"]),
    ("OpenRouter", LLMProvider.OPENROUTER, ["OPENROUTER_API_KEY"]),
    ("Anthropic",  LLMProvider.ANTHROPIC,  ["ANTHROPIC_API_KEY"]),
    ("Google",     LLMProvider.GOOGLE,     ["GOOGLE_API_KEY", "GEMINI_API_KEY"]),
    ("Azure",      LLMProvider.AZURE,      ["AZURE_OPENAI_API_KEY"]),
]

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


def make_config(provider: LLMProvider, max_tokens: int) -> LLMConfig:
    env_name, default = DEFAULT_MODELS[provider]
    model = os.getenv(env_name, default)
    extra = {}
    if provider == LLMProvider.AZURE:
        if os.getenv("AZURE_OPENAI_API_VERSION"):
            extra["api_version"] = os.getenv("AZURE_OPENAI_API_VERSION")
    return LLMConfig(
        provider=provider,
        model_name=model,
        api_base=os.getenv("AZURE_OPENAI_ENDPOINT") if provider == LLMProvider.AZURE else None,
        temperature=0.0,
        max_tokens=max_tokens,
        timeout=120,
        extra_params=extra,
    )


async def _check(label, coro):
    try:
        ok, detail = await coro
        mark = f"{GREEN}PASS{RESET}" if ok else f"{RED}FAIL{RESET}"
        print(f"    [{mark}] {label} {DIM}{detail}{RESET}")
        return ok
    except Exception as e:
        print(f"    [{RED}ERR {RESET}] {label} {RED}{type(e).__name__}: {e}{RESET}")
        return False


async def test_text(provider):
    client = create_llm_client(make_config(provider, 256))
    resp = await client.chat(
        messages=[Message.user("Reply with exactly this word: PONG")],
        temperature=0.0, max_tokens=256)
    txt = (resp.content or "").strip()
    return ("pong" in txt.lower()), f"-> {txt[:40]!r}"


async def test_multimodal(provider):
    client = create_llm_client(make_config(provider, 256))
    msg = Message.user_with_image(
        text="What is the dominant color of this image? Answer with one word only.",
        image_base64=RED_PNG_B64, mime_type="image/png")
    resp = await client.chat(messages=[msg], temperature=0.0, max_tokens=256)
    txt = (resp.content or "").strip()
    return ("red" in txt.lower()), f"-> {txt[:40]!r}"


async def test_tool_call(provider):
    client = create_llm_client(make_config(provider, 256))
    resp = await client.chat(
        messages=[Message.user("What's the weather in Paris? Call the tool.")],
        temperature=0.0, max_tokens=256, tools=[WEATHER_TOOL])
    calls = resp.tool_calls or []
    names = [c.get("function", {}).get("name") for c in calls] if calls else []
    return (bool(calls)), f"-> tool_calls={names}"


async def test_anthropic_streaming(provider):
    # max_tokens > 8192 forces the streaming-accumulate path in AnthropicClient.
    client = create_llm_client(make_config(provider, 16000))
    streams = getattr(client, "_should_stream", lambda *_: None)(16000)
    resp = await client.chat(
        messages=[Message.user("Reply with exactly this word: STREAMED")],
        temperature=0.0, max_tokens=16000)
    txt = (resp.content or "").strip()
    return ("streamed" in txt.lower()), f"(should_stream={streams}) -> {txt[:40]!r}"


async def main():
    print(f"{DIM}python: {sys.executable}{RESET}\n")
    results = {}
    for name, provider, key_envs in PROVIDERS:
        key_present = any(os.getenv(k) for k in key_envs)
        if provider == LLMProvider.AZURE:
            key_present = key_present and bool(os.getenv("AZURE_OPENAI_ENDPOINT"))
        if not key_present:
            print(f"{YELLOW}● {name}{RESET} {DIM}skipped (set {' or '.join(key_envs)}"
                  f"{' + AZURE_OPENAI_ENDPOINT' if provider == LLMProvider.AZURE else ''}){RESET}")
            results[name] = None
            continue

        env_name, default = DEFAULT_MODELS[provider]
        model = os.getenv(env_name, default)
        cap = resolve_max_output_tokens(model)
        print(f"● {name} {DIM}(model={model}, resolved max_output={cap}){RESET}")

        oks = []
        oks.append(await _check("text     ", test_text(provider)))
        oks.append(await _check("multimodal", test_multimodal(provider)))
        oks.append(await _check("tool_call ", test_tool_call(provider)))
        if provider == LLMProvider.ANTHROPIC:
            oks.append(await _check("streaming ", test_anthropic_streaming(provider)))
        results[name] = all(oks)
        print()

    print("=" * 48)
    print("Summary:")
    for name, _, _ in PROVIDERS:
        r = results.get(name)
        tag = (f"{GREEN}ALL PASS{RESET}" if r is True
               else f"{RED}HAS FAILURES{RESET}" if r is False
               else f"{YELLOW}skipped{RESET}")
        print(f"  {name:12} {tag}")

    any_fail = any(r is False for r in results.values())
    sys.exit(1 if any_fail else 0)


if __name__ == "__main__":
    asyncio.run(main())
