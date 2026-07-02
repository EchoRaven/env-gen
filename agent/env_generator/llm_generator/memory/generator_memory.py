"""
Generator Memory - Enhanced Memory System for Multi-Agent Code Generation

Key Features:
1. Conversation Context Management - Intelligent condensation when context grows too large
2. Tool Call Tracking - Record tool calls for pattern detection and optimization
3. File Operation Tracking - Track created, modified, linted files
4. Knowledge Persistence - Important learnings that persist across tasks
5. Cross-Agent Memory Sharing - Share important info via MessageBus
6. Smart Content Classification - Separate compression for tools, decisions, files
7. Importance Scoring - Preserve high-value messages (errors, decisions, API specs)
8. Auto MemoryBank Sync - Automatically update progress.md

Integration Points:
- run_agentic_loop: Auto-condense when messages exceed threshold
- tool_execute: Record tool calls and results
- task_complete: Summarize and persist important learnings
"""

import logging
import re
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Any, Set, Callable, Tuple, TYPE_CHECKING
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum
import json
import asyncio

# Import base classes from utils/memory.py
import sys
_agents_dir = Path(__file__).parent.parent.parent.parent.absolute()
if str(_agents_dir) not in sys.path:
    sys.path.insert(0, str(_agents_dir))

from utils.memory import (
    AgentMemory,
    ShortTermMemory,
    LongTermMemory,
    WorkingMemory,
    LLMSummarizingCondenser,
    MemoryItem,
)
from utils.llm import LLM

if TYPE_CHECKING:
    from memory.memory_bank import MemoryBank


# ==================== Message Classification ====================

class MessageCategory(Enum):
    """Categories for message classification."""
    DECISION = "decision"           # Key decisions and reasoning
    ERROR = "error"                 # Errors and their fixes
    API_SPEC = "api_spec"           # API definitions, schemas
    FILE_OP = "file_op"             # File create/modify/delete
    TOOL_RESULT = "tool_result"     # Tool execution results
    PROGRESS = "progress"           # Task progress updates
    QUESTION = "question"           # Questions between agents
    GENERAL = "general"             # Other messages


# Patterns for message classification
DECISION_PATTERNS = [
    r"decided\s+to", r"will\s+use", r"choosing\s+", r"approach\s*:", 
    r"strategy\s*:", r"architecture", r"because\s+", r"therefore\s+",
    r"conclusion", r"design\s+decision", r"implementation\s+plan"
]

ERROR_PATTERNS = [
    r"error", r"failed", r"exception", r"traceback", r"bug", 
    r"fix(ed|ing)?", r"issue", r"problem", r"warning"
]

API_PATTERNS = [
    r"/api/", r"endpoint", r"route", r"schema", r"response_key",
    r"request\s+body", r"response\s+format", r"authentication",
    r"GET\s+/", r"POST\s+/", r"PUT\s+/", r"DELETE\s+/"
]

FILE_PATTERNS = [
    r"write", r"read", r"edit", r"apply_patch", r"created?\s+file", r"modified?\s+file",
    r"\.jsx?$", r"\.tsx?$", r"\.py$", r"\.sql$", r"\.json$"
]


# ==================== Importance Scoring ====================

@dataclass
class ImportanceScore:
    """Importance score with category breakdown."""
    total: float
    category: MessageCategory
    is_critical: bool = False
    reason: str = ""


