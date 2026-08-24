"""
Log Analysis Tools - Parse, filter, and analyze application logs

Provides:
- LogParseTool: Parse and filter logs from various sources
- LogAnalyzeTool: Analyze logs for errors, patterns, and anomalies
- LogSearchTool: Search logs with regex and context
"""

import re
import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
from collections import Counter
from dataclasses import dataclass, field

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.tool import BaseTool, ToolResult, ToolCategory, create_tool_param
from workspace import Workspace
# #936: docker is absent on a podman gen host; resolve the runtime instead of assuming.


def _rt936(*args, **kwargs):
    """The container binary, resolved on first CALL — see #1055 in
    ``tools/docker_tools.py`` for the full diagnosis.

    Short version: this module is loaded as ``tools.<name>`` (its sibling
    imports use the short form), so a MODULE-LEVEL absolute
    ``env_generator.llm_generator...`` import builds a second copy of the
    package tree whose initialisation re-enters this module mid-execution.
    ``container_runtime`` imports only stdlib, so deferring the lookup to call
    time removes the cycle and leaves every call site unchanged.
    """
    try:
        from multi_agent.runtime.container_runtime import runtime_bin
    except ImportError:  # pragma: no cover - depends on the caller's sys.path
        from env_generator.llm_generator.multi_agent.runtime.container_runtime import runtime_bin
    return runtime_bin(*args, **kwargs)



@dataclass
class LogEntry:
    """Parsed log entry."""
    timestamp: Optional[str] = None
    level: str = "INFO"
    source: str = ""
    message: str = ""
    raw: str = ""
    line_number: int = 0
    extra: Dict[str, Any] = field(default_factory=dict)


