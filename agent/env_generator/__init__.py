"""
Environment Generator

A multi-agent system for generating OpenEnv-compatible environments.

Usage:
    # CLI
    OPENAI_API_KEY=sk-... python -m env_generator.llm_generator.main --name calendar
    
    # Python API
    from env_generator.llm_generator import Orchestrator, GenerationContext
"""

from .llm_generator import Orchestrator, GenerationContext

__all__ = [
    "Orchestrator",
    "GenerationContext",
]
