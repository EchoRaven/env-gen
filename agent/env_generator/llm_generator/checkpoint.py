"""
Checkpoint System for Progress Persistence

Allows generation to be resumed after interruption by:
- Saving state after each phase/file
- Loading state on restart with --resume flag
- Skipping already completed work
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
import shutil


class CheckpointJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder for checkpoint data."""
    def default(self, obj):
        if hasattr(obj, 'to_dict'):
            return obj.to_dict()
        if hasattr(obj, '__dict__'):
            return {k: v for k, v in obj.__dict__.items() if not k.startswith('_')}
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, Enum):
            return obj.value
        try:
            return str(obj)
        except Exception:
            return f"<non-serializable: {type(obj).__name__}>"


@dataclass
class FileCheckpoint:
    """State of a single file"""
    path: str
    phase: str
    status: str  # "pending" | "generating" | "reflecting" | "complete" | "failed"
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    content_hash: Optional[str] = None
    issues: List[str] = field(default_factory=list)
    fixes: List[str] = field(default_factory=list)


@dataclass
class PhaseCheckpoint:
    """State of a single phase"""
    name: str
    status: str  # "pending" | "planning" | "generating" | "reflecting" | "complete" | "failed"
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    iteration: int = 0
    planned_files: List[str] = field(default_factory=list)
    generated_files: List[str] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    fixes: List[str] = field(default_factory=list)


