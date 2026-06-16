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
    def assistant(cls, content: str = None, tool_calls: list = None) -> "Message":
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


def _mask_old_observations(messages: list) -> list:
    """Truncate the bulky text content of stale messages to bound per-call input."""
    cfg = _ctx_cfg()
    if not cfg or not messages:
        return messages
    keep_recent, max_old = cfg
    n = len(messages)
    if n <= keep_recent:
        return messages
    cutoff = n - keep_recent
    # protect the system prompt(s) and the first non-system message (the task)
    first_task = next((i for i, m in enumerate(messages)
                       if getattr(m, "role", "") != "system"), -1)
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
        max_retries: int = None,
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
                
                is_rate_limit = self._is_rate_limit_error(e)
                
                if attempt < total_attempts - 1:
                    if is_rate_limit:
                        # For rate limits, use longer delays and add extra retries
                        retry_after = self._extract_retry_after(e)
                        if retry_after:
                            delay = retry_after + 5  # Add 5 seconds buffer
                        else:
                            # Exponential backoff starting from rate_limit_base_delay
                            delay = rate_limit_base_delay * (2 ** min(attempt, 3))  # Cap at 240s
                        
                        # Add extra retries for rate limits if we haven't already
                        if attempt == max_retries - 1 and rate_limit_extra_retries > 0:
                            total_attempts = max_retries + rate_limit_extra_retries
                            self._logger.info(f"[LLM] Rate limit detected, extending retries to {total_attempts}")
                        
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
        
        raise last_error


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
        safe_messages: list[Message] = [
            Message(role=m.role, content=_sanitize_message_content(m.content), name=m.name, function_call=m.function_call, tool_calls=m.tool_calls, tool_call_id=m.tool_call_id)
            for m in _mask_old_observations(messages)
        ]
        
        # Determine token parameter name based on model. Reasoning-class models
        # (gpt-5, o1, o3) use ``max_completion_tokens`` AND commonly reject the
        # classic sampling params (``temperature``, ``top_p``, ``frequency_penalty``,
        # ``presence_penalty``). We omit them up front for that family to avoid
        # 400 "unsupported_parameter" errors; older chat models keep the params.
        model_name = self.config.model_name
        use_completion_tokens = model_name.startswith(("gpt-5", "o1", "o3"))
        token_param = "max_completion_tokens" if use_completion_tokens else "max_tokens"

        request_params = {
            "model": model_name,
            "messages": [m.to_dict() for m in safe_messages],
            token_param: max_tokens or self.config.max_tokens,
        }
        if not use_completion_tokens:
            request_params["temperature"] = temperature if temperature is not None else self.config.temperature
            request_params["top_p"] = self.config.top_p
            request_params["frequency_penalty"] = self.config.frequency_penalty
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
            hard_timeout = float(getattr(self.config, "timeout", None) or 240)
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
        has_tool_calls = bool(message.tool_calls)
        self._logger.info(f"[LLM Response] latency={latency:.1f}s, prompt_tokens={prompt_tokens}, completion_tokens={completion_tokens}, tool_calls={has_tool_calls}, finish={choice.finish_reason}")
        
        return LLMResponse(
            content=message.content or "",
            model=response.model,
            finish_reason=choice.finish_reason,
            usage={
                "prompt_tokens": response.usage.prompt_tokens,
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
            "messages": [m.to_dict() for m in messages],
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
            "messages": [m.to_dict() for m in messages],
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
            "messages": [m.to_dict() for m in messages],
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

        messages = _mask_old_observations(messages)  # bound per-call input growth
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
            for m in _mask_old_observations(messages)
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
            
            def _do_call():
                return client.models.generate_content(
                    model=self.config.model_name,
                    contents=contents,
                    config=_make_gen_config(),
                )
            
            # Run sync call in thread pool
            task = asyncio.get_event_loop().run_in_executor(None, _do_call)

            # HARD total timeout: the loop used to warn forever and never give up, so
            # one wedged SDK call (sync, in the executor) hung the whole run until an
            # external kill (instagram M2 froze twice on exactly this: "Attempt 1/3
            # starting..." then silence). Past config.timeout, stop awaiting and raise
            # — the retry layer takes over. The executor thread itself can't be
            # cancelled, but it is abandoned and the run moves on.
            hard_timeout = float(getattr(self.config, "timeout", None) or 240)
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
                if hasattr(part, 'text') and part.text:
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
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            prompt_tokens = getattr(response.usage_metadata, 'prompt_token_count', 0) or 0
            completion_tokens = getattr(response.usage_metadata, 'candidates_token_count', 0) or 0
        
        has_tool_calls = bool(tool_calls)
        if has_tool_calls:
            finish_reason = "tool_calls"
        
        self._logger.info(f"[LLM Response] latency={latency:.1f}s, prompt_tokens={prompt_tokens}, completion_tokens={completion_tokens}, tool_calls={has_tool_calls}, finish={finish_reason}")
        
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
        
        # Convert messages
        system_instruction, contents = self._convert_messages_to_google(messages)
        
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

