"""
Context Management - Advanced strategies to combat Context Snowball

Inspired by:
1. Cross-Team Orchestration (Croto) - https://arxiv.org/pdf/2406.08979
   - Hierarchy Partitioning: Group context by importance levels
   - Greedy Aggregation: Merge insights from multiple sources

2. MemGPT / Self-Controlled Memory - https://arxiv.org/abs/2310.08560
   - Tiered memory (main context, recall storage, archival storage)
   - Self-editing of memory based on importance

Key Strategies:
1. Hierarchical Context - Core/Working/Historical layers
2. Incremental Summarization - Rolling summaries, not batch compression
3. Semantic Deduplication - Detect and merge similar content
4. Context Budget - Allocate context window by task phase
5. Smart Tool Result Handling - Type-aware truncation
"""

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple


# =============================================================================
# 1. HIERARCHICAL CONTEXT MANAGEMENT
# =============================================================================

class ContextLayer(Enum):
    """
    Three-tier context hierarchy inspired by MemGPT.
    
    CORE: Always in context (system prompt, critical constraints)
    WORKING: Current task context (recent actions, active state)  
    ARCHIVAL: Compressed history (summaries, can be recalled)
    """
    CORE = "core"           # ~500 tokens, never compressed
    WORKING = "working"     # ~4000 tokens, compressed when full
    ARCHIVAL = "archival"   # Unlimited, stored externally


@dataclass
class ContextItem:
    """A unit of context with metadata."""
    content: str
    layer: ContextLayer
    category: str  # decision, error, api, file, tool, etc.
    importance: float = 0.5
    timestamp: datetime = field(default_factory=datetime.now)
    token_estimate: int = 0
    source: str = ""  # agent_id or "system"
    
    # For deduplication
    content_hash: str = ""
    
    def __post_init__(self):
        if not self.content_hash:
            self.content_hash = self._compute_hash()
        if not self.token_estimate:
            self.token_estimate = len(self.content) // 4  # rough estimate
    
    def _compute_hash(self) -> str:
        """Compute semantic hash (normalized content)."""
        # Normalize whitespace and common variations
        normalized = re.sub(r'\s+', ' ', self.content.lower().strip())
        # Remove timestamps, IDs
        normalized = re.sub(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}', '', normalized)
        normalized = re.sub(r'[a-f0-9]{8,}', '', normalized)
        return hashlib.md5(normalized.encode()).hexdigest()[:12]


