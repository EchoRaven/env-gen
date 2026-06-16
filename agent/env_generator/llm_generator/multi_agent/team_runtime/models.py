"""Shared models for team protocol runtime."""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

class AgentLifecycle(Enum):
    """Agent lifecycle states."""
    SPAWNING = "spawning"
    READY = "ready"
    WORKING = "working"
    IDLE = "idle"
    SHUTTING_DOWN = "shutting_down"
    TERMINATED = "terminated"


class AgentRuntimeKind(Enum):
    """High-level runtime classification for agent instances."""
    RESIDENT = "resident"
    EPHEMERAL = "ephemeral"


@dataclass
class SpawnedAgent:
    """Metadata for a task-scoped spawned runtime."""
    agent_id: str
    agent_type: str
    spawn_time: datetime = field(default_factory=datetime.now)
    parent_id: Optional[str] = None
    task: Optional[str] = None
    role: Optional[str] = None
    lifecycle: AgentLifecycle = AgentLifecycle.SPAWNING
    model: Optional[str] = None
    findings: Dict[str, Any] = field(default_factory=dict)
    task_done_event: Optional[asyncio.Event] = None
    result_done_event: Optional[asyncio.Event] = None
    
    def to_dict(self) -> Dict:
        return {
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "spawn_time": self.spawn_time.isoformat(),
            "parent_id": self.parent_id,
            "task": self.task,
            "role": self.role,
            "lifecycle": self.lifecycle.value,
            "model": self.model,
        }


@dataclass
class TeamAgentSpec:
    """Declarative specification for a managed team member."""
    agent_id: str
    description: str
    agent_type: str = "worker"
    role: Optional[str] = None
    task: Optional[str] = None
    config_profile: Optional[str] = None
    skills: List[str] = field(default_factory=list)
    inherit_parent_skills: bool = True
    capabilities: List[str] = field(default_factory=list)
    model: Optional[str] = None
    write_scopes: List[str] = field(default_factory=list)
    include_vision: Optional[bool] = None
    context: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)
    disabled_tools: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "description": self.description,
            "agent_type": self.agent_type,
            "role": self.role,
            "task": self.task,
            "config_profile": self.config_profile,
            "skills": self.skills,
            "inherit_parent_skills": self.inherit_parent_skills,
            "capabilities": self.capabilities,
            "model": self.model,
            "write_scopes": self.write_scopes,
            "include_vision": self.include_vision,
            "context": self.context,
            "depends_on": self.depends_on,
            "disabled_tools": self.disabled_tools,
        }


@dataclass
class AgentTeam:
    """Runtime team definition + lifecycle state."""
    team_id: str
    parent_id: Optional[str]
    description: str
    collaboration: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    launched_at: Optional[datetime] = None
    status: str = "created"  # created | launching | running | paused | completed | failed | terminated
    members: Dict[str, TeamAgentSpec] = field(default_factory=dict)
    runtime_agent_ids: Dict[str, str] = field(default_factory=dict)  # member_id -> runtime agent_id
    member_states: Dict[str, str] = field(default_factory=dict)  # member_id -> pending|running|completed|failed|paused|terminated
    launch_order: List[str] = field(default_factory=list)
    last_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "team_id": self.team_id,
            "parent_id": self.parent_id,
            "description": self.description,
            "collaboration": self.collaboration,
            "created_at": self.created_at.isoformat(),
            "launched_at": self.launched_at.isoformat() if self.launched_at else None,
            "status": self.status,
            "members": {k: v.to_dict() for k, v in self.members.items()},
            "runtime_agent_ids": self.runtime_agent_ids,
            "member_states": self.member_states,
            "launch_order": self.launch_order,
            "last_error": self.last_error,
        }

class CandidateStatus(Enum):
    """Status of one reasoning candidate."""
    PROPOSED = "proposed"
    ANALYZING = "analyzing"
    SUPPORTED = "supported"
    CHALLENGED = "challenged"
    REFUTED = "refuted"
    CONSENSUS = "consensus"


@dataclass
class ReasoningCandidate:
    """One candidate explanation being analyzed in parallel."""
    id: str
    description: str
    proposed_by: Optional[str] = None
    worker_id: Optional[str] = None
    status: CandidateStatus = CandidateStatus.PROPOSED
    evidence: List[Dict] = field(default_factory=list)
    challenges: List[Dict] = field(default_factory=list)
    confidence: float = 0.5  # 0-1
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "description": self.description,
            "proposed_by": self.proposed_by,
            "worker_id": self.worker_id,
            "status": self.status.value,
            "evidence": self.evidence,
            "challenges": self.challenges,
            "confidence": self.confidence,
        }


