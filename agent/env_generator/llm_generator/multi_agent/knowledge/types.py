"""
Knowledge Types - Data structures for the knowledge management system.

Knowledge entries are self-contained units that provide actionable information
to agents. Each entry combines problem context with solutions, examples, and
best practices so agents can immediately apply what they learn.
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid


class KnowledgeCategory(str, Enum):
    """
    Categories of knowledge - not just issues, but all useful information.
    """
    # Problem-Solution pairs
    ISSUE_SOLUTION = "issue_solution"       # Bug/error and how to fix it
    
    # Tool and API usage
    TOOL_USAGE = "tool_usage"               # How to use a specific tool correctly
    API_PATTERN = "api_pattern"             # API design patterns and conventions
    
    # Database and data
    DB_SCHEMA = "db_schema"                 # Database schema patterns
    DATA_MAPPING = "data_mapping"           # HuggingFace dataset field mappings
    SEED_DATA = "seed_data"                 # Seed data generation patterns
    
    # Frontend and UI/UX
    UI_COMPONENT = "ui_component"           # UI component patterns
    UI_LAYOUT = "ui_layout"                 # Layout and structure patterns
    UI_STYLE = "ui_style"                   # Colors, typography, spacing
    UI_ANIMATION = "ui_animation"           # Animation and transitions
    UI_ACCESSIBILITY = "ui_accessibility"   # A11y best practices
    UI_RESPONSIVE = "ui_responsive"         # Responsive design patterns
    
    # Code patterns
    CODE_PATTERN = "code_pattern"           # General coding patterns
    REACT_PATTERN = "react_pattern"         # React-specific patterns
    EXPRESS_PATTERN = "express_pattern"     # Express.js patterns
    
    # Configuration
    CONFIG = "config"                       # Configuration patterns
    DOCKER = "docker"                       # Docker/container patterns
    
    # Integration
    INTEGRATION = "integration"             # Frontend-backend integration
    
    # Best practices
    BEST_PRACTICE = "best_practice"         # General best practices
    ANTI_PATTERN = "anti_pattern"           # What NOT to do

    # Structured engineering documents (Cutover 15)
    ADR = "adr"                             # Architecture Decision Record
    RUNBOOK = "runbook"                     # Operational procedure
    POSTMORTEM = "postmortem"               # Incident retrospective


class Severity(str, Enum):
    """Severity/importance level"""
    CRITICAL = "critical"   # Will cause failure if ignored
    HIGH = "high"          # Will cause significant issues
    MEDIUM = "medium"      # May cause issues
    LOW = "low"            # Nice to know, optimization


@dataclass
class Knowledge:
    """
    A knowledge entry - self-contained, actionable information.
    
    Design principle: When an agent retrieves this, they should have
    everything they need to understand and apply the knowledge.
    """
    # Identity
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""                         # Short, descriptive title
    category: KnowledgeCategory = KnowledgeCategory.BEST_PRACTICE
    
    # Core content - the actual knowledge
    summary: str = ""                       # One-line summary
    content: str = ""                       # Full explanation/description
    
    # For issue/solution type
    problem: str = ""                       # What's the problem/error
    symptoms: List[str] = field(default_factory=list)  # Error messages, logs
    root_cause: str = ""                    # Why does this happen
    solution: str = ""                      # How to fix/handle it
    
    # Code examples
    example_code: str = ""                  # Correct example
    wrong_code: str = ""                    # What NOT to do (for contrast)
    
    # Context and metadata
    tags: List[str] = field(default_factory=list)      # For search
    keywords: List[str] = field(default_factory=list)  # Trigger words
    severity: Severity = Severity.MEDIUM
    
    # Applicability
    applies_to: List[str] = field(default_factory=list)  # Agents, file types, etc.
    prerequisites: List[str] = field(default_factory=list)  # What to know first
    related_ids: List[str] = field(default_factory=list)  # Related knowledge

    # Structured payload for ADR/RUNBOOK/POSTMORTEM categories (Cutover 15).
    # Free-form for other categories.
    structured_fields: Dict[str, Any] = field(default_factory=dict)
    
    # Usage tracking
    usage_count: int = 0                    # How often accessed
    usefulness_score: float = 0.0           # Feedback-based score
    last_used: Optional[datetime] = None
    
    # Provenance
    source: str = ""                        # Where this came from
    source_url: str = ""                    # Reference URL
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage"""
        return {
            "id": self.id,
            "title": self.title,
            "category": self.category.value,
            "summary": self.summary,
            "content": self.content,
            "problem": self.problem,
            "symptoms": self.symptoms,
            "root_cause": self.root_cause,
            "solution": self.solution,
            "example_code": self.example_code,
            "wrong_code": self.wrong_code,
            "tags": self.tags,
            "keywords": self.keywords,
            "severity": self.severity.value,
            "applies_to": self.applies_to,
            "prerequisites": self.prerequisites,
            "related_ids": self.related_ids,
            "structured_fields": self.structured_fields,
            "usage_count": self.usage_count,
            "usefulness_score": self.usefulness_score,
            "last_used": self.last_used.isoformat() if self.last_used else None,
            "source": self.source,
            "source_url": self.source_url,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Knowledge":
        """Create from dictionary"""
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            title=data.get("title", ""),
            category=KnowledgeCategory(data.get("category", "best_practice")),
            summary=data.get("summary", ""),
            content=data.get("content", ""),
            problem=data.get("problem", ""),
            symptoms=data.get("symptoms", []),
            root_cause=data.get("root_cause", ""),
            solution=data.get("solution", ""),
            example_code=data.get("example_code", ""),
            wrong_code=data.get("wrong_code", ""),
            tags=data.get("tags", []),
            keywords=data.get("keywords", []),
            severity=Severity(data.get("severity", "medium")),
            applies_to=data.get("applies_to", []),
            prerequisites=data.get("prerequisites", []),
            related_ids=data.get("related_ids", []),
            structured_fields=data.get("structured_fields", {}) or {},
            usage_count=data.get("usage_count", 0),
            usefulness_score=data.get("usefulness_score", 0.0),
            last_used=datetime.fromisoformat(data["last_used"]) if data.get("last_used") else None,
            source=data.get("source", ""),
            source_url=data.get("source_url", ""),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.now(),
        )
    
    def to_agent_prompt(self) -> str:
        """
        Format for agent consumption - this is what the agent sees after a search.
        Designed to be immediately actionable.
        """
        lines = [
            f"## {self.title}",
            f"**Category:** {self.category.value} | **Severity:** {self.severity.value}",
        ]
        
        if self.summary:
            lines.extend(["", self.summary])
        
        if self.content:
            lines.extend(["", "### Description", self.content])
        
        if self.problem:
            lines.extend(["", "### Problem", self.problem])
        
        if self.symptoms:
            lines.extend([
                "", 
                "### Symptoms (look for these in logs/errors)",
                *[f"- `{s}`" for s in self.symptoms[:5]]  # Limit to 5
            ])
        
        if self.root_cause:
            lines.extend(["", "### Root Cause", self.root_cause])
        
        if self.solution:
            lines.extend(["", "### Solution", self.solution])
        
        if self.example_code:
            lines.extend([
                "",
                "### Correct Example",
                "```",
                self.example_code,
                "```"
            ])
        
        if self.wrong_code:
            lines.extend([
                "",
                "### Wrong Example (DO NOT do this)",
                "```",
                self.wrong_code,
                "```"
            ])
        
        if self.tags:
            lines.extend(["", f"**Tags:** {', '.join(self.tags)}"])
        
        if self.source_url:
            lines.extend(["", f"**Reference:** {self.source_url}"])
        
        return "\n".join(lines)
    
    def get_search_text(self) -> str:
        """Get combined text for search indexing"""
        parts = [
            self.title,
            self.summary,
            self.content,
            self.problem,
            self.root_cause,
            self.solution,
            " ".join(self.symptoms),
            " ".join(self.tags),
            " ".join(self.keywords),
        ]
        return " ".join(filter(None, parts))


@dataclass 
class KnowledgeQuery:
    """Query for searching knowledge"""
    query: str                                          # Natural language query
    category: Optional[KnowledgeCategory] = None        # Filter by category
    tags: List[str] = field(default_factory=list)       # Filter by tags
    agent: Optional[str] = None                         # Context: which agent is asking
    current_task: Optional[str] = None                  # Context: what task
    severity_min: Optional[Severity] = None             # Minimum severity
    limit: int = 5                                      # Max results


@dataclass
class SearchResult:
    """Result from a knowledge search"""
    knowledge: Knowledge
    score: float                # Relevance score 0-1
    match_type: str             # How it matched: semantic, keyword, exact
    snippet: str = ""           # Relevant snippet from content
