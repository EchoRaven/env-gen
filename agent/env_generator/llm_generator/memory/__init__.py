"""
Memory System for LLM Generator

Based on utils/memory.py base classes:
- ShortTermMemory
- LongTermMemory
- WorkingMemory
- LLMSummarizingCondenser
- AgentMemory

This module provides:
1. GeneratorMemory - Extended AgentMemory for code generation
2. MemoryBank - Structured project documentation (Cursor Memory Bank style)
3. SmartMessageCompressor - Category-based message compression
4. MessageImportanceScorer - Importance scoring for message retention
5. MemoryBankSync - Auto-sync to MemoryBank
"""

from .generator_memory import (
    GeneratorMemory,
    MessageCategory,
    MessageImportanceScorer,
    SmartMessageCompressor,
    MemoryBankSync,
    ImportanceScore,
)
from .memory_bank import MemoryBank

__all__ = [
    "GeneratorMemory",
    "MemoryBank",
    "MessageCategory",
    "MessageImportanceScorer",
    "SmartMessageCompressor",
    "MemoryBankSync",
    "ImportanceScore",
]