class HierarchicalContextManager:
    """
    Manages context across three layers with automatic promotion/demotion.
    
    Core Layer:
    - System prompt
    - Critical constraints (auth patterns, API base URLs)
    - Current task objective
    
    Working Layer:
    - Recent tool calls and results
    - Active file edits
    - Current conversation turns
    
    Archival Layer:
    - Compressed summaries of past work
    - Historical decisions
    - Can be recalled on-demand
    
    Usage:
        ctx = HierarchicalContextManager(max_working_tokens=4000)
        
        # Add items
        ctx.add_core("You are a backend developer...")
        ctx.add_working("Created file: api.py", category="file")
        
        # Build context for LLM
        messages = ctx.build_context()
        
        # After LLM call, commit response
        ctx.commit_turn(user_msg, assistant_msg, tool_results)
    """
    
    def __init__(
        self,
        max_core_tokens: int = 800,
        max_working_tokens: int = 6000,
        compress_threshold: float = 0.85,  # Compress when 85% full
        logger: Optional[logging.Logger] = None,
    ):
        self.max_core_tokens = max_core_tokens
        self.max_working_tokens = max_working_tokens
        self.compress_threshold = compress_threshold
        self._logger = logger or logging.getLogger("HierarchicalContext")
        
        # Three layers
        self._core: List[ContextItem] = []
        self._working: List[ContextItem] = []
        self._archival: List[ContextItem] = []
        
        # Token tracking
        self._core_tokens = 0
        self._working_tokens = 0
        
        # Deduplication
        self._seen_hashes: Set[str] = set()
        
        # Summarization callback
        self._summarize_fn: Optional[Callable[[List[ContextItem]], str]] = None
        
        # Statistics
        self._stats = {
            "items_added": 0,
            "items_deduplicated": 0,
            "compressions": 0,
            "recalls": 0,
        }
    
    def set_summarizer(self, fn: Callable[[List[ContextItem]], str]) -> None:
        """Set async summarization function for compression."""
        self._summarize_fn = fn
    
    # ==================== Core Layer ====================
    
    def add_core(
        self,
        content: str,
        category: str = "system",
        source: str = "system",
    ) -> bool:
        """
        Add to core context (always present).
        
        Use sparingly - this context is NEVER compressed.
        """
        item = ContextItem(
            content=content,
            layer=ContextLayer.CORE,
            category=category,
            importance=1.0,
            source=source,
        )
        
        if self._core_tokens + item.token_estimate > self.max_core_tokens:
            self._logger.warning(f"Core context full ({self._core_tokens}/{self.max_core_tokens})")
            return False
        
        self._core.append(item)
        self._core_tokens += item.token_estimate
        self._stats["items_added"] += 1
        return True
    
    def update_core(self, category: str, content: str, source: str = "system") -> None:
        """Update or add core item by category."""
        # Remove existing with same category
        old_tokens = sum(i.token_estimate for i in self._core if i.category == category)
        self._core = [i for i in self._core if i.category != category]
        self._core_tokens -= old_tokens
        
        # Add new
        self.add_core(content, category, source)
    
    # ==================== Working Layer ====================
    
    def add_working(
        self,
        content: str,
        category: str,
        importance: float = 0.5,
        source: str = "",
        deduplicate: bool = True,
    ) -> Optional[ContextItem]:
        """
        Add to working context.
        
        Args:
            content: The content to add
            category: Category (decision, error, api, file, tool, progress)
            importance: 0.0-1.0, higher = more important
            source: Agent ID or identifier
            deduplicate: Check for similar existing content
            
        Returns:
            ContextItem if added, None if deduplicated
        """
        item = ContextItem(
            content=content,
            layer=ContextLayer.WORKING,
            category=category,
            importance=importance,
            source=source,
        )
        
        # Deduplication check
        if deduplicate and item.content_hash in self._seen_hashes:
            self._stats["items_deduplicated"] += 1
            self._logger.debug(f"Deduplicated: {content[:50]}...")
            return None
        
        self._seen_hashes.add(item.content_hash)
        self._working.append(item)
        self._working_tokens += item.token_estimate
        self._stats["items_added"] += 1
        
        return item
    
    def should_compress(self) -> bool:
        """Check if working context should be compressed."""
        threshold = self.max_working_tokens * self.compress_threshold
        return self._working_tokens > threshold
    
    async def compress_working(self, keep_recent: int = 10) -> str:
        """
        Compress working context, moving old items to archival.
        
        Returns:
            Summary of compressed items
        """
        if len(self._working) <= keep_recent:
            return ""
        
        # Sort by importance and recency
        to_archive = self._working[:-keep_recent]
        to_keep = self._working[-keep_recent:]
        
        # Generate summary
        summary = ""
        if self._summarize_fn:
            try:
                summary = await self._summarize_fn(to_archive)
            except Exception as e:
                self._logger.error(f"Summarization failed: {e}")
                summary = self._simple_summary(to_archive)
        else:
            summary = self._simple_summary(to_archive)
        
        # Create archival item
        archival_item = ContextItem(
            content=summary,
            layer=ContextLayer.ARCHIVAL,
            category="summary",
            importance=0.7,
            source="compression",
        )
        self._archival.append(archival_item)
        
        # Update working
        self._working = to_keep
        self._working_tokens = sum(i.token_estimate for i in to_keep)
        
        self._stats["compressions"] += 1
        self._logger.info(
            f"Compressed {len(to_archive)} items -> archival "
            f"(working: {self._working_tokens} tokens)"
        )
        
        return summary
    
    def _simple_summary(self, items: List[ContextItem]) -> str:
        """Generate simple summary without LLM."""
        by_category: Dict[str, List[str]] = {}
        
        for item in items:
            if item.category not in by_category:
                by_category[item.category] = []
            # Truncate long items
            content = item.content[:200] + "..." if len(item.content) > 200 else item.content
            by_category[item.category].append(content)
        
        sections = []
        for cat, contents in by_category.items():
            sections.append(f"## {cat.title()} ({len(contents)} items)")
            for c in contents[:5]:  # Max 5 per category
                sections.append(f"- {c}")
        
        return "\n".join(sections)
    
    # ==================== Archival Layer ====================
    
    def recall(self, query: str, max_items: int = 3) -> List[ContextItem]:
        """
        Recall relevant items from archival storage.
        
        Simple keyword matching (can be replaced with semantic search).
        """
        query_words = set(query.lower().split())
        
        scored = []
        for item in self._archival:
            content_words = set(item.content.lower().split())
            overlap = len(query_words & content_words)
            if overlap > 0:
                scored.append((overlap, item))
        
        scored.sort(key=lambda x: x[0], reverse=True)
        
        results = [item for _, item in scored[:max_items]]
        self._stats["recalls"] += len(results)
        
        return results
    
    def inject_recall(self, items: List[ContextItem]) -> None:
        """Inject recalled items back into working context."""
        for item in items:
            self.add_working(
                content=f"[RECALLED] {item.content}",
                category="recall",
                importance=0.6,
                deduplicate=True,
            )
    
    # ==================== Context Building ====================
    
    def build_context(
        self,
        include_archival_summary: bool = True,
        format: str = "messages",
    ) -> List[Dict]:
        """
        Build context for LLM call.
        
        Args:
            include_archival_summary: Include brief archival summary
            format: "messages" or "text"
            
        Returns:
            List of message dicts or single text string
        """
        messages = []
        
        # System message from core
        core_content = "\n\n".join(i.content for i in self._core)
        messages.append({"role": "system", "content": core_content})
        
        # Archival summary if requested
        if include_archival_summary and self._archival:
            recent_archival = self._archival[-3:]  # Last 3 summaries
            archival_summary = "[Previous Context Summary]\n" + "\n---\n".join(
                i.content[:500] for i in recent_archival
            )
            messages.append({"role": "user", "content": archival_summary})
        
        # Working context as conversation
        for item in self._working:
            # Map category to role
            if item.category in ("decision", "progress", "file"):
                messages.append({"role": "assistant", "content": item.content})
            else:
                messages.append({"role": "user", "content": item.content})
        
        return messages
    
    def get_stats(self) -> Dict:
        """Get context management statistics."""
        return {
            **self._stats,
            "core_tokens": self._core_tokens,
            "working_tokens": self._working_tokens,
            "working_items": len(self._working),
            "archival_items": len(self._archival),
            "unique_hashes": len(self._seen_hashes),
        }


