"""
Event System for Real-time Progress Streaming

Provides callbacks for generation progress, allowing:
- CLI to display real-time updates
- Web UI to stream progress
- Logging to file
- Custom integrations
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
import json


class SafeJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles non-serializable objects."""
    def default(self, obj):
        # Handle objects with to_dict method
        if hasattr(obj, 'to_dict'):
            return obj.to_dict()
        # Handle objects with __dict__ attribute
        if hasattr(obj, '__dict__'):
            return {k: v for k, v in obj.__dict__.items() if not k.startswith('_')}
        # Handle datetime
        if isinstance(obj, datetime):
            return obj.isoformat()
        # Handle enums
        if isinstance(obj, Enum):
            return obj.value
        # Fallback to string representation
        try:
            return str(obj)
        except Exception:
            return f"<non-serializable: {type(obj).__name__}>"


def safe_json_dumps(obj, **kwargs) -> str:
    """Safely serialize object to JSON string."""
    return json.dumps(obj, cls=SafeJSONEncoder, **kwargs)


class EventType(Enum):
    """Types of events that can be emitted"""
    # Phase events
    PHASE_START = "phase_start"
    PHASE_COMPLETE = "phase_complete"
    PHASE_ERROR = "phase_error"
    
    # File events
    FILE_PLAN = "file_plan"           # Planning which files to generate
    FILE_START = "file_start"         # Starting to generate a file
    FILE_PROGRESS = "file_progress"   # Progress update during generation
    FILE_COMPLETE = "file_complete"   # File generation complete
    FILE_ERROR = "file_error"         # Error generating file
    
    # Thinking events
    THINK_START = "think_start"
    THINK_RESULT = "think_result"
    
    # Tool events
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    
    # Reflection events
    REFLECT_START = "reflect_start"
    REFLECT_CHECK = "reflect_check"   # Running a check
    REFLECT_RESULT = "reflect_result"
    
    # Fix events
    FIX_START = "fix_start"
    FIX_APPLIED = "fix_applied"
    
    # Verification events
    VERIFICATION_START = "verification_start"
    VERIFICATION_ERROR = "verification_error"
    VERIFICATION_PASS = "verification_pass"
    
    # Memory events
    MEMORY_STORE = "memory_store"
    MEMORY_RECALL = "memory_recall"
    
    # Overall
    GENERATION_START = "generation_start"
    GENERATION_COMPLETE = "generation_complete"
    GENERATION_ERROR = "generation_error"


@dataclass
class Event:
    """A single event"""
    type: EventType
    message: str
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> dict:
        return {
            "type": self.type.value,
            "message": self.message,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
        }
    
    def to_json(self) -> str:
        return safe_json_dumps(self.to_dict())


class EventEmitter:
    """
    Manages event listeners and emits events.
    
    Usage:
        emitter = EventEmitter()
        
        # Add listener
        emitter.on(EventType.FILE_START, lambda e: print(f"Generating: {e.data['path']}"))
        
        # Or listen to all events
        emitter.on_all(lambda e: print(f"[{e.type.value}] {e.message}"))
        
        # Emit event
        emitter.emit(EventType.FILE_START, "Starting generation", {"path": "models.py"})
    """
    
    def __init__(self):
        self._listeners: Dict[EventType, List[Callable[[Event], None]]] = {}
        self._global_listeners: List[Callable[[Event], None]] = []
        self._event_history: List[Event] = []
        self._record_history = False
    
    def on(self, event_type: EventType, callback: Callable[[Event], None]) -> None:
        """Register a listener for a specific event type"""
        if event_type not in self._listeners:
            self._listeners[event_type] = []
        self._listeners[event_type].append(callback)
    
    def on_all(self, callback: Callable[[Event], None]) -> None:
        """Register a listener for all events"""
        self._global_listeners.append(callback)
    
    def off(self, event_type: EventType, callback: Callable[[Event], None]) -> None:
        """Remove a listener"""
        if event_type in self._listeners:
            self._listeners[event_type] = [
                cb for cb in self._listeners[event_type] if cb != callback
            ]
    
    def emit(self, event_type: EventType, message: str, data: Dict[str, Any] = None) -> Event:
        """Emit an event to all listeners"""
        event = Event(
            type=event_type,
            message=message,
            data=data or {},
        )
        
        # Record history if enabled
        if self._record_history:
            self._event_history.append(event)
        
        # Notify specific listeners
        if event_type in self._listeners:
            for callback in self._listeners[event_type]:
                try:
                    callback(event)
                except Exception as e:
                    # Don't let listener errors break the flow
                    pass
        
        # Notify global listeners
        for callback in self._global_listeners:
            try:
                callback(event)
            except Exception:
                pass
        
        return event
    
    def enable_history(self) -> None:
        """Enable recording of event history"""
        self._record_history = True
    
    def get_history(self) -> List[Event]:
        """Get recorded event history"""
        return self._event_history.copy()
    
    def clear_history(self) -> None:
        """Clear event history"""
        self._event_history.clear()


