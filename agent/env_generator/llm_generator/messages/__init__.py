"""
Messages - Re-exports from utils.message for backward compatibility

All message types are now unified in utils/message.py
"""

from utils.message import (
    Task,
    TaskType,
    FileSpec,
    Issue,
    IssueSeverity,
    TaskResult,
    FixResult,
    VerifyResult,
    TaskStatus,
    CommandResult,
)

__all__ = [
    "Task",
    "TaskType", 
    "FileSpec",
    "Issue",
    "IssueSeverity",
    "TaskResult",
    "FixResult",
    "VerifyResult",
    "TaskStatus",
    "CommandResult",
]

