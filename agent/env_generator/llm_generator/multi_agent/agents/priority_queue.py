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
        # #1203hp: how many messages this queue has silently thrown away.
        self.evicted = 0
    
    async def put(self, message: BaseMessage) -> Optional[BaseMessage]:
        """Add message to queue with priority; return what this put threw away.

        #1203hu: THE RETURN VALUE EXISTS BECAUSE THE COUNTER ALONE REACHED NOBODY.
        `self.evicted` (below) is incremented here, silently, and its ONLY readout in
        the framework is inside messaging.py's handler for a DIFFERENT queue filling
        up (the `asyncio.QueueFull` of the ordinary dispatch queue, `FIX #150`). Those
        two conditions are independent, so on r180 -- the first run after #1203ht made
        this heap urgent-only -- the arithmetic came out:

            agents that received URGENT/HIGH      5  (backend debugger frontend
                                                      orchestrator verifier)
            agents that ever hit dispatch-FULL    3  (frontend 259, backend 211,
                                                      verifier 128)

        The debugger and the orchestrator can throw an URGENT message away and no line
        is ever printed -- not because the eviction is rare there but because the only
        thing that prints the number is another queue's failure. frontend's count was
        observable only by that coincidence, and reached 24.

        Returning the evicted message lets the ONE caller -- which has the agent id and
        the logger, and which this class deliberately does not -- say what was lost at
        the moment it is lost. Post-#1203ht the heap holds only priority 0 and 1, and
        `pop()` after `sort()` takes the LEAST urgent, so every return value here is a
        HIGH (or, in an all-URGENT heap, an URGENT) message that nothing will read.

        #1203hp: THE EVICTION BELOW IS THE ONLY DROP IN THE MESSAGE PATH THAT COUNTS
        NOTHING. `FIX #150` drops the ordinary-dispatch copy of a message when the bounded
        dispatch queue fills and says so LOUDLY -- 125022 warnings across 157 run logs on
        disk, r173 alone 2955 -- on the stated grounds that "the message already reached
        `_subscription_inbox`, the priority queue, and the interrupt channel for urgent
        types". Two of those three are urgent-only:

            every use of `_priority_queue` in the framework is `put` (messaging.py:122,
            for EVERY message), `get_if_urgent` (messaging.py:587, which pops only
            `priority <= 1`), and this constructor. `get()` has NO caller.

        So an ORDINARY message's priority-queue copy is never read, this heap fills with
        copies nothing will ever take, and from then on every `put` evicts one -- with no
        counter, no log line and no way to know afterwards that it happened. #1034's rule
        is that a truncation says how much went; a dropped message is the same thing one
        level up. Urgent delivery is unaffected (the heap's minimum is the most urgent, so
        `get_if_urgent` still sees it, and the eviction takes the LOWEST priority).

        `evicted` is therefore a counter, not a fix: it makes the frequency observable for
        the first time. Whether the eviction should instead be a drop-on-arrival for
        ordinary messages depends on that number, which nothing has ever measured."""
        async with self._lock:
            thrown_away = None
            if len(self._heap) >= self._maxsize:
                self._heap.sort()
                thrown_away = self._heap.pop().message
                self.evicted += 1

            heapq.heappush(self._heap, PrioritizedMessage.from_message(message))
            self._not_empty.set()
        return thrown_away
    
    async def get(self, timeout: Optional[float] = None) -> Optional[BaseMessage]:
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

