"""
Memory Module - Advanced memory management with LLM-based condensation

Inspired by OpenHands, this module provides:
- Short-term memory (conversation buffer)
- Long-term memory (persistent storage)
- Working memory (current task context)
- LLM Summarizing Condenser (intelligent history compression)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, Callable
from uuid import uuid4
from collections import deque
import json


@dataclass
class MemoryItem:
    """Single memory item."""
    id: str = field(default_factory=lambda: str(uuid4()))
    content: str = ""
    metadata: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    importance: float = 0.5  # 0.0 - 1.0
    access_count: int = 0
    last_accessed: Optional[datetime] = None
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content": self.content,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
            "importance": self.importance,
            "access_count": self.access_count,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "MemoryItem":
        return cls(
            id=data.get("id", str(uuid4())),
            content=data.get("content", ""),
            metadata=data.get("metadata", {}),
            timestamp=datetime.fromisoformat(data["timestamp"]) if "timestamp" in data else datetime.now(),
            importance=data.get("importance", 0.5),
            access_count=data.get("access_count", 0),
        )
    
    def access(self) -> None:
        """Record memory access."""
        self.access_count += 1
        self.last_accessed = datetime.now()
    
    def __str__(self) -> str:
        return self.content[:100] + "..." if len(self.content) > 100 else self.content


class ShortTermMemory:
    """
    Short-term memory (conversation buffer).
    
    - Fixed size buffer with FIFO eviction
    - Fast access for recent items
    """
    
    def __init__(self, max_size: int = 50):
        self.max_size = max_size
        self._buffer: deque[MemoryItem] = deque(maxlen=max_size)
        self._index: dict[str, MemoryItem] = {}
    
    def add(self, content: str, metadata: dict = None, importance: float = 0.5) -> str:
        """Add item to memory."""
        item = MemoryItem(
            content=content,
            metadata=metadata or {},
            importance=importance,
        )
        
        # Handle overflow
        if len(self._buffer) >= self.max_size:
            oldest = self._buffer[0]
            self._index.pop(oldest.id, None)
        
        self._buffer.append(item)
        self._index[item.id] = item
        return item.id
    
    def get(self, item_id: str) -> Optional[MemoryItem]:
        """Get item by ID."""
        item = self._index.get(item_id)
        if item:
            item.access()
        return item
    
    def search(self, query: str, limit: int = 5) -> list[MemoryItem]:
        """Simple text search."""
        query_lower = query.lower()
        results = []
        
        for item in self._buffer:
            if query_lower in item.content.lower():
                item.access()
                results.append(item)
        
        results.sort(key=lambda x: (x.importance, x.timestamp), reverse=True)
        return results[:limit]
    
    def get_recent(self, n: int = 10) -> list[MemoryItem]:
        """Get most recent items."""
        items = list(self._buffer)[-n:]
        items.reverse()
        return items
    
    def clear(self) -> None:
        """Clear all memory."""
        self._buffer.clear()
        self._index.clear()
    
    def to_list(self) -> list[MemoryItem]:
        """Get all items."""
        return list(self._buffer)
    
    def __len__(self) -> int:
        return len(self._buffer)


class LongTermMemory:
    """
    Long-term memory with persistence.
    
    - Importance-based retention
    - Supports serialization
    """
    
    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self._memories: dict[str, MemoryItem] = {}
    
    def add(self, content: str, metadata: dict = None, importance: float = 0.5) -> str:
        """Add item to memory."""
        item = MemoryItem(
            content=content,
            metadata=metadata or {},
            importance=importance,
        )
        
        if len(self._memories) >= self.max_size:
            self._evict()
        
        self._memories[item.id] = item
        return item.id
    
    def _evict(self) -> None:
        """Evict least valuable memory."""
        if not self._memories:
            return
        
        now = datetime.now()
        
        def score(item: MemoryItem) -> float:
            age_hours = (now - item.timestamp).total_seconds() / 3600
            recency = 1.0 / (1.0 + age_hours)
            frequency = min(1.0, item.access_count / 10.0)
            return item.importance * 0.5 + recency * 0.3 + frequency * 0.2
        
        min_item = min(self._memories.values(), key=score)
        del self._memories[min_item.id]
    
    def get(self, item_id: str) -> Optional[MemoryItem]:
        """Get item by ID."""
        item = self._memories.get(item_id)
        if item:
            item.access()
        return item
    
    def search(self, query: str, limit: int = 5) -> list[MemoryItem]:
        """Text search with ranking."""
        query_lower = query.lower()
        query_words = set(query_lower.split())
        
        scored_items = []
        for item in self._memories.values():
            content_lower = item.content.lower()
            score = 0.0
            
            if query_lower in content_lower:
                score += 2.0
            
            content_words = set(content_lower.split())
            overlap = len(query_words & content_words)
            score += overlap * 0.5
            score *= (0.5 + item.importance * 0.5)
            
            if score > 0:
                scored_items.append((score, item))
        
        scored_items.sort(key=lambda x: x[0], reverse=True)
        
        results = []
        for _, item in scored_items[:limit]:
            item.access()
            results.append(item)
        
        return results
    
    def clear(self) -> None:
        """Clear all memory."""
        self._memories.clear()
    
    def to_list(self) -> list[MemoryItem]:
        """Get all items."""
        return list(self._memories.values())
    
    def save(self, filepath: str) -> None:
        """Save to file."""
        data = {
            "max_size": self.max_size,
            "memories": [m.to_dict() for m in self._memories.values()]
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    
    def load(self, filepath: str) -> None:
        """Load from file."""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        self.max_size = data.get("max_size", self.max_size)
        self._memories.clear()
        
        for item_data in data.get("memories", []):
            item = MemoryItem.from_dict(item_data)
            self._memories[item.id] = item
    
    def __len__(self) -> int:
        return len(self._memories)


class WorkingMemory:
    """
    Working memory for current task context.
    
    - Key-value storage
    - Task-specific information
    - Action history tracking
    """
    
    def __init__(self):
        self._storage: dict[str, Any] = {}
        self._task_id: Optional[str] = None
        self._history: list[dict] = []
    
    def set_task(self, task_id: str) -> None:
        """Set current task and clear previous context."""
        if self._task_id != task_id:
            self.clear()
            self._task_id = task_id
    
    def set(self, key: str, value: Any) -> None:
        """Set a value."""
        self._storage[key] = value
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a value."""
        return self._storage.get(key, default)
    
    def delete(self, key: str) -> bool:
        """Delete a value."""
        if key in self._storage:
            del self._storage[key]
            return True
        return False
    
    def has(self, key: str) -> bool:
        """Check if key exists."""
        return key in self._storage
    
    def add_step(self, thought: str = None, action: str = None,
                 action_input: Any = None, observation: str = None) -> None:
        """Add a step to action history."""
        step = {"timestamp": datetime.now().isoformat()}
        if thought:
            step["thought"] = thought
        if action:
            step["action"] = action
        if action_input is not None:
            step["action_input"] = action_input
        if observation:
            step["observation"] = observation
        self._history.append(step)
    
    def get_history(self) -> list[dict]:
        """Get action history."""
        return self._history.copy()
    
    def clear(self) -> None:
        """Clear working memory."""
        self._storage.clear()
        self._history.clear()
        self._task_id = None
    
    def to_dict(self) -> dict:
        """Export as dictionary."""
        return {
            "task_id": self._task_id,
            "storage": self._storage.copy(),
            "history_length": len(self._history),
        }


