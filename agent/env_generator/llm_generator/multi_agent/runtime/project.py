"""
Project-level metadata persistence.

A "project" == a single env-generator workspace (output_dir). One project per
workspace. Metadata lives at `<workspace>/project.json` and survives crashes,
exits, and orchestrator re-starts. The 5 hubs (Code/API/Work/Event/Run) are
already isolated per workspace via `<workspace>/shared/hubs/`, so no
per-hub project-id namespacing is needed.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

VALID_STATUSES = {"active", "paused", "completed", "failed", "archived"}
PROJECT_JSON = "project.json"


@dataclass
class ProjectMetadata:
    id: str
    name: str
    created_at: float
    last_active_at: float
    description: str = ""
    status: str = "active"
    agents_used: List[str] = field(default_factory=list)
    schema_version: int = 1

    def __post_init__(self):
        if self.status not in VALID_STATUSES:
            raise ValueError(
                f"status must be one of {sorted(VALID_STATUSES)}, got {self.status!r}"
            )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectMetadata":
        # Only pass known fields — tolerate forward-compat extras.
        known = {k for k in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


def save_project_metadata(workspace_dir: Path, md: ProjectMetadata) -> Path:
    workspace_dir = Path(workspace_dir)
    workspace_dir.mkdir(parents=True, exist_ok=True)
    path = workspace_dir / PROJECT_JSON
    path.write_text(json.dumps(md.to_dict(), indent=2, sort_keys=True))
    return path


def load_project_metadata(workspace_dir: Path) -> Optional[ProjectMetadata]:
    path = Path(workspace_dir) / PROJECT_JSON
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None
    return ProjectMetadata.from_dict(data)


def now_ts() -> float:
    return time.time()


from typing import Iterable, Tuple


class ProjectIndex:
    """
    Scans a workspaces-root directory for child workspaces containing
    `project.json` files. Provides list/filter/get APIs for project pickers
    (UI homepage, CLI `resume`).

    Layout assumption:
        <workspaces_root>/
            <project_id_1>/   # workspace == project
                project.json
                shared/hubs/...
            <project_id_2>/
                project.json
                shared/hubs/...
            not_a_project/    # ignored (no project.json)
    """

    def __init__(self, workspaces_root: Path):
        self.root = Path(workspaces_root)

    def _iter_metadata(self) -> Iterable[Tuple[ProjectMetadata, Path]]:
        if not self.root.exists():
            return
        for child in self.root.iterdir():
            if not child.is_dir():
                continue
            md = load_project_metadata(child)
            if md is None:
                continue
            yield md, child

    def list(self, status: Optional[str] = None) -> List[ProjectMetadata]:
        results = []
        for md, _ in self._iter_metadata():
            if status is not None and md.status != status:
                continue
            results.append(md)
        results.sort(key=lambda m: m.last_active_at, reverse=True)
        return results

    def get(self, project_id: str) -> Tuple[Optional[ProjectMetadata], Optional[Path]]:
        for md, workspace in self._iter_metadata():
            if md.id == project_id:
                return md, workspace
        return None, None


def list_projects(workspaces_root: Path, status: Optional[str] = None) -> List[ProjectMetadata]:
    """List projects under a workspaces-root, optionally filtered by status."""
    return ProjectIndex(workspaces_root).list(status=status)


def resume_project(workspaces_root: Path, project_id: str) -> Optional[Path]:
    """Return the workspace path for a project_id, or None if not found.

    The caller passes this path to HubRegistry(...) to resume.
    """
    _, workspace = ProjectIndex(workspaces_root).get(project_id)
    return workspace
