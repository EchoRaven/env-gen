"""
Priority message queue utilities for agents.
Separated from EnvGenAgent to keep base agent lean.
"""

import asyncio
import heapq
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from utils.message import BaseMessage, MessagePriority


@dataclass(order=True)
class PrioritizedMessage:
    """
    Message wrapper for priority queue.
    
    Ordering: 
    1. By priority (lower number = higher priority)
    2. By timestamp (earlier = first) for FIFO within same priority
    
    Priority levels:
    - URGENT (0): Immediate attention, processed first
    - HIGH (1): Important, process ASAP
    - NORMAL (2): Standard processing order
    - LOW (3): Not time-sensitive
    """
    priority: int  # Lower = higher priority (URGENT=0, HIGH=1, NORMAL=2, LOW=3)
    timestamp: float  # For FIFO within same priority (earlier = lower = first)
    message: BaseMessage = field(compare=False)
    
    @classmethod
    def from_message(cls, msg: BaseMessage) -> "PrioritizedMessage":
        priority_map = {
            MessagePriority.URGENT: 0,
            MessagePriority.HIGH: 1,
            MessagePriority.NORMAL: 2,
            MessagePriority.LOW: 3,
        }
        priority = priority_map.get(msg.header.priority, 2)
        # timestamp is used for FIFO ordering within same priority
        return cls(priority=priority, timestamp=datetime.now().timestamp(), message=msg)


class PriorityMessageQueue:
    """Thread-safe priority message queue."""
    
    def __init__(self, maxsize: int = 1000):
        self._heap: List[PrioritizedMessage] = []
        self._lock = asyncio.Lock()
        self._not_empty = asyncio.Event()
        self._maxsize = maxsize
    
    async def put(self, message: BaseMessage) -> None:
        """Add message to queue with priority."""
        async with self._lock:
            if len(self._heap) >= self._maxsize:
                self._heap.sort()
                self._heap.pop()
            
            heapq.heappush(self._heap, PrioritizedMessage.from_message(message))
            self._not_empty.set()
    
    async def get(self, timeout: float = None) -> Optional[BaseMessage]:
        """Get highest priority message."""
        try:
            if timeout:
                await asyncio.wait_for(self._not_empty.wait(), timeout=timeout)
            else:
                await self._not_empty.wait()
        except asyncio.TimeoutError:
            return None
        
        async with self._lock:
            if not self._heap:
                self._not_empty.clear()
                return None
            
            item = heapq.heappop(self._heap)
            if not self._heap:
                self._not_empty.clear()
            return item.message
    
    async def peek_urgent(self) -> Optional[BaseMessage]:
        """Check if there's an urgent message without removing it."""
        async with self._lock:
            if self._heap and self._heap[0].priority <= 1:
                return self._heap[0].message
            return None
    
    async def get_if_urgent(self) -> Optional[BaseMessage]:
        """Get message only if it's urgent (URGENT or HIGH priority)."""
        async with self._lock:
            if self._heap and self._heap[0].priority <= 1:
                item = heapq.heappop(self._heap)
                if not self._heap:
                    self._not_empty.clear()
                return item.message
            return None
    
    def qsize(self) -> int:
        return len(self._heap)
    
    def empty(self) -> bool:
        return len(self._heap) == 0

