"""
Generation Context - Shared state across all agents
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime


@dataclass
class GeneratedFile:
    """Track a generated file"""
    path: str
    content: str
    phase: str  # Which phase generated it
    timestamp: datetime = field(default_factory=datetime.now)
    verified: bool = False
    issues: List[str] = field(default_factory=list)


@dataclass
class GenerationContext:
    """
    Shared context for environment generation.
    
    Passed between all agents to maintain state.
    """
    # Basic info
    name: str
    display_name: str = ""
    description: str = ""
    domain_type: str = "custom"
    
    # Output configuration
    output_dir: Optional[Path] = None
    
    # Design phase outputs
    entities: List[Dict] = field(default_factory=list)
    features: List[str] = field(default_factory=list)
    api_endpoints: List[Dict] = field(default_factory=list)
    
    # Ports - all dynamically assigned by orchestrator
    # These are shared across all agents to ensure consistency
    api_port: int = 0           # External API port (host machine)
    ui_port: int = 0            # External frontend port (host machine)
    openenv_port: int = 0       # OpenEnv compatibility port
    backend_internal_port: int = 0   # Backend server port inside container
    frontend_internal_port: int = 0  # Frontend dev server port inside container
    db_port: int = 0                 # PostgreSQL port (dynamically assigned)
    
    # Generated files tracking
    files: Dict[str, GeneratedFile] = field(default_factory=dict)
    
    # Phase tracking
    current_phase: str = ""
    completed_phases: List[str] = field(default_factory=list)
    phase_results: Dict[str, Any] = field(default_factory=dict)
    
    # Issues and fixes
    issues_found: List[str] = field(default_factory=list)
    fixes_applied: List[str] = field(default_factory=list)
    
    # Screenshot-based generation
    reference_screenshots: List[str] = field(default_factory=list)  # Paths to reference images
    design_analysis: Optional[Dict] = None  # Extracted design info from screenshots
    
    def __post_init__(self):
        if not self.display_name:
            self.display_name = self.name.replace("_", " ").title()
        if self.output_dir and isinstance(self.output_dir, str):
            self.output_dir = Path(self.output_dir)
    
    @property
    def class_name(self) -> str:
        """PascalCase name for class names"""
        return "".join(word.capitalize() for word in self.name.split("_"))
    
    def add_file(self, path: str, content: str, phase: str) -> None:
        """Record a generated file"""
        self.files[path] = GeneratedFile(
            path=path,
            content=content,
            phase=phase,
        )
    
    def get_file(self, path: str) -> Optional[str]:
        """Get content of a generated file"""
        f = self.files.get(path)
        return f.content if f else None
    
    def get_files_by_phase(self, phase: str) -> List[str]:
        """Get all files generated in a phase"""
        return [path for path, f in self.files.items() if f.phase == phase]
    
    def list_all_files(self) -> List[str]:
        """List all generated file paths"""
        return list(self.files.keys())
    
    def mark_phase_complete(self, phase: str, result: Any = None) -> None:
        """Mark a phase as complete"""
        if phase not in self.completed_phases:
            self.completed_phases.append(phase)
        self.phase_results[phase] = result
    
    def is_phase_complete(self, phase: str) -> bool:
        """Check if a phase is complete"""
        return phase in self.completed_phases
    
    def to_dict(self) -> Dict[str, Any]:
        """Export context as dict"""
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "domain_type": self.domain_type,
            "entities": self.entities,
            "features": self.features,
            "files_count": len(self.files),
            "completed_phases": self.completed_phases,
        }

