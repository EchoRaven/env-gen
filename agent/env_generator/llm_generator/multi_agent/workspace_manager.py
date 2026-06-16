"""
Workspace Manager — project base-dir owner + directory bootstrap.

Step 4 FOLD (docs/workspace_root_redesign.md): the previous
``AGENT_WRITE_DIRS`` + ``_can_write`` machinery has moved into
``ROUTING_TABLE.allowed_writers`` in
``multi_agent/runtime/path_routed_workspace.py`` — a single source
of truth for both routing and write-scope decisions.

What remains here:
  * ``base_dir`` ownership (the project root)
  * ``_init_directories`` (creates the default workspace dir tree)

What was removed:
  * ``AGENT_WRITE_DIRS`` table
  * ``_can_write`` / ``can_write`` (now ``workspace.is_write_allowed``)
  * ``register_agent_write_scopes`` / ``unregister_agent_write_scopes``
    / ``resolve_agent_write_scopes`` / ``get_default_write_scopes`` /
    ``get_registered_write_scopes`` / ``get_agent_write_dir``
  * ``read_file`` / ``write_file`` / ``list_files`` / ``get_all_design_docs``
    / ``get_stats`` — all dead, no remaining callers.
"""

import logging
from pathlib import Path


class WorkspaceManager:
    """
    Owns the project base directory and ensures the default tree exists.

    Directory layout (each created at init):
        design/                 design specs (shared, written by design)
        app/database/init/      database schema/seed
        app/backend/src/        backend code
        app/frontend/src/       frontend code
        docker/                 compose / runtime files
        tasks/                  task definitions
        screenshots/            reference screenshots (read-only)

    All write-scope decisions live in ``ROUTING_TABLE`` in
    ``multi_agent/runtime/path_routed_workspace.py``.
    """

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._logger = logging.getLogger("WorkspaceManager")
        self._init_directories()

    def _init_directories(self) -> None:
        """Create the default workspace directory tree."""
        dirs = [
            "design",
            "app/database/init",
            "app/backend/src/routes",
            "app/backend/src/middleware",
            "app/backend/src/utils",
            "app/backend/src/config",
            "app/frontend/src/pages",
            "app/frontend/src/components",
            "app/frontend/src/components/ui",
            "app/frontend/src/services",
            "app/frontend/src/contexts",
            "app/frontend/src/hooks",
            "docker",
            "tasks",
            "screenshots",
        ]
        for d in dirs:
            (self.base_dir / d).mkdir(parents=True, exist_ok=True)