class LogParser:
    """Parse logs from various formats."""
    
    # Common log patterns
    PATTERNS = {
        # Node.js / Express
        "node": re.compile(
            r"(?P<timestamp>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?)\s*"
            r"(?P<level>error|warn|info|debug|verbose)?\s*:?\s*"
            r"(?P<message>.*)",
            re.IGNORECASE
        ),
        # Docker Compose
        "docker": re.compile(
            r"(?P<service>\w+[-_]?\w*)\s*\|\s*"
            r"(?P<timestamp>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?)?\s*"
            r"(?P<level>error|warn|info|debug)?\s*:?\s*"
            r"(?P<message>.*)",
            re.IGNORECASE
        ),
        # Python logging
        "python": re.compile(
            r"(?P<timestamp>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:,\d+)?)\s+"
            r"(?P<level>ERROR|WARNING|INFO|DEBUG|CRITICAL)\s+"
            r"(?P<source>[\w.]+)\s+"
            r"(?P<message>.*)",
            re.IGNORECASE
        ),
        # Nginx access log
        "nginx_access": re.compile(
            r"(?P<ip>[\d.]+)\s+-\s+-\s+"
            r"\[(?P<timestamp>[^\]]+)\]\s+"
            r"\"(?P<method>\w+)\s+(?P<path>[^\s]+)\s+[^\"]+\"\s+"
            r"(?P<status>\d+)\s+"
            r"(?P<size>\d+)",
        ),
        # Nginx error log
        "nginx_error": re.compile(
            r"(?P<timestamp>\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2})\s+"
            r"\[(?P<level>\w+)\]\s+"
            r"(?P<message>.*)",
        ),
        # PostgreSQL
        "postgres": re.compile(
            r"(?P<timestamp>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?\s+\w+)\s+"
            r"\[(?P<pid>\d+)\]\s+"
            r"(?P<level>LOG|ERROR|WARNING|NOTICE|INFO|DEBUG):\s+"
            r"(?P<message>.*)",
            re.IGNORECASE
        ),
        # Generic timestamp + message
        "generic": re.compile(
            r"(?P<timestamp>\d{4}[-/]\d{2}[-/]\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\s*"
            r"(?P<level>error|warn(?:ing)?|info|debug|fatal|critical)?\s*:?\s*"
            r"(?P<message>.*)",
            re.IGNORECASE
        ),
    }
    
    # Error patterns to highlight
    ERROR_PATTERNS = [
        (re.compile(r"error", re.I), "error"),
        (re.compile(r"exception", re.I), "exception"),
        (re.compile(r"failed", re.I), "failure"),
        (re.compile(r"timeout", re.I), "timeout"),
        (re.compile(r"refused", re.I), "connection"),
        (re.compile(r"not found", re.I), "not_found"),
        (re.compile(r"unauthorized|401", re.I), "auth"),
        (re.compile(r"forbidden|403", re.I), "permission"),
        (re.compile(r"internal.*error|500", re.I), "server_error"),
        (re.compile(r"ECONNREFUSED|ENOTFOUND", re.I), "network"),
    ]
    
    def parse_line(self, line: str, line_number: int = 0) -> LogEntry:
        """Parse a single log line."""
        line = line.strip()
        if not line:
            return None
        
        # Try each pattern
        for format_name, pattern in self.PATTERNS.items():
            match = pattern.match(line)
            if match:
                groups = match.groupdict()
                return LogEntry(
                    timestamp=groups.get("timestamp"),
                    level=self._normalize_level(groups.get("level", "")),
                    source=groups.get("source") or groups.get("service", ""),
                    message=groups.get("message", line),
                    raw=line,
                    line_number=line_number,
                    extra={k: v for k, v in groups.items() 
                           if k not in ["timestamp", "level", "source", "message", "service"]}
                )
        
        # Fallback: treat whole line as message
        return LogEntry(
            message=line,
            raw=line,
            line_number=line_number,
            level=self._detect_level(line)
        )
    
    def _normalize_level(self, level: str) -> str:
        """Normalize log level to standard names."""
        if not level:
            return "INFO"
        
        level = level.upper()
        mapping = {
            "WARN": "WARNING",
            "ERR": "ERROR",
            "FATAL": "ERROR",
            "CRITICAL": "ERROR",
            "VERBOSE": "DEBUG",
        }
        return mapping.get(level, level)
    
    def _detect_level(self, line: str) -> str:
        """Detect log level from message content."""
        line_lower = line.lower()
        
        if any(kw in line_lower for kw in ["error", "exception", "failed", "fatal"]):
            return "ERROR"
        elif any(kw in line_lower for kw in ["warn", "warning"]):
            return "WARNING"
        elif any(kw in line_lower for kw in ["debug"]):
            return "DEBUG"
        
        return "INFO"
    
    def parse_logs(self, content: str) -> List[LogEntry]:
        """Parse multiple lines of logs."""
        entries = []
        for i, line in enumerate(content.split("\n"), 1):
            entry = self.parse_line(line, i)
            if entry:
                entries.append(entry)
        return entries
    
    def categorize_error(self, message: str) -> List[str]:
        """Categorize an error message."""
        categories = []
        for pattern, category in self.ERROR_PATTERNS:
            if pattern.search(message):
                categories.append(category)
        return categories


