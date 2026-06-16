"""
Communication Module - Defines communication mechanisms between Agents

Supports:
- MessageBus: Message bus
- MessageRouter: Message router
- EventEmitter: Event emitter
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional, TYPE_CHECKING
from uuid import uuid4
import asyncio
import logging
from collections import defaultdict

from .message import (
    BaseMessage,
    MessageType,
    MessagePriority,
    MessageHeader,
)

if TYPE_CHECKING:
    from .base_agent import BaseAgent


@dataclass
class Subscription:
    """Message subscription"""
    subscription_id: str = field(default_factory=lambda: str(uuid4()))
    subscriber_id: str = ""
    message_types: list[MessageType] = field(default_factory=list)  # Empty list means subscribe to all
    filter_func: Optional[Callable[[BaseMessage], bool]] = None
    callback: Optional[Callable[[BaseMessage], Any]] = None
    async_callback: Optional[Callable[[BaseMessage], Any]] = None
    priority: int = 0  # Higher priority is processed first
    created_at: datetime = field(default_factory=datetime.now)


class MessageBus:
    """
    Message Bus
    
    Responsible for message delivery between Agents
    Supports:
    - Point-to-point messages
    - Broadcast messages
    - Publish/subscribe pattern
    """
    
    def __init__(self, max_queue_size: int = 1000):
        self._agents: dict[str, "BaseAgent"] = {}
        self._subscriptions: dict[str, list[Subscription]] = defaultdict(list)  # message_type -> subscriptions
        self._all_subscriptions: list[Subscription] = []  # Subscriptions for all messages
        self._message_queue: asyncio.Queue[BaseMessage] = asyncio.Queue(maxsize=max_queue_size)
        self._running = False
        self._process_task: Optional[asyncio.Task] = None
        self._logger = logging.getLogger("MessageBus")
        self._message_history: list[BaseMessage] = []
        self._history_size = 100
    
    def register_agent(self, agent: "BaseAgent") -> None:
        """Register Agent"""
        self._agents[agent.agent_id] = agent
        self._logger.info(f"Agent registered: {agent.name} ({agent.agent_id})")
    
    def unregister_agent(self, agent_id: str) -> bool:
        """Unregister Agent"""
        if agent_id in self._agents:
            del self._agents[agent_id]
            # Clean up subscriptions for this Agent
            self._cleanup_subscriptions(agent_id)
            self._logger.info(f"Agent unregistered: {agent_id}")
            return True
        return False
    
    def get_agent(self, agent_id: str) -> Optional["BaseAgent"]:
        """Get Agent"""
        return self._agents.get(agent_id)
    
    def list_agents(self) -> list[str]:
        """List all Agent IDs"""
        return list(self._agents.keys())
    
    def subscribe(
        self,
        subscriber_id: str,
        message_types: list[MessageType] = None,
        filter_func: Callable[[BaseMessage], bool] = None,
        callback: Callable[[BaseMessage], Any] = None,
        async_callback: Callable[[BaseMessage], Any] = None,
        priority: int = 0,
    ) -> str:
        """
        Subscribe to messages
        
        Args:
            subscriber_id: Subscriber ID
            message_types: Message types to subscribe to, None means all
            filter_func: Filter function
            callback: Synchronous callback
            async_callback: Asynchronous callback
            priority: Priority
            
        Returns:
            Subscription ID
        """
        subscription = Subscription(
            subscriber_id=subscriber_id,
            message_types=message_types or [],
            filter_func=filter_func,
            callback=callback,
            async_callback=async_callback,
            priority=priority,
        )
        
        if not message_types:
            self._all_subscriptions.append(subscription)
        else:
            for msg_type in message_types:
                self._subscriptions[msg_type.value].append(subscription)
        
        self._logger.debug(f"Subscription created: {subscription.subscription_id}")
        return subscription.subscription_id
    
    def unsubscribe(self, subscription_id: str) -> bool:
        """Unsubscribe"""
        # Find and remove from all subscriptions
        for subs in self._subscriptions.values():
            for sub in subs[:]:
                if sub.subscription_id == subscription_id:
                    subs.remove(sub)
                    return True
        
        for sub in self._all_subscriptions[:]:
            if sub.subscription_id == subscription_id:
                self._all_subscriptions.remove(sub)
                return True
        
        return False
    
    def _cleanup_subscriptions(self, agent_id: str) -> None:
        """Clean up all subscriptions for an Agent"""
        for subs in self._subscriptions.values():
            for sub in subs[:]:
                if sub.subscriber_id == agent_id:
                    subs.remove(sub)
        
        for sub in self._all_subscriptions[:]:
            if sub.subscriber_id == agent_id:
                self._all_subscriptions.remove(sub)
    
    async def publish(self, message: BaseMessage) -> None:
        """Publish message"""
        await self._message_queue.put(message)
    
    async def send(self, message: BaseMessage) -> bool:
        """
        Send point-to-point message
        
        Returns:
            Whether send was successful
        """
        target_id = message.header.target_agent_id
        
        if not target_id:
            # Broadcast
            await self.broadcast(message)
            return True
        
        target = self._agents.get(target_id)
        if not target:
            self._logger.warning(f"Target agent not found: {target_id}")
            return False
        
        await target.receive_message(message)
        self._record_message(message)
        return True
    
    async def broadcast(self, message: BaseMessage, exclude: list[str] = None) -> int:
        """
        Broadcast message
        
        Returns:
            Number of Agents sent to
        """
        exclude = exclude or []
        source_id = message.header.source_agent_id
        count = 0
        
        for agent_id, agent in self._agents.items():
            if agent_id != source_id and agent_id not in exclude:
                await agent.receive_message(message)
                count += 1
        
        self._record_message(message)
        return count
    
    async def start(self) -> None:
        """Start message bus"""
        if self._running:
            return
        
        self._running = True
        self._process_task = asyncio.create_task(self._process_loop())
        self._logger.info("MessageBus started")
    
    async def stop(self) -> None:
        """Stop message bus"""
        self._running = False
        
        if self._process_task:
            self._process_task.cancel()
            try:
                await self._process_task
            except asyncio.CancelledError:
                pass
        
        self._logger.info("MessageBus stopped")
    
    async def _process_loop(self) -> None:
        """Message processing loop"""
        while self._running:
            try:
                message = await asyncio.wait_for(
                    self._message_queue.get(),
                    timeout=1.0
                )
                await self._dispatch_message(message)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._logger.error(f"Error processing message: {e}")
    
    async def _dispatch_message(self, message: BaseMessage) -> None:
        """Dispatch message to subscribers"""
        # Collect applicable subscriptions
        subscriptions = []
        
        # Type-specific subscriptions
        type_subs = self._subscriptions.get(message.message_type.value, [])
        subscriptions.extend(type_subs)
        
        # All-message subscriptions
        subscriptions.extend(self._all_subscriptions)
        
        # Sort by priority
        subscriptions.sort(key=lambda s: s.priority, reverse=True)
        
        # Call callbacks
        for sub in subscriptions:
            # Filter check
            if sub.filter_func and not sub.filter_func(message):
                continue
            
            try:
                if sub.async_callback:
                    await sub.async_callback(message)
                elif sub.callback:
                    sub.callback(message)
            except Exception as e:
                self._logger.error(f"Subscription callback error: {e}")
        
        # Point-to-point send
        if message.header.target_agent_id:
            await self.send(message)
        
        self._record_message(message)
    
    def _record_message(self, message: BaseMessage) -> None:
        """Record message history"""
        self._message_history.append(message)
        if len(self._message_history) > self._history_size:
            self._message_history = self._message_history[-self._history_size:]
    
    def get_stats(self) -> dict:
        """Get statistics"""
        return {
            "registered_agents": len(self._agents),
            "queue_size": self._message_queue.qsize(),
            "subscriptions_count": sum(len(s) for s in self._subscriptions.values()) + len(self._all_subscriptions),
            "messages_in_history": len(self._message_history),
            "running": self._running,
        }


class EventEmitter:
    """
    Event Emitter
    
    Lightweight event system for Agent internal or inter-component communication
    """
    
    def __init__(self):
        self._listeners: dict[str, list[Callable]] = defaultdict(list)
        self._async_listeners: dict[str, list[Callable]] = defaultdict(list)
        self._once_listeners: dict[str, list[Callable]] = defaultdict(list)
    
    def on(self, event: str, callback: Callable) -> None:
        """Listen to event"""
        if asyncio.iscoroutinefunction(callback):
            self._async_listeners[event].append(callback)
        else:
            self._listeners[event].append(callback)
    
    def once(self, event: str, callback: Callable) -> None:
        """Listen to one-time event"""
        self._once_listeners[event].append(callback)
    
    def off(self, event: str, callback: Callable = None) -> None:
        """Stop listening"""
        if callback is None:
            # Remove all listeners for this event
            self._listeners.pop(event, None)
            self._async_listeners.pop(event, None)
            self._once_listeners.pop(event, None)
        else:
            if callback in self._listeners.get(event, []):
                self._listeners[event].remove(callback)
            if callback in self._async_listeners.get(event, []):
                self._async_listeners[event].remove(callback)
            if callback in self._once_listeners.get(event, []):
                self._once_listeners[event].remove(callback)
    
    async def emit(self, event: str, *args, **kwargs) -> None:
        """Emit event"""
        # Synchronous listeners
        for callback in self._listeners.get(event, []):
            try:
                callback(*args, **kwargs)
            except Exception:
                pass
        
        # Asynchronous listeners
        for callback in self._async_listeners.get(event, []):
            try:
                await callback(*args, **kwargs)
            except Exception:
                pass
        
        # One-time listeners
        once_callbacks = self._once_listeners.pop(event, [])
        for callback in once_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(*args, **kwargs)
                else:
                    callback(*args, **kwargs)
            except Exception:
                pass
    
    def emit_sync(self, event: str, *args, **kwargs) -> None:
        """Emit event synchronously (only calls synchronous listeners)"""
        for callback in self._listeners.get(event, []):
            try:
                callback(*args, **kwargs)
            except Exception:
                pass
        
        # One-time synchronous listeners
        once_callbacks = [c for c in self._once_listeners.get(event, []) 
                         if not asyncio.iscoroutinefunction(c)]
        for callback in once_callbacks:
            try:
                callback(*args, **kwargs)
                self._once_listeners[event].remove(callback)
            except Exception:
                pass
    
    def listener_count(self, event: str) -> int:
        """Get listener count"""
        return (len(self._listeners.get(event, [])) + 
                len(self._async_listeners.get(event, [])) +
                len(self._once_listeners.get(event, [])))
    
    def events(self) -> list[str]:
        """Get all events with listeners"""
        all_events = set()
        all_events.update(self._listeners.keys())
        all_events.update(self._async_listeners.keys())
        all_events.update(self._once_listeners.keys())
        return list(all_events)


class MessageRouter:
    """
    Message Router
    
    Rule-based message routing
    """
    
    def __init__(self, message_bus: MessageBus):
        self._bus = message_bus
        self._routes: list[tuple[Callable[[BaseMessage], bool], str]] = []  # (condition, target_agent_id)
        self._default_route: Optional[str] = None
    
    def add_route(
        self,
        condition: Callable[[BaseMessage], bool],
        target_agent_id: str,
    ) -> None:
        """
        Add routing rule
        
        Args:
            condition: Condition function, routes to target when returns True
            target_agent_id: Target Agent ID
        """
        self._routes.append((condition, target_agent_id))
    
    def add_type_route(
        self,
        message_type: MessageType,
        target_agent_id: str,
    ) -> None:
        """Add route by message type"""
        self.add_route(
            lambda m: m.message_type == message_type,
            target_agent_id
        )
    
    def set_default_route(self, target_agent_id: str) -> None:
        """Set default route"""
        self._default_route = target_agent_id
    
    async def route(self, message: BaseMessage) -> bool:
        """
        Route message
        
        Returns:
            Whether routing was successful
        """
        # Check routing rules
        for condition, target_id in self._routes:
            if condition(message):
                message.header.target_agent_id = target_id
                return await self._bus.send(message)
        
        # Default route
        if self._default_route:
            message.header.target_agent_id = self._default_route
            return await self._bus.send(message)
        
        return False
    
    def clear_routes(self) -> None:
        """Clear all routes"""
        self._routes.clear()
        self._default_route = None
