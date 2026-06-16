"""Persona catalog extracted from team_protocols."""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

@dataclass
class AgentPersona:
    """Definition of an agent persona."""
    persona_id: str
    name: str
    description: str
    focus: List[str]  # What to focus on
    personality: str  # How to behave
    prompt_addition: str  # Added to system prompt
    
    def to_dict(self) -> Dict:
        return {
            "persona_id": self.persona_id,
            "name": self.name,
            "description": self.description,
            "focus": self.focus,
            "personality": self.personality,
        }


class PersonaCatalog:
    """
    Flexible persona catalog for spawned workers.
    """
    
    PREDEFINED_PERSONAS = {
        "risk_analyst": AgentPersona(
            persona_id="risk_analyst",
            name="Risk Analyst",
            description="Focus on security vulnerabilities and best practices",
            focus=["injection attacks", "authentication", "authorization", "data exposure", "OWASP Top 10"],
            personality="Paranoid and thorough. Assume all inputs are malicious.",
            prompt_addition="""You are a RISK ANALYST. Your job is to find high-risk flaws.
Focus on: SQL injection, XSS, CSRF, auth bypass, data exposure, insecure defaults.
Be paranoid - assume all user input is malicious.
Report issues with severity (Critical/High/Medium/Low).""",
        ),

        "performance_analyst": AgentPersona(
            persona_id="performance_analyst",
            name="Performance Analyst",
            description="Focus on performance issues and optimizations",
            focus=["N+1 queries", "memory leaks", "inefficient algorithms", "caching", "async operations"],
            personality="Efficiency-obsessed. Every millisecond matters.",
            prompt_addition="""You are a PERFORMANCE ANALYST. Your job is to find performance issues.
Focus on: N+1 queries, memory leaks, O(n²) algorithms, missing indexes, blocking I/O.
Think about scale - will this work with 1M users?
Report issues with estimated impact.""",
        ),

        "quality_analyst": AgentPersona(
            persona_id="quality_analyst",
            name="Quality Analyst",
            description="Focus on test coverage and quality",
            focus=["missing tests", "edge cases", "error handling", "integration tests"],
            personality="Skeptical. If it's not tested, it's broken.",
            prompt_addition="""You are a QUALITY ANALYST. Your job is to ensure work is well-tested.
Focus on: Missing unit tests, uncovered edge cases, error paths, integration gaps.
Ask: What could go wrong? Is that tested?
Suggest specific test cases for missing coverage.""",
        ),

        "challenger": AgentPersona(
            persona_id="challenger",
            name="Challenger",
            description="Challenge all assumptions and find problems",
            focus=["assumptions", "edge cases", "failure modes", "alternatives"],
            personality="Contrarian. If everyone agrees, something's wrong.",
            prompt_addition="""You are a CHALLENGER. Your job is to challenge everything.
Question every assumption. Find the holes in every argument.
Ask: What if this fails? What are we missing? What's the worst case?
Don't accept 'it usually works' - find when it doesn't.""",
        ),

        "supporter": AgentPersona(
            persona_id="supporter",
            name="Supporter",
            description="Find the good and build on it",
            focus=["strengths", "potential", "improvements", "best practices"],
            personality="Positive but not naive. Build on what works.",
            prompt_addition="""You are a SUPPORTER. Your job is to find what's working well.
Identify strengths and good patterns to build on.
Suggest improvements that enhance existing good code.
Balance positivity with practical suggestions.""",
        ),

        "root_cause_analyst": AgentPersona(
            persona_id="root_cause_analyst",
            name="Root Cause Analyst",
            description="Dig deep to find the true cause",
            focus=["5 whys", "causal chain", "systemic issues", "patterns"],
            personality="Persistent. The obvious answer is rarely the real one.",
            prompt_addition="""You are a ROOT CAUSE ANALYST. Your job is to find the TRUE cause.
Don't stop at symptoms - ask why 5 times.
Look for patterns - is this a one-off or systemic?
The fix should address the root cause, not just the symptom.""",
        ),

        "data_flow_analyst": AgentPersona(
            persona_id="data_flow_analyst",
            name="Data Flow Analyst",
            description="Follow the data to find issues",
            focus=["data flow", "state changes", "side effects", "data integrity"],
            personality="Methodical. Trace every byte.",
            prompt_addition="""You are a DATA FLOW ANALYST. Your job is to trace data flow.
Follow data from input to output. Where does it change? Where could it corrupt?
Check: data types, null handling, encoding, serialization boundaries.
Map the complete data journey.""",
        ),
    }
    
    def __init__(self):
        self._custom_personas: Dict[str, AgentPersona] = {}
        self._agent_personas: Dict[str, str] = {}  # agent_id -> persona_id
        self._logger = logging.getLogger("PersonaCatalog")

    def get_persona(self, persona_id: str) -> Optional[AgentPersona]:
        """Get a persona by ID."""
        if persona_id in self.PREDEFINED_PERSONAS:
            return self.PREDEFINED_PERSONAS[persona_id]
        return self._custom_personas.get(persona_id)

    def create_custom_persona(
        self,
        persona_id: str,
        name: str,
        description: str,
        focus: List[str],
        personality: str,
        prompt_addition: str,
    ) -> AgentPersona:
        """Create a custom persona."""
        role = AgentPersona(
            persona_id=persona_id,
            name=name,
            description=description,
            focus=focus,
            personality=personality,
            prompt_addition=prompt_addition,
        )
        self._custom_personas[persona_id] = role
        self._logger.info(f"Created custom persona: {persona_id}")
        return role

    def assign_persona(self, agent_id: str, persona_id: str) -> bool:
        """Assign a persona to an agent."""
        role = self.get_persona(persona_id)
        if not role:
            self._logger.warning(f"Persona {persona_id} not found")
            return False

        self._agent_personas[agent_id] = persona_id
        self._logger.info(f"Assigned persona {persona_id} to agent {agent_id}")
        return True

    def get_agent_persona(self, agent_id: str) -> Optional[AgentPersona]:
        """Get the persona assigned to an agent."""
        persona_id = self._agent_personas.get(agent_id)
        if persona_id:
            return self.get_persona(persona_id)
        return None

    def get_persona_prompt(self, persona_id: str) -> str:
        """Get the prompt addition for a persona."""
        role = self.get_persona(persona_id)
        return role.prompt_addition if role else ""

    def list_personas(self) -> List[AgentPersona]:
        """List all available personas."""
        roles = list(self.PREDEFINED_PERSONAS.values())
        roles.extend(self._custom_personas.values())
        return roles

    def get_quality_personas(self) -> List[str]:
        """Get IDs of quality-oriented personas."""
        return ["risk_analyst", "performance_analyst", "quality_analyst"]

    def get_challenge_personas(self) -> List[str]:
        """Get IDs of challenge-oriented personas."""
        return ["challenger", "supporter"]

    def get_diagnostic_personas(self) -> List[str]:
        """Get IDs of diagnostic personas."""
        return ["root_cause_analyst", "data_flow_analyst"]