# ===== LLM Summarizing Condenser =====

CONDENSER_PROMPT = """You are maintaining a context-aware state summary for an interactive agent.
Summarize the following events while preserving essential information.

Track these categories as applicable:
- USER_CONTEXT: Key requirements, goals, and clarifications
- TASK_TRACKING: Active tasks with IDs and statuses  
- COMPLETED: Tasks done with brief results
- PENDING: Tasks still needed
- CURRENT_STATE: Relevant state information
- CODE_STATE: File paths, key structures (if applicable)
- ERRORS_FIXED: Issues resolved and how

PRIORITIZE:
1. Capture key user requirements
2. Distinguish completed vs pending tasks
3. Keep sections concise and actionable
4. Preserve exact task IDs and file paths

<PREVIOUS_SUMMARY>
{previous_summary}
</PREVIOUS_SUMMARY>

<EVENTS_TO_SUMMARIZE>
{events}
</EVENTS_TO_SUMMARIZE>

Provide a concise summary:"""


class LLMSummarizingCondenser:
    """
    Condenser that uses LLM to summarize forgotten events.
    
    Maintains a condensed history by summarizing older events when
    the history grows too large.
    
    Inspired by OpenHands LLMSummarizingCondenser.
    """
    
    def __init__(
        self,
        llm_func: Callable[[str], str],  # Async function that calls LLM
        max_size: int = 100,
        keep_first: int = 2,
        max_event_length: int = 5000,
    ):
        """
        Args:
            llm_func: Async function that takes prompt and returns LLM response
            max_size: Maximum events before condensation triggers
            keep_first: Number of initial events to always keep
            max_event_length: Maximum length per event in summary
        """
        if keep_first >= max_size // 2:
            raise ValueError(f"keep_first ({keep_first}) must be < half of max_size ({max_size})")
        
        self.llm_func = llm_func
        self.max_size = max_size
        self.keep_first = keep_first
        self.max_event_length = max_event_length
        
        self._summary: str = ""
        self._condensation_count: int = 0
    
    def should_condense(self, events: list) -> bool:
        """Check if events should be condensed."""
        return len(events) > self.max_size
    
    async def condense(self, events: list[MemoryItem]) -> tuple[list[MemoryItem], str]:
        """
        Condense events by summarizing older ones.
        
        Args:
            events: List of memory items to condense
            
        Returns:
            (condensed_events, summary)
        """
        if not self.should_condense(events):
            return events, self._summary
        
        # Keep first N and last N/2 events
        target_size = self.max_size // 2
        events_from_tail = target_size - self.keep_first - 1
        
        head_events = events[:self.keep_first]
        tail_events = events[-events_from_tail:]
        forgotten_events = events[self.keep_first:-events_from_tail]
        
        # Format events for summarization
        events_text = "\n".join(
            self._truncate(str(e.content)) for e in forgotten_events
        )
        
        # Generate summary using LLM
        prompt = CONDENSER_PROMPT.format(
            previous_summary=self._summary or "No previous summary.",
            events=events_text,
        )
        
        new_summary = await self.llm_func(prompt)
        self._summary = new_summary
        self._condensation_count += 1
        
        # Create summary memory item
        summary_item = MemoryItem(
            content=f"[CONDENSED SUMMARY #{self._condensation_count}]\n{new_summary}",
            metadata={"type": "condensation_summary", "count": self._condensation_count},
            importance=0.9,
        )
        
        # Return condensed events: head + summary + tail
        condensed = head_events + [summary_item] + tail_events
        
        return condensed, new_summary
    
    def _truncate(self, content: str) -> str:
        """Truncate content to max length."""
        if len(content) <= self.max_event_length:
            return content
        return content[:self.max_event_length] + "... [truncated]"
    
    @property
    def summary(self) -> str:
        """Get current summary."""
        return self._summary
    
    @property
    def condensation_count(self) -> int:
        """Get number of condensations performed."""
        return self._condensation_count

    async def update_summary(self, events: list[MemoryItem]) -> str:
        """
        Force update summary with recent events (regardless of count).
        
        Used at end of tasks to ensure next task has context.
        
        Args:
            events: Recent events to include in summary
            
        Returns:
            Updated summary
        """
        if not events:
            return self._summary
        
        # Format recent events
        recent_text = "\n".join(
            self._truncate(str(e.content)) for e in events[-20:]  # Last 20 events
        )
        
        # Generate updated summary using LLM
        prompt = CONDENSER_PROMPT.format(
            previous_summary=self._summary or "No previous summary.",
            events=recent_text,
        )
        
        try:
            new_summary = await self.llm_func(prompt)
            self._summary = new_summary
            return new_summary
        except Exception:
            return self._summary