@dataclass
class ParallelReasoningResult:
    """Result of a parallel candidate analysis session."""
    problem: str
    winning_candidate: Optional[ReasoningCandidate] = None
    all_candidates: List[ReasoningCandidate] = field(default_factory=list)
    challenge_rounds: int = 0
    consensus_reached: bool = False
    summary: str = ""
    duration: float = 0.0
    
    def to_dict(self) -> Dict:
        return {
            "problem": self.problem,
            "winning_candidate": self.winning_candidate.to_dict() if self.winning_candidate else None,
            "all_candidates": [h.to_dict() for h in self.all_candidates],
            "challenge_rounds": self.challenge_rounds,
            "consensus_reached": self.consensus_reached,
            "summary": self.summary,
            "duration": self.duration,
        }

class PlanStatus(Enum):
    """Plan approval status."""
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVISION_REQUESTED = "revision_requested"


@dataclass
class Plan:
    """A plan submitted for a decision."""
    id: str
    agent_id: str
    title: str
    description: str
    steps: List[Dict] = field(default_factory=list)
    status: PlanStatus = PlanStatus.DRAFT
    feedback: Optional[str] = None
    decision_maker_id: Optional[str] = None
    submitted_at: Optional[datetime] = None
    decided_at: Optional[datetime] = None
    revision_count: int = 0
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "title": self.title,
            "description": self.description,
            "steps": self.steps,
            "status": self.status.value,
            "feedback": self.feedback,
            "decision_maker_id": self.decision_maker_id,
            "revision_count": self.revision_count,
        }

class PracticeType(Enum):
    """Types of team practices."""
    PARALLEL_REASONING = "parallel_reasoning"   # Multi-candidate reasoning
    QUALITY_ANALYSIS = "quality_analysis"       # Multi-angle analysis teams
    PARALLEL_EXECUTION = "parallel_execution"   # Parallel task-scoped workers
    DEBUGGING = "debugging"                     # Multi-perspective debugging
    CUSTOM = "custom"                # Custom team patterns


@dataclass
class TeamPractice:
    """
    A recorded team practice that can be reused.
    
    Stores successful team collaboration patterns:
    - What problem was being solved
    - What agents were spawned (types, roles)
    - What was the outcome
    - How effective was it
    """
    id: str
    practice_type: PracticeType
    problem_category: str  # e.g., "api_bug", "performance", "security", "ui_component"
    description: str
    
    # Team composition
    agents_spawned: List[Dict] = field(default_factory=list)  # [{type, role, task}]
    
    # Context
    context: Dict[str, Any] = field(default_factory=dict)  # Original problem context
    
    # Outcome
    success: bool = False
    outcome_summary: str = ""
    findings: List[Dict] = field(default_factory=list)  # Key findings from the team
    
    # Metrics
    duration_seconds: float = 0.0
    agent_count: int = 0
    
    # Metadata
    created_at: datetime = field(default_factory=datetime.now)
    created_by: Optional[str] = None  # Agent that created this practice
    reuse_count: int = 0  # How many times this practice has been reused
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "practice_type": self.practice_type.value,
            "problem_category": self.problem_category,
            "description": self.description,
            "agents_spawned": self.agents_spawned,
            "context": self.context,
            "success": self.success,
            "outcome_summary": self.outcome_summary,
            "findings": self.findings,
            "duration_seconds": self.duration_seconds,
            "agent_count": self.agent_count,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "reuse_count": self.reuse_count,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "TeamPractice":
        data = data.copy()
        data["practice_type"] = PracticeType(data["practice_type"])
        if "created_at" in data and isinstance(data["created_at"], str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        return cls(**data)

    def to_knowledge_format(self) -> Dict:
        """Convert to format suitable for knowledge storage."""
        return {
            "type": "team_practice",
            "category": self.problem_category,
            "pattern": {
                "practice_type": self.practice_type.value,
                "team_composition": [
                    {"type": a["type"], "role": a.get("role")}
                    for a in self.agents_spawned
                ],
                "agent_count": self.agent_count,
            },
            "problem": self.description,
            "solution": self.outcome_summary,
            "success": self.success,
            "key_findings": self.findings[:3],
            "reuse_hint": (
                f"For {self.problem_category} problems, spawn {self.agent_count} agents "
                f"with roles: {[a.get('role', a['type']) for a in self.agents_spawned]}"
            ),
        }

__all__ = [
    "AgentLifecycle", "AgentRuntimeKind", "SpawnedAgent", "TeamAgentSpec", "AgentTeam",
    "CandidateStatus", "ReasoningCandidate", "ParallelReasoningResult",
    "PlanStatus", "Plan",
    "PracticeType", "TeamPractice",
]