# =============================================================================
# 2. INCREMENTAL SUMMARIZATION
# =============================================================================

class IncrementalSummarizer:
    """
    Rolling summarization that maintains a condensed view of history.
    
    Unlike batch compression, this continuously updates summaries
    as new information arrives, preventing context from exploding.
    
    Inspired by Croto's "Greedy Aggregation" - extract best insights.
    """
    
    def __init__(
        self,
        max_summary_tokens: int = 1000,
        update_interval: int = 5,  # Update every N items
    ):
        self.max_summary_tokens = max_summary_tokens
        self.update_interval = update_interval
        
        # Current rolling summary
        self._summary = ""
        self._summary_version = 0
        
        # Buffer for pending items
        self._buffer: List[str] = []
        
        # Category-specific summaries
        self._category_summaries: Dict[str, str] = {
            "decisions": "",
            "errors": "",
            "files": "",
            "api": "",
        }
        
        # LLM for summarization (optional)
        self._llm: Optional[Any] = None
        self._logger = logging.getLogger("IncrementalSummarizer")
    
    def set_llm(self, llm: Any) -> None:
        """Set LLM for intelligent summarization."""
        self._llm = llm
    
    def add(self, content: str, category: str = "general") -> bool:
        """
        Add content and potentially trigger summary update.
        
        Returns:
            True if summary was updated
        """
        self._buffer.append(f"[{category}] {content}")
        
        if len(self._buffer) >= self.update_interval:
            self._update_summary()
            return True
        
        return False
    
    def _update_summary(self) -> None:
        """Update rolling summary with buffered items."""
        if not self._buffer:
            return
        
        # Categorize buffered items
        for item in self._buffer:
            category = self._extract_category(item)
            self._update_category_summary(category, item)
        
        # Build combined summary
        sections = []
        for cat, summary in self._category_summaries.items():
            if summary:
                sections.append(f"## {cat.title()}\n{summary}")
        
        self._summary = "\n\n".join(sections)
        self._summary_version += 1
        self._buffer.clear()
        
        self._logger.debug(f"Summary updated (v{self._summary_version})")
    
    def _extract_category(self, item: str) -> str:
        """Extract category from item."""
        match = re.match(r'\[(\w+)\]', item)
        if match:
            cat = match.group(1).lower()
            if cat in self._category_summaries:
                return cat
        return "general"
    
    def _update_category_summary(self, category: str, item: str) -> None:
        """Update category-specific summary."""
        content = re.sub(r'^\[\w+\]\s*', '', item)  # Remove category tag
        
        if category not in self._category_summaries:
            return
        
        current = self._category_summaries[category]
        
        # Simple append with dedup
        if content not in current:
            if len(current) > 500:
                # Truncate old content
                current = current[-400:] + "\n..."
            
            self._category_summaries[category] = f"{current}\n- {content[:200]}"
    
    def get_summary(self) -> str:
        """Get current rolling summary."""
        # Include any pending buffer items
        if self._buffer:
            pending = "\n## Pending\n" + "\n".join(f"- {b[:100]}" for b in self._buffer[:5])
            return self._summary + pending
        
        return self._summary
    
    def get_category_summary(self, category: str) -> str:
        """Get summary for specific category."""
        return self._category_summaries.get(category, "")