# ===== Unified Agent Memory =====

class AgentMemory:
    """
    Unified memory system for an Agent.
    
    Combines:
    - Short-term memory (recent conversation)
    - Working memory (current task)
    - Long-term memory (persistent knowledge)
    - Optional LLM condenser for intelligent summarization
    """
    
    def __init__(
        self,
        short_term_size: int = 50,
        long_term_size: int = 1000,
        condenser_llm_func: Callable = None,
        condenser_max_size: int = 100,
    ):
        self.short_term = ShortTermMemory(max_size=short_term_size)
        self.working = WorkingMemory()
        self.long_term = LongTermMemory(max_size=long_term_size)
        
        # Optional condenser
        self.condenser: Optional[LLMSummarizingCondenser] = None
        if condenser_llm_func:
            self.condenser = LLMSummarizingCondenser(
                llm_func=condenser_llm_func,
                max_size=condenser_max_size,
            )
    
    def remember(self, content: str, memory_type: str = "short",
                 metadata: dict = None, importance: float = 0.5) -> str:
        """
        Add a memory.
        
        Args:
            content: Memory content
            memory_type: "short" or "long"
            metadata: Additional metadata
            importance: Importance score (0.0 - 1.0)
            
        Returns:
            Memory item ID
        """
        if memory_type == "long":
            return self.long_term.add(content, metadata, importance)
        return self.short_term.add(content, metadata, importance)
    
    def recall(self, query: str, sources: list[str] = None, limit: int = 5) -> list[MemoryItem]:
        """
        Search across memory systems.
        
        Args:
            query: Search query
            sources: List of sources to search ("short", "long")
            limit: Maximum results per source
            
        Returns:
            Combined search results
        """
        sources = sources or ["short", "long"]
        results = []
        
        if "short" in sources:
            results.extend(self.short_term.search(query, limit))
        
        if "long" in sources:
            results.extend(self.long_term.search(query, limit))
        
        # Deduplicate
        seen_ids = set()
        unique_results = []
        for item in results:
            if item.id not in seen_ids:
                seen_ids.add(item.id)
                unique_results.append(item)
        
        unique_results.sort(key=lambda x: (x.importance, x.timestamp), reverse=True)
        return unique_results[:limit * len(sources)]
    
    async def condense_if_needed(self) -> bool:
        """
        Condense short-term memory if it's too large.
        
        Returns:
            True if condensation was performed
        """
        if not self.condenser:
            return False
        
        events = self.short_term.to_list()
        if not self.condenser.should_condense(events):
            return False
        
        condensed_events, summary = await self.condenser.condense(events)
        
        # Replace short-term memory with condensed version
        self.short_term.clear()
        for event in condensed_events:
            self.short_term._buffer.append(event)
            self.short_term._index[event.id] = event
        
        return True
    
    async def update_summary(self, min_events: int = 5) -> bool:
        """
        Update condenser summary with recent events.
        
        Call at end of tasks to ensure next task has context, even if
        not enough events to trigger full condensation.
        
        Args:
            min_events: Minimum events needed to trigger update
            
        Returns:
            True if summary was updated
        """
        if not self.condenser:
            return False
        
        events = self.short_term.to_list()
        if len(events) < min_events:
            return False
        
        # Force update summary with recent events
        await self.condenser.update_summary(events)
        return True
    
    def get_context_string(self, max_items: int = 10) -> str:
        """
        Get formatted context string for prompt inclusion.
        
        Returns:
            Formatted string with recent memories and working context
        """
        lines = []
        
        # Condenser summary
        if self.condenser and self.condenser.summary:
            lines.append("## Previous Context Summary")
            lines.append(self.condenser.summary[:500])
            lines.append("")
        
        # Working memory context
        if self.working._storage:
            lines.append("## Current Task Context")
            for key, value in list(self.working._storage.items())[:10]:
                value_str = str(value)[:200]
                lines.append(f"- {key}: {value_str}")
            lines.append("")
        
        # Recent history
        recent = self.short_term.get_recent(max_items)
        if recent:
            lines.append("## Recent Activity")
            for item in recent:
                role = item.metadata.get("role", "system")
                content = item.content[:150] + "..." if len(item.content) > 150 else item.content
                lines.append(f"[{role}] {content}")
            lines.append("")
        
        return "\n".join(lines)
    
    def save(self, filepath: str) -> None:
        """Save long-term memory to file."""
        self.long_term.save(filepath)
    
    def load(self, filepath: str) -> None:
        """Load long-term memory from file."""
        self.long_term.load(filepath)
    
    def clear_all(self) -> None:
        """Clear all memories."""
        self.short_term.clear()
        self.working.clear()
        self.long_term.clear()
    
    def stats(self) -> dict:
        """Get memory statistics."""
        return {
            "short_term_count": len(self.short_term),
            "long_term_count": len(self.long_term),
            "working_memory_keys": list(self.working._storage.keys()),
            "history_steps": len(self.working.get_history()),
            "condensation_count": self.condenser.condensation_count if self.condenser else 0,
        }
