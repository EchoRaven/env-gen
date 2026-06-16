"""Shared imports/helpers for split team tool modules."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.tool import BaseTool, ToolResult, create_tool_param, ToolCategory


class RunParallelReasoningTool(BaseTool):
    """Run parallel reasoning across multiple candidate explanations."""
    
    NAME = "run_parallel_reasoning"
    DESCRIPTION = """Run a parallel reasoning session for complex diagnosis or decision support.

This spawns multiple workers, each analyzing a different candidate explanation.
They will:
1. Gather evidence for their candidate
2. Challenge each other's findings
3. Run challenge rounds until consensus or max rounds

USE THIS FOR:
- Complex bugs with multiple possible causes
- Architecture decisions needing multiple perspectives
- Any problem where parallel analysis helps

Example:
    run_parallel_reasoning(
        problem="API returns 500 error intermittently",
        candidates=["Database connection timeout", "Memory leak", "Race condition"]
    )
"""
    
    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.CUSTOM)
        self._parallel_reasoning = None
        self._agent_id = None
    
    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "problem": {
                        "type": "string",
                        "description": "Description of the problem to investigate",
                    },
                    "candidates": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of candidate explanations to analyze (2-5 recommended)",
                    },
                    "context": {
                        "type": "object",
                        "description": "Optional context (files, logs, etc.)",
                    },
                },
                "required": ["problem", "candidates"],
            }
        )
    
    async def execute(
        self,
        problem: str,
        candidates: List[str],
        context: Optional[Dict] = None,
        **kwargs
    ) -> ToolResult:
        if not self._parallel_reasoning:
            return ToolResult(success=False, error_message="Parallel reasoning protocol not configured")
        
        if len(candidates) < 2:
            return ToolResult(success=False, error_message="Need at least 2 candidates for parallel reasoning")
        
        if len(candidates) > 5:
            return ToolResult(success=False, error_message="Too many candidates (max 5). Focus on the strongest options.")
        
        try:
            result = await self._parallel_reasoning.run_parallel_reasoning(
                problem=problem,
                candidates=candidates,
                requester_id=self._agent_id or "",
                context=context,
            )
            
            return ToolResult(success=True, data=result.to_dict())
        except Exception as e:
            return ToolResult(success=False, error_message=str(e))


# ============================================================
# 3. PLAN DECISION TOOLS
# ============================================================
