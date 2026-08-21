"""
LLM Client Module - Provides unified interface for LLM calls

Supports:
- OpenAI (GPT-4, GPT-3.5)
- Anthropic (Claude)
- Azure OpenAI
- Local models (Ollama, vLLM)
- Custom endpoints
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, AsyncIterator, Optional, Union, Tuple, Set
import asyncio
import base64
import json
import logging
import os
import re

from .config import LLMConfig, LLMProvider


def _redact_secrets(text: str) -> str:
    """
    Best-effort redaction of secrets and very large inline blobs.

    Purpose:
    - Avoid sending accidental credentials/tokens to LLM providers
    - Reduce chance of OpenAI 'invalid_prompt' due to policy triggers on sensitive content
    """
    if not text:
        return text

    # Common API keys / tokens
    patterns = [
        # OpenAI-style
        (r"\bsk-[A-Za-z0-9_-]{20,}\b", "[REDACTED_OPENAI_KEY]"),
        # Google API key
        (r"\bAIza[0-9A-Za-z\-_]{30,}\b", "[REDACTED_GOOGLE_KEY]"),
        # JWT tokens
        (r"\beyJ[A-Za-z0-9_\-]+=*\.[A-Za-z0-9_\-]+=*\.[A-Za-z0-9_\-]+=*\b", "[REDACTED_JWT]"),
        # data:image base64 blobs (very large)
        (r"data:image\/[^;]+;base64,[A-Za-z0-9+/=]{200,}", "data:image/...;base64,[TRUNCATED]"),
    ]
    redacted = text
    for pat, repl in patterns:
        redacted = re.sub(pat, repl, redacted)

    # Redact obvious password assignments in text
    redacted = re.sub(r"(?im)^(.*\bpassword\b\s*[:=]\s*)(.+)$", r"\1[REDACTED]", redacted)
    redacted = re.sub(r"(?im)^(.*\bpasswd\b\s*[:=]\s*)(.+)$", r"\1[REDACTED]", redacted)

    return redacted


def _sanitize_message_content(content: Optional[Union[str, list]]) -> Optional[Union[str, list]]:
    if content is None:
        return None
    if isinstance(content, str):
        return _redact_secrets(content)
    if isinstance(content, list):
        # Check if this is valid multimodal content (each item should have 'type')
        all_valid_multimodal = all(
            isinstance(part, dict) and 'type' in part 
            for part in content
        )
        
        if all_valid_multimodal:
            # Valid multimodal - sanitize and keep as list
            sanitized_parts = []
            for part in content:
                if part.get("type") == "text" and isinstance(part.get("text"), str):
                    new_part = dict(part)
                    new_part["text"] = _redact_secrets(new_part["text"])
                    sanitized_parts.append(new_part)
                else:
                    sanitized_parts.append(part)
            return sanitized_parts
        else:
            # Invalid multimodal format - convert to string
            # This handles cases where content accidentally became a list
            text_parts = []
            for part in content:
                if isinstance(part, str):
                    text_parts.append(part)
                elif isinstance(part, dict):
                    if 'text' in part:
                        text_parts.append(str(part['text']))
                    elif 'content' in part:
                        text_parts.append(str(part['content']))
                    else:
                        text_parts.append(str(part))
                else:
                    text_parts.append(str(part))
            return _redact_secrets(" ".join(text_parts))
    
    # Non-string, non-list content - convert to string
    return _redact_secrets(str(content))


# #248: per-image size ceiling. Claude on GCP Vertex rejects anything over 5 MB
# ("image exceeds 5 MB maximum: 7876848 b") — the design-prep phase sends full-size
# reference screenshots, so EVERY vision call failed on that provider while Gemini had
# accepted the same bytes. Downscale/re-encode until it fits; never raise.
_IMG_BYTE_LIMIT = int(os.environ.get("ENVGEN_IMAGE_BYTE_LIMIT", "4500000"))



def _sniff_image_mime(raw: bytes):
    """#248e — true image type from magic bytes. Claude accepts only jpeg/png/gif/webp and
    rejects a payload whose declared media type disagrees with its bytes."""
    if raw[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return None


def _fit_image_b64(image_base64: str, mime_type: str = "image/png"):
    """Return (base64, mime) shrunk to fit ``_IMG_BYTE_LIMIT``. No-op when it already
    fits or when Pillow is unavailable — a provider with no limit is unaffected."""
    # #248e: trust the BYTES over the declared media type — the engine sometimes labels a
    # JPEG as image/png and Claude rejects the mismatch (found by the sidecar work).
    # NOTE: providers measure the BASE64 STRING, not the decoded bytes — Vertex reported
    # "exceeds 5 MB maximum: 5763156 b" for an image whose decoded size was only ~4.3 MB,
    # so a decoded-size test skipped exactly the images that get rejected. Gate on len(b64).
    try:
        raw = base64.b64decode(image_base64)
    except Exception:
        return image_base64, mime_type
    sniffed = _sniff_image_mime(raw)
    if sniffed and sniffed != mime_type:
        mime_type = sniffed
    if len(image_base64) <= _IMG_BYTE_LIMIT:
        return image_base64, mime_type
    try:
        import io
        from PIL import Image
        im = Image.open(io.BytesIO(raw))
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        data = None
        for scale, quality in ((1.0, 82), (0.75, 80), (0.6, 75), (0.45, 70), (0.33, 65), (0.25, 60)):
            buf = io.BytesIO()
            if scale == 1.0:
                shrunk = im
            else:
                w, h = im.size
                shrunk = im.resize((max(1, int(w * scale)), max(1, int(h * scale))))
            shrunk.save(buf, format="JPEG", quality=quality, optimize=True)
            data = buf.getvalue()
            enc = base64.b64encode(data).decode("ascii")
            if len(enc) <= _IMG_BYTE_LIMIT:
                return enc, "image/jpeg"
        if data:
            return base64.b64encode(data).decode("ascii"), "image/jpeg"
    except Exception:
        pass
    return image_base64, mime_type



def _fit_message_images(msg: dict) -> dict:
    """#248 (universal): shrink every ``image_url`` data-URI in a serialized message so it
    fits the provider's per-image cap. ``user_with_image`` is only ONE of the paths that
    build vision content — design_prep builds ``image_url`` parts directly and hands them
    to ``user_multimodal``, so the fit must live where EVERY message is serialized for the
    request. Pure/best-effort: a message with no images is returned unchanged."""
    try:
        content = msg.get("content")
        if not isinstance(content, list):
            return msg
        changed = False
        parts = []
        for part in content:
            if (isinstance(part, dict) and part.get("type") == "image_url"
                    and isinstance(part.get("image_url"), dict)):
                url = str(part["image_url"].get("url") or "")
                if url.startswith("data:") and ";base64," in url:
                    head, b64 = url.split(";base64,", 1)
                    mime = head[len("data:"):] or "image/png"
                    nb64, nmime = _fit_image_b64(b64, mime)
                    if nb64 is not b64:
                        part = {**part, "image_url": {**part["image_url"],
                                                      "url": f"data:{nmime};base64,{nb64}"}}
                        changed = True
            parts.append(part)
        return {**msg, "content": parts} if changed else msg
    except Exception:
        return msg



def _drop_orphan_tool_results(messages):
    """#249 — keep a ``role=tool`` message only when the tool_call it answers was announced
    by the MOST RECENT assistant turn.

    Anthropic-backed providers reject the whole request with "unexpected `tool_use_id`
    found in `tool_result` blocks … must have a corresponding `tool_use` block in the
    PREVIOUS message". Adjacency matters, not mere presence somewhere earlier, and the
    orphans are produced by observation masking/truncation — so this runs AFTER masking.
    Handles BOTH Message objects and already-serialized dicts: some call sites pass dicts,
    and an attribute-only implementation silently passed those straight through (#249c
    shipped with that hole). OpenAI tolerates orphans; Anthropic does not. Pure."""
    def _get(m, key):
        if isinstance(m, dict):
            return m.get(key)
        return getattr(m, key, None)

    try:
        pending = set()          # ids announced by the most recent assistant turn
        keep, dropped = [], 0
        for m in messages:
            role = _get(m, "role")
            if role == "assistant":
                pending = set()
                for tc in (_get(m, "tool_calls") or []):
                    tid = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                    if tid:
                        pending.add(str(tid))
            elif role == "tool":
                tid = _get(m, "tool_call_id")
                if not tid or str(tid) not in pending:
                    dropped += 1
                    continue
            else:
                pending = set()  # any other turn closes the tool_result window
            keep.append(m)
        return keep if dropped else messages
    except Exception:
        return messages



_ANTHROPIC_FAMILIES = ("claude", "vertex", "anthropic", "fable", "opus", "sonnet", "haiku")


def _needs_anthropic_shape(model: str) -> bool:
    m = (model or "").lower()
    return any(k in m for k in _ANTHROPIC_FAMILIES)


def _normalize_for_anthropic(msgs: list) -> list:
    """#250 — reshape an OpenAI-style message list into what Anthropic actually accepts.

    Evidence (r46/r48 WIRE-SHAPE dumps): the assistant→tool pairing was ALREADY adjacent and
    correct, yet the gateway still answered 'unexpected tool_use_id'. What the dumps show is
    a shape Anthropic does not allow: system messages in the MIDDLE of the conversation
    (indices 2 and 7) and runs of consecutive user turns (3,4,5 / 12,13 / 15,16,17). The
    gateway must fold those into Anthropic's one-top-level-system + strictly alternating
    user/assistant form, and its folding shifts the tool_result away from its tool_use.

    So do the folding ourselves, deterministically:
      * hoist every system message into ONE leading system message,
      * merge consecutive same-role turns (text joined) — but NEVER merge across a
        tool boundary, so an assistant's tool_calls stay immediately followed by results,
      * leave role=tool messages alone (the gateway maps them to tool_result blocks).
    Pure; only applied for Anthropic-backed models."""
    if not msgs:
        return msgs
    sys_parts, rest = [], []
    for m in msgs:
        role = m.get("role")
        if role == "system":
            c = m.get("content")
            if isinstance(c, str) and c.strip():
                sys_parts.append(c)
            continue
        rest.append(m)

    out = []
    for m in rest:
        role = m.get("role")
        prev = out[-1] if out else None
        mergeable = (
            prev is not None
            and prev.get("role") == role
            and role in ("user", "assistant")
            and not prev.get("tool_calls") and not m.get("tool_calls")
            and isinstance(prev.get("content"), str) and isinstance(m.get("content"), str)
        )
        if mergeable:
            prev["content"] = (prev["content"] or "") + "\n\n" + (m.get("content") or "")
            continue
        out.append(dict(m))

    # #265b: Claude rejects a conversation that ends on an assistant turn ("does not
    # support assistant message prefill"). Normally the framework's prompt IS the last
    # user turn, but after #265 flattens an unanswered trailing tool call the assistant
    # becomes last — trading one 400 for another. Close the turn explicitly.
    if out and out[-1].get("role") == "assistant":
        out.append({"role": "user", "content": "Continue."})
    if sys_parts:
        out.insert(0, {"role": "system", "content": "\n\n".join(sys_parts)})
    return out


def _flatten_tool_protocol(msgs: list) -> list:
    """#259 — render a tool exchange as TEXT for a request that declares no tools.

    Bisected live against the gateway: the SAME 8-message list returns 200 with a ``tools``
    key and 400 ``unexpected tool_use_id ... must have a corresponding tool_use block in
    the previous message`` without one. With no tool declarations there is nothing for the
    assistant's ``tool_use`` block to refer to, so it is dropped in translation and the
    following ``tool_result`` is orphaned. Every WIRE-SHAPE dump that made this look like a
    pairing bug (r46/r48/r53) showed the pairing adjacent and correct — the payload was
    simply unrepresentable, and the framework issues plenty of tool-less calls (planning,
    summarisation, condensation) over histories that contain tool exchanges.

    Information-preserving on purpose: the call and its result stay visible as text, so a
    planning/summarising turn still knows what was invoked and what came back.
    """
    out = []
    for m in msgs:
        role = m.get("role")
        if role == "tool" or m.get("tool_call_id"):
            body = m.get("content")
            out.append({"role": "user",
                        "content": f"[tool result] {body if isinstance(body, str) else body}"})
            continue
        calls = m.get("tool_calls")
        if calls:
            lines = []
            for c in calls:
                fn = (c or {}).get("function") or {}
                lines.append(f"[tool call] {fn.get('name')}({fn.get('arguments')})")
            base = m.get("content")
            base = base if isinstance(base, str) and base.strip() else ""
            merged = (base + ("\n" if base else "") + "\n".join(lines)) or "[tool call]"
            trimmed = {k: v for k, v in m.items() if k not in ("tool_calls", "function_call")}
            trimmed["content"] = merged
            out.append(trimmed)
            continue
        out.append(m)
    return out


_LEGAL_TOOL_ID_RE = re.compile(r"[^a-zA-Z0-9_-]")


def _sanitize_tool_ids(msgs: list) -> list:
    """#261 — tool ids must match ``^[a-zA-Z0-9_-]+$``.

    r54 logged 220 x ``messages.N.content.0.tool_use.id: String should match
    '^[a-zA-Z0-9_-]+$'``. Probed live: "", "a.b", "a:b", "a b" are all rejected; "call_1"
    and a plain uuid pass. The rewrite is applied through ONE shared map so an assistant's
    tool_calls and the matching tool message keep the same id — diverge and #249 sees an
    orphan and silently drops the result.
    """
    mapping: dict = {}

    def _fix(raw, i):
        key = raw if isinstance(raw, str) else ""
        if key in mapping:
            return mapping[key]
        clean = _LEGAL_TOOL_ID_RE.sub("_", key)
        if not clean:
            clean = f"call_{i}"
        while clean in mapping.values() and mapping.get(key) != clean:
            clean = f"{clean}_{i}"
        mapping[key] = clean
        return clean

    out = []
    for i, m in enumerate(msgs):
        calls = m.get("tool_calls")
        has_tcid = "tool_call_id" in m          # '' is a REAL id here, and it is falsy —
        tcid = m.get("tool_call_id")            # testing truthiness skipped exactly the
        if not calls and not has_tcid:          # empty ids this function exists to repair
            out.append(m)
            continue
        n = dict(m)
        if calls:
            n["tool_calls"] = [{**c, "id": _fix(c.get("id"), i)} for c in calls]
        if has_tcid:
            n["tool_call_id"] = _fix(tcid, i)
        out.append(n)
    return out


def _drop_empty_text_turns(msgs: list) -> list:
    """#260 — an empty / whitespace-only / None TEXT block is rejected outright.

    r54 logged 800 x "text content blocks must contain non-whitespace text". Probed live:
    content="" -> "must be non-empty", content="   " -> "must contain non-whitespace
    text", content=None -> "Unsupported message content type".

    Scope matters. content=None is LEGAL on a message that carries tool_calls (its content
    array holds the tool_use block), so those are kept as-is — dropping one would orphan
    its result. A tool result with an empty body is kept too, with a placeholder: "the tool
    ran and returned nothing" is information, and removing it would orphan the call. Only a
    turn with no text, no tool_calls and no tool_call_id is dropped, and that carries
    nothing at all.
    """
    out = []
    for m in msgs:
        c = m.get("content")
        has_text = isinstance(c, str) and c.strip()
        if not isinstance(c, str):          # multimodal / already-structured content
            out.append(m)
            continue
        if has_text:
            out.append(m)
            continue
        if m.get("tool_calls"):
            out.append({**m, "content": None})
            continue
        if m.get("role") == "tool" or m.get("tool_call_id"):
            out.append({**m, "content": "(empty result)"})
            continue
        # nothing to say and nothing to carry
    return out


def _flatten_dangling_tool_calls(msgs: list) -> list:
    """#265 — the MIRROR of #249: a tool_call with no result is as fatal as the reverse.

    r56 (live): ``400 messages.142: `tool_use` ids were found without `tool_result` blocks
    immediately after: call_148`` — and the browser_test_user lane then wedged, every one of
    its calls failing on the same message. #249 prunes orphan RESULTS; nothing pruned the
    other direction, so an assistant turn whose calls were never answered (a step that ended
    at its round budget, or a result lost to condensation) goes out with dangling tool_use
    blocks and is rejected outright.

    Repaired the same way as #259: keep the attempt as TEXT so the model still sees what it
    tried to invoke, and drop only the protocol structure that cannot be satisfied.
    """
    out = []
    for i, m in enumerate(msgs):
        calls = m.get("tool_calls")
        if not calls:
            out.append(m)
            continue
        nxt = msgs[i + 1] if i + 1 < len(msgs) else None
        answered = set()
        if nxt is not None and (nxt.get("role") == "tool" or nxt.get("tool_call_id")):
            j = i + 1
            while j < len(msgs) and (msgs[j].get("role") == "tool"
                                     or msgs[j].get("tool_call_id")):
                answered.add(msgs[j].get("tool_call_id"))
                j += 1
        kept = [c for c in calls if c.get("id") in answered]
        if len(kept) == len(calls):
            out.append(m)
            continue
        lines = []
        for c in calls:
            if c.get("id") in answered:
                continue
            fn = (c or {}).get("function") or {}
            lines.append(f"[tool call, no result recorded] {fn.get('name')}({fn.get('arguments')})")
        base = m.get("content")
        base = base if isinstance(base, str) and base.strip() else ""
        n = dict(m)
        n["content"] = (base + ("\n" if base else "") + "\n".join(lines)) or "[tool call]"
        if kept:
            n["tool_calls"] = kept
        else:
            n.pop("tool_calls", None)
            n.pop("function_call", None)
        out.append(n)
    return out


def _prepare_messages_for_request(messages, model: Optional[str] = None, tools=None):
    """Single serialization contract for EVERY request path: prune orphan tool_results
    (#249), fit oversized images (#248), and — when the request declares no tools — flatten
    the tool protocol to text (#259). Four call sites built the wire payload independently,
    so a fix applied to one left the others failing; this is the one place provider-protocol
    repairs belong."""
    # ORDER IS LOAD-BEARING. #261 must run FIRST: every pairing decision below compares
    # ids, and a raw EMPTY id made #249 treat a perfectly good result as an orphan, drop
    # it, and leave #265 to strip the now-dangling call — losing the whole exchange.
    wire = _sanitize_tool_ids([m if isinstance(m, dict) else m.to_dict()
                               for m in messages])          # #261
    wire = _drop_orphan_tool_results(wire)                   # #249 result -> call
    wire = _flatten_dangling_tool_calls(wire)                # #265 call -> result
    wire = [_fit_message_images(m) for m in wire]            # #248
    wire = _drop_empty_text_turns(wire)                      # #260
    if not tools:
        wire = _flatten_tool_protocol(wire)
    if _needs_anthropic_shape(model):
        wire = _normalize_for_anthropic(wire)
    return wire


@dataclass
class Message:
    """Chat message - supports both text and multimodal content"""
    role: str  # "system", "user", "assistant", "tool"
    content: Optional[Union[str, list]] = None  # str for text, list for multimodal
    name: Optional[str] = None  # For function messages
    function_call: Optional[dict] = None  # For assistant function calls
    tool_calls: Optional[list] = None  # For tool calls
    tool_call_id: Optional[str] = None  # For tool response
    
    def to_dict(self) -> dict:
        d = {"role": self.role}
        if self.content is not None:
            d["content"] = self.content
        if self.name:
            d["name"] = self.name
        if self.function_call:
            d["function_call"] = self.function_call
        if self.tool_calls:
            d["tool_calls"] = [
                {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                if hasattr(tc, 'id') else tc
                for tc in self.tool_calls
            ]
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        return d
    
    @classmethod
    def system(cls, content: str) -> "Message":
        return cls(role="system", content=content)
    
    @classmethod
    def user(cls, content: str) -> "Message":
        return cls(role="user", content=content)
    
    @classmethod
    def user_with_image(cls, text: str, image_base64: str, mime_type: str = "image/png") -> "Message":
        """Create user message with text and image (multimodal)"""
        image_base64, mime_type = _fit_image_b64(image_base64, mime_type)
        return cls(
            role="user",
            content=[
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_base64}", "detail": "high"}}
            ]
        )
    
    @classmethod
    def user_multimodal(cls, content_parts: list) -> "Message":
        """Create user message with multiple content parts (text, images, etc.)
        
        Args:
            content_parts: List of dicts like:
                [{"type": "text", "text": "..."}, 
                 {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}]
        """
        return cls(role="user", content=content_parts)
    
    @classmethod
    def assistant(cls, content: Optional[str] = None, tool_calls: Optional[list] = None) -> "Message":
        return cls(role="assistant", content=content, tool_calls=tool_calls)
    
    @classmethod
    def tool(cls, content: str, tool_call_id: str) -> "Message":
        """Create tool response message"""
        return cls(role="tool", content=content, tool_call_id=tool_call_id)


# --- Context-size control --------------------------------------------------
# The per-call message history grows unbounded as agents accumulate tool outputs
# (observed: median ~95K, max ~768K chars/call) and input tokens dominate the LLM
# cost (input >> output). Cap it by truncating the bulky text CONTENT of OLD
# messages (older than the recent window), while preserving system messages, the
# first message (the task), every message's role, and tool_call pairing — so
# correctness holds and only stale bulk is dropped. The stable prefix that remains
# is also what Gemini implicit caching discounts. Tunable via env:
#   ENVGEN_CTX_MASK=0 disables; ENVGEN_CTX_KEEP_RECENT (default 8);
#   ENVGEN_CTX_MAX_OLD_CHARS (default 6000).
def _ctx_cfg():
    if os.environ.get("ENVGEN_CTX_MASK", "1") != "1":
        return None
    try:
        keep = int(os.environ.get("ENVGEN_CTX_KEEP_RECENT", "8"))
        cap = int(os.environ.get("ENVGEN_CTX_MAX_OLD_CHARS", "6000"))
    except ValueError:
        keep, cap = 8, 6000
    return max(keep, 1), max(cap, 500)


def _mask_block() -> int:
    """#255: how many steps the masking cutoff holds still. 1 disables quantisation."""
    try:
        return max(1, int(os.environ.get("ENVGEN_MASK_BLOCK", "16") or 16))
    except (TypeError, ValueError):
        return 16


def _total_str_chars(messages: list) -> int:
    total = 0
    for m in messages:
        c = getattr(m, "content", None)
        if isinstance(c, str):
            total += len(c)
    return total


def _apply_observation_mask(messages: list, cutoff: int, max_old: int,
                            first_task: int) -> list:
    stub = "\n…[older output truncated to save context]…\n"
    out = []
    for i, m in enumerate(messages):
        c = getattr(m, "content", None)
        if (i >= cutoff or i == first_task or getattr(m, "role", "") == "system"
                or not isinstance(c, str) or len(c) <= max_old):
            out.append(m)
            continue
        out.append(Message(role=m.role,
                           content=c[: max_old * 3 // 4] + stub + c[-max_old // 4:],
                           name=m.name, function_call=m.function_call,
                           tool_calls=m.tool_calls, tool_call_id=m.tool_call_id))
    return out


def _mask_old_observations(messages: list, model: Optional[str] = None) -> list:
    """Truncate the bulky text content of stale messages to bound per-call input —
    but ONLY when the full history would exceed the model's RECOMMENDED WORKING
    window. A large-context model (e.g. Gemini's ~1M) keeps its COMPLETE history
    (no info loss); trimming kicks in only to avoid genuine overflow. (Was: always
    trimmed to keep_recent + max_old regardless of model, wasting a big window while
    cutting old info.)"""
    cfg = _ctx_cfg()
    if not cfg or not messages:
        return messages
    keep_recent, max_old = cfg
    # MODEL-AWARE budget: if everything fits the model's working window, keep it ALL.
    try:
        from utils.model_limits import resolve_ctx_working_chars
        budget = resolve_ctx_working_chars(model) if model else 0
    except Exception:
        budget = 0
    if budget:
        total = 0
        for m in messages:
            c = getattr(m, "content", None)
            if isinstance(c, str):
                total += len(c)
        if total <= budget:
            return messages
    n = len(messages)
    if n <= keep_recent:
        return messages
    # protect the system prompt(s) and the first non-system message (the task)
    first_task = next((i for i, m in enumerate(messages)
                       if getattr(m, "role", "") != "system"), -1)
    exact_cutoff = n - keep_recent

    # #255 PREFIX STABILITY. A prompt cache is keyed on the longest common PREFIX, and
    # ``exact_cutoff`` advances on EVERY step — so on every step the messages that just
    # crossed it flip from full text to truncated text, invalidating the cache from that
    # position onward. Forever. r51 measured 456.7M prompt vs 0.9M completion tokens, i.e.
    # this run's entire cost IS the prompt, and 40% of it was re-sent uncached. Quantising
    # the cutoff DOWN to a block boundary keeps the masked set byte-identical for BLOCK
    # consecutive steps. It is also strictly information-preserving: a quantised cutoff is
    # <= the exact one, so it never truncates a message the old code would have kept.
    # (Latent on Gemini — 2.45M working window, masking never fired; constant on
    # Claude/opus-4.7 at 313.6k, where r51's ~318k-char mean prompt is over the line on
    # essentially every call.)
    block = _mask_block()
    cutoff = (exact_cutoff // block) * block if block > 1 else exact_cutoff
    if cutoff <= 0:
        cutoff = exact_cutoff
    out = _apply_observation_mask(messages, cutoff, max_old, first_task)
    if not budget or _total_str_chars(out) <= budget:
        return out

    # #255 BUDGET FLOOR. Under real pressure, fitting the window outranks cache reuse —
    # and the old code did NOT actually fit it: masking was a fixed-shape truncation, so a
    # long history stayed far over budget (400 messages capped at 6000 chars each is still
    # 2.4M) and the provider answered 400. Give up stability first, then tighten the per-
    # message cap, then the recent window — each step only as far as the budget demands.
    out = _apply_observation_mask(messages, exact_cutoff, max_old, first_task)
    cap = max_old
    while _total_str_chars(out) > budget and cap > 400:
        cap //= 2
        out = _apply_observation_mask(messages, exact_cutoff, cap, first_task)
    keep = keep_recent
    while _total_str_chars(out) > budget and keep > 2:
        keep = max(2, keep // 2)
        out = _apply_observation_mask(messages, n - keep, cap, first_task)
    return out


def _llm_hard_timeout(config_timeout, env) -> float:
    """FIX #187: the per-call watchdog timeout. config.timeout defaults to 1800s,
    so one wedged SDK call could hold a lane 30min before the watchdog cancelled
    it — indistinguishable from a dead run (handoff 2026-07-18 §3-3). Cap the
    watchdog at 600s (observed real-call max: 237s) unless the config is already
    tighter; ENVGEN_LLM_HARD_TIMEOUT_S overrides the cap in either direction.
    The retry layer re-rolls after the cancel, so a cancelled slow call is
    retried, not lost."""
    try:
        cap = float(env.get("ENVGEN_LLM_HARD_TIMEOUT_S") or 600)
    except Exception:
        cap = 600.0
    try:
        cfg = float(config_timeout or 240)
    except Exception:
        cfg = 240.0
    return min(cfg, cap)


def _prune_stale_images_for_reroll(contents, keep_last, make_text_part):
    """FIX #187: MALFORMED_FUNCTION_CALL storms correlate with huge MULTIMODAL
    contexts (gm_val_run14: 571 malformeds during the screenshot-heavy analyst
    phase; tiktok-r4's analyst was at 3.98M chars). After repeated malformed
    re-rolls the temperature perturbation alone keeps replaying the same doomed
    payload — so ALSO drop all but the newest ``keep_last`` inline images,
    replacing each with a text placeholder (the model keeps positional context).
    Pure + duck-typed (parts need only .text/.inline_data); never mutates the
    caller's contents (the un-pruned list is reused by later attempts).
    Returns (pruned_contents, n_pruned) — n_pruned==0 means "use the original".
    """
    try:
        total = 0
        for c in (contents or []):
            for p in (getattr(c, "parts", None) or []):
                if getattr(p, "inline_data", None) is not None:
                    total += 1
        n_drop = total - max(0, int(keep_last))
        if n_drop <= 0:
            return contents, 0
        seen = 0
        pruned_contents = []
        for c in (contents or []):
            parts = getattr(c, "parts", None) or []
            new_parts = []
            changed = False
            for p in parts:
                if getattr(p, "inline_data", None) is not None:
                    seen += 1
                    if seen <= n_drop:
                        new_parts.append(make_text_part(
                            "[stale inline image elided after repeated "
                            "MALFORMED_FUNCTION_CALL re-rolls]"))
                        changed = True
                        continue
                new_parts.append(p)
            if changed:
                c = type(c)(role=getattr(c, "role", None), parts=new_parts)
            pruned_contents.append(c)
        return pruned_contents, n_drop
    except Exception:
        return contents, 0


def _malformed_extra_retries() -> int:
    """FIX #187: extra attempts granted ONLY to MALFORMED_FUNCTION_CALL streaks
    (a cheap transient generation failure — the temperature ladder + image-prune
    need more than 2 re-rolls during a storm). ENVGEN_MALFORMED_EXTRA_RETRIES=0
    disables."""
    try:
        return max(0, int(os.environ.get("ENVGEN_MALFORMED_EXTRA_RETRIES") or 2))
    except Exception:
        return 2


def _extend_retry_budget(is_malformed, is_rate_limit, attempt, total_attempts,
                         max_retries, malformed_extra, rate_limit_extra) -> int:
    """FIX #187: the pure retry-budget extension rule, evaluated on EVERY failure.
    Extends only on the LAST remaining attempt; each cause is idempotent (its
    target total is absolute, so re-applying never grows the budget again).
    NOTE this also FIXES the old inline rate-limit extension, which was dead code:
    its `attempt == max_retries-1` check sat inside `attempt < total_attempts-1`
    — mutually exclusive on the final attempt, so rate limits never actually got
    the extra attempts the log line promised."""
    try:
        if attempt != total_attempts - 1:
            return total_attempts
        target = total_attempts
        if is_malformed and (malformed_extra or 0) > 0:
            target = max(target, max_retries + malformed_extra)
        if is_rate_limit and (rate_limit_extra or 0) > 0:
            target = max(target, max_retries + rate_limit_extra)
        return target
    except Exception:
        return total_attempts


# #326 — a TERMINAL provider error is UNRECOVERABLE: retrying wastes wall-clock and never
# succeeds. The metagen key hitting its spend cap returned HTTP 400 "Spend exceeded. Budget
# for mg key ..." on EVERY call; with no terminal classification, all four lanes spun ~4500
# rejected attempts for hours until the wall-clock cap. Classify billing/quota exhaustion and
# hard-auth rejection as terminal → fail the call immediately AND latch a reason the run loop
# can poll (terminal_llm_error()) to abort the whole run cleanly.
_TERMINAL_LLM_ERROR = {"reason": None}

# Specific billing/quota phrases — deliberately NOT the generic "quota"/"exceeded" (those
# appear in transient 429 rate-limit messages, e.g. Gemini ResourceExhausted).
_TERMINAL_ERROR_PHRASES = (
    "spend exceeded", "budget for", "insufficient_quota", "insufficient quota",
    "payment required", "billing hard limit", "entitlement",
)


def _is_terminal_llm_error(error: Exception) -> bool:
    """True for an UNRECOVERABLE provider error — spend/budget/quota exhaustion or a hard auth
    rejection (401/403). A 429 rate limit is transient and explicitly NOT terminal."""
    status = getattr(error, "status_code", None)
    if isinstance(status, int) and status == 429:
        return False
    s = str(error).lower()
    if any(p in s for p in _TERMINAL_ERROR_PHRASES):
        return True
    if isinstance(status, int) and status in (401, 403, 402):
        return True
    return False


def terminal_llm_error() -> Optional[str]:
    """The latched reason if any LLM call hit a terminal provider error (budget/quota exhausted,
    hard auth), else None. A run loop should poll this and abort instead of spinning."""
    return _TERMINAL_LLM_ERROR["reason"]


@dataclass
class LLMResponse:
    """LLM response"""
    content: str
    model: str
    finish_reason: str = "stop"  # stop, length, function_call, tool_calls
    usage: dict = field(default_factory=dict)  # prompt_tokens, completion_tokens, total_tokens
    function_call: Optional[dict] = None
    tool_calls: Optional[list] = None
    raw_response: Optional[Any] = None
    latency: float = 0.0  # seconds
    reasoning: Optional[str] = None  # model thinking summary (Gemini include_thoughts), for observability
    
    @property
    def prompt_tokens(self) -> int:
        return self.usage.get("prompt_tokens", 0)
    
    @property
    def completion_tokens(self) -> int:
        return self.usage.get("completion_tokens", 0)
    
    @property
    def total_tokens(self) -> int:
        return self.usage.get("total_tokens", 0)


class BaseLLMClient(ABC):
    """
    Base LLM Client
    
    All LLM providers must implement this interface
    """
    
    def __init__(self, config: LLMConfig):
        self.config = config
        self._logger = logging.getLogger(f"LLM.{config.provider.value}")
    
    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop: Optional[list[str]] = None,
        functions: Optional[list[dict]] = None,
        tools: Optional[list[dict]] = None,
        **kwargs
    ) -> LLMResponse:
        """
        Send chat completion request
        
        Args:
            messages: List of chat messages
            temperature: Sampling temperature (overrides config)
            max_tokens: Maximum tokens to generate (overrides config)
            stop: Stop sequences
            functions: Function definitions for function calling
            tools: Tool definitions for tool use
            
        Returns:
            LLM response
        """
        pass
    
    @abstractmethod
    async def chat_stream(
        self,
        messages: list[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop: Optional[list[str]] = None,
        **kwargs
    ) -> AsyncIterator[str]:
        """
        Send streaming chat completion request
        
        Yields:
            Response content chunks
        """
        pass
    
    async def complete(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> LLMResponse:
        """
        Simple completion interface
        
        Args:
            prompt: User prompt
            system_prompt: Optional system prompt
            
        Returns:
            LLM response
        """
        messages = []
        if system_prompt:
            messages.append(Message.system(system_prompt))
        messages.append(Message.user(prompt))
        return await self.chat(messages, **kwargs)
    
    def _is_rate_limit_error(self, error: Exception) -> bool:
        """Check if error is a rate limit error"""
        # An explicit HTTP status is authoritative: only 429 is a rate limit.
        # Other 4xx (e.g. 400 invalid_request) must NOT be retried as throttling
        # even if the message happens to contain words like "quota"/"exceeded".
        status = getattr(error, "status_code", None)
        if isinstance(status, int):
            if status == 429:
                return True
            if 400 <= status < 500:
                return False

        error_str = str(error).lower()
        error_type = type(error).__name__.lower()

        # Common rate limit indicators
        rate_limit_keywords = [
            "rate_limit", "rate limit", "ratelimit",
            "429", "too many requests",
            "resource_exhausted", "resourceexhausted",
            "quota", "exceeded",
            "throttl",
        ]
        
        for keyword in rate_limit_keywords:
            if keyword in error_str or keyword in error_type:
                return True
        
        # Check for HTTP 429 status code
        if hasattr(error, 'status_code') and error.status_code == 429:
            return True
        if hasattr(error, 'code') and error.code == 429:
            return True
            
        return False
    
    def _extract_retry_after(self, error: Exception) -> Optional[float]:
        """Try to extract retry-after time from error"""
        error_str = str(error)
        
        # Try to find retry-after in error message (e.g., "retry after 60 seconds")
        import re
        patterns = [
            r'retry.?after[:\s]+(\d+)',
            r'wait[:\s]+(\d+)',
            r'(\d+)\s*seconds?',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, error_str.lower())
            if match:
                return float(match.group(1))
        
        return None
    
    async def _retry_with_backoff(
        self,
        func,
        *args,
        max_retries: Optional[int] = None,
        **kwargs
    ) -> Any:
        """Retry with exponential backoff and smart rate limit handling"""
        max_retries = max_retries or self.config.retry_attempts
        last_error = None
        
        # For rate limits, we may want more retries with longer delays
        rate_limit_extra_retries = 3
        rate_limit_base_delay = 30  # Start with 30 seconds for rate limits
        
        attempt = 0
        total_attempts = max_retries
        
        while attempt < total_attempts:
            try:
                attempt_start = datetime.now()
                self._logger.debug(f"[LLM] Attempt {attempt + 1}/{total_attempts} starting...")
                result = await func(*args, **kwargs)
                elapsed = (datetime.now() - attempt_start).total_seconds()
                self._logger.info(f"[LLM] Attempt {attempt + 1} succeeded in {elapsed:.1f}s")
                return result
            except Exception as e:
                elapsed = (datetime.now() - attempt_start).total_seconds()
                last_error = e
                error_type = type(e).__name__
                error_msg = str(e)[:200]  # Truncate long errors
                if not error_msg.strip():
                    # #582: a bare exception (classically `assert x` with no message) logged as
                    # "[AssertionError] " and nothing else — 2313 such 3-attempt failure groups
                    # across the netflix arc, every one undiagnosable: the type alone says
                    # neither what asserted nor where. `agent/utils/llm.py` contains no assert,
                    # so these originate in the SDK/transport and only the frame identifies
                    # them. Attach the innermost frame so ONE failure names its own cause
                    # instead of seeding another blind retry. Log-only; guarded so building a
                    # log line can never itself raise.
                    error_msg = _blank_error_origin(e)

                # #326: a TERMINAL provider error (spend/budget/quota exhausted, hard auth) is
                # unrecoverable — do NOT burn retries, and latch a reason the run loop can poll
                # to abort. Latch BEFORE re-raising so a caught exception still surfaces it.
                if _is_terminal_llm_error(e):
                    _TERMINAL_LLM_ERROR["reason"] = f"[{error_type}] {error_msg}"
                    self._logger.error(
                        f"[LLM] TERMINAL provider error — not retrying, run should abort: "
                        f"[{error_type}] {error_msg}")
                    raise

                is_rate_limit = self._is_rate_limit_error(e)
                # FIX #187: budget extension is decided by the PURE rule (see
                # _extend_retry_budget — it also fixes the old dead-code rate-limit
                # extension). MALFORMED streaks get a small extra budget so the
                # temperature ladder + stale-image prune have room to work.
                is_malformed = "MALFORMED" in str(e).upper()
                _new_total = _extend_retry_budget(
                    is_malformed, is_rate_limit, attempt, total_attempts,
                    max_retries, _malformed_extra_retries(), rate_limit_extra_retries)
                if _new_total != total_attempts:
                    total_attempts = _new_total
                    self._logger.info(
                        f"[LLM] {'MALFORMED streak' if is_malformed else 'Rate limit'} on the "
                        f"final attempt — extending retries to {total_attempts}")

                if attempt < total_attempts - 1:
                    if is_rate_limit:
                        # For rate limits, use longer delays
                        retry_after = self._extract_retry_after(e)
                        if retry_after:
                            delay = retry_after + 5  # Add 5 seconds buffer
                        else:
                            # Exponential backoff starting from rate_limit_base_delay
                            delay = rate_limit_base_delay * (2 ** min(attempt, 3))  # Cap at 240s

                        self._logger.warning(
                            f"[LLM] Rate limit hit on attempt {attempt + 1}. "
                            f"Sleeping {delay:.0f}s before retry... [{error_type}] {error_msg}"
                        )
                    else:
                        # Normal exponential backoff for other errors
                        delay = self.config.retry_delay * (2 ** attempt)
                        self._logger.warning(
                            f"[LLM] Attempt {attempt + 1} failed after {elapsed:.1f}s: "
                            f"[{error_type}] {error_msg}. Retrying in {delay}s..."
                        )
                    
                    await asyncio.sleep(delay)
                else:
                    self._logger.error(f"[LLM] All {total_attempts} attempts failed. Last error: [{error_type}] {error_msg}")
                
                attempt += 1
        
        # #659: `raise last_error` with NOTHING to raise. `last_error` starts as None and is
        # only assigned inside the retry loop, so when the loop body never runs the bare
        # `raise None` becomes "TypeError: exceptions must derive from BaseException" — a
        # message that names neither the call nor the reason. The loop is skipped whenever the
        # attempt budget resolves to 0, and `retry_attempts: 0` is a natural thing to put in a
        # config file meaning "do not retry" (`utils/config.py` defaults it to 3 but reads it
        # straight from the LLM config block). Same #634 lesson: an error that misdescribes the
        # condition costs a whole debugging round.
        if last_error is None:
            raise RuntimeError(
                f"LLM call made no attempts: the retry budget resolved to {total_attempts}. "
                "Set `retry_attempts` to at least 1 in the LLM config.")
        raise last_error


def _blank_error_origin(error: BaseException) -> str:
    """#582 — a one-line origin for an exception whose ``str()`` is EMPTY.

    A bare ``assert x`` raises ``AssertionError('')``, so the retry log printed
    ``[AssertionError] `` and nothing else — 2313 three-attempt failure groups across the
    netflix arc, none of them diagnosable. This module has no ``assert``, so they originate in
    the SDK/transport and only the frame identifies them.

    Returns ``(no message) at <file>:<line> in <func>: <source>``, or ``(no message)`` when the
    traceback is unavailable. Never raises — it runs while building a log line on an
    already-failing path."""
    try:
        import traceback as _tb
        frames = _tb.extract_tb(error.__traceback__)
        if not frames:
            return "(no message)"
        f = frames[-1]
        where = f"{str(f.filename).split('/')[-1]}:{f.lineno} in {f.name}"
        src = (f.line or "").strip()[:120]
        return f"(no message) at {where}" + (f": {src}" if src else "")
    except Exception:
        return "(no message)"


def _gpt5_reasoning_effort(model_name, reasoning_effort) -> dict:
    """`reasoning_effort` is a gpt-5-only request param.

    Return ``{"reasoning_effort": <e>}`` iff the model is gpt-5 AND an effort is set,
    else ``{}`` — so the param never reaches gpt-4 / o-series / Anthropic / Gemini,
    which reject it. Single source of truth for the gate rule.
    """
    if reasoning_effort and str(model_name).startswith("gpt-5"):
        return {"reasoning_effort": str(reasoning_effort)}
    return {}


def build_openai_request_params(*, model_name, messages, reasoning_effort=None, **rest):
    """Pure helper assembling OpenAI request params with the gpt-5-gated reasoning_effort.

    The LLM wrapper applies the same gate via :func:`_gpt5_reasoning_effort`, so the rule
    lives in exactly one place; this helper exists so the gate is unit-testable.
    """
    params = {"model": model_name, "messages": messages}
    params.update(rest)
    params.update(_gpt5_reasoning_effort(model_name, reasoning_effort))
    return params


class OpenAIClient(BaseLLMClient):
    """OpenAI API Client"""
    OPENAI_MAX_TOOLS = 128
    ROUTER_TOOL_NAME = "tool_router"
    # Keep orchestration-critical tools available when OpenAI tool count is truncated.
    TOOL_TRUNCATION_PRIORITY = {
        # Core control flow / completion
        "finish",
        "plan",
        "verify_plan",
        "deliver_project",
        "wait",
        "think",
        # Agent collaboration / reporting
        "check_inbox",
        "send_message",
        "broadcast",
        "report_issue",
        "report_progress",
        "report_completion",
        "get_progress",
        # Validation/runtime gates
        "execute_task_suite",
        "verify_api_contract",
        "read",
        "write",
        "edit",
        "apply_patch",
        # Dynamic team tools
        "spawn_worker",
        "parallel_execute",
        "terminate_runtime_agent",
        "list_runtime_agents",
        "team_health_summary",
        "create_agent_team",
        "define_team_agent",
        "launch_agent_team",
        "monitor_agent_team",
        "pause_agent_team",
        "resume_agent_team",
        "terminate_agent_team",
        "run_parallel_reasoning",
        "submit_plan",
        "accept_plan",
        "request_plan_changes",
        "list_pending_plan_decisions",
        "list_personas",
        "create_persona",
        "get_similar_practices",
        "suggest_team",
        "record_practice",
    }
    TOOL_TRUNCATION_MUST_HAVE = {"finish", "spawn_worker", "parallel_execute"}
    
    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self._client = None
        # For >128 tool sets: rotate non-critical tool exposure across requests
        # so most tools remain reachable over time instead of being permanently dropped.
        self._tool_rotation_offset = 0
    
    # Default API bases for OpenAI-compatible providers that need a non-default
    # endpoint. OPENAI itself uses the SDK default (None).
    PROVIDER_DEFAULT_BASE_URLS = {
        LLMProvider.OPENROUTER: "https://openrouter.ai/api/v1",
    }
    # Per-provider API key environment variables, tried in order.
    PROVIDER_API_KEY_ENVS = {
        LLMProvider.OPENROUTER: ("OPENROUTER_API_KEY", "OPENAI_API_KEY"),
        LLMProvider.OPENAI: ("OPENAI_API_KEY",),
        LLMProvider.AZURE: ("AZURE_OPENAI_API_KEY", "OPENAI_API_KEY"),
    }
    # Azure OpenAI requires an explicit API version. Overridable via
    # config.extra_params["api_version"] or AZURE_OPENAI_API_VERSION.
    AZURE_DEFAULT_API_VERSION = "2024-10-21"

    def _is_azure(self) -> bool:
        return self.config.provider == LLMProvider.AZURE

    def _resolve_base_url(self) -> Optional[str]:
        """Resolve the base URL: explicit api_base wins, else a provider default."""
        if self.config.api_base:
            return self.config.api_base
        return self.PROVIDER_DEFAULT_BASE_URLS.get(self.config.provider)

    def _resolve_api_key(self) -> Optional[str]:
        """Resolve the API key: explicit config wins, else provider env vars."""
        if self.config.api_key:
            return self.config.api_key
        for env in self.PROVIDER_API_KEY_ENVS.get(self.config.provider, ("OPENAI_API_KEY",)):
            value = os.getenv(env)
            if value:
                return value
        return None

    def _resolve_api_version(self) -> str:
        """Azure API version: extra_params > env > default."""
        return (
            (self.config.extra_params or {}).get("api_version")
            or os.getenv("AZURE_OPENAI_API_VERSION")
            or self.AZURE_DEFAULT_API_VERSION
        )

    def _get_client(self):
        """Lazy initialization of the (Azure) OpenAI client"""
        if self._client is None:
            if self._is_azure():
                try:
                    from openai import AsyncAzureOpenAI
                except ImportError:
                    raise ImportError("Please install openai: pip install openai")

                # Azure endpoint comes from api_base or AZURE_OPENAI_ENDPOINT;
                # config.model_name is the deployment name.
                endpoint = self._resolve_base_url() or os.getenv("AZURE_OPENAI_ENDPOINT")
                self._client = AsyncAzureOpenAI(
                    api_key=self._resolve_api_key(),
                    azure_endpoint=endpoint,
                    api_version=self._resolve_api_version(),
                    timeout=self.config.timeout,
                )
            else:
                try:
                    from openai import AsyncOpenAI
                except ImportError:
                    raise ImportError("Please install openai: pip install openai")

                self._client = AsyncOpenAI(
                    api_key=self._resolve_api_key(),
                    base_url=self._resolve_base_url(),
                    timeout=self.config.timeout,
                )
        return self._client

    @staticmethod
    def _tool_name(tool_schema: dict) -> Optional[str]:
        if not isinstance(tool_schema, dict):
            return None
        fn = tool_schema.get("function")
        if isinstance(fn, dict):
            return fn.get("name")
        return None

    def _truncate_tools_with_priority(self, tools: list[dict], limit: Optional[int] = None) -> list[dict]:
        """
        Truncate tools to provider limit while preserving critical orchestration tools.
        Non-critical tools are exposed via round-robin windows across requests.
        """
        limit = limit or self.OPENAI_MAX_TOOLS
        if len(tools) <= limit:
            return tools

        selected_indices: list[int] = []
        selected_set = set()

        # 1) Reserve priority tools first (in original order).
        for idx, schema in enumerate(tools):
            name = self._tool_name(schema)
            if name in self.TOOL_TRUNCATION_PRIORITY and idx not in selected_set:
                selected_indices.append(idx)
                selected_set.add(idx)
                if len(selected_indices) >= limit:
                    break

        # 2) Fill remaining slots with a rotating window of non-priority tools.
        if len(selected_indices) < limit:
            non_priority_indices = [i for i in range(len(tools)) if i not in selected_set]
            remaining = limit - len(selected_indices)

            if non_priority_indices and remaining > 0:
                start = self._tool_rotation_offset % len(non_priority_indices)
                # Circular slice of non-priority tools
                for k in range(remaining):
                    idx = non_priority_indices[(start + k) % len(non_priority_indices)]
                    selected_indices.append(idx)
                    selected_set.add(idx)
                self._tool_rotation_offset = (start + remaining) % max(1, len(non_priority_indices))

        selected_indices.sort()
        # 3) Force-include must-have tools (if present in original tool set).
        name_to_index = {
            self._tool_name(schema): idx
            for idx, schema in enumerate(tools)
            if self._tool_name(schema)
        }
        selected_set = set(selected_indices)
        missing_must_have_now = [
            name for name in self.TOOL_TRUNCATION_MUST_HAVE
            if name in name_to_index and name_to_index[name] not in selected_set
        ]
        if missing_must_have_now:
            # Replace from the end (least stable/least-priority in current selection).
            replace_cursor = len(selected_indices) - 1
            for must_name in missing_must_have_now:
                must_idx = name_to_index[must_name]
                while replace_cursor >= 0 and selected_indices[replace_cursor] == must_idx:
                    replace_cursor -= 1
                if replace_cursor < 0:
                    break
                selected_set.discard(selected_indices[replace_cursor])
                selected_indices[replace_cursor] = must_idx
                selected_set.add(must_idx)
                replace_cursor -= 1

        selected_indices = sorted(set(selected_indices))
        # Keep exact limit when set() compaction shrinks result.
        if len(selected_indices) < limit:
            for idx in range(len(tools)):
                if idx in selected_set:
                    continue
                selected_indices.append(idx)
                selected_set.add(idx)
                if len(selected_indices) >= limit:
                    break
        selected_indices = sorted(selected_indices[:limit])
        truncated = [tools[i] for i in selected_indices]

        kept_names = {self._tool_name(t) for t in truncated}
        missing_must_have = sorted(
            name for name in self.TOOL_TRUNCATION_MUST_HAVE
            if name in name_to_index and name not in kept_names
        )
        if missing_must_have:
            self._logger.warning(
                f"[LLM] Tool truncation still dropped critical tools: {missing_must_have}. "
                f"kept={len(truncated)}/{len(tools)}"
            )
        else:
            self._logger.warning(
                f"[LLM] OpenAI tools limit exceeded: {len(tools)} > {limit}. "
                f"Applied priority + rotating-window truncation; kept critical tools and "
                f"rotated non-critical tool exposure (offset={self._tool_rotation_offset})."
            )

        return truncated

    def _build_tool_router(self, omitted_tools: list[dict]) -> Optional[dict]:
        """
        Build a gateway tool that can invoke omitted tools by name.
        """
        omitted_names = []
        for schema in omitted_tools:
            name = self._tool_name(schema)
            if name and name != self.ROUTER_TOOL_NAME:
                omitted_names.append(name)
        omitted_names = sorted(set(omitted_names))
        if not omitted_names:
            return None

        return {
            "type": "function",
            "function": {
                "name": self.ROUTER_TOOL_NAME,
                "description": (
                    "Invoke a tool that is not directly exposed in this turn due to tool limits. "
                    "Provide target tool name and exact arguments object for that tool."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tool_name": {
                            "type": "string",
                            "enum": omitted_names,
                            "description": "Target tool to invoke.",
                        },
                        "arguments": {
                            "type": "object",
                            "description": "Arguments for target tool.",
                            "additionalProperties": True,
                        },
                    },
                    "required": ["tool_name", "arguments"],
                    "additionalProperties": False,
                },
            },
        }

    def _prepare_tools_for_openai(self, tools: list[dict]) -> Tuple[list[dict], Set[str]]:
        """
        Prepare tool list for OpenAI limits.
        Returns (effective_tools, omitted_tool_names_covered_by_router).
        """
        if len(tools) <= self.OPENAI_MAX_TOOLS:
            return tools, set()

        # Keep one slot for the gateway tool.
        selected = self._truncate_tools_with_priority(tools, limit=max(1, self.OPENAI_MAX_TOOLS - 1))

        selected_names = {self._tool_name(t) for t in selected}
        omitted = [t for t in tools if self._tool_name(t) not in selected_names]
        router = self._build_tool_router(omitted)

        if not router:
            # Fallback to normal truncation if no omitted names available.
            return self._truncate_tools_with_priority(tools), set()

        effective = selected + [router]
        omitted_names = {
            self._tool_name(t) for t in omitted
            if self._tool_name(t)
        }
        self._logger.warning(
            f"[LLM] OpenAI tools limit exceeded: {len(tools)} > {self.OPENAI_MAX_TOOLS}. "
            f"Using {self.ROUTER_TOOL_NAME} gateway for {len(omitted_names)} omitted tools."
        )
        return effective, omitted_names

    def _rewrite_router_tool_calls(self, tool_calls: list[Any], omitted_names: Set[str]) -> list[dict]:
        """
        Rewrite tool_router(...) calls back into concrete tool calls.
        """
        rewritten: list[dict] = []
        for tc in tool_calls or []:
            d = tc.model_dump() if hasattr(tc, "model_dump") else dict(tc)
            fn = d.get("function", {}) or {}
            name = fn.get("name")
            if name != self.ROUTER_TOOL_NAME:
                rewritten.append(d)
                continue

            args_raw = fn.get("arguments", "{}")
            try:
                payload = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
            except Exception:
                payload = {}

            target = payload.get("tool_name")
            target_args = payload.get("arguments", {})
            if isinstance(target_args, str):
                try:
                    target_args = json.loads(target_args)
                except Exception:
                    target_args = {"value": target_args}
            if not isinstance(target_args, dict):
                target_args = {"value": target_args}

            if not target or (omitted_names and target not in omitted_names):
                # Convert invalid gateway calls into a no-op thought to avoid hard failures.
                d["function"] = {
                    "name": "think",
                    "arguments": json.dumps(
                        {
                            "thought": (
                                f"tool_router call ignored: invalid target '{target}'. "
                                f"Use a valid omitted tool name."
                            )
                        }
                    ),
                }
                rewritten.append(d)
                continue

            d["function"] = {
                "name": target,
                "arguments": json.dumps(target_args),
            }
            rewritten.append(d)

        return rewritten
    
    async def chat(
        self,
        messages: list[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop: Optional[list[str]] = None,
        functions: Optional[list[dict]] = None,
        tools: Optional[list[dict]] = None,
        **kwargs
    ) -> LLMResponse:
        client = self._get_client()

        # Always sanitize outgoing content (redact keys/tokens/password-like lines).
        # #249: Anthropic-backed providers reject the WHOLE request with
        # "unexpected `tool_use_id` found in `tool_result` blocks" when a role=tool
        # message has no matching tool_call in a preceding assistant message. Observation
        # masking/truncation can drop the assistant turn while keeping its results, so
        # prune orphans before serializing. OpenAI tolerates them; Anthropic does not.
        safe_messages: list[Message] = [
            Message(role=m.role, content=_sanitize_message_content(m.content), name=m.name, function_call=m.function_call, tool_calls=m.tool_calls, tool_call_id=m.tool_call_id)
            for m in _drop_orphan_tool_results(
                _mask_old_observations(messages, self.config.model_name))
        ]
        
        # Determine token parameter name based on model. Reasoning-class models
        # (gpt-5, o1, o3) use ``max_completion_tokens`` AND commonly reject the
        # classic sampling params (``temperature``, ``top_p``, ``frequency_penalty``,
        # ``presence_penalty``). We omit them up front for that family to avoid
        # 400 "unsupported_parameter" errors; older chat models keep the params.
        model_name = self.config.model_name
        use_completion_tokens = model_name.startswith(("gpt-5", "o1", "o3"))
        token_param = "max_completion_tokens" if use_completion_tokens else "max_tokens"
        # #247: some providers reject the classic sampling params outright. Claude on GCP
        # Vertex answers 400 "`temperature` is deprecated for this model", and the Llama
        # API's OpenAI-compat gateway answers 400 "frequency_penalty is not supported in
        # OpenAI compatibility mode" — every call fails, so a run on such a provider cannot
        # start at all. Drop them for the known-hostile families (and via an env override
        # for any provider we meet next); max_tokens is still sent, which Vertex REQUIRES.
        _ml = (model_name or "").lower()
        _drops_sampling = (
            use_completion_tokens
            or any(k in _ml for k in ("claude", "vertex", "anthropic", "fable"))
            or str(os.environ.get("ENVGEN_NO_SAMPLING_PARAMS", "")).strip().lower()
            in ("1", "true", "yes", "on"))

        request_params = {
            "model": model_name,
            # #259: pass the OUTGOING tool declarations — a history containing a tool
            # exchange is only representable when the request also declares tools.
            "messages": _prepare_messages_for_request(safe_messages, model_name,
                                                     tools=(tools or functions)),
            token_param: max_tokens or self.config.max_tokens,
        }
        if not _drops_sampling:
            request_params["temperature"] = temperature if temperature is not None else self.config.temperature
            request_params["top_p"] = self.config.top_p
            # #247: only send the penalties when they are actually SET. They default to
            # 0.0 (a semantic no-op), yet third-party OpenAI-compatible endpoints reject
            # them outright — the Llama API compat gateway answers every call with
            # 400 "frequency_penalty is not supported in OpenAI compatibility mode",
            # so a run on such a provider cannot make a single LLM call. Omitting a
            # zero penalty changes nothing for providers that do accept it.
            if self.config.frequency_penalty:
                request_params["frequency_penalty"] = self.config.frequency_penalty
            if self.config.presence_penalty:
                request_params["presence_penalty"] = self.config.presence_penalty
        
        if stop:
            request_params["stop"] = stop
        if functions:
            request_params["functions"] = functions
        omitted_tool_names: Set[str] = set()
        if tools:
            effective_tools, omitted_tool_names = self._prepare_tools_for_openai(tools)
            request_params["tools"] = effective_tools
        
        request_params.update(kwargs)
        
        start_time = datetime.now()
        
        # Log request info for debugging
        msg_count = len(safe_messages)
        total_content_len = sum(len(str(m.content or "")) for m in safe_messages)
        tool_count = len(tools) if tools else 0
        self._logger.info(f"[LLM Request] model={model_name}, messages={msg_count}, content_chars={total_content_len}, tools={tool_count}")
        
        async def _call_with_progress():
            """Wrapper that logs progress during long waits"""
            warn_interval = 60  # Log warning every 60 seconds
            call_start = datetime.now()
            
            async def _do_call():
                return await client.chat.completions.create(**request_params)
            
            # Create task so we can check on it
            task = asyncio.create_task(_do_call())

            # HARD total timeout: this loop used to warn forever and never cancel, so
            # one wedged HTTP call hung the whole run until an external kill. Past
            # config.timeout, cancel and raise — the retry layer takes over.
            # FIX #187: capped — config.timeout defaults to 1800s, which let one
            # wedged SDK call hold a lane 30min (looked like a dead run, §3-3).
            hard_timeout = _llm_hard_timeout(
                getattr(self.config, "timeout", None), os.environ)
            while not task.done():
                try:
                    # Wait for up to warn_interval seconds
                    return await asyncio.wait_for(asyncio.shield(task), timeout=warn_interval)
                except asyncio.TimeoutError:
                    elapsed = (datetime.now() - call_start).total_seconds()
                    if elapsed >= hard_timeout:
                        task.cancel()
                        self._logger.warning(
                            f"[LLM] Call exceeded hard timeout ({hard_timeout:.0f}s) — cancelling for retry")
                        raise TimeoutError(f"LLM call exceeded {hard_timeout:.0f}s")
                    self._logger.warning(f"[LLM] Still waiting for API response... elapsed={elapsed:.0f}s")
                    # Continue waiting
                    continue

            return await task
        
        async def _call():
            return await _call_with_progress()
        
        try:
            response = await self._retry_with_backoff(_call)
        except Exception as e:
            msg = str(e).lower()
            if "tool_use_id" in msg or "integrity check" in msg:
                # #249e DIAGNOSTIC: dump the ACTUAL wire message shape so the orphan can be
                # identified instead of guessed at (three blind patches cost three runs).
                try:
                    shape = []
                    for i, mm in enumerate(request_params.get("messages") or []):
                        r = mm.get("role")
                        ids = [tc.get("id") for tc in (mm.get("tool_calls") or [])
                               if isinstance(tc, dict)]
                        shape.append(f"{i}:{r}"
                                     + (f" calls={ids}" if ids else "")
                                     + (f" result_for={mm.get('tool_call_id')}"
                                        if mm.get("tool_call_id") else ""))
                    self._logger.error("[LLM] WIRE-SHAPE on tool-protocol 400: " + " | ".join(shape))
                except Exception:
                    pass
            if ("invalid_prompt" in msg) or ("flagged as potentially violating" in msg) or ("usage policy" in msg):
                raise RuntimeError(
                    "OpenAI rejected the prompt as invalid_prompt (policy filter). "
                    "This usually indicates the prompt contains sensitive data or other policy-triggering content."
                ) from e
            raise
        latency = (datetime.now() - start_time).total_seconds()
        
        choice = response.choices[0]
        message = choice.message
        
        # Log response summary
        prompt_tokens = response.usage.prompt_tokens if response.usage else 0
        completion_tokens = response.usage.completion_tokens if response.usage else 0
        # #1026: REPORT CACHED PREFIX TOKENS ON THIS PATH TOO.
        #
        # The Responses path already logs `cached_tokens` (see the other [LLM Response] site);
        # this chat-completions path — the one every netflix run actually takes — did not read
        # `usage.prompt_tokens_details` at all, so the single largest cost axis in a run was
        # unmeasurable. r172: 210,779,817 prompt tokens over 4,155 calls against 1,030,351
        # completion tokens, with the per-call prompt flat at ~41k from 9 messages onward
        # (frontend_agent.j2 alone is 104,817 chars ≈ 26k tokens, plus a 28,779-char shared
        # macro). That static prefix is re-sent every call, and whether the provider is
        # serving it from cache decides whether ~137M of those tokens are real work or free.
        #
        # Nothing here changes what is SENT. It only stops the answer being invisible: one run
        # now says whether the prefix is cached, and a 0 would make prompt-size work the
        # highest-leverage wall-clock fix available (r172 died on a 7200s cap).
        cached_tokens = 0
        try:
            _details = getattr(response.usage, "prompt_tokens_details", None) if response.usage else None
            cached_tokens = int(getattr(_details, "cached_tokens", 0) or 0)
        except Exception:
            cached_tokens = 0          # a provider without the field must never break a call
        has_tool_calls = bool(message.tool_calls)
        self._logger.info(f"[LLM Response] latency={latency:.1f}s, prompt_tokens={prompt_tokens}, cached_tokens={cached_tokens}, completion_tokens={completion_tokens}, tool_calls={has_tool_calls}, finish={choice.finish_reason}")

        return LLMResponse(
            content=message.content or "",
            model=response.model,
            finish_reason=choice.finish_reason,
            usage={
                "prompt_tokens": response.usage.prompt_tokens,
                "cached_tokens": cached_tokens,      # #1026
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            },
            function_call=message.function_call.model_dump() if message.function_call else None,
            tool_calls=self._rewrite_router_tool_calls(message.tool_calls, omitted_tool_names) if message.tool_calls else None,
            raw_response=response,
            latency=latency,
        )
    
    async def chat_stream(
        self,
        messages: list[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop: Optional[list[str]] = None,
        **kwargs
    ) -> AsyncIterator[str]:
        client = self._get_client()
        
        request_params = {
            "model": self.config.model_name,
            "messages": _prepare_messages_for_request(messages, self.config.model_name),
            "temperature": temperature or self.config.temperature,
            "max_tokens": max_tokens or self.config.max_tokens,
            "stream": True,
        }
        
        if stop:
            request_params["stop"] = stop
        
        request_params.update(kwargs)
        
        response = await client.chat.completions.create(**request_params)
        
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


class AnthropicClient(BaseLLMClient):
    """Anthropic API Client"""

    # The Messages API rejects non-streaming requests whose output could take
    # longer than ~10 minutes ("Streaming is required..."). Above this output
    # cap we transparently switch chat() to streaming and accumulate the final
    # message, so large caps (Opus 128k, Sonnet 64k) are safely usable.
    STREAMING_MAX_TOKENS_THRESHOLD = 8192

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self._client = None

    def _should_stream(self, max_tokens: int) -> bool:
        """True when the requested output size warrants the streaming path."""
        return bool(max_tokens) and max_tokens > self.STREAMING_MAX_TOKENS_THRESHOLD

    def _parse_response(self, response, latency: float) -> LLMResponse:
        """Build an LLMResponse from an Anthropic Message.

        Works for both ``messages.create()`` and the streaming
        ``get_final_message()`` result, which share the same shape.
        """
        content = ""
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                content += block.text
            elif block.type == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "type": "function",
                    "function": {
                        "name": block.name,
                        "arguments": json.dumps(block.input),
                    }
                })

        return LLMResponse(
            content=content,
            model=response.model,
            finish_reason=response.stop_reason or "stop",
            usage={
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
            },
            tool_calls=tool_calls if tool_calls else None,
            raw_response=response,
            latency=latency,
        )
    
    def _get_client(self):
        """Lazy initialization of Anthropic client"""
        if self._client is None:
            try:
                from anthropic import AsyncAnthropic
            except ImportError:
                raise ImportError("Please install anthropic: pip install anthropic")
            
            client_kwargs = dict(
                api_key=self.config.api_key or os.getenv("ANTHROPIC_API_KEY"),
                timeout=self.config.timeout,
            )
            # Allow pointing at an Anthropic-compatible gateway.
            if self.config.api_base:
                client_kwargs["base_url"] = self.config.api_base
            self._client = AsyncAnthropic(**client_kwargs)
        return self._client

    @staticmethod
    def _apply_prompt_caching(request_params: dict) -> None:
        """Attach an ephemeral ``cache_control`` breakpoint to the stable system prompt.

        Anthropic bills a cached prefix at ~10% of fresh input, and the engine sends a
        large CONSTANT system prompt (per role, every turn) — so one breakpoint on
        ``system`` (which caches the tools+system prefix, in canonical request order)
        turns most of the per-turn input cost into a cache_read after the first call.

        ANTHROPIC-NATIVE ONLY, and that is the point: the OpenAI-compat wrapper silently
        DROPS ``cache_control`` for opus (proven inert — constant token count, no
        cache_read), which is why the engine must talk the messages API directly. Verified
        live on claude-opus-4-7: call 1 cache_creation=34303/read=0, call 2 read=34303.

        Gated by ENVGEN_ANTHROPIC_CACHE (default on); a no-op when there is no system
        prompt or a breakpoint is already present. Sub-minimum prefixes (<1024 tok for
        opus) are simply not cached by the API — safe to always mark."""
        if os.getenv("ENVGEN_ANTHROPIC_CACHE", "1").strip().lower() in ("0", "false", "no", "off"):
            return
        sysv = request_params.get("system")
        if isinstance(sysv, str):
            if sysv.strip():
                request_params["system"] = [{
                    "type": "text",
                    "text": sysv,
                    "cache_control": {"type": "ephemeral"},
                }]
        elif isinstance(sysv, list) and sysv:
            if not any(isinstance(b, dict) and b.get("cache_control") for b in sysv):
                for b in reversed(sysv):
                    if isinstance(b, dict) and b.get("type") == "text":
                        b["cache_control"] = {"type": "ephemeral"}
                        break

    @staticmethod
    def _convert_content_to_anthropic(content):
        """Convert OpenAI-style message content into Anthropic content blocks.

        Plain strings pass through unchanged. Multimodal lists map
        ``{"type": "image_url", "image_url": {"url": ...}}`` parts into
        Anthropic image blocks: ``data:`` URIs become a base64 source,
        http(s) URLs become a url source.
        """
        if not isinstance(content, list):
            return content

        blocks = []
        for part in content:
            if not isinstance(part, dict):
                blocks.append({"type": "text", "text": str(part)})
                continue

            ptype = part.get("type")
            if ptype == "text":
                blocks.append({"type": "text", "text": part.get("text", "")})
            elif ptype == "image_url":
                url = (part.get("image_url") or {}).get("url", "")
                if url.startswith("data:"):
                    header, _, data = url.partition(",")
                    # header looks like "data:image/png;base64"
                    media_type = header[len("data:"):].split(";")[0] or "image/png"
                    # The data-URI header frequently LIES (a .jpg staged as image/png):
                    # Anthropic 400s on the mismatch ("appears to be a image/jpeg") and the
                    # whole vision call is lost — 20+ reference decodes dropped on a Netflix
                    # run. Trust the BYTES: sniff the magic number from the base64 head.
                    try:
                        import base64 as _b64
                        head = _b64.b64decode(data[:24])[:12] if data else b""
                        if head[:3] == b"\xff\xd8\xff":
                            media_type = "image/jpeg"
                        elif head[:8] == b"\x89PNG\r\n\x1a\n":
                            media_type = "image/png"
                        elif head[:6] in (b"GIF87a", b"GIF89a"):
                            media_type = "image/gif"
                        elif head[:4] == b"RIFF" and head[8:12] == b"WEBP":
                            media_type = "image/webp"
                    except Exception:
                        pass
                    blocks.append({
                        "type": "image",
                        "source": {"type": "base64",
                                    "media_type": media_type,
                                    "data": data},
                    })
                elif url:
                    blocks.append({
                        "type": "image",
                        "source": {"type": "url", "url": url},
                    })
            elif ptype == "image":
                # Already in Anthropic format.
                blocks.append(part)
            elif part.get("text") is not None:
                blocks.append({"type": "text", "text": part["text"]})

        return blocks

    def _convert_messages_to_anthropic(self, messages: list[Message]):
        """Split out the system prompt and convert the rest to Anthropic format.

        Unlike OpenAI, Anthropic does not accept a ``tool`` role or OpenAI-style
        ``tool_calls`` on assistant messages, and it requires strictly
        alternating user/assistant turns. So we:
          - collect all system messages into one system string;
          - turn ``role="tool"`` results into a ``user`` turn carrying a
            ``tool_result`` block (keyed by ``tool_call_id`` -> ``tool_use_id``);
          - turn assistant ``tool_calls`` into ``tool_use`` content blocks;
          - merge consecutive same-role turns into one (multiple text/blocks),
            which also collapses the many sequential stage prompts;
          - never emit an empty content list (Anthropic rejects it).

        Returns ``(system_content, chat_messages)``.
        """
        import json as _json
        system_parts: list[str] = []
        raw: list[dict] = []  # [{role, blocks}]

        for m in messages:
            if m.role == "system":
                txt = m.content if isinstance(m.content, str) else str(m.content or "")
                if txt:
                    system_parts.append(txt)
                continue

            if m.role == "tool":
                content = m.content
                if not isinstance(content, str):
                    content = self._convert_content_to_anthropic(content)
                raw.append({"role": "user", "blocks": [{
                    "type": "tool_result",
                    "tool_use_id": m.tool_call_id or "",
                    "content": content if content not in (None, "") else "(no output)",
                }]})
                continue

            # user / assistant text (+ assistant tool calls)
            blocks: list = []
            converted = self._convert_content_to_anthropic(m.content)
            if isinstance(converted, str):
                if converted.strip():
                    blocks.append({"type": "text", "text": converted})
            elif isinstance(converted, list):
                blocks.extend(converted)

            if m.role == "assistant" and m.tool_calls:
                for tc in m.tool_calls:
                    fn = (tc or {}).get("function") or {}
                    args = fn.get("arguments")
                    if isinstance(args, str):
                        try:
                            args = _json.loads(args) if args.strip() else {}
                        except Exception:
                            args = {"_raw": args}
                    if not isinstance(args, dict):
                        args = {}
                    blocks.append({
                        "type": "tool_use",
                        "id": (tc or {}).get("id") or fn.get("name", "tool"),
                        "name": fn.get("name", ""),
                        "input": args,
                    })

            raw.append({"role": m.role, "blocks": blocks})

        # Merge consecutive same-role turns (Anthropic requires alternation).
        merged: list[dict] = []
        for turn in raw:
            if merged and merged[-1]["role"] == turn["role"]:
                merged[-1]["blocks"].extend(turn["blocks"])
            else:
                merged.append({"role": turn["role"], "blocks": list(turn["blocks"])})

        chat_messages = []
        for turn in merged:
            blocks = turn["blocks"] or [{"type": "text", "text": "(no content)"}]
            if (
                len(blocks) == 1
                and isinstance(blocks[0], dict)
                and blocks[0].get("type") == "text"
            ):
                content = blocks[0].get("text", "")
            else:
                content = blocks
            chat_messages.append({"role": turn["role"], "content": content})

        return "\n\n".join(system_parts), chat_messages

    @staticmethod
    def _convert_tools_to_anthropic(tools: Optional[list[dict]]) -> Optional[list[dict]]:
        """Convert OpenAI-style tool schemas to Anthropic's tool format.

        OpenAI: ``{"type": "function", "function": {name, description, parameters}}``
        Anthropic: ``{name, description, input_schema}``. Tools already in
        Anthropic format (have ``input_schema``) pass through unchanged.
        """
        if not tools:
            return tools

        converted = []
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            # Already Anthropic-native.
            if "input_schema" in tool:
                converted.append(tool)
                continue
            fn = tool.get("function") if tool.get("type") == "function" else tool
            fn = fn or {}
            converted.append({
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
            })
        return converted

    async def chat(
        self,
        messages: list[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop: Optional[list[str]] = None,
        tools: Optional[list[dict]] = None,
        **kwargs
    ) -> LLMResponse:
        client = self._get_client()

        # Extract system message and convert content to Anthropic format
        # (maps OpenAI-style image_url parts to Anthropic image blocks).
        # NOTE: observation masking is OpenAI/Google-only — Anthropic deliberately
        # sends the FULL history and relies on the condenser + the 1M context window.
        system_content, chat_messages = self._convert_messages_to_anthropic(messages)

        request_params = {
            "model": self.config.model_name,
            "messages": chat_messages,
            "max_tokens": max_tokens or self.config.max_tokens,
        }
        # Newer Anthropic models reject `temperature` ("deprecated for this
        # model"). Only send it until we learn this model refuses it.
        if not getattr(self, "_omit_temperature", False):
            request_params["temperature"] = temperature if temperature is not None else self.config.temperature

        if system_content:
            request_params["system"] = system_content
        if stop:
            request_params["stop_sequences"] = stop
        if tools:
            request_params["tools"] = self._convert_tools_to_anthropic(tools)

        request_params.update(kwargs)
        self._apply_prompt_caching(request_params)

        effective_max_tokens = request_params.get("max_tokens")
        start_time = datetime.now()

        if self._should_stream(effective_max_tokens):
            # Large output: stream and accumulate the final message. This
            # avoids the non-streaming 10-minute "Streaming is required" error
            # while returning the same Message shape as create().
            async def _call():
                try:
                    async with client.messages.stream(**request_params) as stream:
                        return await stream.get_final_message()
                except Exception as e:
                    if self._handle_temperature_rejection(e, request_params):
                        async with client.messages.stream(**request_params) as stream:
                            return await stream.get_final_message()
                    raise
        else:
            async def _call():
                try:
                    return await client.messages.create(**request_params)
                except Exception as e:
                    if self._handle_temperature_rejection(e, request_params):
                        return await client.messages.create(**request_params)
                    raise

        response = await self._retry_with_backoff(_call)
        latency = (datetime.now() - start_time).total_seconds()

        return self._parse_response(response, latency)

    async def chat_stream(
        self,
        messages: list[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop: Optional[list[str]] = None,
        **kwargs
    ) -> AsyncIterator[str]:
        client = self._get_client()

        # Extract system message and convert content to Anthropic format.
        system_content, chat_messages = self._convert_messages_to_anthropic(messages)

        request_params = {
            "model": self.config.model_name,
            "messages": chat_messages,
            "max_tokens": max_tokens or self.config.max_tokens,
            "stream": True,
        }
        if not getattr(self, "_omit_temperature", False):
            request_params["temperature"] = temperature if temperature is not None else self.config.temperature

        if system_content:
            request_params["system"] = system_content
        if stop:
            request_params["stop_sequences"] = stop

        request_params.update(kwargs)
        self._apply_prompt_caching(request_params)

        async with client.messages.stream(**request_params) as stream:
            async for text in stream.text_stream:
                yield text

    def _handle_temperature_rejection(self, error: Exception, request_params: dict) -> bool:
        """If *error* is Anthropic's "`temperature` is deprecated for this model"
        400, drop the param from *request_params*, remember it for this client,
        and return True so the caller can retry. Returns False otherwise.
        """
        if getattr(self, "_omit_temperature", False) and "temperature" not in request_params:
            return False
        msg = str(error).lower()
        if "temperature" in msg and ("deprecated" in msg or "not support" in msg or "unsupported" in msg or "invalid_request" in msg):
            if "temperature" in request_params:
                request_params.pop("temperature", None)
                self._omit_temperature = True
                self._logger.warning(
                    "Anthropic model rejected `temperature`; retrying without it "
                    "and omitting it for subsequent calls on this client."
                )
                return True
        return False


class LocalLLMClient(BaseLLMClient):
    """
    Local LLM Client (Ollama, vLLM, etc.)
    
    Uses OpenAI-compatible API format
    """
    
    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self._client = None
    
    def _get_client(self):
        """Lazy initialization using httpx"""
        if self._client is None:
            try:
                import httpx
            except ImportError:
                raise ImportError("Please install httpx: pip install httpx")
            
            self._client = httpx.AsyncClient(
                base_url=self.config.api_base or "http://localhost:11434",
                timeout=self.config.timeout,
            )
        return self._client
    
    async def chat(
        self,
        messages: list[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop: Optional[list[str]] = None,
        **kwargs
    ) -> LLMResponse:
        client = self._get_client()
        
        # Ollama format
        request_data = {
            "model": self.config.model_name,
            "messages": _prepare_messages_for_request(messages, self.config.model_name),
            "stream": False,
            "options": {
                "temperature": temperature or self.config.temperature,
                "num_predict": max_tokens or self.config.max_tokens,
            }
        }
        
        if stop:
            request_data["options"]["stop"] = stop
        
        start_time = datetime.now()
        
        response = await client.post("/api/chat", json=request_data)
        response.raise_for_status()
        data = response.json()
        
        latency = (datetime.now() - start_time).total_seconds()
        
        return LLMResponse(
            content=data.get("message", {}).get("content", ""),
            model=data.get("model", self.config.model_name),
            finish_reason="stop",
            usage={
                "prompt_tokens": data.get("prompt_eval_count", 0),
                "completion_tokens": data.get("eval_count", 0),
                "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
            },
            raw_response=data,
            latency=latency,
        )
    
    async def chat_stream(
        self,
        messages: list[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop: Optional[list[str]] = None,
        **kwargs
    ) -> AsyncIterator[str]:
        client = self._get_client()
        
        request_data = {
            "model": self.config.model_name,
            "messages": _prepare_messages_for_request(messages, self.config.model_name),
            "stream": True,
            "options": {
                "temperature": temperature or self.config.temperature,
                "num_predict": max_tokens or self.config.max_tokens,
            }
        }
        
        if stop:
            request_data["options"]["stop"] = stop
        
        async with client.stream("POST", "/api/chat", json=request_data) as response:
            async for line in response.aiter_lines():
                if line:
                    data = json.loads(line)
                    if "message" in data and "content" in data["message"]:
                        yield data["message"]["content"]


class GoogleClient(BaseLLMClient):
    """
    Google Gemini Client
    
    Uses the native google-generativeai SDK for full Gemini 3 support
    including automatic thought_signature handling for function calls.
    Set GOOGLE_API_KEY or GEMINI_API_KEY environment variable.
    
    Install: pip install google-generativeai
    """
    
    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self._client = None
        self._model = None
    
    def _get_client(self):
        """Lazy initialization of Google GenAI client"""
        if self._client is None:
            try:
                from google import genai
                from google.genai import types
            except ImportError:
                raise ImportError("Please install google-generativeai: pip install google-generativeai")
            
            api_key = self.config.api_key or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
            if not api_key:
                raise ValueError("Google API key not found. Set GOOGLE_API_KEY or GEMINI_API_KEY environment variable.")

            # A REQUEST TIMEOUT is mandatory: without http_options the SDK call can
            # hang forever on a wedged connection — the whole multi-agent run froze
            # mid-kickoff on one such call ("Attempt 1/3 starting..." with no
            # response, instagram 2026-06-09 23:18). With a timeout the call raises
            # and the retry layer (3 attempts) recovers in minutes instead of never.
            timeout_ms = int(float(self.config.timeout or 240) * 1000)
            try:
                self._client = genai.Client(
                    api_key=api_key,
                    http_options=types.HttpOptions(timeout=timeout_ms),
                )
            except Exception:
                # Older google-genai without HttpOptions(timeout=...) — degrade to
                # the untimed client rather than fail construction.
                self._client = genai.Client(api_key=api_key)
            self._types = types
        return self._client
    
    def _convert_openai_tools_to_google(self, tools: list[dict]) -> list:
        """Convert OpenAI-style tool definitions to Google format"""
        from google.genai import types
        
        def convert_schema(schema: dict) -> types.Schema:
            """Recursively convert JSON schema to Google Schema"""
            if not schema:
                return types.Schema(type="STRING")
            
            # Handle type - can be string or list (e.g., ["string", "null"] for nullable)
            raw_type = schema.get("type", "string")
            if isinstance(raw_type, list):
                # Take the first non-null type
                schema_type = next((t for t in raw_type if t != "null"), "string").upper()
            else:
                schema_type = raw_type.upper()
            type_map = {
                "STRING": "STRING",
                "NUMBER": "NUMBER", 
                "INTEGER": "INTEGER",
                "BOOLEAN": "BOOLEAN",
                "ARRAY": "ARRAY",
                "OBJECT": "OBJECT",
            }
            google_type = type_map.get(schema_type, "STRING")
            
            kwargs = {
                "type": google_type,
                "description": schema.get("description", ""),
            }
            
            # Handle enum
            if "enum" in schema:
                kwargs["enum"] = schema["enum"]
            
            # Handle array items - Google requires this for ARRAY type
            if google_type == "ARRAY":
                items = schema.get("items", {"type": "string"})
                kwargs["items"] = convert_schema(items)
            
            # Handle object properties
            if google_type == "OBJECT" and "properties" in schema:
                props = schema.get("properties", {})
                kwargs["properties"] = {
                    k: convert_schema(v) for k, v in props.items()
                }
                if "required" in schema:
                    kwargs["required"] = schema["required"]
            
            return types.Schema(**kwargs)
        
        google_tools = []
        function_declarations = []
        
        for tool in tools:
            if tool.get("type") == "function":
                func = tool.get("function", {})
                params = func.get("parameters", {})
                
                # Convert parameters schema
                param_schema = None
                if params and params.get("properties"):
                    param_schema = convert_schema(params)
                
                function_declarations.append(
                    types.FunctionDeclaration(
                        name=func.get("name", ""),
                        description=func.get("description", ""),
                        parameters=param_schema,
                    )
                )
        
        # Google prefers all functions in a single Tool
        if function_declarations:
            google_tools.append(types.Tool(function_declarations=function_declarations))
        
        return google_tools
    
    def _convert_messages_to_google(self, messages: list[Message]) -> tuple:
        """Convert OpenAI-style messages to Google format
        
        Returns: (system_instruction, contents)
        """
        from google.genai import types

        # NOTE: observation masking is applied ONCE by the callers (chat/chat_stream)
        # before they hand messages here. Masking again at this layer double-trimmed
        # every call; the redundant call was removed (user 2026-06-24).
        system_instruction = None
        contents = []

        # Gemini pairs function_call<->function_response BY NAME (unlike OpenAI's
        # tool_call_id and Anthropic's tool_use_id, which pair by id). Our Message
        # tool results only carry `tool_call_id`, never `.name`, so every result
        # used to be sent named "tool" -> name mismatch on every turn ->
        # MALFORMED_FUNCTION_CALL and the model echoing literal tokens like
        # `tool_error`/`get_skill` as tool names (youtube run). Build a
        # {tool_call_id: function_name} map from the assistant tool_calls so each
        # response is paired with the REAL function name of its originating call.
        tool_call_names: dict[str, str] = {}
        for msg in messages:
            if getattr(msg, "role", "") != "assistant" or not msg.tool_calls:
                continue
            for tc in msg.tool_calls:
                if hasattr(tc, "function"):
                    tc_id = getattr(tc, "id", None)
                    fn_name = getattr(tc.function, "name", None)
                elif isinstance(tc, dict):
                    tc_id = tc.get("id")
                    fn_name = (tc.get("function") or {}).get("name")
                else:
                    tc_id = fn_name = None
                if tc_id and fn_name:
                    tool_call_names[tc_id] = fn_name

        for msg in messages:
            if msg.role == "system":
                system_instruction = msg.content if isinstance(msg.content, str) else str(msg.content)
            elif msg.role == "user":
                if isinstance(msg.content, list):
                    # Multimodal content
                    parts = []
                    for part in msg.content:
                        if part.get("type") == "text":
                            parts.append(types.Part.from_text(text=part.get("text", "")))
                        elif part.get("type") == "image_url":
                            # Handle base64 images
                            url = part.get("image_url", {}).get("url", "")
                            if url.startswith("data:"):
                                # Extract base64 data
                                import base64
                                # Format: data:image/png;base64,<data>
                                header, data = url.split(",", 1)
                                mime_type = header.split(":")[1].split(";")[0]
                                parts.append(types.Part.from_bytes(
                                    data=base64.b64decode(data),
                                    mime_type=mime_type
                                ))
                    contents.append(types.Content(role="user", parts=parts))
                else:
                    contents.append(types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=msg.content or "")]
                    ))
            elif msg.role == "assistant":
                parts = []
                if msg.content:
                    parts.append(types.Part.from_text(text=msg.content))
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        if hasattr(tc, 'function'):
                            func = tc.function
                            args = json.loads(func.arguments) if isinstance(func.arguments, str) else func.arguments
                            thought_sig = getattr(tc, 'thought_signature', None)
                            if thought_sig:
                                # Create Part with thought_signature for Gemini 3
                                parts.append(types.Part(
                                    function_call=types.FunctionCall(name=func.name, args=args),
                                    thought_signature=thought_sig
                                ))
                            else:
                                parts.append(types.Part.from_function_call(
                                    name=func.name,
                                    args=args
                                ))
                        elif isinstance(tc, dict):
                            func = tc.get("function", {})
                            args = func.get("arguments", {})
                            if isinstance(args, str):
                                args = json.loads(args)
                            thought_sig = tc.get("thought_signature")
                            if thought_sig:
                                # Create Part with thought_signature for Gemini 3
                                parts.append(types.Part(
                                    function_call=types.FunctionCall(name=func.get("name", ""), args=args),
                                    thought_signature=thought_sig
                                ))
                            else:
                                parts.append(types.Part.from_function_call(
                                    name=func.get("name", ""),
                                    args=args
                                ))
                if parts:
                    contents.append(types.Content(role="model", parts=parts))
            elif msg.role == "tool":
                # Tool response: pair with the REAL originating function name so
                # Gemini's name-based call<->response matching succeeds. Prefer the
                # name resolved from this turn's tool_calls (by tool_call_id), then
                # any explicit msg.name, falling back to "tool" only if truly unknown.
                resolved_name = (
                    tool_call_names.get(msg.tool_call_id)
                    or msg.name
                    or "tool"
                )
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part.from_function_response(
                        name=resolved_name,
                        response={"result": msg.content}
                    )]
                ))
        
        return system_instruction, contents
    
    async def chat(
        self,
        messages: list[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop: Optional[list[str]] = None,
        functions: Optional[list[dict]] = None,
        tools: Optional[list[dict]] = None,
        tool_choice: Optional[str] = None,
        **kwargs
    ) -> LLMResponse:
        """Send chat request to Gemini using native SDK"""
        client = self._get_client()
        from google.genai import types
        
        # Always sanitize outgoing content
        safe_messages: list[Message] = [
            Message(role=m.role, content=_sanitize_message_content(m.content), name=m.name, function_call=m.function_call, tool_calls=m.tool_calls, tool_call_id=m.tool_call_id)
            for m in _drop_orphan_tool_results(
                _mask_old_observations(messages, self.config.model_name))
        ]
        
        # Convert messages to Google format
        system_instruction, contents = self._convert_messages_to_google(safe_messages)
        
        # Convert tools if provided
        google_tools = None
        if tools:
            google_tools = self._convert_openai_tools_to_google(tools)
        elif functions:
            google_tools = self._convert_openai_tools_to_google([{"type": "function", "function": f} for f in functions])
        
        # Build generation config
        # Mutable retry state: consecutive MALFORMED on the SAME logical call
        # lowers the temperature on the re-roll. Measured (2026-06-11
        # controlled trials): gemini-3.1-preview has a stochastic baseline
        # MALFORMED_FUNCTION_CALL rate even on tiny calls — identical re-rolls
        # can sit in the same failure pocket; perturbing the sampling breaks
        # the streak cheaply.
        _retry_state = {"malformed": 0}

        def _make_gen_config():
            _temp = temperature if temperature is not None else self.config.temperature
            if _retry_state["malformed"]:
                _temp = max(0.1, (_temp or 0.7) * (0.5 ** _retry_state["malformed"]))
            cfg = types.GenerateContentConfig(
                temperature=_temp,
                max_output_tokens=max_tokens if max_tokens is not None else self.config.max_tokens,
                system_instruction=system_instruction,
                tools=google_tools,
            )
            # FIX #88 (instagram run-8, live): a NO-TOOLS single-shot call still came back
            # finish=tool_calls on the -customtools variant (the model hallucinated a tool
            # call; 20 completion tokens instead of the requested JSON) → the caller's JSON
            # parse silently failed. JSON mode (response_mime_type='application/json')
            # makes tool-call emission impossible and guarantees parseable text.
            if kwargs.get("response_mime_type"):
                try:
                    cfg.response_mime_type = str(kwargs["response_mime_type"])
                except Exception:
                    pass
            # MALFORMED_FUNCTION_CALL mitigation (google-genai 1.61 + gemini-3.x):
            # ask Gemini to VALIDATE generated tool calls against the declared
            # schema. MALFORMED stems from the model emitting tool-call codegen that
            # doesn't parse; VALIDATED mode constrains it to the schema and sharply
            # cuts the malformed rate — a source-level fix vs. our re-roll
            # perturbation (which only breaks streaks after the fact). Self-disables
            # for the session if the model/tool-surface ever rejects it (see
            # _do_call). Toggle via ENVGEN_GEMINI_VALIDATED_FC=0.
            # FIX #92: tool_choice='required'/'any' forces a function call (Gemini
            # mode=ANY) — the single-shot enrich delivers its doc AS the forced call
            # (the -customtools variant resists no-tools long-form output: 11-20
            # completion tokens on a 9k-token prompt, run-8/run-12 live).
            if google_tools and str(tool_choice or "").lower() in ("required", "any"):
                try:
                    cfg.tool_config = types.ToolConfig(
                        function_calling_config=types.FunctionCallingConfig(
                            mode=types.FunctionCallingConfigMode.ANY))
                except Exception:
                    pass
            elif (google_tools
                    and not getattr(self, "_validated_fc_disabled", False)
                    and os.environ.get("ENVGEN_GEMINI_VALIDATED_FC", "1").lower()
                        not in ("0", "false", "no", "off")):
                try:
                    cfg.tool_config = types.ToolConfig(
                        function_calling_config=types.FunctionCallingConfig(
                            mode=types.FunctionCallingConfigMode.VALIDATED))
                except Exception:
                    pass  # older SDK without VALIDATED → skip silently
            elif (not google_tools
                    and os.environ.get("ENVGEN_GEMINI_FC_NONE", "1").lower()
                        not in ("0", "false", "no", "off")):
                # FIX #140 (log-mining runs 50-62): EVERY run's first ~90s hit a
                # deterministic 9-18-retry MALFORMED_FUNCTION_CALL cluster on
                # tools=0 requests (13/13 runs; kickoff roadmap/spec authoring,
                # ~40k-char prompts) — the -customtools variant attempts tool-call
                # codegen even with NO declared tools, and the re-roll retries the
                # same doomed prompt. mode=NONE tells Gemini function calling is
                # unavailable for this request → plain-text output, no codegen.
                try:
                    cfg.tool_config = types.ToolConfig(
                        function_calling_config=types.FunctionCallingConfig(
                            mode=types.FunctionCallingConfigMode.NONE))
                except Exception:
                    pass  # older SDK without NONE → skip silently
            # OBSERVABILITY: surface Gemini's thinking (it's a thinking model and
            # reasons regardless; include_thoughts just RETURNS the summary). Lets us
            # see WHY an agent did something (e.g. called run_validation early) instead
            # of a black box. Captured + logged separately from response content/tool
            # args (see the part loop). Toggle via ENVGEN_GEMINI_INCLUDE_THOUGHTS=0.
            if os.environ.get("ENVGEN_GEMINI_INCLUDE_THOUGHTS", "1").lower() not in ("0", "false", "no", "off"):
                try:
                    cfg.thinking_config = types.ThinkingConfig(include_thoughts=True)
                except Exception:
                    pass
            if stop:
                cfg.stop_sequences = stop
            return cfg

        gen_config = _make_gen_config()
        
        start_time = datetime.now()
        
        # Log request info
        msg_count = len(safe_messages)
        total_content_len = sum(len(str(m.content or "")) for m in safe_messages)
        tool_count = len(tools) if tools else 0
        self._logger.info(f"[LLM Request] model={self.config.model_name}, messages={msg_count}, content_chars={total_content_len}, tools={tool_count}")
        
        async def _call_with_progress():
            """Wrapper that logs progress during long waits"""
            warn_interval = 60
            call_start = datetime.now()
            
            def _effective_contents():
                # FIX #187: after 2 malformed re-rolls the temperature ladder alone
                # is replaying the same doomed payload — MALFORMED storms correlate
                # with huge multimodal contexts, so drop all but the newest inline
                # image(s) from the RETRY payload (originals untouched).
                if _retry_state["malformed"] >= 2:
                    try:
                        _keep = max(0, int(os.environ.get(
                            "ENVGEN_MALFORMED_IMAGE_KEEP") or 1))
                    except Exception:
                        _keep = 1
                    _pruned, _n = _prune_stale_images_for_reroll(
                        contents, _keep, lambda t: types.Part.from_text(text=t))
                    if _n:
                        self._logger.warning(
                            f"[LLM] MALFORMED re-roll {_retry_state['malformed']}: "
                            f"pruned {_n} stale inline image(s) from the retry payload")
                        return _pruned
                return contents

            def _do_call():
                try:
                    return client.models.generate_content(
                        model=self.config.model_name,
                        contents=_effective_contents(),
                        config=_make_gen_config(),
                    )
                except Exception as _e:
                    # If the model/tool-surface rejects the VALIDATED function-calling
                    # config, disable it for this client and retry once WITHOUT it, so
                    # the MALFORMED mitigation can never wedge a run.
                    _m = str(_e).lower()
                    if (not getattr(self, "_validated_fc_disabled", False)
                            and ("function_calling_config" in _m or "tool_config" in _m
                                 or "validated" in _m or "function calling mode" in _m)):
                        self._validated_fc_disabled = True
                        self._logger.warning(
                            "Gemini rejected VALIDATED function-calling config (%s); "
                            "disabling it for this client and retrying without it.", str(_e)[:120])
                        return client.models.generate_content(
                            model=self.config.model_name,
                            contents=_effective_contents(),
                            config=_make_gen_config(),
                        )
                    raise
            
            # Run sync call in thread pool
            task = asyncio.get_event_loop().run_in_executor(None, _do_call)

            # HARD total timeout: the loop used to warn forever and never give up, so
            # one wedged SDK call (sync, in the executor) hung the whole run until an
            # external kill (instagram M2 froze twice on exactly this: "Attempt 1/3
            # starting..." then silence). Past config.timeout, stop awaiting and raise
            # — the retry layer takes over. The executor thread itself can't be
            # cancelled, but it is abandoned and the run moves on.
            # FIX #187: capped — config.timeout defaults to 1800s, which let one
            # wedged SDK call hold a lane 30min (looked like a dead run, §3-3).
            hard_timeout = _llm_hard_timeout(
                getattr(self.config, "timeout", None), os.environ)
            while True:
                try:
                    return await asyncio.wait_for(asyncio.shield(task), timeout=warn_interval)
                except asyncio.TimeoutError:
                    elapsed = (datetime.now() - call_start).total_seconds()
                    if task.done():
                        return task.result()
                    if elapsed >= hard_timeout:
                        self._logger.warning(
                            f"[LLM] Call exceeded hard timeout ({hard_timeout:.0f}s) — abandoning for retry")
                        raise TimeoutError(f"LLM call exceeded {hard_timeout:.0f}s")
                    self._logger.warning(f"[LLM] Still waiting for API response... elapsed={elapsed:.0f}s")
                    continue
        
        async def _call():
            resp = await _call_with_progress()
            # MALFORMED_FUNCTION_CALL is a transient GENERATION failure (gemini
            # emitted an unparsable tool call): the response carries no usable
            # tool_calls and often no text, so surfacing it as a normal turn
            # makes the agent silently drop its intended action (instagram run
            # 2026-06-10: frontend "completed" its kickoff with zero tool calls
            # — 6 malformed responses in one run). Raise so the retry layer
            # re-rolls the generation instead.
            try:
                _fr = str(resp.candidates[0].finish_reason) if resp.candidates else ""
            except Exception:
                _fr = ""
            if "MALFORMED" in _fr:  # MALFORMED_FUNCTION_CALL / MALFORMED_RESPONSE
                _retry_state["malformed"] += 1
                raise RuntimeError(
                    f"gemini returned {_fr.split('.')[-1]} — retrying generation "
                    f"(re-roll {_retry_state['malformed']}, temperature lowered)")
            return resp
        
        response = await self._retry_with_backoff(_call)
        latency = (datetime.now() - start_time).total_seconds()
        
        # Extract content and tool calls from response
        content = ""
        tool_calls = []
        finish_reason = "stop"
        thinking = ""

        if response.candidates:
            candidate = response.candidates[0]
            finish_reason = str(candidate.finish_reason) if candidate.finish_reason else "stop"

            # gemini-3.x can return candidate.content=None or parts=None (thinking
            # consumed the whole completion budget, or a safety stop). Iterating it
            # raised "'NoneType' object is not iterable", which burned all retries and
            # ABORTED a whole run mid-kickoff (instagram 2026-06-10 01:22, facilitator
            # + knowledge calls died in a row). Treat as an empty-content response.
            _parts = (candidate.content.parts
                      if (candidate.content is not None
                          and candidate.content.parts is not None) else [])
            for part in _parts:
                if getattr(part, 'thought', False):
                    # Gemini thinking summary — capture for visibility; NEVER fold it
                    # into response content or tool args (it would corrupt both).
                    thinking += getattr(part, 'text', '') or ''
                elif hasattr(part, 'text') and part.text:
                    content += part.text
                elif hasattr(part, 'function_call') and part.function_call:
                    fc = part.function_call
                    tc = {
                        "id": f"call_{len(tool_calls)}",
                        "type": "function",
                        "function": {
                            "name": fc.name,
                            "arguments": json.dumps(dict(fc.args)) if fc.args else "{}",
                        }
                    }
                    # Preserve thought_signature for Gemini 3 multi-turn function calling
                    if hasattr(part, 'thought_signature') and part.thought_signature:
                        tc["thought_signature"] = part.thought_signature
                    tool_calls.append(tc)
        
        # Get usage stats
        prompt_tokens = 0
        completion_tokens = 0
        cached_tokens = 0
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            prompt_tokens = getattr(response.usage_metadata, 'prompt_token_count', 0) or 0
            completion_tokens = getattr(response.usage_metadata, 'candidates_token_count', 0) or 0
            # gemini IMPLICIT caching (2.5+/3 auto-caches a stable prefix incl. the
            # system_instruction; the cached portion is billed ~4x cheaper). Capture +
            # log it so cache effectiveness is VISIBLE (it was silently dropped). A
            # cached_tokens that stays 0 every turn => no cache hits (the prefix isn't
            # stable) => consider EXPLICIT cached_content for the system prompt.
            cached_tokens = getattr(response.usage_metadata, 'cached_content_token_count', 0) or 0
        
        has_tool_calls = bool(tool_calls)
        if has_tool_calls:
            finish_reason = "tool_calls"

        # Surface the model's reasoning so it isn't a black box (e.g. WHY a tool
        # was chosen). Logged under the agent's own logger → greppable per-agent in
        # the run log, alongside the action it led to.
        _thinking = thinking.strip()
        if _thinking:
            self._logger.info(f"[LLM thinking] {_thinking[:1500]}")

        self._logger.info(f"[LLM Response] latency={latency:.1f}s, prompt_tokens={prompt_tokens}, cached_tokens={cached_tokens}, completion_tokens={completion_tokens}, tool_calls={has_tool_calls}, finish={finish_reason}")

        return LLMResponse(
            content=content,
            model=self.config.model_name,
            finish_reason=finish_reason,
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            tool_calls=tool_calls if tool_calls else None,
            raw_response=response,
            latency=latency,
            reasoning=_thinking or None,
        )
    
    async def chat_stream(
        self,
        messages: list[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop: Optional[list[str]] = None,
        **kwargs
    ) -> AsyncIterator[str]:
        """Stream chat response from Gemini"""
        client = self._get_client()
        from google.genai import types

        # Convert messages (mask ONCE here — _convert_messages_to_google no longer masks)
        system_instruction, contents = self._convert_messages_to_google(
            _mask_old_observations(messages, self.config.model_name)
        )

        gen_config = types.GenerateContentConfig(
            temperature=temperature or self.config.temperature,
            max_output_tokens=max_tokens or self.config.max_tokens,
            system_instruction=system_instruction,
        )
        
        if stop:
            gen_config.stop_sequences = stop
        
        def _stream():
            return client.models.generate_content_stream(
                model=self.config.model_name,
                contents=contents,
                config=gen_config,
            )
        
        # Run in thread pool since SDK is sync
        stream = await asyncio.get_event_loop().run_in_executor(None, _stream)
        
        for chunk in stream:
            if chunk.candidates:
                _c = chunk.candidates[0].content
                for part in (_c.parts if (_c is not None and _c.parts is not None) else []):
                    if hasattr(part, 'text') and part.text:
                        yield part.text


def _split_data_uri(url: str) -> Tuple[Optional[str], Optional[str]]:
    """Return (mime, base64_data) from a ``data:<mime>;base64,<data>`` URL, else (None, None)."""
    if not isinstance(url, str):
        return None, None
    m = re.match(r"data:([^;]+);base64,(.*)", url, re.DOTALL)
    if m:
        return m.group(1), m.group(2)
    return None, None


class MetagenClient(BaseLLMClient):
    """Meta MetaGen provider — wraps the ``metagen`` SDK's ``dialog_completion`` behind the
    engine's OpenAI-style ``chat`` contract (text + tools + vision + usage).

    The engine's ``tools`` are already OpenAI/Azure function schema, which is exactly what
    MetaGen's ``tools`` string expects for a 3P model (GPT/Claude/Gemini) — so use GPT-5.6
    (native structured tool calling). Llama/2P/OSS models silently drop ``tools``.

    ``metagen`` is a Meta-internal package imported LAZILY so this module still loads on hosts
    without it. SDK symbol names that vary across versions are resolved defensively; if the real
    SDK differs, the failure is localized here. Verify against
    ``fbcode/gen_ai/metagen/pymetagen/lib/metagen_platform.py``.
    """

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self._platform = None
        self._sdk_ns = None

    # --- SDK bootstrap ---------------------------------------------------
    def _sdk(self):
        """Resolve metagen SDK symbols. ``metagen`` is a lazy package: the dialog classes
        are bound only via ``from metagen import X`` (plain ``metagen.X`` attribute access
        raises), so import them explicitly (matching the SDK's documented usage) and cache
        them on a namespace. Optional/version-varying classes are resolved best-effort."""
        if self._sdk_ns is None:
            import types as _types
            import metagen.bento as _bento  # side effect: full package init (SDK's import order)
            ns = _types.SimpleNamespace(bento=_bento)
            from metagen import (Dialog, DialogMessage, DialogSource,
                                 DialogTextContent, MetaGenKey)
            ns.Dialog = Dialog
            ns.DialogMessage = DialogMessage
            ns.DialogSource = DialogSource
            ns.DialogTextContent = DialogTextContent
            ns.MetaGenKey = MetaGenKey
            for name in ("DialogAttachmentContent", "MessageAttachmentType",
                         "DialogToolResponseContent",
                         "DialogGenericToolCallRequestContentV2",
                         "DialogGenericToolCallRequestContent",
                         "DialogToolCallRequestContent"):
                try:  # `from metagen import <name>` semantics (bare getattr won't bind it)
                    setattr(ns, name, getattr(__import__("metagen", fromlist=[name]), name))
                except Exception:
                    setattr(ns, name, None)
            self._sdk_ns = ns
        return self._sdk_ns

    def _get_platform(self):
        if self._platform is None:
            sdk = self._sdk()
            key = self.config.api_key or os.environ.get("METAGEN_API_KEY")
            factory = os.environ.get("ENVGEN_METAGEN_FACTORY", "bento").lower()
            if factory == "devserver":
                tpf = getattr(__import__("metagen", fromlist=["thrift_platform_factory"]),
                              "thrift_platform_factory", None)
                if tpf is not None:
                    self._platform = tpf.create_for_current_unix_user_for_devserver_only(
                        metagen_auth_credential=sdk.MetaGenKey(key=key), auto_rate_limit=True)
                    return self._platform
            self._platform = sdk.bento.create_metagen_platform(sdk.MetaGenKey(key=key))
        return self._platform

    # --- request conversion ---------------------------------------------
    def _source(self, mg, role: str):
        DS = mg.DialogSource
        mapping = {"system": "SYSTEM", "user": "USER", "assistant": "ASSISTANT",
                   "developer": "DEVELOPER", "tool": "IPYTHON", "function": "IPYTHON"}
        return getattr(DS, mapping.get(role, "USER"), getattr(DS, "USER"))

    def _attachment(self, mg, url: str):
        mime, b64 = _split_data_uri(url)
        if not b64:
            return None
        Att = getattr(mg, "DialogAttachmentContent", None)
        MAT = getattr(mg, "MessageAttachmentType", None)
        if Att is None or MAT is None:
            return None
        atype = getattr(MAT, "BASE64", None) or getattr(MAT, "BASE64_IMAGE", None)
        for kw in ({"data": b64, "type": atype, "mime": mime or "image/png"},
                   {"data": b64, "type": atype, "mime_type": mime or "image/png"}):
            try:
                return Att(**kw)
            except Exception:
                continue
        return None

    @staticmethod
    def _tc_name_args(tc) -> Tuple[str, str]:
        if isinstance(tc, dict):
            fn = tc.get("function") or {}
            args = fn.get("arguments")
            return (fn.get("name") or tc.get("name") or "",
                    args if isinstance(args, str) else json.dumps(args or {}))
        fn = getattr(tc, "function", None)
        name = getattr(fn, "name", "") if fn else getattr(tc, "name", "")
        args = getattr(fn, "arguments", "{}") if fn else "{}"
        return name, args if isinstance(args, str) else json.dumps(args or {})

    def _tool_call_content(self, mg, name: str, args_string: str):
        for cls in ("DialogGenericToolCallRequestContentV2",
                    "DialogGenericToolCallRequestContent", "DialogToolCallRequestContent"):
            C = getattr(mg, cls, None)
            if C is None:
                continue
            for kw in ({"name": name, "parameters_string": args_string},
                       {"name": name, "parameters": args_string}):
                try:
                    return C(**kw)
                except Exception:
                    continue
        return None

    def _tool_response_content(self, mg, message: "Message") -> list:
        body = (message.content if isinstance(message.content, str)
                else json.dumps(message.content) if message.content is not None else "")
        name = message.name or message.tool_call_id or "tool"
        C = getattr(mg, "DialogToolResponseContent", None)
        if C is not None:
            for kw in ({"toolName": name, "toolData": body},
                       {"tool_name": name, "tool_data": body}, {"name": name, "body": body}):
                try:
                    return [C(**kw)]
                except Exception:
                    continue
        return [mg.DialogTextContent(text=f"[tool result {name}] {body}")]

    def _contents_for(self, mg, message: "Message") -> list:
        contents = []
        c = message.content
        if isinstance(c, str):
            if c:
                contents.append(mg.DialogTextContent(text=c))
        elif isinstance(c, list):
            for part in c:
                if not isinstance(part, dict):
                    contents.append(mg.DialogTextContent(text=str(part)))
                    continue
                if part.get("type") == "text":
                    contents.append(mg.DialogTextContent(text=part.get("text", "")))
                elif part.get("type") == "image_url":
                    url = (part.get("image_url") or {}).get("url", "")
                    att = self._attachment(mg, url)
                    contents.append(att if att is not None else
                                    mg.DialogTextContent(text="[image omitted: metagen attachment unsupported]"))
        if message.tool_calls:
            for tc in message.tool_calls:
                name, args = self._tc_name_args(tc)
                rc = self._tool_call_content(mg, name, args)
                contents.append(rc if rc is not None else
                                mg.DialogTextContent(text=f"[assistant tool_call] {name}({args})"))
        if not contents:
            contents.append(mg.DialogTextContent(text=""))
        return contents

    def _convert_messages(self, mg, messages: list) -> list:
        dmsgs = []
        for m in messages:
            role = getattr(m, "role", "user")
            if role == "tool":
                dmsgs.append(mg.DialogMessage(source=self._source(mg, "tool"),
                                              contents=self._tool_response_content(mg, m)))
            else:
                dmsgs.append(mg.DialogMessage(source=self._source(mg, role),
                                              contents=self._contents_for(mg, m)))
        return dmsgs

    @staticmethod
    def _tool_config(tool_choice):
        if not tool_choice:
            return None
        if tool_choice in ("required", "any"):
            return {"tool_choice": "required"}
        if tool_choice == "auto":
            return {"tool_choice": "auto"}
        if isinstance(tool_choice, dict):
            return {"tool_choice": "required", "tool_choice_name": tool_choice}
        return None

    @staticmethod
    def _guided_schema(kwargs) -> Optional[str]:
        if kwargs.get("response_mime_type") == "application/json":
            sch = kwargs.get("response_schema")
            if sch:
                return sch if isinstance(sch, str) else json.dumps(sch)
        return None

    # --- response parsing ------------------------------------------------
    @staticmethod
    def _norm_finish(finish) -> str:
        s = str(finish or "").upper()
        if "MAX_OUTPUT" in s or "LENGTH" in s:
            return "length"
        return "stop"

    def _parse_response(self, resp) -> Tuple[str, list, str, dict, Optional[str]]:
        text_parts, reasoning_parts, tool_calls = [], [], []
        choices = getattr(resp, "choices", None) or []
        finish = None
        if choices:
            ch = choices[0]
            finish = getattr(ch, "finish_reason", None)
            dialog = getattr(ch, "dialog", None)
            for msg in (getattr(dialog, "messages", None) or []):
                for c in (getattr(msg, "contents", None) or []):
                    nm = getattr(c, "name", None)
                    ps = getattr(c, "parameters_string", None)
                    if ps is None and hasattr(c, "getParametersString"):
                        try:
                            ps = c.getParametersString()
                        except Exception:
                            ps = None
                    if nm is None and hasattr(c, "getName"):
                        try:
                            nm = c.getName()
                        except Exception:
                            nm = None
                    if nm is not None and ps is not None:
                        tool_calls.append({"id": f"call_{len(tool_calls)}", "type": "function",
                                           "function": {"name": nm,
                                                        "arguments": ps if isinstance(ps, str) else json.dumps(ps)}})
                        continue
                    txt = getattr(c, "text", None)
                    if isinstance(txt, str):
                        (reasoning_parts if "Reasoning" in type(c).__name__ else text_parts).append(txt)
        u = getattr(resp, "usage", None)
        usage = {}
        if u is not None:
            pt = getattr(u, "num_prompt_tokens", None) or 0
            ctk = getattr(u, "num_completion_tokens", None) or 0
            tt = getattr(u, "num_total_tokens", None)
            usage = {"prompt_tokens": pt, "completion_tokens": ctk,
                     "total_tokens": tt if tt is not None else pt + ctk}
        fr = "tool_calls" if tool_calls else self._norm_finish(finish)
        return "".join(text_parts), tool_calls, fr, usage, ("\n".join(reasoning_parts) or None)

    # --- the chat contract ----------------------------------------------
    async def _complete_once(self, dialog, params, tools_requested):
        def _sync():
            return self._get_platform().dialog_completion(dialog=dialog, **params)
        timeout = _llm_hard_timeout(self.config.timeout, os.environ)
        resp = await asyncio.wait_for(asyncio.to_thread(_sync), timeout=timeout)
        parsed = self._parse_response(resp)
        content, tool_calls, _fr, _u, _r = parsed
        if tools_requested and not tool_calls and not (content or "").strip():
            # empty text AND no parseable tool call — treat like MALFORMED so the
            # retry/backoff ladder re-rolls (mirrors GoogleClient's MALFORMED path).
            raise RuntimeError("metagen returned MALFORMED tool call: empty content and no tool_calls")
        return resp, parsed

    async def chat(
        self,
        messages: list,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop: Optional[list] = None,
        functions: Optional[list] = None,
        tools: Optional[list] = None,
        **kwargs,
    ) -> LLMResponse:
        start = datetime.now()
        safe = [Message(role=m.role, content=_sanitize_message_content(m.content),
                        name=m.name, function_call=m.function_call,
                        tool_calls=m.tool_calls, tool_call_id=m.tool_call_id)
                for m in _drop_orphan_tool_results(
                _mask_old_observations(messages, self.config.model_name))]
        mg = self._sdk()
        dialog = mg.Dialog(messages=self._convert_messages(mg, safe))
        params = {
            "model": self.config.model_name,
            "temperature": self.config.temperature if temperature is None else temperature,
            "max_tokens": self.config.max_tokens if max_tokens is None else max_tokens,
        }
        if self.config.top_p is not None:
            params["top_p"] = self.config.top_p
        tool_list = tools or functions
        if tool_list:
            params["tools"] = json.dumps(tool_list)  # OpenAI/Azure schema string (3P models)
            tcfg = self._tool_config(kwargs.get("tool_choice"))
            if tcfg:
                params["tool_config"] = tcfg
        gds = self._guided_schema(kwargs)
        if gds:
            params["guided_decode_json_schema"] = gds
        resp, parsed = await self._retry_with_backoff(
            self._complete_once, dialog, params, bool(tool_list))
        content, tool_calls, fr, usage, reasoning = parsed
        return LLMResponse(
            content=content or "", model=self.config.model_name, finish_reason=fr,
            usage=usage, tool_calls=tool_calls or None, raw_response=resp,
            latency=(datetime.now() - start).total_seconds(), reasoning=reasoning)

    async def chat_stream(
        self,
        messages: list,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop: Optional[list] = None,
        **kwargs,
    ) -> AsyncIterator[str]:
        # MetaGen has a streaming API, but the multi-agent engine never streams; a
        # single-chunk fallback satisfies the abstract method.
        resp = await self.chat(messages, temperature=temperature,
                               max_tokens=max_tokens, stop=stop, **kwargs)
        if resp.content:
            yield resp.content


def create_llm_client(config: LLMConfig) -> BaseLLMClient:
    """
    Factory function to create LLM client based on config

    Args:
        config: LLM configuration

    Returns:
        Appropriate LLM client instance
    """
    provider_map = {
        LLMProvider.OPENAI: OpenAIClient,
        LLMProvider.OPENROUTER: OpenAIClient,  # OpenRouter is OpenAI-compatible
        LLMProvider.ANTHROPIC: AnthropicClient,
        LLMProvider.GOOGLE: GoogleClient,  # Gemini via OpenAI-compatible API
        LLMProvider.AZURE: OpenAIClient,  # Azure uses OpenAI-compatible API
        LLMProvider.METAGEN: MetagenClient,  # Meta MetaGen SDK (dialog_completion)
        LLMProvider.LOCAL: LocalLLMClient,
        LLMProvider.CUSTOM: LocalLLMClient,  # Custom endpoints use OpenAI-compatible API
    }
    
    client_class = provider_map.get(config.provider)
    if not client_class:
        raise ValueError(f"Unsupported LLM provider: {config.provider}")
    
    return client_class(config)


# Convenience class for easy usage
class LLM:
    """
    High-level LLM interface
    
    Usage:
        llm = LLM(config)
        response = await llm.chat("What is 2+2?")
        
        # Or with system prompt
        response = await llm.chat(
            "Translate to French: Hello",
            system="You are a translator."
        )
    """
    
    def __init__(self, config: LLMConfig):
        self.config = config
        self._client = create_llm_client(config)
        self._history: list[Message] = []
    
    async def chat(
        self,
        prompt: str,
        system: Optional[str] = None,
        history: bool = False,
        **kwargs
    ) -> str:
        """
        Simple chat interface
        
        Args:
            prompt: User message
            system: System prompt
            history: Whether to include conversation history
            
        Returns:
            Assistant response content
        """
        messages = []
        
        if system:
            messages.append(Message.system(system))
        
        if history:
            messages.extend(self._history)
        
        user_msg = Message.user(prompt)
        messages.append(user_msg)
        
        response = await self._client.chat(messages, **kwargs)
        
        if history:
            self._history.append(user_msg)
            self._history.append(Message.assistant(response.content))
        
        return response.content
    
    async def chat_with_response(
        self,
        prompt: str,
        system: Optional[str] = None,
        **kwargs
    ) -> LLMResponse:
        """
        Chat and return full response object
        """
        messages = []
        if system:
            messages.append(Message.system(system))
        messages.append(Message.user(prompt))
        
        return await self._client.chat(messages, **kwargs)
    
    async def chat_messages(
        self,
        messages: list[Message],
        **kwargs
    ) -> LLMResponse:
        """
        Chat with explicit message list.

        reasoning_effort is a gpt-5-only param: gate it here (single chokepoint for the
        agent path) so non-gpt-5 / Anthropic / Gemini clients never receive it.
        """
        effort = kwargs.pop("reasoning_effort", None)
        kwargs.update(_gpt5_reasoning_effort(self.config.model_name, effort))
        return await self._client.chat(messages, **kwargs)
    
    async def stream(
        self,
        prompt: str,
        system: Optional[str] = None,
        **kwargs
    ) -> AsyncIterator[str]:
        """
        Streaming chat
        """
        messages = []
        if system:
            messages.append(Message.system(system))
        messages.append(Message.user(prompt))
        
        async for chunk in self._client.chat_stream(messages, **kwargs):
            yield chunk
    
    def clear_history(self) -> None:
        """Clear conversation history"""
        self._history.clear()
    
    @property
    def client(self) -> BaseLLMClient:
        """Get underlying client for advanced usage"""
        return self._client