class MessageImportanceScorer:
    """
    Scores message importance for smart retention during compression.
    
    High importance (0.8-1.0):
    - Errors and their fixes
    - Key architectural decisions
    - API specifications
    - Critical progress milestones
    
    Medium importance (0.5-0.8):
    - File operations
    - Tool results with meaningful output
    - Questions and answers between agents
    
    Low importance (0.0-0.5):
    - Redundant tool calls
    - Verbose file contents
    - Repetitive reasoning
    """
    
    # Base scores by category
    CATEGORY_BASE_SCORES = {
        MessageCategory.ERROR: 0.9,
        MessageCategory.DECISION: 0.85,
        MessageCategory.API_SPEC: 0.8,
        MessageCategory.QUESTION: 0.7,
        MessageCategory.PROGRESS: 0.6,
        MessageCategory.FILE_OP: 0.5,
        MessageCategory.TOOL_RESULT: 0.4,
        MessageCategory.GENERAL: 0.3,
    }
    
    # Keywords that boost importance
    BOOST_KEYWORDS = {
        "critical": 0.2, "important": 0.15, "must": 0.1, "required": 0.1,
        "authentication": 0.15, "security": 0.15, "database": 0.1,
        "schema": 0.1, "migration": 0.1, "breaking": 0.2,
    }
    
    # Keywords that reduce importance
    REDUCE_KEYWORDS = {
        "lint passed": -0.3, "no changes": -0.2, "already exists": -0.2,
        "skipping": -0.2, "unchanged": -0.2,
    }
    
    def classify_message(self, content: str) -> MessageCategory:
        """Classify a message into a category."""
        content_lower = content.lower()
        
        # Check patterns in priority order
        for pattern in ERROR_PATTERNS:
            if re.search(pattern, content_lower):
                return MessageCategory.ERROR
        
        for pattern in API_PATTERNS:
            if re.search(pattern, content_lower):
                return MessageCategory.API_SPEC
        
        for pattern in DECISION_PATTERNS:
            if re.search(pattern, content_lower):
                return MessageCategory.DECISION
        
        for pattern in FILE_PATTERNS:
            if re.search(pattern, content_lower):
                return MessageCategory.FILE_OP
        
        if "?" in content or "question" in content_lower:
            return MessageCategory.QUESTION
        
        if any(w in content_lower for w in ["completed", "finished", "done", "progress"]):
            return MessageCategory.PROGRESS
        
        if "tool" in content_lower or "result" in content_lower:
            return MessageCategory.TOOL_RESULT
        
        return MessageCategory.GENERAL
    
    def score_message(self, content: str, role: str = "assistant") -> ImportanceScore:
        """
        Score a message's importance.
        
        Returns ImportanceScore with total score (0-1), category, and reasoning.
        """
        category = self.classify_message(content)
        base_score = self.CATEGORY_BASE_SCORES[category]
        content_lower = content.lower()
        
        # Apply keyword boosts
        boost = 0.0
        for keyword, boost_value in self.BOOST_KEYWORDS.items():
            if keyword in content_lower:
                boost += boost_value
        
        # Apply keyword reductions
        for keyword, reduce_value in self.REDUCE_KEYWORDS.items():
            if keyword in content_lower:
                boost += reduce_value
        
        # Role-based adjustments
        if role == "user":
            boost += 0.1  # User messages are often important context
        
        # Length penalty for very short or very long messages
        length = len(content)
        if length < 20:
            boost -= 0.1  # Very short, likely not important
        elif length > 5000:
            boost -= 0.2  # Very long, likely verbose
        
        # Calculate final score
        total = max(0.0, min(1.0, base_score + boost))
        is_critical = category in [MessageCategory.ERROR, MessageCategory.API_SPEC] and total > 0.7
        
        reason = f"Category: {category.value}, base={base_score:.2f}, boost={boost:+.2f}"
        
        return ImportanceScore(
            total=total,
            category=category,
            is_critical=is_critical,
            reason=reason
        )
    
    def filter_by_importance(
        self, 
        messages: List[Dict], 
        min_score: float = 0.4,
        always_keep_critical: bool = True
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        Filter messages by importance score.
        
        Returns (important_messages, low_importance_messages).
        """
        important = []
        low_importance = []
        
        for msg in messages:
            content = self._get_content(msg)
            role = self._get_role(msg)
            score = self.score_message(content, role)
            
            if score.total >= min_score or (always_keep_critical and score.is_critical):
                important.append(msg)
            else:
                low_importance.append(msg)
        
        return important, low_importance
    
    def _get_role(self, msg) -> str:
        if hasattr(msg, 'role'):
            return msg.role
        elif isinstance(msg, dict):
            return msg.get("role", "unknown")
        return "unknown"
    
    def _get_content(self, msg) -> str:
        if hasattr(msg, 'content'):
            return msg.content or ""
        elif isinstance(msg, dict):
            return msg.get("content", "")
        return str(msg)


# ==================== Smart Message Compressor ====================

CATEGORIZED_CONDENSER_PROMPT = """You are writing a WORKING-STATE HANDOFF for a coding agent that is MID-IMPLEMENTATION
and must KEEP WRITING CODE on the very next turn. This is NOT a retrospective report — it is
a launch pad. Optimize every sentence for "what do I write next", not "what did I do".

The agent's recent code and tool history continues verbatim below this handoff, so do NOT
restate it. Capture only the durable facts the agent would otherwise forget once the older
turns are dropped.

=== ERRORS & FIXES (carry forward only if still UNRESOLVED) ===
{errors}

=== KEY DECISIONS / CONVENTIONS to keep obeying ===
{decisions}

=== API SPECIFICATIONS / SCHEMAS still in force ===
{api_specs}

=== FILE OPERATIONS (names + purpose only) ===
{file_ops}

=== TOOL RESULTS ===
{tool_results}

=== OTHER MESSAGES ===
{others}

Produce a SHORT handoff (max 1200 tokens) with EXACTLY these sections, in order:

## STILL TO DO
The concrete remaining work — endpoints/routes/tasks that do NOT yet have code. Be specific
(method + path or task name). If you cannot tell what remains from the history above, write
exactly: "Query your open/assigned tasks ONCE, then implement the first one."

## CONVENTIONS IN FORCE
The decisions, API specs, schemas, and unresolved errors the next code must respect. Bullets only.

## ALREADY DONE (one line)
A single line naming the files/endpoints already completed, so the agent does not redo them.

Do NOT add a "next steps" pep talk, do NOT re-summarize the recent turns, do NOT include code —
the agent already has its most recent code example verbatim below."""


# Tool names whose assistant(tool_calls)+result pair is a concrete code anchor.
# When condensing, the single most-recent such pair is pinned into the kept set
# VERBATIM so a coding agent always has a fresh handler to copy from instead of a
# collapsed "wrote X to path" line. Mirrors the file-write set used elsewhere in
# the runtime (context_management / tooling).
CODE_WRITE_TOOL_NAMES = frozenset({"write", "edit", "apply_patch"})


# Forward-directive imperative appended to every condensation handoff so the
# message reads as a resume-work instruction rather than a reflective recap. The
# reflective framing was the momentum killer: after the first condensation the
# coding lane saw a "here is a summary of your history" block and dropped into
# reflect/re-plan mode (looping on memory-bank reads) instead of writing the next
# handler. This line keeps it in code-now mode.
RESUME_DIRECTIVE = (
    "RESUME NOW: you are mid-implementation. Continue by WRITING CODE for the next "
    "item under 'STILL TO DO' — copy the structure of the most-recent handler shown "
    "verbatim below. Do NOT re-plan, do NOT re-summarize, do NOT re-read files that "
    "are already written, and do NOT update the memory bank before you have written "
    "the next handler. If 'STILL TO DO' is unclear, query your open tasks ONCE then "
    "implement the first one."
)


class SmartMessageCompressor:
    """
    Smart message compressor that:
    1. Classifies messages by category
    2. Scores importance
    3. Applies category-specific compression strategies
    4. Preserves critical information
    5. Pins the most-recent code-writing tool pair verbatim (code anchor) and
       emits a forward-directive handoff so a coding lane keeps implementing.
    """

    def __init__(self, llm: Optional[LLM] = None):
        self.llm = llm
        self.scorer = MessageImportanceScorer()
        self._compression_count = 0
        self._last_summary = ""
        self._logger = logging.getLogger("smart_compressor")
    
    async def compress(
        self, 
        messages: List[Dict],
        keep_recent: int = 15,
        min_importance: float = 0.4
    ) -> Tuple[List[Dict], str]:
        """
        Smart compress messages.
        
        Args:
            messages: All messages
            keep_recent: Number of recent messages to always keep
            min_importance: Minimum importance score to keep without summarizing
            
        Returns:
            (compressed_messages, summary_of_removed)
        """
        if len(messages) <= keep_recent:
            return messages, ""

        # Separate system messages
        system_msgs = [m for m in messages if self._get_role(m) == "system"]
        other_msgs = [m for m in messages if self._get_role(m) != "system"]

        if len(other_msgs) <= keep_recent:
            return messages, ""

        # Find safe cut-off point
        cut_off = self._find_safe_cutoff(other_msgs, keep_recent)
        if cut_off <= 5:  # Not worth compressing
            return messages, ""

        to_compress = other_msgs[:cut_off]
        to_keep = other_msgs[cut_off:]

        # CODE ANCHOR: if the most-recent file-write assistant(tool_calls)+result
        # pair lives in the about-to-be-condensed segment, lift it (verbatim) to
        # the FRONT of the kept set instead of letting it collapse into a summary
        # line. A coding lane copies the structure of its last handler; losing that
        # concrete example is a big part of why momentum stalled after the first
        # condensation. _extract_code_anchor preserves tool_call/tool pairing.
        anchor_pair = self._extract_code_anchor(to_compress)
        if anchor_pair:
            to_keep = anchor_pair + to_keep

        # Best-effort remaining-work hint, derived from the about-to-be-dropped
        # segment, so the handoff names unfinished endpoints/tasks even before the
        # framework re-injects its per-step impl directive.
        remaining_work = self._derive_remaining_work(to_compress)

        # Classify messages
        categorized = self._categorize_messages(to_compress)

        # Generate summary
        if self.llm:
            summary = await self._llm_categorized_compress(categorized)
        else:
            summary = self._simple_categorized_compress(categorized)

        self._compression_count += 1
        self._last_summary = summary

        # Forward-directive handoff message. Framed as an active working-state
        # directive (NOT "[SMART CONTEXT SUMMARY]") and ALWAYS ended with the
        # resume imperative so the lane stays in code-now mode.
        summary_content = self._build_directive_message(
            summary=summary,
            remaining_work=remaining_work,
            has_anchor=bool(anchor_pair),
        )

        if messages and hasattr(messages[0], 'role'):
            from utils.llm import Message
            summary_msg = Message.user(summary_content)
        else:
            summary_msg = {"role": "user", "content": summary_content}

        return system_msgs + [summary_msg] + to_keep, summary
    
    def _categorize_messages(self, messages: List[Dict]) -> Dict[MessageCategory, List[Dict]]:
        """Categorize messages by type."""
        categorized = {cat: [] for cat in MessageCategory}

        for msg in messages:
            content = self._get_content(msg)
            category = self.scorer.classify_message(content)
            categorized[category].append(msg)

        return categorized

    def _get_tool_calls(self, msg) -> List[Any]:
        """Read an assistant message's tool_calls (Message object or dict)."""
        if hasattr(msg, "tool_calls"):
            return list(msg.tool_calls or [])
        if isinstance(msg, dict):
            return list(msg.get("tool_calls") or [])
        return []

    def _get_tool_call_id(self, msg) -> str:
        """Read a tool result's parent id (Message object or dict)."""
        if hasattr(msg, "tool_call_id"):
            return msg.tool_call_id or ""
        if isinstance(msg, dict):
            return str(msg.get("tool_call_id") or "")
        return ""

    @staticmethod
    def _tool_call_name(tc: Any) -> str:
        """Extract the tool name from a tool_call (object or dict shape)."""
        fn = getattr(tc, "function", None)
        if fn is not None:
            name = getattr(fn, "name", None)
            if name:
                return str(name)
        if isinstance(tc, dict):
            fn = tc.get("function") or {}
            if isinstance(fn, dict) and fn.get("name"):
                return str(fn["name"])
            if tc.get("name"):
                return str(tc["name"])
        return ""

    @staticmethod
    def _tool_call_id_of(tc: Any) -> str:
        """Extract the id from a tool_call (object or dict shape)."""
        tid = getattr(tc, "id", None)
        if tid:
            return str(tid)
        if isinstance(tc, dict) and tc.get("id"):
            return str(tc["id"])
        return ""

    def _extract_code_anchor(self, messages: List[Dict]) -> List[Dict]:
        """Return the most-recent file-write assistant(tool_calls)+result pair.

        Walks ``messages`` from the end and finds the last assistant message
        whose ``tool_calls`` include a file-writing tool. Returns that assistant
        message followed by every immediately-following ``tool`` result that
        answers one of its tool_calls — so the returned slice is a self-contained,
        pairing-valid block that can be prepended to the kept set. Returns ``[]``
        when no such pair exists (e.g. nothing was written in the dropped span).
        """
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            if self._get_role(msg) != "assistant":
                continue
            tcs = self._get_tool_calls(msg)
            if not tcs:
                continue
            names = {self._tool_call_name(tc) for tc in tcs}
            if not (names & CODE_WRITE_TOOL_NAMES):
                continue
            call_ids = {self._tool_call_id_of(tc) for tc in tcs if self._tool_call_id_of(tc)}
            anchor = [msg]
            # Gather the tool results that answer this assistant's calls.
            j = i + 1
            while j < len(messages) and self._get_role(messages[j]) == "tool":
                result_id = self._get_tool_call_id(messages[j])
                # Keep contiguous tool results; if ids are present, only keep the
                # ones belonging to this assistant so we never carry an orphan.
                if call_ids and result_id and result_id not in call_ids:
                    break
                anchor.append(messages[j])
                j += 1
            return anchor
        return []

    def _derive_remaining_work(self, messages: List[Dict]) -> str:
        """Best-effort list of endpoints/routes registered but not yet implemented.

        Scans the dropped span for ``METHOD /path`` mentions and for any
        framework-tracked "still have NO route code" / "NEXT to implement"
        directives, returning a short newline-joined hint. Returns "" when nothing
        useful is derivable — in which case the handoff instructs the agent to
        query its open tasks once instead.
        """
        next_hints: List[str] = []
        endpoints: List[str] = []
        seen: Set[str] = set()
        for msg in messages:
            content = self._get_content(msg)
            if not content:
                continue
            # Framework-tracked "NEXT to implement: [...]" lines are authoritative.
            for m in re.finditer(r"NEXT to implement:\s*(.+)", content):
                hint = m.group(1).strip()[:200]
                if hint and hint not in next_hints:
                    next_hints.append(hint)
            # Generic METHOD /path mentions as a fallback.
            for m in re.finditer(
                r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/[\w/{}.:-]*)", content
            ):
                ep = f"{m.group(1)} {m.group(2)}"
                if ep not in seen:
                    seen.add(ep)
                    endpoints.append(ep)
        if next_hints:
            return "Framework-tracked next: " + " | ".join(next_hints[:3])
        if endpoints:
            return "Endpoints seen (verify which still lack a handler): " + ", ".join(
                endpoints[:8]
            )
        return ""

    def _build_directive_message(
        self,
        *,
        summary: str,
        remaining_work: str,
        has_anchor: bool,
    ) -> str:
        """Assemble the forward-directive handoff message.

        Shape: a working-state header, the (forward-framed) handoff summary, the
        derived remaining-work hint, a pointer to the verbatim code anchor when
        present, and ALWAYS the resume imperative last so the final thing the lane
        reads is "write code now".
        """
        parts: List[str] = [
            f"[WORKING STATE — condense #{self._compression_count}] "
            "Older turns were folded into this handoff so you can keep implementing. "
            "Treat it as your launch pad, not a report to review."
        ]
        if summary and summary.strip():
            parts.append(summary.strip())
        if remaining_work:
            parts.append(f"REMAINING WORK (derived): {remaining_work}")
        if has_anchor:
            parts.append(
                "Your most-recent file-write tool call + its result are preserved "
                "VERBATIM in the recent history below — copy that handler's shape "
                "for the next one."
            )
        parts.append(RESUME_DIRECTIVE)
        return "\n\n".join(parts)
    
    async def _llm_categorized_compress(self, categorized: Dict[MessageCategory, List[Dict]]) -> str:
        """Use LLM to compress categorized messages."""
        def format_msgs(msgs: List[Dict], max_chars: int = 3000) -> str:
            if not msgs:
                return "(none)"
            
            formatted = []
            total_chars = 0
            for msg in msgs:
                content = self._get_content(msg)[:500]
                role = self._get_role(msg)
                line = f"- [{role}] {content}"
                if total_chars + len(line) > max_chars:
                    formatted.append("... (more messages truncated)")
                    break
                formatted.append(line)
                total_chars += len(line)
            
            return "\n".join(formatted)
        
        prompt = CATEGORIZED_CONDENSER_PROMPT.format(
            errors=format_msgs(categorized[MessageCategory.ERROR]),
            decisions=format_msgs(categorized[MessageCategory.DECISION]),
            api_specs=format_msgs(categorized[MessageCategory.API_SPEC]),
            file_ops=format_msgs(categorized[MessageCategory.FILE_OP]),
            tool_results=format_msgs(categorized[MessageCategory.TOOL_RESULT], max_chars=1000),
            others=format_msgs(
                categorized[MessageCategory.GENERAL] + 
                categorized[MessageCategory.PROGRESS] + 
                categorized[MessageCategory.QUESTION],
                max_chars=1000
            ),
        )
        
        try:
            return await self.llm.chat(prompt, temperature=0.3)
        except Exception as e:
            self._logger.error(f"LLM compression failed: {e}")
            return self._simple_categorized_compress(categorized)
    
    def _simple_categorized_compress(self, categorized: Dict[MessageCategory, List[Dict]]) -> str:
        """Forward-framed compression without an LLM.

        Mirrors the LLM prompt's section order (STILL TO DO / CONVENTIONS IN
        FORCE / ALREADY DONE) so the no-LLM fallback reads as a launch pad too.
        The caller appends the resume imperative, so this only supplies content.
        """
        sections: List[str] = ["## STILL TO DO"]
        # Remaining work is derived by the caller and placed in the directive
        # message; here we point the agent at it explicitly.
        sections.append(
            "- See REMAINING WORK below, or query your open/assigned tasks ONCE "
            "then implement the first one."
        )

        conventions: List[str] = []
        for msg in categorized[MessageCategory.API_SPEC][:5]:
            conventions.append(f"- API spec: {self._get_content(msg)[:200]}")
        for msg in categorized[MessageCategory.DECISION][:5]:
            conventions.append(f"- Decision: {self._get_content(msg)[:200]}")
        for msg in categorized[MessageCategory.ERROR][:5]:
            conventions.append(f"- Watch (error/fix): {self._get_content(msg)[:200]}")
        if conventions:
            sections.append("\n## CONVENTIONS IN FORCE")
            sections.extend(conventions)

        # ALREADY DONE: one line of file names so the agent does not redo them.
        file_ops = categorized[MessageCategory.FILE_OP]
        if file_ops:
            paths = set()
            for msg in file_ops:
                content = self._get_content(msg)
                for match in re.finditer(r'[\w/.-]+\.(jsx?|tsx?|py|sql|json|md)', content):
                    paths.add(match.group())
            done_line = ", ".join(list(paths)[:10]) if paths else f"{len(file_ops)} file ops"
            sections.append(f"\n## ALREADY DONE (do not redo)\n- {done_line}")

        return "\n".join(sections)
    
    def _find_safe_cutoff(self, msgs: List, target_keep: int) -> int:
        """Find safe cut-off that doesn't break message pairs.

        ``to_keep = msgs[cut_off:]`` must NOT begin with an orphan ``tool``
        message whose parent ``assistant`` (carrying its ``tool_calls``) is
        condensed away. The only illegal landing is a ``tool`` index; a
        ``user`` or ``assistant`` index is always safe (an assistant's tool
        results follow it and stay together inside ``to_keep``).

        Previous bug (the messages=770 root cause): the walk also stepped
        backward whenever it landed on an ``assistant`` with tool_calls that
        was followed by a tool result. In a dense block of strictly
        alternating ``assistant(tool_calls)`` / ``tool`` pairs — exactly the
        orchestrator's ``check_inbox`` / communicate pattern — every backward
        step hit either a tool or such an assistant, so the cut degenerated
        all the way to 0 and the smart compressor's ``cut_off <= 5`` guard
        then bailed (return messages, ""). Condensation therefore NEVER fired
        for tool-heavy lanes even though should_condense_messages was True,
        letting the live messages list grow without bound. Stepping back only
        over a run of tool messages lands on the parent assistant and stops,
        so the cut is bounded and tool_call/tool pairs stay intact.
        """
        cut_off = len(msgs) - target_keep
        if cut_off <= 0:
            return 0

        # Step back only over a contiguous run of tool messages (one assistant
        # may emit several tool_calls → several tool results) to land on the
        # parent assistant, which is itself a safe cut point.
        while cut_off > 0 and self._get_role(msgs[cut_off]) == "tool":
            cut_off -= 1

        return max(0, cut_off)
    
    def _get_role(self, msg) -> str:
        if hasattr(msg, 'role'):
            return msg.role
        elif isinstance(msg, dict):
            return msg.get("role", "unknown")
        return "unknown"
    
    def _get_content(self, msg) -> str:
        if hasattr(msg, 'content'):
            return msg.content or ""
        elif isinstance(msg, dict):
            return msg.get("content", "")
        return str(msg)
    
    @property
    def summary(self) -> str:
        return self._last_summary