class LogParseTool(BaseTool):
    """Parse and filter logs from Docker containers or files."""
    
    NAME = "log_parse"
    
    DESCRIPTION = """Parse and filter application logs.

Sources:
- Docker container logs (via docker_logs)
- Log files in workspace
- Raw log text

Filtering:
- By level: error, warning, info, debug
- By time: last N minutes
- By pattern: regex search

Examples:
    log_parse(source="backend", level="error")     # Backend errors
    log_parse(source="frontend", last_minutes=5)   # Recent frontend logs
    log_parse(file="app.log", pattern="timeout")   # Search for timeouts
"""
    
    def __init__(self, *, workspace: Workspace):
        super().__init__(name=self.NAME, category=ToolCategory.RUNTIME)
        if workspace is None:
            raise ValueError(f"{self.NAME}: workspace is required (no bypass construction)")
        self.workspace = workspace
        self._parser = LogParser()
    
    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "Docker service name (backend, frontend, db)"
                    },
                    "file": {
                        "type": "string",
                        "description": "Log file path (alternative to source)"
                    },
                    "level": {
                        "type": "string",
                        "enum": ["error", "warning", "info", "debug", "all"],
                        "description": "Minimum log level to show (default: all)"
                    },
                    "pattern": {
                        "type": "string",
                        "description": "Regex pattern to filter messages"
                    },
                    "last_lines": {
                        "type": "integer",
                        "description": "Number of most recent lines (default: 100)"
                    },
                    "raw_logs": {
                        "type": "string",
                        "description": "Raw log content to parse (alternative to source/file)"
                    }
                },
                "required": []
            }
        )
    
    def execute(
        self,
        source: Optional[str] = None,
        file: Optional[str] = None,
        level: str = "all",
        pattern: Optional[str] = None,
        last_lines: int = 100,
        raw_logs: Optional[str] = None
    ) -> ToolResult:
        # Get log content
        if raw_logs:
            content = raw_logs
        elif file:
            try:
                file_path = self.workspace.resolve(file)
                if not file_path.exists():
                    return ToolResult.fail(f"Log file not found: {file}")
                content = file_path.read_text()
            except Exception as e:
                return ToolResult.fail(f"Cannot read log file: {e}")
        elif source:
            # Get from Docker
            content = self._get_docker_logs(source, last_lines)
            if content is None:
                return ToolResult.fail(f"Cannot get logs for service: {source}")
        else:
            return ToolResult.fail("Provide source, file, or raw_logs")
        
        # Parse logs
        entries = self._parser.parse_logs(content)
        
        # Filter by level
        level_priority = {"ERROR": 4, "WARNING": 3, "INFO": 2, "DEBUG": 1}
        if level != "all":
            min_priority = level_priority.get(level.upper(), 0)
            entries = [e for e in entries if level_priority.get(e.level, 0) >= min_priority]
        
        # Filter by pattern
        if pattern:
            try:
                regex = re.compile(pattern, re.IGNORECASE)
                entries = [e for e in entries if regex.search(e.message) or regex.search(e.raw)]
            except re.error as e:
                return ToolResult.fail(f"Invalid regex pattern: {e}")
        
        # Limit output
        if len(entries) > last_lines:
            entries = entries[-last_lines:]
        
        # Format output
        output_lines = []
        for entry in entries:
            prefix = f"[{entry.level}]" if entry.level != "INFO" else ""
            ts = f"{entry.timestamp} " if entry.timestamp else ""
            src = f"({entry.source}) " if entry.source else ""
            output_lines.append(f"{ts}{prefix}{src}{entry.message}")
        
        # Count by level
        level_counts = Counter(e.level for e in entries)
        
        return ToolResult.ok(data={
            "total_entries": len(entries),
            "by_level": dict(level_counts),
            "output": "\n".join(output_lines[-100:]),  # Limit final output
            "has_errors": level_counts.get("ERROR", 0) > 0,
            "error_count": level_counts.get("ERROR", 0),
        })
    
    def _get_docker_logs(self, service: str, lines: int) -> Optional[str]:
        """Get logs from Docker container."""
        import subprocess
        
        try:
            # Find compose file
            compose_paths = [
                self.workspace.resolve("docker/docker-compose.yml"),
                self.workspace.resolve("docker/docker-compose.dev.yml"),
                self.workspace.resolve("docker-compose.yml"),
            ]
            
            compose_file = None
            for path in compose_paths:
                if path.exists():
                    compose_file = path
                    break
            
            if not compose_file:
                return None
            
            result = subprocess.run(
                [_rt936(), "compose", "-f", str(compose_file), "logs", "--tail", str(lines), service],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(self.workspace.base_root),
                encoding='utf-8',
                errors='replace',
            )
            
            return result.stdout + result.stderr
            
        except Exception:
            return None