# =============================================================================
# 3. SMART TOOL RESULT HANDLING
# =============================================================================

class ToolResultCompressor:
    """
    Intelligent compression of tool results based on tool type.
    
    Different tools have different result patterns:
    - read: Often huge, keep structure + truncate content
    - list_dir: Medium, keep full
    - write: Small, keep full
    - run_command: Variable, keep errors fully, truncate success
    """
    
    # Downstream hard clip (step_pipeline/tooling.py: max_result_len) is the REAL
    # per-tool-result budget the rest of the pipeline absorbs. The compressor must
    # not destructively pre-empt it for reads.
    DOWNSTREAM_CLIP_CHARS = 16000

    # Tool-specific compression rules
    COMPRESSION_RULES = {
        # `read` previously used head_tail @ 2000 chars: it kept head+tail and
        # DROPPED THE MIDDLE. For a code file the route/function bodies live in
        # that middle, so the model saw an empty-looking shell -> the "all
        # endpoints return empty dicts" mis-diagnosis, then re-read/flail loops.
        # Fix: keep a CONTIGUOUS leading span (head strategy, no dropped middle)
        # bounded by the downstream clip. Cost tradeoff: bigger reads cost more
        # input tokens, but the 2000-char middle-drop provoked re-read loops that
        # cost more overall — head-to-clip is the cheaper, correct budget.
        "read": {
            "max_chars": DOWNSTREAM_CLIP_CHARS,
            "strategy": "head",  # contiguous leading span; never drop the middle
            "keep_structure": True,
        },
        "list_dir": {
            "max_chars": 1500,
            "strategy": "truncate",
            "keep_structure": True,
        },
        "write": {
            "max_chars": 500,
            "strategy": "summary",
            "keep_structure": False,
        },
        "edit": {
            "max_chars": 500,
            "strategy": "summary",
            "keep_structure": False,
        },
        "apply_patch": {
            "max_chars": 700,
            "strategy": "summary",
            "keep_structure": False,
        },
        "run_terminal_cmd": {
            "max_chars": 1000,
            "strategy": "error_preserve",  # Keep errors fully
            "keep_structure": False,
        },
        "grep": {
            "max_chars": 1500,
            "strategy": "head",
            "keep_structure": True,
        },
        "codebase_search": {
            "max_chars": 2000,
            "strategy": "head",
            "keep_structure": True,
        },
        # `default` (unknown tools) stays at 1000 with `truncate`: that strategy
        # keeps a CONTIGUOUS leading span and never drops the middle, so it does
        # NOT exhibit the read-shell pathology this fix targets. It is also
        # deliberately small (test_inbox_no_content_truncation) to avoid
        # ballooning context for every tool — widen specific tools explicitly
        # instead of the global default.
        "default": {
            "max_chars": 1000,
            "strategy": "truncate",
            "keep_structure": False,
        },
        # 2026-06-02 v3 re-pilot fix (3rd truncation site discovered):
        # check_inbox / eventhub_inbox / search_messages / get_important_messages
        # all carry inter-agent messages that frequently exceed 1000 chars
        # (orchestrator task_ready payloads can be ~3500 chars for a
        # full Facebook-scale spec). The default 1000-char cap was
        # silently truncating them at the LLM-context boundary — the
        # check_inbox tool itself returned full content (per
        # communication_tools.py:878 fix at commit 3394a34e), but the
        # ToolResultCompressor stripped it back to 1000 here. Result:
        # design agent kept asking orchestrator to "resend untruncated"
        # because that's exactly what it kept seeing. Per user
        # 2026-06-01/02 directive ("不要截断，这个肯定要完整信息的"),
        # message-passing tools get a high cap. 50k is roughly the
        # claude-opus / gpt-4 context-budget-per-tool-call ceiling
        # the rest of the pipeline can absorb without thrashing.
        "check_inbox": {
            "max_chars": 50000,
            "strategy": "truncate",
            "keep_structure": True,
        },
        "eventhub_inbox": {
            "max_chars": 50000,
            "strategy": "truncate",
            "keep_structure": True,
        },
        "search_messages": {
            "max_chars": 50000,
            "strategy": "truncate",
            "keep_structure": True,
        },
        "get_important_messages": {
            "max_chars": 50000,
            "strategy": "truncate",
            "keep_structure": True,
        },
        "eventhub_get_thread": {
            "max_chars": 50000,
            "strategy": "truncate",
            "keep_structure": True,
        },
        # #307: list tools are the SOURCE OF TRUTH for "what already exists".
        # Truncating them to the 1000-char default hid endpoints/tables/tasks
        # beyond the cut → an agent that couldn't see an endpoint already existed
        # RE-IMPLEMENTED it (duplicate/conflicting APIs). #303/#305 made the rows
        # COMPACT (~60 bytes), so the FULL list now fits cheaply — give it a high
        # cap so it is shown COMPLETE. A pathologically huge list still uses `head`
        # (whole leading rows) + the #304 recovery pointer, never silent loss.
        "registryhub_list_endpoints": {
            "max_chars": 60000,
            "strategy": "head",
            "keep_structure": True,
        },
        "registryhub_list_tables": {
            "max_chars": 60000,
            "strategy": "head",
            "keep_structure": True,
        },
        "workhub_list_tasks": {
            "max_chars": 60000,
            "strategy": "head",
            "keep_structure": True,
        },
    }
    
    def __init__(self):
        self._logger = logging.getLogger("ToolResultCompressor")
    
    def compress(
        self,
        tool_name: str,
        result: str,
        success: bool = True,
    ) -> str:
        """
        Compress tool result based on tool type.
        
        Args:
            tool_name: Name of the tool
            result: Raw result string
            success: Whether tool succeeded
            
        Returns:
            Compressed result
        """
        rules = self.COMPRESSION_RULES.get(tool_name, self.COMPRESSION_RULES["default"])
        max_chars = rules["max_chars"]
        strategy = rules["strategy"]
        
        # Never compress short results
        if len(result) <= max_chars:
            return result
        
        # Error preserve strategy
        if strategy == "error_preserve" and not success:
            # Keep errors fully (up to 3000 chars)
            return result[:3000]
        
        # Apply compression strategy
        if strategy == "head_tail":
            return self._head_tail(result, max_chars, tool_name)
        elif strategy == "head":
            return self._head(result, max_chars, tool_name)
        elif strategy == "summary":
            return self._summary(result, tool_name)
        else:
            return self._truncate(result, max_chars, tool_name)

    def _recovery_hint(self, tool_name: str) -> str:
        """#304 — a generic, honest pointer telling the agent the result was
        truncated AND how to recover the omitted content, so a truncated result
        never silently drops information (the #274 hazard at the compressor
        layer). Tool-aware where a precise path exists; generic otherwise."""
        t = str(tool_name or "")
        if t == "read":
            return "read(path, offset=<next line>) to continue"
        if "list" in t:
            return ("call the matching get-by-id tool for full detail, or re-run "
                    "with a narrower filter")
        return ("re-run this tool with narrower args / pagination, or use a "
                "get-by-id / read(offset=) call, to see the omitted content")

    def _head_tail(self, text: str, max_chars: int, tool_name: str = "") -> str:
        """Keep head and tail of text."""
        head_size = max_chars * 2 // 3
        tail_size = max_chars // 3

        head = text[:head_size]
        tail = text[-tail_size:]

        return (f"{head}\n\n... [{len(text) - max_chars} of {len(text)} chars "
                f"omitted — {self._recovery_hint(tool_name)}] ...\n\n{tail}")

    def _head(self, text: str, max_chars: int, tool_name: str = "") -> str:
        """Keep only head of text."""
        return (text[:max_chars] + f"\n\n... [{len(text) - max_chars} more of "
                f"{len(text)} chars omitted — {self._recovery_hint(tool_name)}]")

    def _truncate(self, text: str, max_chars: int, tool_name: str = "") -> str:
        """Simple truncation — with a recovery pointer (never a bare '...')."""
        return (text[:max_chars] + f"\n… [truncated: {len(text) - max_chars} of "
                f"{len(text)} chars omitted — {self._recovery_hint(tool_name)}]")

    def _summary(self, text: str, tool_name: str) -> str:
        """Generate brief summary."""
        lines = text.split('\n')

        # For write/edit/apply_patch, extract path-ish summary
        if tool_name in {"write", "edit", "apply_patch"}:
            for line in lines[:5]:
                if 'path' in line.lower() or 'file' in line.lower():
                    return f"[{tool_name}] {line[:200]}"

        # Generic summary
        return (f"[{tool_name} result] {len(lines)} lines, {len(text)} chars — "
                f"summarized; {self._recovery_hint(tool_name)}")