# ==================== MemoryBank Auto-Sync ====================

class MemoryBankSync:
    """
    Automatically syncs agent activity to MemoryBank.
    
    Tracks:
    - Completed tasks -> progress.md
    - Current focus -> active_context.md
    - Errors and issues -> progress.md (Known Issues)
    - Key decisions -> system_patterns.md
    """
    
    def __init__(self, memory_bank: Optional["MemoryBank"] = None):
        self.memory_bank = memory_bank
        self._pending_updates: Dict[str, List[str]] = {
            "completed": [],
            "in_progress": [],
            "issues": [],
            "decisions": [],
        }
        self._last_sync = datetime.now()
        self._logger = logging.getLogger("memory_sync")
    
    def record_completion(self, item: str) -> None:
        """Record a completed task."""
        self._pending_updates["completed"].append(item)
        self._maybe_sync()
    
    def record_progress(self, item: str) -> None:
        """Record current work in progress."""
        self._pending_updates["in_progress"].append(item)
        self._maybe_sync()
    
    def record_issue(self, issue: str) -> None:
        """Record a known issue."""
        self._pending_updates["issues"].append(issue)
        self._maybe_sync()
    
    def record_decision(self, decision: str) -> None:
        """Record a key decision."""
        self._pending_updates["decisions"].append(decision)
        self._maybe_sync()
    
    def _maybe_sync(self) -> None:
        """Sync if enough time has passed or enough updates accumulated."""
        # total_seconds() (not .seconds, which is the 0-86399 intraday component and
        # resets at midnight — breaking the 30s threshold across a day rollover).
        time_since_sync = (datetime.now() - self._last_sync).total_seconds()
        total_pending = sum(len(v) for v in self._pending_updates.values())
        
        # Sync every 30 seconds or when 5+ updates pending
        if time_since_sync >= 30 or total_pending >= 5:
            self.sync()
    
    def sync(self) -> None:
        """Sync pending updates to MemoryBank."""
        if not self.memory_bank:
            return
        
        try:
            # Sync completed items
            for item in self._pending_updates["completed"]:
                self.memory_bank.append_to_progress(item, category="completed")
            
            # Sync in-progress items
            if self._pending_updates["in_progress"]:
                latest = self._pending_updates["in_progress"][-1]
                self.memory_bank.update_active_context(
                    focus=f"Working on: {latest}",
                    recent_change=latest
                )
            
            # Sync issues
            for issue in self._pending_updates["issues"]:
                self.memory_bank.append_to_progress(issue, category="issues")

            # Sync decisions
            for decision in self._pending_updates["decisions"]:
                if hasattr(self.memory_bank, "append_decision"):
                    self.memory_bank.append_decision(decision)
            
            # Clear pending
            for key in self._pending_updates:
                self._pending_updates[key] = []
            
            self._last_sync = datetime.now()
            self._logger.debug("Synced to MemoryBank")
            
        except Exception as e:
            self._logger.error(f"MemoryBank sync failed: {e}")
    
    def force_sync(self) -> None:
        """Force immediate sync."""
        self.sync()