# ===== Pre-built Listeners =====

class ConsoleListener:
    """
    Pretty console output for events.
    
    Shows real-time progress with colors and formatting.
    """
    
    # ANSI color codes
    COLORS = {
        "reset": "\033[0m",
        "bold": "\033[1m",
        "dim": "\033[2m",
        "green": "\033[32m",
        "yellow": "\033[33m",
        "blue": "\033[34m",
        "magenta": "\033[35m",
        "cyan": "\033[36m",
        "red": "\033[31m",
        "white": "\033[37m",
    }
    
    ICONS = {
        EventType.PHASE_START: "📦",
        EventType.PHASE_COMPLETE: "✅",
        EventType.PHASE_ERROR: "❌",
        EventType.FILE_PLAN: "📋",
        EventType.FILE_START: "📝",
        EventType.FILE_PROGRESS: "⏳",
        EventType.FILE_COMPLETE: "✓",
        EventType.FILE_ERROR: "✗",
        EventType.THINK_START: "🤔",
        EventType.THINK_RESULT: "💡",
        EventType.TOOL_CALL: "🔧",
        EventType.TOOL_RESULT: "📊",
        EventType.REFLECT_START: "🔍",
        EventType.REFLECT_CHECK: "🔎",
        EventType.REFLECT_RESULT: "📋",
        EventType.FIX_START: "🔨",
        EventType.FIX_APPLIED: "✔️",
        EventType.VERIFICATION_START: "🧪",
        EventType.VERIFICATION_ERROR: "⚠️",
        EventType.VERIFICATION_PASS: "✅",
        EventType.MEMORY_STORE: "💾",
        EventType.MEMORY_RECALL: "📚",
        EventType.GENERATION_START: "🚀",
        EventType.GENERATION_COMPLETE: "🎉",
        EventType.GENERATION_ERROR: "💥",
    }
    
    def __init__(self, verbose: bool = False, use_colors: bool = True):
        self.verbose = verbose
        self.use_colors = use_colors
        self._indent_level = 0
    
    def _color(self, text: str, color: str) -> str:
        if not self.use_colors:
            return text
        return f"{self.COLORS.get(color, '')}{text}{self.COLORS['reset']}"
    
    def _get_indent(self) -> str:
        return "  " * self._indent_level
    
    def __call__(self, event: Event) -> None:
        """Handle an event"""
        icon = self.ICONS.get(event.type, "•")
        indent = self._get_indent()
        
        # Adjust indent based on event type
        if event.type == EventType.PHASE_START:
            self._indent_level = 0
            print()
            print(self._color("=" * 60, "dim"))
            print(f"{icon} {self._color(event.message, 'bold')}")
            print(self._color("=" * 60, "dim"))
            self._indent_level = 1
            
        elif event.type == EventType.PHASE_COMPLETE:
            self._indent_level = 0
            print(f"{indent}{icon} {self._color(event.message, 'green')}")
            if event.data.get("files_count"):
                print(f"{indent}   Files: {event.data['files_count']}")
            
        elif event.type == EventType.FILE_PLAN:
            files = event.data.get("files", [])
            details = event.data.get("details", [])
            print(f"{indent}{icon} {self._color('Planned files:', 'cyan')}")
            if details:
                for d in details[:10]:
                    purpose = d.get("purpose", "")[:40]
                    print(f"{indent}   • {d.get('path', '')} - {purpose}")
            else:
                for f in files[:10]:
                    print(f"{indent}   • {f}")
            if len(files) > 10:
                print(f"{indent}   ... and {len(files) - 10} more")
            
        elif event.type == EventType.FILE_START:
            path = event.data.get("path", "unknown")
            purpose = event.data.get("purpose", "")[:50]
            print(f"{indent}{icon} {self._color(path, 'yellow')}")
            if purpose and self.verbose:
                print(f"{indent}   Purpose: {purpose}")
            
        elif event.type == EventType.FILE_COMPLETE:
            path = event.data.get("path", "unknown")
            lines = event.data.get("lines", 0)
            print(f"{indent}{icon} {self._color(path, 'green')} ({lines} lines)")
            
        elif event.type == EventType.THINK_START:
            if self.verbose:
                print(f"{indent}{icon} {self._color('Thinking...', 'magenta')}")
            
        elif event.type == EventType.THINK_RESULT:
            if self.verbose:
                result = event.data.get("result", "")[:100]
                print(f"{indent}{icon} {self._color('Analysis:', 'magenta')} {result}...")
            
        elif event.type == EventType.TOOL_CALL:
            if self.verbose:
                tool = event.data.get("tool", "unknown")
                target = event.data.get("target", "")
                print(f"{indent}{icon} {self._color(tool, 'blue')}({target[:30]})")
            
        elif event.type == EventType.REFLECT_START:
            print(f"{indent}{icon} {self._color('Reflecting...', 'cyan')}")
            
        elif event.type == EventType.REFLECT_RESULT:
            quality = event.data.get("quality", "unknown")
            issues = event.data.get("issues", [])
            color = "green" if quality == "good" else "yellow" if quality == "needs_improvement" else "red"
            print(f"{indent}{icon} Quality: {self._color(quality, color)}")
            if issues and self.verbose:
                for issue in issues[:3]:
                    print(f"{indent}   ⚠️ {issue[:60]}")
            
        elif event.type == EventType.FIX_APPLIED:
            fix = event.data.get("fix", "")[:60]
            print(f"{indent}{icon} {self._color('Fixed:', 'green')} {fix}")
        
        elif event.type == EventType.VERIFICATION_START:
            print(f"{indent}{icon} {self._color('Running verification...', 'cyan')}")
        
        elif event.type == EventType.VERIFICATION_ERROR:
            check = event.data.get("check", "unknown")
            message = event.data.get("message", "")[:80]
            print(f"{indent}{icon} {self._color(f'{check}:', 'red')} {message}")
        
        elif event.type == EventType.VERIFICATION_PASS:
            check = event.data.get("check", "")
            print(f"{indent}{icon} {self._color(f'{check} passed', 'green')}")
            
        elif event.type == EventType.GENERATION_START:
            name = event.data.get("name", "unknown")
            print()
            print(self._color("🚀 " + "=" * 56, "bold"))
            print(self._color(f"   Generating: {name}", "bold"))
            print(self._color("   " + "=" * 56, "bold"))
            
        elif event.type == EventType.GENERATION_COMPLETE:
            duration = event.data.get("duration", 0)
            files = event.data.get("total_files", 0)
            print()
            print(self._color("🎉 " + "=" * 56, "green"))
            print(self._color(f"   Generation Complete!", "green"))
            print(f"   📁 {files} files generated")
            print(f"   ⏱️  {duration:.1f} seconds")
            print(self._color("   " + "=" * 56, "green"))
            
        elif event.type == EventType.GENERATION_ERROR:
            error = event.data.get("error") or event.message or "Unknown error"
            print()
            print(self._color(f"💥 ERROR: {error}", "red"))