# =============================================================================
# 4. CONTEXT BUDGET ALLOCATION
# =============================================================================

class TaskPhase(Enum):
    """Phases of task execution with different context needs."""
    PLANNING = "planning"       # Need broad context, less detail
    IMPLEMENTING = "implementing"  # Need specific code context
    DEBUGGING = "debugging"     # Need error traces, full details
    REVIEWING = "reviewing"     # Need diff context, test results


class ContextBudgetAllocator:
    """
    Allocate context window based on task phase.
    
    Different phases need different context compositions:
    - Planning: More archival, less working detail
    - Implementing: Code-heavy, recent changes
    - Debugging: Error traces, stack traces, full tool results
    - Reviewing: Diffs, test outputs
    """
    
    # Budget allocation by phase (% of total context)
    PHASE_BUDGETS = {
        TaskPhase.PLANNING: {
            "core": 0.15,
            "archival": 0.35,
            "working": 0.50,
        },
        TaskPhase.IMPLEMENTING: {
            "core": 0.10,
            "archival": 0.15,
            "working": 0.75,
        },
        TaskPhase.DEBUGGING: {
            "core": 0.10,
            "archival": 0.10,
            "working": 0.80,
        },
        TaskPhase.REVIEWING: {
            "core": 0.10,
            "archival": 0.20,
            "working": 0.70,
        },
    }
    
    def __init__(self, total_context_tokens: int = 8000):
        self.total_tokens = total_context_tokens
        self._current_phase = TaskPhase.PLANNING
        self._logger = logging.getLogger("ContextBudget")
    
    def set_phase(self, phase: TaskPhase) -> Dict[str, int]:
        """
        Set current phase and return token budgets.
        
        Returns:
            Dict with token limits for each layer
        """
        self._current_phase = phase
        budgets = self.PHASE_BUDGETS[phase]
        
        allocation = {
            "core": int(self.total_tokens * budgets["core"]),
            "archival": int(self.total_tokens * budgets["archival"]),
            "working": int(self.total_tokens * budgets["working"]),
        }
        
        self._logger.info(f"Phase: {phase.value}, Budget: {allocation}")
        return allocation
    
    def get_current_budgets(self) -> Dict[str, int]:
        """Get current phase budgets."""
        return self.set_phase(self._current_phase)
    
    def detect_phase(self, recent_actions: List[str]) -> TaskPhase:
        """
        Auto-detect phase from recent actions.
        
        Simple heuristic based on tool usage patterns.
        """
        action_str = " ".join(recent_actions).lower()
        
        if any(w in action_str for w in ["error", "fix", "debug", "traceback"]):
            return TaskPhase.DEBUGGING
        elif any(w in action_str for w in ["test", "review", "diff", "check"]):
            return TaskPhase.REVIEWING
        elif any(w in action_str for w in ["write", "edit", "apply_patch", "create"]):
            return TaskPhase.IMPLEMENTING
        else:
            return TaskPhase.PLANNING