# ==================== Legacy Message Condensation ====================

MESSAGE_CONDENSER_PROMPT = """You are writing a WORKING-STATE HANDOFF for a coding agent that is MID-IMPLEMENTATION
and must KEEP WRITING CODE on the very next turn. This is a launch pad, NOT a retrospective.
The agent's most recent code and tool history continues verbatim below this handoff, so do NOT
restate it — capture only what the agent would otherwise forget once the older turns drop off.

The agent works on code generation with tools like write, read, edit, apply_patch, lint.

<MESSAGE_HISTORY>
{messages}
</MESSAGE_HISTORY>

Produce a SHORT handoff (max 1200 tokens) with EXACTLY these sections, in order:

## STILL TO DO
The concrete remaining work — endpoints/routes/tasks that do NOT yet have code. Be specific
(method + path or task name). If the remaining work is not clear from the history above, write
exactly: "Query your open/assigned tasks ONCE, then implement the first one."

## CONVENTIONS IN FORCE
The decisions, API specs/schemas, and any still-UNRESOLVED errors the next code must respect.

## ALREADY DONE (one line)
A single line naming files/endpoints already completed, so the agent does not redo them.

Do NOT add a "next steps" pep talk, do NOT re-summarize the recent turns, do NOT paste code."""


@dataclass
class ConversationCondenser:
    """
    Condenses LLM conversation messages when they grow too long.
    
    Now uses SmartMessageCompressor for intelligent category-based compression.
    Unlike memory-based condensation, this works directly on the
    messages list used in the agentic loop.
    """
    
    llm: Optional[LLM] = None
    max_messages: int = 60  # Trigger condensation after this many messages
    keep_recent: int = 28   # Always keep this many recent messages
    # keep_recent was 15 — too aggressive once condensation actually fired: it
    # dropped the working context (current task spec, file structure, recent code)
    # the lane needs to keep WRITING code, so the backend looped on memory-bank
    # bookkeeping instead of implementing (2 endpoints vs 18 pre-condensation-fix).
    # 28 keeps enough to code while staying far below the ~770-message saturation.
    use_smart_compression: bool = True  # Use new smart compressor
    _condensation_count: int = 0
    _last_summary: str = ""
    _smart_compressor: Optional[SmartMessageCompressor] = None
    
    def __post_init__(self):
        """Initialize smart compressor if enabled."""
        if self.use_smart_compression:
            self._smart_compressor = SmartMessageCompressor(llm=self.llm)
    
    async def maybe_condense(self, messages: List[Dict]) -> List[Dict]:
        """
        Condense messages if they exceed threshold.
        
        Args:
            messages: List of message dicts (role, content)
            
        Returns:
            Condensed messages list (or original if no condensation needed)
        """
        if len(messages) <= self.max_messages:
            return messages
        
        # Use smart compression if available
        if self.use_smart_compression and self._smart_compressor:
            compressed, summary = await self._smart_compressor.compress(
                messages, 
                keep_recent=self.keep_recent
            )
            if summary:
                self._condensation_count += 1
                self._last_summary = summary
            return compressed
        
        if not self.llm:
            # No LLM available - simple truncation
            return self._simple_truncate(messages)
        
        return await self._llm_condense(messages)
    
    def _get_role(self, msg) -> str:
        """Get role from message (works with both dict and Message objects)."""
        if hasattr(msg, 'role'):
            return msg.role
        elif isinstance(msg, dict):
            return msg.get("role", "unknown")
        return "unknown"
    
    def _get_content(self, msg) -> str:
        """Get content from message (works with both dict and Message objects)."""
        if hasattr(msg, 'content'):
            return msg.content or ""
        elif isinstance(msg, dict):
            return msg.get("content", "")
        return str(msg)
    
    def _find_safe_cutoff(self, other_msgs: List, target_keep: int) -> int:
        """Find a safe cut-off point that doesn't break assistant+tool message pairs.

        ``to_keep = other_msgs[cut_off:]`` must NOT begin with an orphan
        ``tool`` message — i.e. a tool result whose parent ``assistant``
        (the one carrying its ``tool_calls``) would be condensed away. The
        ONLY illegal cut index is one that points at a ``tool`` message;
        cutting at a ``user`` or ``assistant`` message is always safe (if
        that assistant has tool_calls, its tool results follow it and remain
        together inside ``to_keep``).

        Previous bug: the walk also stepped backward whenever it landed on an
        ``assistant`` that had tool_calls followed by a tool result. In a dense
        block of strictly alternating ``assistant(tool_calls)`` / ``tool``
        pairs — exactly the orchestrator's ``check_inbox`` / communicate
        pattern — every backward step hit either a tool or such an assistant,
        so the walk degenerated all the way to 0 and condensation NEVER fired.
        That is how a tool-heavy lane reached messages=770 despite
        should_condense_messages being True. Stepping back only off a ``tool``
        index lands on its parent assistant and stops, so the cut is bounded
        and pairs stay intact.
        """
        cut_off = len(other_msgs) - target_keep

        if cut_off <= 0:
            return 0

        # The only unsafe landing is a tool message (its parent assistant
        # would be condensed away). Step back over any run of tool messages
        # (an assistant may emit several tool_calls → several tool results) to
        # land on the parent assistant, which is itself a safe cut point.
        while cut_off > 0 and self._get_role(other_msgs[cut_off]) == "tool":
            cut_off -= 1

        return max(0, cut_off)
    
    def _simple_truncate(self, messages: List) -> List:
        """Simple truncation without LLM."""
        # Keep system message + recent messages
        system_msgs = [m for m in messages if self._get_role(m) == "system"]
        other_msgs = [m for m in messages if self._get_role(m) != "system"]
        
        if len(other_msgs) <= self.keep_recent:
            return messages
        
        # Find safe cut-off point
        cut_off = self._find_safe_cutoff(other_msgs, self.keep_recent)
        
        if cut_off <= 0:
            return messages
        
        to_keep = other_msgs[cut_off:]
        
        # Forward-directive truncation notice (no LLM): keep the lane in code-now
        # mode rather than handing it a passive "messages condensed" recap.
        truncated_count = cut_off
        summary_content = (
            f"[WORKING STATE] {truncated_count} older turns were folded away; your "
            f"recent history below is current. {RESUME_DIRECTIVE}"
        )
        
        # Return same type as input - check if using Message objects
        if hasattr(messages[0], 'role'):
            # Import Message class dynamically
            from utils.llm import Message
            summary_msg = Message.user(summary_content)
        else:
            summary_msg = {"role": "user", "content": summary_content}
        
        return system_msgs + [summary_msg] + to_keep
    
    async def _llm_condense(self, messages: List) -> List:
        """Condense using LLM summarization."""
        # Keep system messages and recent messages
        system_msgs = [m for m in messages if self._get_role(m) == "system"]
        other_msgs = [m for m in messages if self._get_role(m) != "system"]
        
        if len(other_msgs) <= self.keep_recent:
            return messages
        
        # Find safe cut-off point
        cut_off = self._find_safe_cutoff(other_msgs, self.keep_recent)
        
        if cut_off <= 0:
            # Can't condense safely
            return messages
        
        to_condense = other_msgs[:cut_off]
        to_keep = other_msgs[cut_off:]
        
        # Format messages for condensation
        formatted = []
        for msg in to_condense:
            role = self._get_role(msg)
            content = self._get_content(msg)
            if isinstance(content, list):
                # Handle multi-part content
                content = " ".join(str(c.get("text", c)) if isinstance(c, dict) else str(c) for c in content)
            # Truncate very long content
            if len(str(content)) > 2000:
                content = str(content)[:2000] + "... [truncated]"
            formatted.append(f"[{role}] {content}")
        
        messages_text = "\n\n".join(formatted)
        
        # Generate summary
        prompt = MESSAGE_CONDENSER_PROMPT.format(messages=messages_text)
        
        try:
            summary = await self.llm.chat(prompt, temperature=0.3)
            self._last_summary = summary
            self._condensation_count += 1
            
            summary_content = (
                f"[WORKING STATE — condense #{self._condensation_count}] "
                f"Older turns were folded into this handoff so you can keep "
                f"implementing.\n\n{summary}\n\n{RESUME_DIRECTIVE}"
            )
            
            # Return same type as input - check if using Message objects
            if messages and hasattr(messages[0], 'role'):
                from utils.llm import Message
                summary_msg = Message.user(summary_content)
            else:
                summary_msg = {"role": "user", "content": summary_content}
            
            return system_msgs + [summary_msg] + to_keep
            
        except Exception as e:
            logging.getLogger("condenser").error(f"LLM condensation failed: {e}")
            return self._simple_truncate(messages)
    
    @property
    def summary(self) -> str:
        return self._last_summary