class LogAnalyzeTool(BaseTool):
    """Analyze logs for patterns, errors, and anomalies."""
    
    NAME = "log_analyze"
    
    DESCRIPTION = """Analyze logs to identify issues and patterns.

Analysis includes:
- Error categorization and frequency
- Common error messages (grouped)
- Timeline of errors
- Performance indicators (response times, timeouts)

Examples:
    log_analyze(source="backend")              # Analyze backend logs
    log_analyze(file="app.log")                # Analyze log file
    log_analyze(source="frontend", focus="network")  # Focus on network issues
"""
    
    def __init__(self, *, workspace: Workspace):
        super().__init__(name=self.NAME, category=ToolCategory.RUNTIME)
        if workspace is None:
            raise ValueError(f"{self.NAME}: workspace is required (no bypass construction)")
        self.workspace = workspace
        self._parser = LogParser()
        self._parse_tool = LogParseTool(workspace=self.workspace)
    
    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "Docker service name"
                    },
                    "file": {
                        "type": "string",
                        "description": "Log file path"
                    },
                    "focus": {
                        "type": "string",
                        "enum": ["all", "errors", "network", "auth", "performance"],
                        "description": "Focus area for analysis (default: errors)"
                    },
                    "raw_logs": {
                        "type": "string",
                        "description": "Raw log content to analyze"
                    }
                },
                "required": []
            }
        )
    
    def execute(
        self,
        source: Optional[str] = None,
        file: Optional[str] = None,
        focus: str = "errors",
        raw_logs: Optional[str] = None
    ) -> ToolResult:
        # Get parsed logs
        parse_result = self._parse_tool.execute(
            source=source,
            file=file,
            raw_logs=raw_logs,
            level="all",
            last_lines=500
        )
        
        if not parse_result.success:
            return parse_result
        
        # Re-parse for detailed analysis
        content = raw_logs
        if not content:
            if file:
                file_path = self.workspace.resolve(file)
                content = file_path.read_text() if file_path.exists() else ""
            elif source:
                content = self._parse_tool._get_docker_logs(source, 500) or ""
        
        entries = self._parser.parse_logs(content)
        
        # Analyze
        analysis = {
            "total_lines": len(entries),
            "by_level": dict(Counter(e.level for e in entries)),
            "errors": [],
            "warnings": [],
            "error_categories": {},
            "common_errors": [],
            "suggestions": [],
        }
        
        # Collect errors and warnings
        error_messages = []
        for entry in entries:
            if entry.level == "ERROR":
                analysis["errors"].append({
                    "line": entry.line_number,
                    "message": entry.message[:200],
                    "categories": self._parser.categorize_error(entry.message)
                })
                error_messages.append(entry.message)
            elif entry.level == "WARNING":
                analysis["warnings"].append({
                    "line": entry.line_number,
                    "message": entry.message[:200]
                })
        
        # Limit lists
        analysis["errors"] = analysis["errors"][:20]
        analysis["warnings"] = analysis["warnings"][:10]
        
        # Categorize errors
        all_categories = []
        for entry in entries:
            if entry.level == "ERROR":
                all_categories.extend(self._parser.categorize_error(entry.message))
        
        analysis["error_categories"] = dict(Counter(all_categories))
        
        # Find common error patterns
        if error_messages:
            # Simplify messages for grouping
            simplified = [self._simplify_message(m) for m in error_messages]
            common = Counter(simplified).most_common(5)
            analysis["common_errors"] = [
                {"pattern": pattern, "count": count}
                for pattern, count in common
            ]
        
        # Generate suggestions based on categories
        category_suggestions = {
            "network": "Check if all services are running and network connectivity is OK",
            "auth": "Verify authentication tokens and credentials",
            "not_found": "Check file paths, URLs, and database table names",
            "timeout": "Consider increasing timeouts or checking for slow queries",
            "server_error": "Check backend logs for stack traces",
            "connection": "Verify database/service connectivity and Docker network",
        }
        
        for category in analysis["error_categories"]:
            if category in category_suggestions:
                analysis["suggestions"].append(category_suggestions[category])
        
        # Summary
        error_count = analysis["by_level"].get("ERROR", 0)
        warning_count = analysis["by_level"].get("WARNING", 0)
        
        if error_count == 0 and warning_count == 0:
            analysis["summary"] = "No errors or warnings found"
            analysis["health"] = "healthy"
        elif error_count == 0:
            analysis["summary"] = f"{warning_count} warnings found"
            analysis["health"] = "warning"
        else:
            analysis["summary"] = f"{error_count} errors, {warning_count} warnings found"
            analysis["health"] = "unhealthy"
        
        return ToolResult.ok(data=analysis)
    
    def _simplify_message(self, message: str) -> str:
        """Simplify error message for pattern matching."""
        # Remove specific values
        simplified = re.sub(r"'[^']*'", "'...'", message)
        simplified = re.sub(r'"[^"]*"', '"..."', simplified)
        simplified = re.sub(r"\b\d+\b", "N", simplified)
        simplified = re.sub(r"\b[0-9a-f]{8,}\b", "ID", simplified, flags=re.I)
        
        # Truncate
        return simplified[:100]