class FileLogger:
    """Log events to a JSON file"""
    
    def __init__(self, filepath: str):
        self.filepath = filepath
        self._events = []
    
    def __call__(self, event: Event) -> None:
        self._events.append(event.to_dict())
        
        # Write incrementally with safe encoder
        with open(self.filepath, "w") as f:
            f.write(safe_json_dumps(self._events, indent=2))


class JsonlEventLogger:
    """
    Append-only JSONL event log for real-time monitoring.

    Unlike `FileLogger`, this does not rewrite prior events, so external UIs can
    tail the file cheaply while generation is in progress.
    """

    def __init__(self, filepath: str):
        self.filepath = filepath
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("")

    def __call__(self, event: Event) -> None:
        with open(self.filepath, "a", encoding="utf-8") as f:
            f.write(event.to_json())
            f.write("\n")
            f.flush()


class RealTimeTextLogger:
    """
    Real-time text log file that can be tailed with `tail -f`.
    
    Logs human-readable format, immediately flushed for real-time monitoring.
    """
    
    def __init__(self, filepath: str):
        self.filepath = filepath
        # Clear file at start
        with open(filepath, "w") as f:
            f.write(f"=== Generation Started at {datetime.now().isoformat()} ===\n\n")
    
    def __call__(self, event: Event) -> None:
        timestamp = event.timestamp.strftime("%H:%M:%S")
        event_type = event.type.value.upper()
        
        # Format based on event type
        if event.type == EventType.PHASE_START:
            line = f"\n{'='*60}\n[{timestamp}] PHASE: {event.message}\n{'='*60}\n"
        elif event.type == EventType.PHASE_COMPLETE:
            line = f"[{timestamp}] PHASE COMPLETE: {event.message}\n"
        elif event.type == EventType.FILE_PLAN:
            files = event.data.get("files", [])
            details = event.data.get("details", [])
            line = f"[{timestamp}] 📋 PLAN: {len(files)} files for phase\n"
            if details:
                for d in details[:10]:
                    purpose = d.get("purpose", "")[:60]
                    line += f"    • {d.get('path', '')}\n"
                    if purpose:
                        line += f"      Purpose: {purpose}\n"
            else:
                for f in files[:10]:
                    line += f"    • {f}\n"
            if len(files) > 10:
                line += f"    ... and {len(files) - 10} more\n"
        elif event.type == EventType.FILE_START:
            path = event.data.get("path", "unknown")
            purpose = event.data.get("purpose", "")
            line = f"[{timestamp}] START: {path}\n"
            if purpose:
                line += f"         Purpose: {purpose[:80]}\n"
        elif event.type == EventType.FILE_COMPLETE:
            path = event.data.get("path", "unknown")
            lines = event.data.get("lines", 0)
            quality = event.data.get("quality", "")
            line = f"[{timestamp}] DONE: {path} ({lines} lines, {quality})\n"
        elif event.type == EventType.FILE_ERROR:
            path = event.data.get("path", "unknown")
            error = event.data.get("error", "")
            line = f"[{timestamp}] ERROR: {path} - {error}\n"
        elif event.type == EventType.THINK_START:
            topic = event.data.get("topic", "")
            line = f"[{timestamp}] 🤔 THINK: {topic}\n"
        elif event.type == EventType.THINK_RESULT:
            result = event.data.get("result", "")
            # Show more detailed thinking content
            line = f"[{timestamp}] 💡 THOUGHT:\n"
            # Pretty print if it's a dict/JSON
            if isinstance(result, dict):
                try:
                    formatted = safe_json_dumps(result, indent=2, ensure_ascii=False)
                    for l in formatted.split("\n")[:30]:  # Limit lines
                        line += f"    {l}\n"
                    if len(formatted.split("\n")) > 30:
                        line += "    ... (truncated)\n"
                except:
                    line += f"    {str(result)[:500]}\n"
            else:
                # Show first 500 chars with line breaks
                result_str = str(result)[:500]
                for l in result_str.split("\n")[:15]:
                    line += f"    {l}\n"
                if len(result_str) >= 500:
                    line += "    ... (truncated)\n"
        elif event.type == EventType.TOOL_CALL:
            tool = event.data.get("tool", "unknown")
            target = event.data.get("target", "")
            args = event.data.get("args", {})
            line = f"[{timestamp}] 🔧 TOOL: {tool}\n"
            if target:
                line += f"    target: {target}\n"
            if args:
                for k, v in list(args.items())[:5]:
                    line += f"    {k}: {str(v)[:100]}\n"
        elif event.type == EventType.TOOL_RESULT:
            tool = event.data.get("tool", "unknown")
            success = event.data.get("success", False)
            result = event.data.get("result", "")
            line = f"[{timestamp}] 📊 TOOL RESULT: {tool} -> {'✓' if success else '✗'}\n"
            if result and not success:
                line += f"    Error: {str(result)[:200]}\n"
        elif event.type == EventType.REFLECT_START:
            path = event.data.get("path", "")
            context = event.data.get("context", "")
            line = f"[{timestamp}] 🔍 REFLECT: {path}\n"
            if context:
                line += f"    Context: {context}\n"
        elif event.type == EventType.REFLECT_CHECK:
            check = event.data.get("check", "")
            result = event.data.get("result", "")
            line = f"[{timestamp}] 🔎 CHECK: {check}\n"
            if result:
                line += f"    Result: {str(result)[:200]}\n"
        elif event.type == EventType.REFLECT_RESULT:
            quality = event.data.get("quality", "unknown")
            issues = event.data.get("issues", [])
            suggestions = event.data.get("suggestions", [])
            line = f"[{timestamp}] 📋 REFLECTION: Quality={quality}\n"
            if issues:
                line += "    Issues:\n"
                for issue in issues[:5]:
                    line += f"      ⚠️ {issue[:100]}\n"
            if suggestions:
                line += "    Suggestions:\n"
                for sug in suggestions[:3]:
                    line += f"      💡 {sug[:100]}\n"
        elif event.type == EventType.FIX_START:
            issues = event.data.get("issues", [])
            approach = event.data.get("approach", "")
            line = f"[{timestamp}] 🔨 FIX START: {len(issues)} issues\n"
            if approach:
                line += f"    Approach: {approach}\n"
            for issue in issues[:3]:
                line += f"    - {issue[:80]}\n"
        elif event.type == EventType.FIX_APPLIED:
            fix = event.data.get("fix", "")
            file_path = event.data.get("file", "")
            line = f"[{timestamp}] ✔️ FIXED: {file_path}\n"
            line += f"    {fix[:150]}\n"
        elif event.type == EventType.GENERATION_START:
            name = event.data.get("name", "unknown")
            line = f"\n{'#'*60}\n# GENERATION START: {name}\n{'#'*60}\n\n"
        elif event.type == EventType.GENERATION_COMPLETE:
            duration = event.data.get("duration", 0)
            files = event.data.get("total_files", 0)
            line = f"\n{'#'*60}\n# COMPLETE! {files} files in {duration:.1f}s\n{'#'*60}\n"
        elif event.type == EventType.GENERATION_ERROR:
            error = event.data.get("error") or event.message or "Unknown"
            line = f"\n[{timestamp}] *** ERROR ***: {error}\n"
        elif event.type == EventType.VERIFICATION_START:
            line = f"[{timestamp}] 🧪 VERIFICATION START\n"
        elif event.type == EventType.VERIFICATION_ERROR:
            check = event.data.get("check", "unknown")
            message = event.data.get("message", "")
            details = event.data.get("details", {})
            line = f"[{timestamp}] ⚠️ VERIFY FAILED: {check}\n"
            line += f"    Message: {message[:200]}\n"
            if details:
                for k, v in list(details.items())[:5]:
                    line += f"    {k}: {str(v)[:100]}\n"
        elif event.type == EventType.VERIFICATION_PASS:
            check = event.data.get("check", "")
            line = f"[{timestamp}] ✅ VERIFY PASS: {check}\n"
        else:
            line = f"[{timestamp}] {event_type}: {event.message}\n"
        
        # Append and immediately flush
        with open(self.filepath, "a") as f:
            f.write(line)
            f.flush()


# ===== Helper to create common setup =====

def create_console_emitter(verbose: bool = False) -> EventEmitter:
    """Create an emitter with console output"""
    emitter = EventEmitter()
    emitter.on_all(ConsoleListener(verbose=verbose))
    return emitter