# ==================== Enhanced Generator Memory ====================

class GeneratorMemory(AgentMemory):
    """
    Enhanced memory system for code generation agents.
    
    Features:
    1. Conversation condensation - Works with messages list
    2. Knowledge extraction - Auto-extract learnings from completed tasks
    3. Cross-agent sharing - Share important info with other agents
    4. Semantic recall - Search memory by meaning (when embeddings available)
    5. Smart compression - Category-based message compression
    6. Importance scoring - Preserve high-value messages
    7. Auto MemoryBank sync - Automatically update progress
    """
    
    def __init__(
        self,
        llm: LLM = None,
        short_term_size: int = 100,
        long_term_size: int = 1000,
        condenser_max_size: int = 80,
        memory_bank: Optional["MemoryBank"] = None,
        persistence_mode: str = "session",
        persistence_path: Optional[str] = None,
        knowledge_ttl_seconds: Optional[int] = None,
    ):
        # Create LLM wrapper for condenser
        async def llm_func(prompt: str) -> str:
            if llm:
                return await llm.chat(prompt, temperature=0.3)
            return "[Condensation unavailable - no LLM provided]"
        
        super().__init__(
            short_term_size=short_term_size,
            long_term_size=long_term_size,
            condenser_llm_func=llm_func if llm else None,
            condenser_max_size=condenser_max_size,
        )
        
        self._llm = llm
        self._logger = logging.getLogger("generator_memory")
        
        # Conversation condenser (for messages list) - now with smart compression.
        # Honor condenser_max_size here too: previously this ignored the
        # caller's condenser_max_size and silently used the dataclass default
        # (max_messages=60), so should_condense_messages/condense_messages
        # never matched the intended ~30 threshold. Bounding the live messages
        # list is what keeps each LLM call's context from growing unbounded.
        self.conversation_condenser = ConversationCondenser(
            llm=llm,
            max_messages=condenser_max_size,
            use_smart_compression=True,
        )
        
        # Importance scorer for filtering messages
        self.importance_scorer = MessageImportanceScorer()
        
        # MemoryBank auto-sync
        self.memory_bank_sync = MemoryBankSync(memory_bank=memory_bank)
        
        # File operation tracking
        self._files_created: Set[str] = set()
        self._files_modified: Set[str] = set()
        self._files_linted: Set[str] = set()
        self._lint_results: Dict[str, bool] = {}  # path -> passed
        
        # Tool call tracking
        self._tool_calls: List[Dict[str, Any]] = []
        self._tool_call_counts: Dict[str, int] = {}
        self._consecutive_same_tool: int = 0
        self._last_tool: str = ""
        
        # Knowledge store (important learnings)
        self._knowledge: List[Dict[str, Any]] = []
        
        # Phase tracking
        self._current_phase: str = ""
        self._phase_start_time: Optional[datetime] = None
        
        # Error tracking
        self._errors: List[Dict[str, Any]] = []
        
        # Cross-agent message queue
        self._outgoing_knowledge: List[Dict[str, Any]] = []
        
        # Working memory (current task context, plans, etc.)
        self._working_memory: Dict[str, Any] = {}
        self._auto_knowledge_min_chars: int = 80
        self._auto_knowledge_min_tokens: int = 8
        self._auto_knowledge_dedup_ttl_seconds: int = 3600
        self._recent_auto_knowledge_fingerprints: Dict[str, datetime] = {}
        self._auto_knowledge_attempted_total: int = 0
        self._auto_knowledge_stored_total: int = 0
        self._auto_knowledge_dedup_skipped_total: int = 0
        self._auto_knowledge_quality_skipped_total: int = 0
        self._knowledge_expired_removed_total: int = 0

        # Optional persistent knowledge lifecycle
        self._persistence_mode = (persistence_mode or "session").lower()
        self._persistence_path = Path(persistence_path) if persistence_path else None
        self._knowledge_ttl_seconds = knowledge_ttl_seconds
        self._persist_flush_every = 10
        self._knowledge_since_flush = 0
        self._load_persisted_knowledge()
        self.cleanup_expired_knowledge()

    # ==================== Knowledge Persistence Lifecycle ====================

    def _normalize_persistence_mode(self) -> str:
        mode = self._persistence_mode
        if mode in ("off", "none"):
            return "session"
        if mode not in ("session", "jsonl"):
            return "session"
        return mode

    def _load_persisted_knowledge(self) -> None:
        """
        Load persisted knowledge entries when jsonl mode is enabled.
        """
        mode = self._normalize_persistence_mode()
        if mode != "jsonl" or not self._persistence_path:
            return
        if not self._persistence_path.exists():
            return

        loaded: List[Dict[str, Any]] = []
        try:
            with self._persistence_path.open("r", encoding="utf-8") as f:
                for line in f:
                    raw = line.strip()
                    if not raw:
                        continue
                    try:
                        entry = json.loads(raw)
                    except Exception:
                        continue
                    if isinstance(entry, dict):
                        loaded.append(entry)
        except Exception as e:
            self._logger.warning(f"Failed loading persisted knowledge: {e}")
            return

        # Deduplicate by id while preserving load order.
        merged = {str(item.get("id", "")): item for item in self._knowledge if isinstance(item, dict)}
        for item in loaded:
            item_id = str(item.get("id", ""))
            if item_id and item_id not in merged:
                merged[item_id] = item

        self._knowledge = list(merged.values())
        self._logger.info(f"Loaded {len(loaded)} persisted knowledge items")

    def _append_persisted_knowledge(self, entry: Dict[str, Any]) -> None:
        """
        Append one knowledge entry to jsonl persistence (best effort).
        """
        mode = self._normalize_persistence_mode()
        if mode != "jsonl" or not self._persistence_path:
            return
        try:
            self._persistence_path.parent.mkdir(parents=True, exist_ok=True)
            with self._persistence_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=True))
                f.write("\n")
            self._knowledge_since_flush += 1
            if self._knowledge_since_flush >= self._persist_flush_every:
                self._compact_persisted_knowledge()
                self._knowledge_since_flush = 0
        except Exception as e:
            self._logger.warning(f"Failed persisting knowledge item: {e}")

    def _compact_persisted_knowledge(self) -> None:
        """
        Rewrite persisted jsonl to remove duplicates and expired entries.
        """
        mode = self._normalize_persistence_mode()
        if mode != "jsonl" or not self._persistence_path:
            return
        try:
            self.cleanup_expired_knowledge()
            self._persistence_path.parent.mkdir(parents=True, exist_ok=True)
            with self._persistence_path.open("w", encoding="utf-8") as f:
                for item in self._knowledge:
                    f.write(json.dumps(item, ensure_ascii=True))
                    f.write("\n")
        except Exception as e:
            self._logger.warning(f"Failed compacting persisted knowledge: {e}")

    def cleanup_expired_knowledge(self, ttl_seconds: Optional[int] = None) -> int:
        """
        Remove knowledge older than TTL from in-memory store (and persisted store via compaction).

        Returns:
            Number of removed entries.
        """
        ttl = ttl_seconds if ttl_seconds is not None else self._knowledge_ttl_seconds
        if not ttl or ttl <= 0:
            return 0

        now = datetime.now()
        kept: List[Dict[str, Any]] = []
        removed = 0
        for entry in self._knowledge:
            ts = self._parse_iso_timestamp(str(entry.get("timestamp", "")))
            if ts is None:
                kept.append(entry)
                continue
            age_seconds = (now - ts).total_seconds()
            if age_seconds > ttl:
                removed += 1
            else:
                kept.append(entry)
        self._knowledge = kept
        self._knowledge_expired_removed_total += removed
        return removed

    def configure_persistence(
        self,
        mode: str = "session",
        path: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
    ) -> None:
        """
        Configure memory lifecycle mode at runtime.

        mode:
            - session: in-memory only
            - jsonl: append-only JSONL persistence + periodic compaction
        """
        self._persistence_mode = (mode or "session").lower()
        if path:
            self._persistence_path = Path(path)
        self._knowledge_ttl_seconds = ttl_seconds
        self._load_persisted_knowledge()
        self.cleanup_expired_knowledge()

    def configure_auto_knowledge(
        self,
        min_chars: int = 80,
        min_tokens: int = 8,
        dedup_ttl_seconds: int = 3600,
    ) -> None:
        """Configure quality and dedup thresholds for auto knowledge extraction."""
        self._auto_knowledge_min_chars = max(20, int(min_chars))
        self._auto_knowledge_min_tokens = max(3, int(min_tokens))
        self._auto_knowledge_dedup_ttl_seconds = max(60, int(dedup_ttl_seconds))
    
    # ==================== MemoryBank Integration ====================
    
    def bind_memory_bank(self, memory_bank: "MemoryBank") -> None:
        """Bind a MemoryBank instance for auto-sync."""
        self.memory_bank_sync = MemoryBankSync(memory_bank=memory_bank)
        self._logger.info("Bound MemoryBank for auto-sync")
    
    def sync_to_memory_bank(self) -> None:
        """Force immediate sync to MemoryBank."""
        if self.memory_bank_sync:
            self.memory_bank_sync.force_sync()
    
    # ==================== Conversation Management ====================
    
    async def condense_messages(self, messages: List[Dict]) -> List[Dict]:
        """
        Condense conversation messages if they're too long.
        
        Call this in the agentic loop periodically.
        
        Args:
            messages: Current messages list
            
        Returns:
            Condensed messages (or original if no condensation needed)
        """
        return await self.conversation_condenser.maybe_condense(messages)
    
    def should_condense_messages(self, messages: List[Dict]) -> bool:
        """Check if messages should be condensed."""
        return len(messages) > self.conversation_condenser.max_messages
    
    def score_message_importance(self, content: str, role: str = "assistant") -> ImportanceScore:
        """
        Score a message's importance.
        
        Args:
            content: Message content
            role: Message role (user, assistant, tool)
            
        Returns:
            ImportanceScore with total, category, is_critical
        """
        return self.importance_scorer.score_message(content, role)
    
    def filter_messages_by_importance(
        self, 
        messages: List[Dict], 
        min_score: float = 0.4
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        Filter messages by importance score.
        
        Args:
            messages: Messages to filter
            min_score: Minimum importance score to keep
            
        Returns:
            (important_messages, low_importance_messages)
        """
        return self.importance_scorer.filter_by_importance(messages, min_score)
    
    def get_message_category(self, content: str) -> MessageCategory:
        """Classify a message into a category."""
        return self.importance_scorer.classify_message(content)
    
    # ==================== Tool Call Tracking ====================
    
    def record_tool_call(
        self, 
        tool_name: str, 
        tool_args: Dict[str, Any], 
        result: Any,
        success: bool = True,
        duration_ms: int = 0
    ) -> Dict[str, Any]:
        """
        Record a tool call with full details.
        
        Args:
            tool_name: Name of the tool
            tool_args: Arguments passed to tool
            result: Tool result (will be truncated)
            success: Whether the call succeeded
            duration_ms: Execution time in milliseconds
            
        Returns:
            Dict with loop detection info
        """
        # Update counts
        self._tool_call_counts[tool_name] = self._tool_call_counts.get(tool_name, 0) + 1
        
        if tool_name == self._last_tool:
            self._consecutive_same_tool += 1
        else:
            self._consecutive_same_tool = 1
        self._last_tool = tool_name
        
        # Create record
        record = {
            "tool": tool_name,
            "args_summary": self._summarize_args(tool_args),
            "success": success,
            "timestamp": datetime.now().isoformat(),
            "duration_ms": duration_ms,
        }
        
        # Track errors
        if not success:
            record["error"] = str(result)[:500]
        
        self._tool_calls.append(record)
        
        # Keep last 100 tool calls
        if len(self._tool_calls) > 100:
            self._tool_calls = self._tool_calls[-100:]
        
        # Auto-extract knowledge from certain tool results
        self._maybe_extract_knowledge(tool_name, tool_args, result, success)
        
        return {
            "consecutive_count": self._consecutive_same_tool,
            "total_count": self._tool_call_counts[tool_name],
            "is_potential_loop": self._consecutive_same_tool > 5,
        }
    
    def _summarize_args(self, args: Dict[str, Any]) -> str:
        """Summarize tool arguments for logging."""
        summary = []
        for key, value in args.items():
            if key in ("content", "code", "data") and len(str(value)) > 100:
                summary.append(f"{key}=[{len(str(value))} chars]")
            else:
                val_str = str(value)[:50]
                summary.append(f"{key}={val_str}")
        return ", ".join(summary)

    @staticmethod
    def _normalize_knowledge_content(content: str) -> str:
        """Normalize content for quality checks and dedup fingerprints."""
        if not content:
            return ""
        normalized = re.sub(r"\s+", " ", str(content)).strip().lower()
        return normalized

    def _prune_auto_knowledge_fingerprints(self) -> None:
        """Drop old fingerprints beyond dedup TTL."""
        if not self._recent_auto_knowledge_fingerprints:
            return
        now = datetime.now()
        kept: Dict[str, datetime] = {}
        for fp, ts in self._recent_auto_knowledge_fingerprints.items():
            age = (now - ts).total_seconds()
            if age <= self._auto_knowledge_dedup_ttl_seconds:
                kept[fp] = ts
        self._recent_auto_knowledge_fingerprints = kept

    def _auto_knowledge_fingerprint(self, category: str, content: str) -> str:
        """Create stable fingerprint for auto-extracted entries."""
        normalized = self._normalize_knowledge_content(content)
        raw = f"{category}|{normalized}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _passes_auto_knowledge_quality(self, content: str) -> bool:
        """Quality gate for auto-extracted knowledge to reduce noise."""
        normalized = self._normalize_knowledge_content(content)
        if len(normalized) < self._auto_knowledge_min_chars:
            return False
        token_count = len(re.findall(r"[a-zA-Z0-9_]+", normalized))
        return token_count >= self._auto_knowledge_min_tokens

    def _record_auto_knowledge_if_new(
        self,
        content: str,
        category: str,
        importance: float,
    ) -> bool:
        """
        Store auto-extracted knowledge only if it passes quality and is not duplicated.
        """
        self._auto_knowledge_attempted_total += 1
        if not self._passes_auto_knowledge_quality(content):
            self._auto_knowledge_quality_skipped_total += 1
            return False
        self._prune_auto_knowledge_fingerprints()
        fp = self._auto_knowledge_fingerprint(category, content)
        if fp in self._recent_auto_knowledge_fingerprints:
            self._auto_knowledge_dedup_skipped_total += 1
            return False

        self.add_knowledge(content=content, category=category, importance=importance)
        self._recent_auto_knowledge_fingerprints[fp] = datetime.now()
        self._auto_knowledge_stored_total += 1
        return True

    def get_memory_health_summary(self) -> Dict[str, Any]:
        """Return lightweight observability summary for memory lifecycle and quality."""
        self._prune_auto_knowledge_fingerprints()
        mode = self._normalize_persistence_mode()
        persistence_path = str(self._persistence_path) if self._persistence_path else ""
        persistence_exists = bool(self._persistence_path and self._persistence_path.exists())
        persistence_size_bytes = 0
        if self._persistence_path and self._persistence_path.exists():
            try:
                persistence_size_bytes = int(self._persistence_path.stat().st_size)
            except Exception:
                persistence_size_bytes = 0

        return {
            "knowledge_count": len(self._knowledge),
            "knowledge_ttl_seconds": self._knowledge_ttl_seconds,
            "knowledge_expired_removed_total": self._knowledge_expired_removed_total,
            "persistence_mode": mode,
            "persistence_path": persistence_path,
            "persistence_exists": persistence_exists,
            "persistence_size_bytes": persistence_size_bytes,
            "auto_knowledge": {
                "min_chars": self._auto_knowledge_min_chars,
                "min_tokens": self._auto_knowledge_min_tokens,
                "dedup_ttl_seconds": self._auto_knowledge_dedup_ttl_seconds,
                "fingerprints_active": len(self._recent_auto_knowledge_fingerprints),
                "attempted_total": self._auto_knowledge_attempted_total,
                "stored_total": self._auto_knowledge_stored_total,
                "dedup_skipped_total": self._auto_knowledge_dedup_skipped_total,
                "quality_skipped_total": self._auto_knowledge_quality_skipped_total,
            },
            "tool_calls_total": len(self._tool_calls),
            "errors_total": len(self._errors),
            "current_phase": self._current_phase,
        }
    
    def _maybe_extract_knowledge(
        self, 
        tool_name: str, 
        tool_args: Dict[str, Any],
        result: Any,
        success: bool
    ) -> None:
        """Auto-extract knowledge from certain tool results."""
        if not success:
            return
            
        # === Auto-save Plan updates ===
        if tool_name == "plan":
            action = tool_args.get("action", "create")
            items = tool_args.get("items", [])
            if action == "create" and items:
                # Save complete plan to working memory
                plan_summary = f"Plan created with {len(items)} items: " + "; ".join(items[:5])
                if len(items) > 5:
                    plan_summary += f"... and {len(items) - 5} more"
                self._working_memory["current_plan"] = {
                    "items": items,
                    "created_at": datetime.now().isoformat(),
                    "completed": []
                }
                self._record_auto_knowledge_if_new(
                    content=plan_summary,
                    category="plan",
                    importance=0.8,
                )
            elif action == "complete":
                item_idx = tool_args.get("item_index", 0)
                plan = self._working_memory.get("current_plan", {})
                if plan and item_idx < len(plan.get("items", [])):
                    completed_item = plan["items"][item_idx]
                    plan.setdefault("completed", []).append(completed_item)
        
        # === Auto-save key decisions from think() ===
        if tool_name == "think":
            thought = tool_args.get("thought", "")
            # Only save substantial thoughts that look like decisions
            decision_keywords = ["decided", "will use", "choosing", "approach", "strategy", 
                               "architecture", "because", "therefore", "conclusion"]
            if len(thought) > 100 and any(kw in thought.lower() for kw in decision_keywords):
                self._record_auto_knowledge_if_new(
                    content=thought[:500] + ("..." if len(thought) > 500 else ""),
                    category="decision",
                    importance=0.7,
                )
        
        # === Extract from error fixes ===
        if tool_name == "lint":
            path = tool_args.get("path", "")
            if path in self._lint_results and not self._lint_results.get(path, True):
                # Was failing, now passes - record the fix
                self._record_auto_knowledge_if_new(
                    content=f"Fixed lint errors in {path}",
                    category="bug_fix",
                    importance=0.7,
                )
        
        # === Extract from write (file creation / overwrite) ===
        if tool_name == "write":
            path = tool_args.get("path", "")
            if path:
                self._files_created.add(self._normalize_path(path))
        
        # === Auto-save important API/endpoint info from send_message ===
        if tool_name == "send_message":
            content = tool_args.get("content", "")
            msg_type = tool_args.get("msg_type", "")
            # Save API-related info shared between agents
            if "api" in content.lower() or "endpoint" in content.lower() or "schema" in content.lower():
                self._record_auto_knowledge_if_new(
                    content=f"Shared info ({msg_type or 'update'}): {content[:300]}",
                    category="tech_context",
                    importance=0.6,
                )
    
    def get_tool_stats(self) -> Dict[str, Any]:
        """Get tool usage statistics."""
        return {
            "total_calls": len(self._tool_calls),
            "by_tool": dict(self._tool_call_counts),
            "last_tool": self._last_tool,
            "consecutive_same": self._consecutive_same_tool,
            "recent_errors": [
                tc for tc in self._tool_calls[-20:] 
                if not tc.get("success", True)
            ]
        }
    
    # ==================== Knowledge Management ====================
    
    def add_knowledge(
        self, 
        content: str, 
        category: str = "general",
        importance: float = 0.5,
        share_with: List[str] = None
    ) -> str:
        """
        Add a piece of knowledge.
        
        Args:
            content: The knowledge content
            category: Category (bug_fix, pattern, decision, etc.)
            importance: Importance score (0-1)
            share_with: List of agent IDs to share with
            
        Returns:
            Knowledge ID
        """
        knowledge_id = f"k_{len(self._knowledge)}_{datetime.now().strftime('%H%M%S')}"
        
        entry = {
            "id": knowledge_id,
            "content": content,
            "category": category,
            "importance": importance,
            "timestamp": datetime.now().isoformat(),
            "phase": self._current_phase,
        }
        
        self._knowledge.append(entry)
        self._append_persisted_knowledge(entry)
        self.cleanup_expired_knowledge()
        
        # Also add to long-term memory
        self.remember(
            content,
            memory_type="long",
            metadata={"category": category, "knowledge_id": knowledge_id},
            importance=importance
        )
        
        # Queue for cross-agent sharing
        if share_with:
            self._outgoing_knowledge.append({
                "knowledge": entry,
                "targets": share_with,
            })
        
        # Auto-sync to MemoryBank based on category
        if self.memory_bank_sync:
            if category in ["bug_fix", "error"]:
                self.memory_bank_sync.record_issue(content[:200])
            elif category == "decision":
                self.memory_bank_sync.record_decision(content[:200])
            elif category in ["progress", "task_complete"]:
                self.memory_bank_sync.record_completion(content[:200])
        
        self._logger.debug(f"Added knowledge [{category}]: {content[:100]}")
        return knowledge_id
    
    def recall_knowledge(
        self, 
        query: str = None, 
        category: str = None,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Recall knowledge by query or category.
        
        Args:
            query: Text query to search
            category: Filter by category
            limit: Maximum results
            
        Returns:
            List of matching knowledge entries
        """
        results = self._knowledge.copy()

        # Filter by category first
        if category:
            results = [k for k in results if k.get("category") == category]

        # No query: preserve legacy behavior (importance-first)
        if not query:
            results.sort(key=lambda x: x.get("importance", 0), reverse=True)
            return results[:limit]

        # Query path: token + phrase based scoring with importance/recency tie-breakers.
        query_tokens = self._tokenize_text(query)
        scored: List[Tuple[float, Dict[str, Any]]] = []

        for entry in results:
            score = self._score_knowledge_entry(entry, query, query_tokens)
            if score > 0.0:
                scored.append((score, entry))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [entry for _, entry in scored[:limit]]

    @staticmethod
    def _tokenize_text(text: str) -> List[str]:
        """
        Lightweight tokenizer for recall matching.

        Keeps alnum/underscore tokens and drops very short noise terms.
        """
        if not text:
            return []
        return [tok for tok in re.findall(r"[a-zA-Z0-9_]+", text.lower()) if len(tok) >= 2]

    @staticmethod
    def _parse_iso_timestamp(raw: str) -> Optional[datetime]:
        """Best-effort ISO timestamp parser used by recall ranking."""
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except Exception:
            return None

    def _score_knowledge_entry(
        self,
        entry: Dict[str, Any],
        query: str,
        query_tokens: List[str],
    ) -> float:
        """
        Score a knowledge entry for recall relevance.

        Heuristics:
        - exact phrase match (highest boost)
        - token overlap in content/category/phase
        - importance weighting
        - mild recency weighting (recent memories break ties)
        """
        content = str(entry.get("content", "")).lower()
        category = str(entry.get("category", "")).lower()
        phase = str(entry.get("phase", "")).lower()
        query_lower = query.lower().strip()

        if not content and not category and not phase:
            return 0.0

        score = 0.0

        # Phrase match gets a strong signal.
        if query_lower and query_lower in content:
            score += 3.0
        if query_lower and query_lower == category:
            score += 1.5

        # Token-level matching across fields.
        for token in query_tokens:
            if token in content:
                score += 1.2
            elif token in category:
                score += 0.9
            elif token in phase:
                score += 0.6

        # Short-circuit non-matches to avoid irrelevant results.
        if score <= 0.0:
            return 0.0

        # Importance is explicit user/agent signal (0.0-1.0 expected).
        try:
            importance = float(entry.get("importance", 0.0))
        except Exception:
            importance = 0.0
        score += max(0.0, min(1.0, importance))

        # Slight recency preference to keep current context relevant.
        ts = self._parse_iso_timestamp(str(entry.get("timestamp", "")))
        if ts is not None:
            hours_old = max(0.0, (datetime.now() - ts).total_seconds() / 3600.0)
            if hours_old < 24:
                score += 0.35
            elif hours_old < 72:
                score += 0.20
            elif hours_old < 168:
                score += 0.10

        return score
    
    def get_outgoing_knowledge(self) -> List[Dict[str, Any]]:
        """Get and clear outgoing knowledge queue."""
        outgoing = self._outgoing_knowledge.copy()
        self._outgoing_knowledge.clear()
        return outgoing
    
    # ==================== File Tracking ====================
    
    def record_file_created(self, path: str) -> None:
        """Record a file creation."""
        normalized = self._normalize_path(path)
        self._files_created.add(normalized)
        
        self.working.set("last_file_created", normalized)
        self.remember(
            f"Created file: {normalized}",
            memory_type="short",
            metadata={"type": "file_created", "path": normalized},
            importance=0.7,
        )
    
    def record_file_modified(self, path: str) -> None:
        """Record a file modification."""
        normalized = self._normalize_path(path)
        self._files_modified.add(normalized)
        
        self.working.set("last_file_modified", normalized)
        self.remember(
            f"Modified file: {normalized}",
            memory_type="short",
            metadata={"type": "file_modified", "path": normalized},
            importance=0.6,
        )
    
    def record_lint(self, path: str, passed: bool) -> None:
        """Record a lint operation."""
        normalized = self._normalize_path(path)
        self._files_linted.add(normalized)
        self._lint_results[normalized] = passed
        
        if not passed:
            self.remember(
                f"Lint failed: {normalized}",
                memory_type="short",
                metadata={"type": "lint_failed", "path": normalized},
                importance=0.8,
            )
    
    def is_file_linted(self, path: str) -> bool:
        """Check if a file has been linted."""
        return self._normalize_path(path) in self._files_linted
    
    def get_unlinted_files(self) -> List[str]:
        """Get files that have been created but not linted."""
        NO_LINT_EXTENSIONS = {'.json', '.md', '.sql', '.txt', '.env', '.yml', '.yaml', '.toml', '.lock', '.png', '.jpg', '.svg'}
        
        unlinted = []
        for path in (self._files_created - self._files_linted):
            ext = Path(path).suffix.lower()
            if ext not in NO_LINT_EXTENSIONS:
                unlinted.append(path)
        
        return unlinted
    
    def get_file_stats(self) -> Dict[str, int]:
        """Get file operation statistics."""
        return {
            "created": len(self._files_created),
            "modified": len(self._files_modified),
            "linted": len(self._files_linted),
            "lint_passed": sum(1 for v in self._lint_results.values() if v),
            "lint_failed": sum(1 for v in self._lint_results.values() if not v),
        }
    
    # ==================== Phase Tracking ====================
    
    def set_phase(self, phase: str) -> None:
        """Set current phase and log duration of previous."""
        if self._current_phase and self._phase_start_time:
            duration = int((datetime.now() - self._phase_start_time).total_seconds())
            self.add_knowledge(
                f"Phase '{self._current_phase}' completed in {duration}s",
                category="progress",
                importance=0.6
            )
        
        self._current_phase = phase
        self._phase_start_time = datetime.now()
        self.working.set("current_phase", phase)
        self.working.set("phase_start", datetime.now().isoformat())
        
        # Sync phase change to MemoryBank
        if self.memory_bank_sync:
            self.memory_bank_sync.record_progress(f"Started phase: {phase}")
    
    # ==================== Error Tracking ====================
    
    def record_error(self, error: str, context: str = "") -> None:
        """Record an error."""
        self._errors.append({
            "error": error[:500],
            "context": context[:200],
            "time": datetime.now().isoformat(),
            "phase": self._current_phase,
        })
        
        self.remember(
            f"Error in {self._current_phase}: {error[:200]}",
            memory_type="short",
            metadata={"type": "error", "context": context},
            importance=0.9,
        )
        
        # Auto-sync error to MemoryBank
        if self.memory_bank_sync:
            self.memory_bank_sync.record_issue(f"{error[:150]} (in {self._current_phase})")
    
    # ==================== Context Generation ====================
    
    def get_memory_context(self, include_knowledge: bool = True) -> str:
        """
        Get memory context string for injection into prompts.
        
        Args:
            include_knowledge: Whether to include knowledge entries
            
        Returns:
            Formatted context string
        """
        lines = []
        
        # Condensed summary
        if self.conversation_condenser.summary:
            lines.append("## Previous Context Summary")
            lines.append(self.conversation_condenser.summary[:800])
            lines.append("")
        
        # Current phase
        if self._current_phase:
            duration = 0
            if self._phase_start_time:
                duration = int((datetime.now() - self._phase_start_time).total_seconds())
            lines.append(f"## Current Phase: {self._current_phase} ({duration}s)")
            lines.append("")
        
        # File stats
        stats = self.get_file_stats()
        if stats["created"] > 0:
            lines.append("## File Progress")
            lines.append(f"- Created: {stats['created']} files")
            lines.append(f"- Linted: {stats['linted']} ({stats['lint_passed']} passed)")
            unlinted = self.get_unlinted_files()
            if unlinted:
                lines.append(f"- Awaiting lint: {', '.join(unlinted[:5])}")
            lines.append("")
        
        # Recent knowledge
        if include_knowledge and self._knowledge:
            recent_knowledge = sorted(
                self._knowledge, 
                key=lambda x: x.get("importance", 0), 
                reverse=True
            )[:5]
            if recent_knowledge:
                lines.append("## Key Learnings")
                for k in recent_knowledge:
                    lines.append(f"- [{k['category']}] {k['content'][:100]}")
                lines.append("")
        
        # Recent errors
        if self._errors:
            lines.append("## Recent Issues")
            for err in self._errors[-3:]:
                lines.append(f"- {err['error'][:100]}")
            lines.append("")
        
        return "\n".join(lines)
    
    def get_operation_context(self) -> str:
        """Get current operation state as context string."""
        lines = ["=== OPERATION STATE ==="]
        
        if self._current_phase:
            duration = int((datetime.now() - self._phase_start_time).total_seconds()) if self._phase_start_time else 0
            lines.append(f"Phase: {self._current_phase} ({duration}s)")
        
        stats = self.get_file_stats()
        lines.append(f"Files: {stats['created']} created, {stats['linted']} linted")
        
        unlinted = self.get_unlinted_files()
        if unlinted:
            lines.append(f"Unlinted: {', '.join(unlinted[:5])}")
        
        if self._errors:
            lines.append(f"Recent error: {self._errors[-1]['error'][:100]}")
        
        tool_stats = self.get_tool_stats()
        if tool_stats["consecutive_same"] > 3:
            lines.append(f"WARNING: {tool_stats['consecutive_same']} consecutive {self._last_tool} calls")
        
        lines.append("=== END STATE ===")
        return "\n".join(lines)
    
    # ==================== Task Lifecycle ====================
    
    async def on_task_complete(self, task_summary: str = "") -> None:
        """
        Called when a task completes. Extracts and persists learnings.
        
        Args:
            task_summary: Optional summary of what was accomplished
        """
        # Update condenser summary with recent events
        await self.update_summary()
        
        # Auto-extract knowledge from task
        if self._files_created:
            self.add_knowledge(
                f"Task created {len(self._files_created)} files: {', '.join(list(self._files_created)[:5])}",
                category="progress",
                importance=0.6
            )
        
        if task_summary:
            self.add_knowledge(task_summary, category="task_complete", importance=0.7)
    
    def reset_for_task(self) -> None:
        """Reset task-specific tracking while preserving long-term memory."""
        self._files_created.clear()
        self._files_modified.clear()
        self._files_linted.clear()
        self._lint_results.clear()
        self._tool_calls.clear()
        self._tool_call_counts.clear()
        self._consecutive_same_tool = 0
        self._last_tool = ""
        self._errors.clear()
        self.working.clear()
    
    def reset_all(self) -> None:
        """Full reset including all memory."""
        self.reset_for_task()
        self.short_term.clear()
        self._knowledge.clear()
        # Don't clear long-term - it should persist
        if self._normalize_persistence_mode() == "jsonl" and self._persistence_path:
            # Keep storage file but compact to reflect reset state.
            self._compact_persisted_knowledge()
    
    # ==================== Persistence ====================
    
    def save_state(self, filepath: str) -> None:
        """Save memory state to file."""
        state = {
            "knowledge": self._knowledge,
            "files_created": list(self._files_created),
            "current_phase": self._current_phase,
            "tool_call_counts": self._tool_call_counts,
            "condenser_summary": self.conversation_condenser.summary,
        }
        
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2)
        
        # Also save long-term memory
        self.long_term.save(str(Path(filepath).parent / "long_term.json"))
    
    def load_state(self, filepath: str) -> None:
        """Load memory state from file."""
        if not Path(filepath).exists():
            return
        
        with open(filepath, 'r', encoding='utf-8') as f:
            state = json.load(f)
        
        self._knowledge = state.get("knowledge", [])
        self._files_created = set(state.get("files_created", []))
        self._current_phase = state.get("current_phase", "")
        self._tool_call_counts = state.get("tool_call_counts", {})
        self.conversation_condenser._last_summary = state.get("condenser_summary", "")
        
        # Load long-term memory
        lt_path = Path(filepath).parent / "long_term.json"
        if lt_path.exists():
            self.long_term.load(str(lt_path))
    
    # ==================== Helpers ====================
    
    def _normalize_path(self, path: str) -> str:
        """Normalize a file path for consistent tracking."""
        path = str(path)
        if path.startswith("./"):
            path = path[2:]
        if path.startswith("/"):
            try:
                path = str(Path(path).name)
            except:
                pass
        return path
    
    def stats(self) -> dict:
        """Extended stats."""
        base_stats = super().stats()
        base_stats.update({
            "files_created": len(self._files_created),
            "files_modified": len(self._files_modified),
            "files_linted": len(self._files_linted),
            "current_phase": self._current_phase,
            "errors": len(self._errors),
            "knowledge_count": len(self._knowledge),
            "tool_calls": len(self._tool_calls),
            "condensation_count": self.conversation_condenser._condensation_count,
        })
        return base_stats