class LogSearchTool(BaseTool):
    """Search logs with regex and context."""
    
    NAME = "log_search"
    
    DESCRIPTION = """Search logs for specific patterns with context.

Features:
- Regex pattern matching
- Context lines before/after matches
- Multiple sources (Docker services, files)
- Highlight matches

Examples:
    log_search("ERROR", source="backend")
    log_search("timeout|refused", source="frontend", context=3)
    log_search("SELECT.*FROM", file="queries.log")
"""
    
    def __init__(self, *, workspace: Workspace):
        super().__init__(name=self.NAME, category=ToolCategory.RUNTIME)
        if workspace is None:
            raise ValueError(f"{self.NAME}: workspace is required (no bypass construction)")
        self.workspace = workspace
    
    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Regex pattern to search for"
                    },
                    "source": {
                        "type": "string",
                        "description": "Docker service name"
                    },
                    "file": {
                        "type": "string",
                        "description": "Log file path"
                    },
                    "context": {
                        "type": "integer",
                        "description": "Lines of context before/after match (default: 2)"
                    },
                    "max_matches": {
                        "type": "integer",
                        "description": "Maximum matches to return (default: 20)"
                    }
                },
                "required": ["pattern"]
            }
        )
    
    def execute(
        self,
        pattern: str,
        source: Optional[str] = None,
        file: Optional[str] = None,
        context: int = 2,
        max_matches: int = 20
    ) -> ToolResult:
        # Compile pattern
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            return ToolResult.fail(f"Invalid regex: {e}")
        
        # Get log content
        content = ""
        if file:
            try:
                file_path = self.workspace.resolve(file)
                if not file_path.exists():
                    return ToolResult.fail(f"File not found: {file}")
                content = file_path.read_text()
            except Exception as e:
                return ToolResult.fail(f"Cannot read file: {e}")
        elif source:
            parse_tool = LogParseTool(workspace=self.workspace)
            content = parse_tool._get_docker_logs(source, 500) or ""
            if not content:
                return ToolResult.fail(f"Cannot get logs for: {source}")
        else:
            return ToolResult.fail("Provide source or file")
        
        lines = content.split("\n")
        matches = []
        
        # Find matches with context
        for i, line in enumerate(lines):
            if regex.search(line):
                # Get context
                start = max(0, i - context)
                end = min(len(lines), i + context + 1)
                
                context_lines = []
                for j in range(start, end):
                    prefix = ">>>" if j == i else "   "
                    context_lines.append(f"{prefix} {j + 1}: {lines[j]}")
                
                matches.append({
                    "line_number": i + 1,
                    "match": line[:200],
                    "context": "\n".join(context_lines)
                })
                
                if len(matches) >= max_matches:
                    break
        
        if not matches:
            return ToolResult.ok(data={
                "pattern": pattern,
                "matches": 0,
                "message": f"No matches found for pattern: {pattern}"
            })
        
        # Format output
        output_parts = []
        for m in matches:
            output_parts.append(f"--- Line {m['line_number']} ---")
            output_parts.append(m["context"])
            output_parts.append("")
        
        return ToolResult.ok(data={
            "pattern": pattern,
            "matches": len(matches),
            "total_in_log": sum(1 for line in lines if regex.search(line)),
            "results": matches[:10],  # Limit detailed results
            "output": "\n".join(output_parts[:50])  # Limit output
        })


def create_log_tools(*, workspace: Workspace) -> List[BaseTool]:
    """Create all log tools."""
    return [
        LogParseTool(workspace=workspace),
        LogAnalyzeTool(workspace=workspace),
        LogSearchTool(workspace=workspace),
    ]


__all__ = [
    "LogParser",
    "LogEntry",
    "LogParseTool",
    "LogAnalyzeTool",
    "LogSearchTool",
    "create_log_tools",
]