# =============================================================================
# 5. INTEGRATED CONTEXT MANAGER
# =============================================================================

class AdvancedContextManager:
    """
    Integrated context manager combining all strategies.
    
    Usage:
        ctx = AdvancedContextManager(max_tokens=8000)
        
        # Set up
        ctx.set_core_context(system_prompt)
        ctx.set_task("Implement user registration API")
        
        # During execution
        ctx.add_tool_result("read", result, success=True)
        ctx.add_decision("Using bcrypt for password hashing")
        ctx.add_error("TypeError: ...", fix="Added type check")
        
        # Build context for LLM
        messages = ctx.build_messages()
        
        # After task
        summary = ctx.finalize_task()
    """
    
    def __init__(
        self,
        max_tokens: int = 8000,
        storage_path: Optional[Path] = None,
    ):
        self.max_tokens = max_tokens
        self.storage_path = storage_path
        
        # Components
        self.hierarchy = HierarchicalContextManager(
            max_working_tokens=int(max_tokens * 0.75)
        )
        self.summarizer = IncrementalSummarizer()
        self.tool_compressor = ToolResultCompressor()
        self.budget = ContextBudgetAllocator(max_tokens)
        
        self._logger = logging.getLogger("AdvancedContext")
        self._current_task = ""
        self._task_start = datetime.now()
    
    def set_core_context(self, system_prompt: str) -> None:
        """Set core system context."""
        self.hierarchy.add_core(system_prompt, category="system")
    
    def set_task(self, task: str) -> None:
        """Set current task."""
        self._current_task = task
        self._task_start = datetime.now()
        self.hierarchy.update_core("task", f"Current Task: {task}")
    
    def add_tool_result(
        self,
        tool_name: str,
        result: str,
        success: bool = True,
        importance: float = 0.5,
    ) -> None:
        """Add tool result with smart compression."""
        compressed = self.tool_compressor.compress(tool_name, result, success)
        
        # Boost importance for errors
        if not success:
            importance = max(importance, 0.8)
        
        self.hierarchy.add_working(
            content=f"[{tool_name}] {compressed}",
            category="tool",
            importance=importance,
        )
        
        # Update incremental summary
        self.summarizer.add(compressed[:200], category="tool")
    
    def add_decision(self, decision: str, reasoning: str = "") -> None:
        """Add a key decision."""
        content = decision
        if reasoning:
            content = f"{decision}\nReason: {reasoning}"
        
        self.hierarchy.add_working(
            content=content,
            category="decision",
            importance=0.9,  # Decisions are important
        )
        self.summarizer.add(decision, category="decisions")
    
    def add_error(self, error: str, fix: str = "") -> None:
        """Add error and optional fix."""
        content = f"Error: {error}"
        if fix:
            content += f"\nFix: {fix}"
        
        self.hierarchy.add_working(
            content=content,
            category="error",
            importance=0.95,  # Errors are critical
        )
        self.summarizer.add(f"{error[:100]} -> {fix[:100]}", category="errors")
    
    def add_file_operation(self, operation: str, path: str) -> None:
        """Add file operation."""
        content = f"{operation}: {path}"
        
        self.hierarchy.add_working(
            content=content,
            category="file",
            importance=0.6,
        )
        self.summarizer.add(path, category="files")
    
    def add_api_spec(self, endpoint: str, method: str, details: str = "") -> None:
        """Add API specification."""
        content = f"{method} {endpoint}"
        if details:
            content += f"\n{details}"
        
        self.hierarchy.add_working(
            content=content,
            category="api",
            importance=0.85,
        )
        self.summarizer.add(f"{method} {endpoint}", category="api")
    
    async def maybe_compress(self) -> bool:
        """Check and perform compression if needed."""
        if self.hierarchy.should_compress():
            await self.hierarchy.compress_working()
            return True
        return False
    
    def recall(self, query: str) -> List[str]:
        """Recall relevant archived context."""
        items = self.hierarchy.recall(query)
        return [i.content for i in items]
    
    def build_messages(self) -> List[Dict]:
        """Build messages for LLM call."""
        return self.hierarchy.build_context()
    
    def get_rolling_summary(self) -> str:
        """Get current incremental summary."""
        return self.summarizer.get_summary()
    
    def detect_and_set_phase(self, recent_actions: List[str]) -> TaskPhase:
        """Auto-detect phase and adjust budgets."""
        phase = self.budget.detect_phase(recent_actions)
        self.budget.set_phase(phase)
        return phase
    
    def finalize_task(self) -> Dict:
        """Finalize task and return summary."""
        duration = (datetime.now() - self._task_start).total_seconds()
        
        return {
            "task": self._current_task,
            "duration_seconds": duration,
            "summary": self.get_rolling_summary(),
            "stats": self.hierarchy.get_stats(),
        }
    
    def save_state(self) -> None:
        """Save context state to storage."""
        if not self.storage_path:
            return
        
        state = {
            "task": self._current_task,
            "summary": self.get_rolling_summary(),
            "stats": self.hierarchy.get_stats(),
            "timestamp": datetime.now().isoformat(),
        }
        
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.storage_path, 'w') as f:
            json.dump(state, f, indent=2)


# =============================================================================
# EXPORT
# =============================================================================

__all__ = [
    "ContextLayer",
    "ContextItem",
    "HierarchicalContextManager",
    "IncrementalSummarizer",
    "ToolResultCompressor",
    "TaskPhase",
    "ContextBudgetAllocator",
    "AdvancedContextManager",
]