@dataclass
class GenerationCheckpoint:
    """Complete generation state"""
    version: str = "1.0"
    name: str = ""
    description: str = ""
    domain_type: str = ""
    started_at: str = ""
    last_updated: str = ""
    status: str = "pending"  # "pending" | "running" | "complete" | "failed"
    current_phase: str = ""
    resume_count: int = 0
    last_error: str = ""
    phases: Dict[str, PhaseCheckpoint] = field(default_factory=dict)
    files: Dict[str, FileCheckpoint] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return {
            "version": self.version,
            "name": self.name,
            "description": self.description,
            "domain_type": self.domain_type,
            "started_at": self.started_at,
            "last_updated": self.last_updated,
            "status": self.status,
            "current_phase": self.current_phase,
            "resume_count": self.resume_count,
            "last_error": self.last_error,
            "phases": {k: asdict(v) for k, v in self.phases.items()},
            "files": {k: asdict(v) for k, v in self.files.items()},
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "GenerationCheckpoint":
        """Create from dictionary"""
        checkpoint = cls(
            version=data.get("version", "1.0"),
            name=data.get("name", ""),
            description=data.get("description", ""),
            domain_type=data.get("domain_type", ""),
            started_at=data.get("started_at", ""),
            last_updated=data.get("last_updated", ""),
            status=data.get("status", "pending"),
            current_phase=data.get("current_phase", ""),
            resume_count=data.get("resume_count", 0),
            last_error=data.get("last_error", ""),
        )
        
        # Reconstruct phases
        for name, phase_data in data.get("phases", {}).items():
            checkpoint.phases[name] = PhaseCheckpoint(**phase_data)
        
        # Reconstruct files
        for path, file_data in data.get("files", {}).items():
            checkpoint.files[path] = FileCheckpoint(**file_data)
        
        return checkpoint


class CheckpointManager:
    """
    Manages saving and loading of generation checkpoints.
    
    Usage:
        manager = CheckpointManager(output_dir / ".checkpoint.json")
        
        # Start new generation
        manager.start_generation(name, description, domain_type)
        
        # Update as we progress
        manager.start_phase("backend")
        manager.start_file("models.py", "backend")
        manager.complete_file("models.py")
        manager.complete_phase("backend")
        
        # Save periodically
        manager.save()
        
        # On restart, load and check what to skip
        if manager.load():
            if manager.is_phase_complete("backend"):
                skip backend...
    """
    
    def __init__(self, checkpoint_path: Path):
        self.checkpoint_path = Path(checkpoint_path)
        self.checkpoint = GenerationCheckpoint()
        self._auto_save = True
    
    def set_auto_save(self, enabled: bool) -> None:
        """Enable/disable automatic saving after each update"""
        self._auto_save = enabled
    
    def _now(self) -> str:
        """Get current timestamp as ISO string"""
        return datetime.now().isoformat()
    
    def _save_if_auto(self) -> None:
        """Save if auto-save is enabled"""
        if self._auto_save:
            self.save()
    
    # ===== Core Operations =====
    
    def save(self) -> None:
        """Save checkpoint to file"""
        self.checkpoint.last_updated = self._now()
        
        # Ensure directory exists
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Create backup of existing checkpoint
        if self.checkpoint_path.exists():
            backup_path = self.checkpoint_path.with_name(self.checkpoint_path.name + ".bak")
            shutil.copy(self.checkpoint_path, backup_path)
        
        # Write new checkpoint with safe encoder
        with open(self.checkpoint_path, "w") as f:
            json.dump(self.checkpoint.to_dict(), f, indent=2, cls=CheckpointJSONEncoder)
    
    def load(self) -> bool:
        """
        Load checkpoint from file.
        
        Returns True if checkpoint was loaded, False if no checkpoint exists.
        """
        if not self.checkpoint_path.exists():
            return False
        
        candidates = [self.checkpoint_path, self.checkpoint_path.with_name(self.checkpoint_path.name + ".bak")]
        for candidate in candidates:
            if not candidate.exists():
                continue
            try:
                with open(candidate, "r") as f:
                    data = json.load(f)
                self.checkpoint = GenerationCheckpoint.from_dict(data)
                return True
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        return False
    
    def clear(self) -> None:
        """Clear checkpoint (start fresh)"""
        if self.checkpoint_path.exists():
            self.checkpoint_path.unlink()
        self.checkpoint = GenerationCheckpoint()
    
    # ===== Generation Level =====
    
    def start_generation(self, name: str, description: str, domain_type: str) -> None:
        """Initialize a new generation"""
        self.checkpoint = GenerationCheckpoint(
            name=name,
            description=description,
            domain_type=domain_type,
            started_at=self._now(),
            last_updated=self._now(),
            status="running",
        )
        self._save_if_auto()
    
    def complete_generation(self, success: bool = True) -> None:
        """Mark generation as complete"""
        self.checkpoint.status = "complete" if success else "failed"
        self._save_if_auto()

    def fail_generation(self, error: str = "", phase: str = "") -> None:
        """Mark generation as failed and capture failure context."""
        self.checkpoint.status = "failed"
        if error:
            self.checkpoint.last_error = error
        if phase:
            self.checkpoint.current_phase = phase
        self._save_if_auto()

    def can_resume(self) -> bool:
        """Whether this checkpoint is resumable."""
        return self.checkpoint.status in {"running", "failed"}

    def resume_generation(self) -> None:
        """Move checkpoint to running state for resumed execution."""
        self.checkpoint.status = "running"
        self.checkpoint.resume_count += 1
        self._save_if_auto()
    
    def get_status(self) -> str:
        """Get overall generation status"""
        return self.checkpoint.status
    
    # ===== Phase Level =====
    
    def start_phase(self, phase: str) -> None:
        """Mark a phase as started"""
        self.checkpoint.current_phase = phase
        self.checkpoint.phases[phase] = PhaseCheckpoint(
            name=phase,
            status="planning",
            started_at=self._now(),
        )
        self._save_if_auto()
    
    def set_phase_planned_files(self, phase: str, files: List[str]) -> None:
        """Record the planned files for a phase"""
        if phase in self.checkpoint.phases:
            self.checkpoint.phases[phase].planned_files = files
            self.checkpoint.phases[phase].status = "generating"
        self._save_if_auto()
    
    def complete_phase(self, phase: str, issues: Optional[List[str]] = None, fixes: Optional[List[str]] = None) -> None:
        """Mark a phase as complete"""
        if phase in self.checkpoint.phases:
            self.checkpoint.phases[phase].status = "complete"
            self.checkpoint.phases[phase].completed_at = self._now()
            if issues:
                self.checkpoint.phases[phase].issues = issues
            if fixes:
                self.checkpoint.phases[phase].fixes = fixes
        self._save_if_auto()
    
    def is_phase_complete(self, phase: str) -> bool:
        """Check if a phase is complete"""
        if phase not in self.checkpoint.phases:
            return False
        return self.checkpoint.phases[phase].status == "complete"
    
    def get_phase_status(self, phase: str) -> Optional[str]:
        """Get status of a phase"""
        if phase not in self.checkpoint.phases:
            return None
        return self.checkpoint.phases[phase].status
    
    def increment_phase_iteration(self, phase: str) -> int:
        """Increment and return iteration count for a phase"""
        if phase in self.checkpoint.phases:
            self.checkpoint.phases[phase].iteration += 1
            self._save_if_auto()
            return self.checkpoint.phases[phase].iteration
        return 0
    
    # ===== File Level =====
    
    def start_file(self, path: str, phase: str) -> None:
        """Mark a file as started"""
        self.checkpoint.files[path] = FileCheckpoint(
            path=path,
            phase=phase,
            status="generating",
            started_at=self._now(),
        )
        self._save_if_auto()
    
    def file_reflecting(self, path: str) -> None:
        """Mark a file as being reflected on"""
        if path in self.checkpoint.files:
            self.checkpoint.files[path].status = "reflecting"
        self._save_if_auto()
    
    def complete_file(self, path: str, content_hash: Optional[str] = None) -> None:
        """Mark a file as complete"""
        if path in self.checkpoint.files:
            self.checkpoint.files[path].status = "complete"
            self.checkpoint.files[path].completed_at = self._now()
            if content_hash:
                self.checkpoint.files[path].content_hash = content_hash
            
            # Also add to phase's generated files
            phase = self.checkpoint.files[path].phase
            if phase in self.checkpoint.phases:
                if path not in self.checkpoint.phases[phase].generated_files:
                    self.checkpoint.phases[phase].generated_files.append(path)
        self._save_if_auto()
    
    def fail_file(self, path: str, issues: Optional[List[str]] = None) -> None:
        """Mark a file as failed"""
        if path in self.checkpoint.files:
            self.checkpoint.files[path].status = "failed"
            if issues:
                self.checkpoint.files[path].issues = issues
        self._save_if_auto()
    
    def is_file_complete(self, path: str, validate_content: bool = True) -> bool:
        """
        Check if a file is complete.
        
        Args:
            path: Path to the file
            validate_content: If True, also validate that the file content is valid
                              (JSON files are parsed, etc.)
        
        Returns:
            True if file is complete and valid
        """
        if path not in self.checkpoint.files:
            return False
        
        if self.checkpoint.files[path].status != "complete":
            return False
        
        if not validate_content:
            return True
        
        # Validate content for data files
        return self._validate_file_content(path)
    
    def get_file_status(self, path: str) -> Optional[str]:
        """Get status of a file"""
        if path not in self.checkpoint.files:
            return None
        return self.checkpoint.files[path].status
    
    def _validate_file_content(self, path: str) -> bool:
        """
        Validate that a file's content is valid.
        
        - JSON files must be valid JSON
        - Python files must have balanced brackets
        - TypeScript files must have balanced braces
        
        Returns True if valid or if file type is not validated.
        """
        # Construct full path
        full_path = self.checkpoint_path.parent / path
        
        if not full_path.exists():
            return False
        
        try:
            content = full_path.read_text(encoding='utf-8')
        except Exception:
            return False
        
        # Validate based on file type
        if path.endswith('.json'):
            try:
                import json
                json.loads(content)
                return True
            except json.JSONDecodeError:
                return False
        
        elif path.endswith('.py'):
            # Check for balanced brackets and basic Python syntax
            try:
                compile(content, path, 'exec')
                return True
            except SyntaxError:
                return False
        
        elif path.endswith(('.ts', '.tsx', '.js', '.jsx')):
            # Basic check: balanced braces
            open_braces = content.count('{')
            close_braces = content.count('}')
            open_parens = content.count('(')
            close_parens = content.count(')')
            
            if open_braces != close_braces or open_parens != close_parens:
                return False
            return True
        
        # For other file types, assume valid
        return True
    
    def invalidate_file(self, path: str) -> None:
        """
        Mark a file as invalid (need to regenerate).
        
        Call this when validation fails on a resumed file.
        """
        if path in self.checkpoint.files:
            self.checkpoint.files[path].status = "pending"
            self.checkpoint.files[path].issues.append("Content validation failed")
        self._save_if_auto()
    
    def get_incomplete_files(self, phase: Optional[str] = None) -> List[str]:
        """Get list of files that are not complete"""
        incomplete = []
        for path, file in self.checkpoint.files.items():
            if phase and file.phase != phase:
                continue
            if file.status != "complete":
                incomplete.append(path)
        return incomplete
    
    # ===== Summary =====
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary of checkpoint state"""
        phases_complete = sum(1 for p in self.checkpoint.phases.values() if p.status == "complete")
        files_complete = sum(1 for f in self.checkpoint.files.values() if f.status == "complete")
        
        return {
            "name": self.checkpoint.name,
            "status": self.checkpoint.status,
            "started_at": self.checkpoint.started_at,
            "last_updated": self.checkpoint.last_updated,
            "current_phase": self.checkpoint.current_phase,
            "resume_count": self.checkpoint.resume_count,
            "last_error": self.checkpoint.last_error,
            "phases_total": len(self.checkpoint.phases),
            "phases_complete": phases_complete,
            "files_total": len(self.checkpoint.files),
            "files_complete": files_complete,
            "can_resume": self.can_resume(),
        }
    
    def print_status(self) -> None:
        """Print human-readable status"""
        summary = self.get_summary()
        
        print("\n" + "="*50)
        print("📊 Checkpoint Status")
        print("="*50)
        print(f"  Name: {summary['name']}")
        print(f"  Status: {summary['status']}")
        print(f"  Phases: {summary['phases_complete']}/{summary['phases_total']}")
        print(f"  Files: {summary['files_complete']}/{summary['files_total']}")
        
        if summary['can_resume']:
            print(f"\n  ⏸️  Generation can be resumed from: {summary['current_phase']}")
        
        print("\n  Phase details:")
        for name, phase in self.checkpoint.phases.items():
            status_icon = "✅" if phase.status == "complete" else "🔄" if phase.status == "generating" else "⏳"
            files = f"{len(phase.generated_files)}/{len(phase.planned_files)}" if phase.planned_files else "?"
            print(f"    {status_icon} {name}: {phase.status} ({files} files)")
        
        print("="*50)

