"""
Docker Tools

Dedicated tools for Docker Compose operations:
- docker_build: Build images
- docker_up: Start containers
- docker_down: Stop containers
- docker_logs: View logs
- docker_status: Container status
- docker_restart: Restart services
"""

import asyncio
import os
import re
import subprocess
from pathlib import Path
from typing import List, Optional, Dict, Any, Union

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.tool import BaseTool, ToolResult, ToolCategory, create_tool_param
from workspace import Workspace

# Import environment cache for avoiding repeated failures
try:
    from .runtime_tools import env_cache
except ImportError:
    env_cache = None


def _docker_daemon_reachable(timeout: int = 3) -> bool:
    """Fast probe to detect whether Docker daemon is currently reachable."""
    try:
        result = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding='utf-8',
            errors='replace',
        )
        return result.returncode == 0 and bool((result.stdout or "").strip())
    except Exception:
        return False


def _run_compose(
    compose_file: Path,
    args: List[str],
    cwd: Path,
    timeout: int,
) -> subprocess.CompletedProcess:
    """Run `docker compose -f <file> ...`.

    R2 round-11 Fix A: force the classic builder via DOCKER_BUILDKIT=0
    + COMPOSE_DOCKER_CLI_BUILD=0. Diagnostic workflow wyqzbwmt3
    confirmed BuildKit on Docker 20.10.8 + kernel 5.11 + custom
    seccomp-allow-all + cgroup v1 hits fork/exec/thread failures
    deterministically (5/5 reproduction in the spike). Until the
    daemon is upgraded (sysadmin ticket: docs/sysadmin_ticket_docker_upgrade.md)
    every BuildKit-reaching docker subprocess in the pipeline must
    pin classic. This is the runtime-side companion to the content-side
    Dockerfile lint at multi_agent/dockerfile_lint.py.
    """
    # FIX #113 (run-29 M4): any build-triggering compose call re-stages the design
    # assets first — a lane integration checkout can transiently drop the tracked
    # public/assets/ files, and an image built in that window ships broken-image
    # glyphs the visual judge scores 0.00. Idempotent, no-op without design/assets.
    if any(a in ("build", "--build") for a in args):
        try:
            from multi_agent.runtime.frontend_scaffold import ensure_assets_staged_for_build
            ensure_assets_staged_for_build(compose_file)
        except Exception:
            pass
    cmd = ["docker", "compose", "-f", str(compose_file)] + args
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding='utf-8',
        errors='replace',
        env={**os.environ, "DOCKER_BUILDKIT": "0", "COMPOSE_DOCKER_CLI_BUILD": "0"},
    )


def _compose_port_conflict_hint(stderr: str, compose_file: Path) -> Optional[str]:
    """Return an agent-actionable hint when compose failed because a host port is busy."""
    text = stderr or ""
    lower = text.lower()
    conflict_markers = (
        "port is already allocated",
        "address already in use",
        "bind for",
        "ports are not available",
        "listen tcp",
    )
    if not any(marker in lower for marker in conflict_markers):
        return None

    ports = sorted(
        {
            int(match)
            for match in re.findall(r"(?::|0\.0\.0\.0:|127\.0\.0\.1:)(\d{2,5})", text)
            if 0 < int(match) <= 65535
        }
    )
    port_text = f" Host ports mentioned: {', '.join(map(str, ports))}." if ports else ""
    rel = compose_file.as_posix()
    return (
        "Docker Compose failed because a host port is already in use."
        f"{port_text}\n"
        f"Compose file: `{rel}`.\n"
        "Do not assume ports are fixed. Agents with `docker/` write scope may edit the compose file. "
        "Prefer assigning free host ports in the `ports:` mappings and updating related environment variables "
        "(API/UI/DB URLs) before retrying `docker_up(build=True)`. Use `cleanup_ports(...)` only when the "
        "conflicting process is clearly stale and safe to stop."
    )


def _find_compose_file_global(workspace_root: Path) -> Optional[Path]:
    """
    Find docker-compose file - very forgiving, searches many locations.
    """
    # Try many possible locations
    candidates = [
        # Standard locations
        workspace_root / "docker/docker-compose.yml",
        workspace_root / "docker/docker-compose.dev.yml",
        workspace_root / "docker/docker-compose.prod.yml",
        workspace_root / "docker-compose.yml",
        workspace_root / "docker-compose.yaml",
        # Alternative locations
        workspace_root / "compose.yml",
        workspace_root / "compose.yaml",
        workspace_root / ".docker/docker-compose.yml",
        workspace_root / "infra/docker-compose.yml",
        workspace_root / "deploy/docker-compose.yml",
    ]
    for path in candidates:
        if path.exists():
            return path
    
    # Last resort: search recursively for any docker-compose file
    for pattern in ["**/docker-compose.yml", "**/docker-compose.yaml", "**/compose.yml"]:
        matches = list(workspace_root.glob(pattern))
        if matches:
            return matches[0]
    
    return None


def _list_services(compose_file: Path, cwd: Path) -> List[str]:
    """List service names defined by the compose file."""
    try:
        result = _run_compose(compose_file, ["config", "--services"], cwd=cwd, timeout=30)
        if result.returncode != 0:
            return []
        return [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    except Exception:
        return []


def _missing_build_contexts(compose_file: Path, service: Optional[str] = None) -> List[str]:
    """Return services whose compose ``build:`` context has no Dockerfile yet.

    docker_up can be triggered before the implementation lanes have written
    their Dockerfiles (smoke #4: the verifier validated ~2.5 min in, before
    backend merged ``app/backend/Dockerfile``). That's a transient "artifact
    not ready", NOT a code defect — distinguishing the two lets the caller
    defer + retry instead of hard-failing and misdiagnosing a missing build
    context as a real bug.

    Build context is resolved relative to the compose file's directory
    (docker compose semantics). Image-only services (no ``build:``) are never
    reported. ``service`` scopes the check to a single service.
    """
    try:
        import yaml
    except Exception:
        return []
    try:
        data = yaml.safe_load(Path(compose_file).read_text()) or {}
    except Exception:
        return []
    services = data.get("services") or {}
    if not isinstance(services, dict):
        return []
    base = Path(compose_file).resolve().parent
    missing: List[str] = []
    for name, spec in services.items():
        if service is not None and name != service:
            continue
        if not isinstance(spec, dict):
            continue
        build = spec.get("build")
        if not build:
            continue
        if isinstance(build, dict):
            ctx = build.get("context") or "."
            dockerfile = build.get("dockerfile") or "Dockerfile"
        else:
            ctx = str(build)
            dockerfile = "Dockerfile"
        if not (base / ctx / dockerfile).exists():
            missing.append(str(name))
    return missing


def _canonicalize_service_name(service: str, available: List[str]) -> Optional[str]:
    """
    Map common synonyms (e.g., env -> env-adapter) and normalize separators so
    verifiers/agents can request 'env' even if compose uses 'env-adapter'.
    """
    if not service:
        return None

    if service in available:
        return service

    raw = service.strip()
    key = raw.lower().replace("_", "-")

    aliases = {
        "db": "db",
        "database": "db",
        "postgres": "db",
        "postgresql": "db",
        "backend": "backend",
        "api": "backend",
        "server": "backend",
        "frontend": "frontend",
        "web": "frontend",
        "ui": "frontend",
        "env": "env-adapter",
        "env-adapter": "env-adapter",
        "envadapter": "env-adapter",
        "env-adaptor": "env-adapter",
        "env-adapter-service": "env-adapter",
    }

    mapped = aliases.get(key, key).replace("_", "-")

    # Case-insensitive exact match
    for a in available:
        if a.lower() == mapped:
            return a
        if a.lower().replace("_", "-") == mapped:
            return a

    # If only one available service contains this token, pick it.
    token = mapped
    candidates = [a for a in available if token in a.lower().replace("_", "-")]
    if len(candidates) == 1:
        return candidates[0]

    return None

class DockerBuildTool(BaseTool):
    """Build Docker images using docker-compose."""
    
    NAME = "docker_build"
    DESCRIPTION = """Build Docker images for the project.

Can build all services or a specific service.
Uses docker-compose build.

Example:
  docker_build()  # Build all
  docker_build(service="backend", no_cache=True)
"""
    
    def __init__(self, *, workspace: Workspace):
        super().__init__(name=self.NAME, category=ToolCategory.RUNTIME)
        if workspace is None:
            raise ValueError(f"{self.NAME}: workspace is required (no bypass construction)")
        self.workspace = workspace
    
    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "description": "Specific service to build (optional, builds all if not specified)"
                    },
                    "no_cache": {
                        "type": "boolean",
                        "description": "Build without cache (default: false)"
                    },
                },
                "required": [],
            },
        )
    
    async def execute(self, service: str = None, no_cache: bool = False) -> ToolResult:
        # Check environment cache - skip if Docker daemon was recently unavailable
        if env_cache:
            should_skip, reason = env_cache.should_skip("docker_daemon", cooldown_seconds=300)
            if should_skip:
                # If Docker recovered after a transient failure, clear stale cooldown.
                if _docker_daemon_reachable():
                    env_cache.record_success("docker_daemon")
                else:
                    return ToolResult.fail(
                        f"{reason}\n"
                        "Docker daemon is not available. Either:\n"
                        "1. Start Docker Desktop/daemon\n"
                        "2. Wait 5 minutes for automatic retry\n"
                        "3. Use non-Docker testing (npm start, etc.)"
                    )
        
        compose_file = self._find_compose_file()
        if not compose_file:
            return ToolResult.fail(
                "docker-compose.yml not found. "
                "Checked: docker/docker-compose.yml, docker/docker-compose.dev.yml, docker/docker-compose.prod.yml, docker-compose.yml"
            )

        try:
            args = ["build"]
            if no_cache:
                args.append("--no-cache")

            if service:
                available = _list_services(compose_file, cwd=self.workspace.base_root)
                canonical = _canonicalize_service_name(service, available) if available else service
                if available and not canonical:
                    return ToolResult.fail(
                        f"Unknown compose service '{service}'. Available services: {', '.join(available)}"
                    )
                args.append(canonical or service)

            result = _run_compose(compose_file, args, cwd=self.workspace.base_root, timeout=600)
            
            if result.returncode != 0:
                stderr_lower = (result.stderr or "").lower()
                # Detect Docker daemon unavailable
                if "cannot connect to the docker daemon" in stderr_lower or "docker.sock" in stderr_lower:
                    if env_cache:
                        env_cache.record_failure("docker_daemon", "Cannot connect to Docker daemon")
                    return ToolResult.fail(
                        f"Docker daemon unavailable:\n{result.stderr}\n\n"
                        "This failure has been cached. Will skip docker operations for 5 minutes.\n"
                        "Start Docker Desktop or use non-Docker testing."
                    )
                return ToolResult.fail(
                    f"Build failed:\n{result.stderr}"
                )
            
            # Mark Docker as available on success
            if env_cache:
                env_cache.record_success("docker_daemon")
            
            return ToolResult.ok(data={
                "success": True,
                "service": service or "all",
                "output": result.stdout[:500] if result.stdout else "Build completed",
            })
        except subprocess.TimeoutExpired:
            return ToolResult.fail("Build timed out after 10 minutes")
        except Exception as e:
            return ToolResult.fail(f"Build error: {e}")
    
    def _find_compose_file(self) -> Optional[Path]:
        """Find docker-compose.yml in project."""
        return _find_compose_file_global(self.workspace.base_root)
        return None


class DockerUpTool(BaseTool):
    """Start Docker containers."""
    
    NAME = "docker_up"
    DESCRIPTION = """Start Docker containers using docker-compose up.

Starts containers in detached mode by default. A full-env boot (no `service`)
defaults to `fresh=True`: it first tears down volumes (`down -v`) so the sandbox
DB boots CLEAN — a stale postgres volume from a prior run would otherwise ignore
POSTGRES_PASSWORD on re-init and the backend's DB auth would fail (a false
validation failure on a correct app). Pass `fresh=False` to preserve volumes.

Example:
  docker_up()              # fresh full-env boot (clean DB) — the validation default
  docker_up(build=True)    # build, then fresh boot
  docker_up(service="backend")   # targeted up; volumes preserved
  docker_up(fresh=False)   # full boot, keep existing volumes/data
"""
    
    def __init__(self, *, workspace: Workspace):
        super().__init__(name=self.NAME, category=ToolCategory.RUNTIME)
        if workspace is None:
            raise ValueError(f"{self.NAME}: workspace is required (no bypass construction)")
        self.workspace = workspace
    
    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "description": "Specific service to start"
                    },
                    "build": {
                        "type": "boolean",
                        "description": "Build images before starting (default: false)"
                    },
                    "force_recreate": {
                        "type": "boolean",
                        "description": "Force recreate containers (default: false)"
                    },
                    "fresh": {
                        "type": "boolean",
                        "description": "Full-env boot only: tear down volumes (down -v) first so the DB boots clean (default: true). Avoids the stale-postgres-volume auth failure. Ignored when `service` is set."
                    },
                },
                "required": [],
            },
        )
    
    async def execute(
        self,
        service: str = None,
        build: bool = False,
        force_recreate: bool = False,
        fresh: bool = True,
    ) -> ToolResult:
        compose_file = self._find_compose_file()
        if not compose_file:
            return ToolResult.fail(
                "docker-compose.yml not found. "
                "Checked: docker/docker-compose.yml, docker/docker-compose.dev.yml, docker/docker-compose.prod.yml, docker-compose.yml"
            )

        # Build-context readiness gate (B3, 2026-06-05). docker_up can be
        # triggered before the implementation lanes have written their
        # Dockerfiles. That's a transient "artifact not ready", NOT a code
        # defect — return a distinct NOT_READY signal so the caller defers
        # and RETRIES once the owning lanes merge, rather than hard-failing
        # and misdiagnosing a missing build context as a real bug + bogus
        # remediation (smoke #4 failure mode).
        missing_ctx = _missing_build_contexts(compose_file, service=service)
        if missing_ctx:
            return ToolResult.fail(
                "VALIDATION_NOT_READY: the following service build context(s) "
                f"have no Dockerfile yet: {', '.join(missing_ctx)}. The "
                "implementation lane(s) have not finished writing+merging these "
                "files. This is NOT a code defect and NOT a missing-file bug — "
                "do NOT open remediation. Wait ~30s for the owning lanes to "
                "finish, then call docker_up(build=True) again. Repeat until "
                "ready (or after several retries, escalate to the orchestrator).",
                not_ready=True,
                missing_build_contexts=missing_ctx,
            )

        try:
            # Fresh-volume hygiene (smoke #5, 2026-06-06): a sandbox env must
            # boot from a CLEAN database. Without this, an anonymous postgres
            # volume from a PRIOR run/up persists, so the compose's
            # POSTGRES_PASSWORD is silently ignored on re-init (postgres only
            # initializes an EMPTY data dir) and the backend's auth to postgres
            # fails — "password authentication failed for user sandbox" — a FALSE
            # api_smoke failure on a CORRECT app (the generated Notes app worked
            # perfectly after a manual ``down -v && up``). Tear down volumes
            # before a full-env boot. Best-effort; skipped for a targeted
            # single-service ``up`` (the caller is managing specific services).
            if fresh and not service:
                _run_compose(
                    compose_file, ["down", "-v", "--remove-orphans"],
                    cwd=self.workspace.base_root, timeout=120,
                )

            # ``--remove-orphans`` cleans up containers from prior runs
            # whose service names no longer appear in the compose file.
            # Without it, smoke #48 surfaced verifier mis-reading orphan
            # containers from a previous smoke ("fb-db") as the current
            # run's only running service — declaring the validation a
            # failure even though docker_up itself succeeded.
            args = ["up", "-d", "--remove-orphans"]
            if build:
                args.append("--build")
            if force_recreate:
                args.append("--force-recreate")

            if service:
                available = _list_services(compose_file, cwd=self.workspace.base_root)
                canonical = _canonicalize_service_name(service, available) if available else service
                if available and not canonical:
                    return ToolResult.fail(
                        f"Unknown compose service '{service}'. Available services: {', '.join(available)}"
                    )
                args.append(canonical or service)

            result = _run_compose(compose_file, args, cwd=self.workspace.base_root, timeout=300)
            
            if result.returncode != 0:
                port_hint = _compose_port_conflict_hint(result.stderr or "", compose_file)
                if port_hint:
                    return ToolResult.fail(
                        f"Failed to start:\n{result.stderr}\n\n{port_hint}",
                        error_code="docker_port_conflict",
                        compose_file=str(compose_file),
                        stderr=result.stderr,
                        hint=port_hint,
                    )
                return ToolResult.fail(
                    f"Failed to start:\n{result.stderr}"
                )
            
            return ToolResult.ok(data={
                "success": True,
                "service": service or "all",
                "message": "Containers started successfully",
            })
        except subprocess.TimeoutExpired:
            return ToolResult.fail("Start timed out")
        except Exception as e:
            return ToolResult.fail(f"Start error: {e}")
    
    def _find_compose_file(self) -> Optional[Path]:
        return _find_compose_file_global(self.workspace.base_root)


class DockerDownTool(BaseTool):
    """Stop and remove Docker containers."""
    
    NAME = "docker_down"
    DESCRIPTION = """Stop and remove Docker containers.

Example:
  docker_down()
  docker_down(volumes=True)  # Also remove volumes
  docker_down(remove_orphans=True)  # Remove orphan containers from previous runs
  docker_down(volumes=True, remove_orphans=True)  # Full cleanup
"""
    
    def __init__(self, *, workspace: Workspace):
        super().__init__(name=self.NAME, category=ToolCategory.RUNTIME)
        if workspace is None:
            raise ValueError(f"{self.NAME}: workspace is required (no bypass construction)")
        self.workspace = workspace
    
    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "volumes": {
                        "type": "boolean",
                        "description": "Also remove volumes (default: false)"
                    },
                    "remove_orphans": {
                        "type": "boolean",
                        "description": "Remove orphan containers from previous runs (default: false). Use this when you see 'No such container' errors."
                    },
                },
                "required": [],
            },
        )
    
    async def execute(self, volumes: bool = False, remove_orphans: bool = False) -> ToolResult:
        compose_file = self._find_compose_file()
        if not compose_file:
            return ToolResult.fail(
                "docker-compose.yml not found. "
                "Checked: docker/docker-compose.yml, docker/docker-compose.dev.yml, docker/docker-compose.prod.yml, docker-compose.yml"
            )
        
        # Use docker compose (v2) instead of docker-compose
        cmd = ["docker", "compose", "-f", str(compose_file), "down"]
        
        if volumes:
            cmd.append("-v")
        
        if remove_orphans:
            cmd.append("--remove-orphans")
        
        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.workspace.base_root),
                capture_output=True,
                text=True,
                timeout=60,
                encoding='utf-8',
                errors='replace',
            )
            
            return ToolResult.ok(data={
                "success": True,
                "message": "Containers stopped and removed",
            })
        except Exception as e:
            return ToolResult.fail(f"Down error: {e}")
    
    def _find_compose_file(self) -> Optional[Path]:
        return _find_compose_file_global(self.workspace.base_root)


class DockerLogsTool(BaseTool):
    """Get logs from Docker containers."""
    
    NAME = "docker_logs"
    DESCRIPTION = """Get logs from a Docker container.

Example:
  docker_logs(service="backend")
  docker_logs(service="backend", tail=50)
"""
    
    def __init__(self, *, workspace: Workspace):
        super().__init__(name=self.NAME, category=ToolCategory.RUNTIME)
        if workspace is None:
            raise ValueError(f"{self.NAME}: workspace is required (no bypass construction)")
        self.workspace = workspace
    
    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "description": "Service name to get logs from"
                    },
                    "tail": {
                        "type": "integer",
                        "description": "Number of lines to show (default: 100)"
                    },
                },
                "required": ["service"],
            },
        )
    
    async def execute(self, service: str, tail: int = 100) -> ToolResult:
        compose_file = self._find_compose_file()
        if not compose_file:
            return ToolResult.fail(
                "docker-compose.yml not found. "
                "Checked: docker/docker-compose.yml, docker/docker-compose.dev.yml, docker/docker-compose.prod.yml, docker-compose.yml"
            )
        
        try:
            available = _list_services(compose_file, cwd=self.workspace.base_root)
            canonical = _canonicalize_service_name(service, available) if available else service
            if available and not canonical:
                return ToolResult.fail(
                    f"Unknown compose service '{service}'. Available services: {', '.join(available)}"
                )

            result = _run_compose(
                compose_file,
                ["logs", "--tail", str(tail), canonical or service],
                cwd=self.workspace.base_root,
                timeout=30,
            )
            
            logs = result.stdout or result.stderr or "(no logs)"
            
            return ToolResult.ok(data={
                "service": service,
                "logs": logs[:5000],  # Limit output
                "lines": len(logs.split("\n")),
            })
        except Exception as e:
            return ToolResult.fail(f"Logs error: {e}")
    
    def _find_compose_file(self) -> Optional[Path]:
        return _find_compose_file_global(self.workspace.base_root)


class DockerStatusTool(BaseTool):
    """Get status of Docker containers."""
    
    NAME = "docker_status"
    DESCRIPTION = """Check status of all Docker containers.

Returns running/stopped status for each service.

Example:
  docker_status()
"""
    
    def __init__(self, *, workspace: Workspace):
        super().__init__(name=self.NAME, category=ToolCategory.RUNTIME)
        if workspace is None:
            raise ValueError(f"{self.NAME}: workspace is required (no bypass construction)")
        self.workspace = workspace
    
    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
            },
        )
    
    async def execute(self) -> ToolResult:
        compose_file = self._find_compose_file()
        if not compose_file:
            return ToolResult.fail(
                "docker-compose.yml not found. "
                "Checked: docker/docker-compose.yml, docker/docker-compose.dev.yml, docker/docker-compose.prod.yml, docker-compose.yml"
            )
        
        # Use docker compose (v2) instead of docker-compose
        cmd = ["docker", "compose", "-f", str(compose_file), "ps"]
        
        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.workspace.base_root),
                capture_output=True,
                text=True,
                timeout=30,
                encoding='utf-8',
                errors='replace',
            )
            
            # Parse output
            lines = result.stdout.strip().split("\n")
            services = []
            
            for line in lines[1:]:  # Skip header
                if line.strip():
                    parts = line.split()
                    if len(parts) >= 2:
                        name = parts[0]
                        status = "running" if "Up" in line else "stopped"
                        services.append({"name": name, "status": status})
            
            return ToolResult.ok(data={
                "services": services,
                "raw": result.stdout[:1000],
            })
        except Exception as e:
            return ToolResult.fail(f"Status error: {e}")
    
    def _find_compose_file(self) -> Optional[Path]:
        return _find_compose_file_global(self.workspace.base_root)


class DockerRestartTool(BaseTool):
    """Restart Docker containers."""
    
    NAME = "docker_restart"
    DESCRIPTION = """Restart a Docker service.

Example:
  docker_restart(service="backend")
"""
    
    def __init__(self, *, workspace: Workspace):
        super().__init__(name=self.NAME, category=ToolCategory.RUNTIME)
        if workspace is None:
            raise ValueError(f"{self.NAME}: workspace is required (no bypass construction)")
        self.workspace = workspace
    
    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "description": "Service to restart"
                    },
                },
                "required": ["service"],
            },
        )
    
    async def execute(self, service: str) -> ToolResult:
        compose_file = self._find_compose_file()
        if not compose_file:
            return ToolResult.fail(
                "docker-compose.yml not found. "
                "Checked: docker/docker-compose.yml, docker/docker-compose.dev.yml, docker/docker-compose.prod.yml, docker-compose.yml"
            )

        try:
            available = _list_services(compose_file, cwd=self.workspace.base_root)
            canonical = _canonicalize_service_name(service, available) if available else service
            if available and not canonical:
                return ToolResult.fail(
                    f"Unknown compose service '{service}'. Available services: {', '.join(available)}"
                )

            result = _run_compose(
                compose_file,
                ["restart", canonical or service],
                cwd=self.workspace.base_root,
                timeout=60,
            )
            
            if result.returncode != 0:
                return ToolResult.fail(f"Restart failed: {result.stderr}")
            
            return ToolResult.ok(data={
                "service": canonical or service,
                "message": f"Service {canonical or service} restarted",
            })
        except Exception as e:
            return ToolResult.fail(f"Restart error: {e}")
    
    def _find_compose_file(self) -> Optional[Path]:
        return _find_compose_file_global(self.workspace.base_root)


class DockerValidateTool(BaseTool):
    """Validate Docker configuration and build context paths."""
    
    NAME = "docker_validate"
    DESCRIPTION = """Validate docker-compose.yml configuration.

Checks:
- Whether build context paths exist and are correct
- Whether Dockerfiles exist in each context
- Whether source files would be included in builds

This is critical for debugging "placeholder" or stale container issues.

Example:
  docker_validate()
  docker_validate(fix=True)  # Auto-fix common path issues
"""
    
    def __init__(self, *, workspace: Workspace):
        super().__init__(name=self.NAME, category=ToolCategory.RUNTIME)
        if workspace is None:
            raise ValueError(f"{self.NAME}: workspace is required (no bypass construction)")
        self.workspace = workspace
    
    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "fix": {
                        "type": "boolean",
                        "description": "Auto-fix common path issues (default: false)"
                    },
                },
                "required": [],
            },
        )
    
    async def execute(self, fix: bool = False) -> ToolResult:
        compose_file = _find_compose_file_global(self.workspace.base_root)
        if not compose_file:
            return ToolResult.fail(
                "docker-compose.yml not found in workspace"
            )
        
        issues = []
        fixes_applied = []
        valid_services = []
        
        # Parse docker-compose.yml
        try:
            import yaml
            with open(compose_file, 'r') as f:
                compose_data = yaml.safe_load(f)
        except Exception as e:
            return ToolResult.fail(f"Failed to parse docker-compose.yml: {e}")
        
        services = compose_data.get('services', {})
        compose_dir = compose_file.parent
        
        for service_name, service_config in services.items():
            build_config = service_config.get('build', {})
            
            if isinstance(build_config, str):
                context_path = build_config
                dockerfile = "Dockerfile"
            elif isinstance(build_config, dict):
                context_path = build_config.get('context', '.')
                dockerfile = build_config.get('dockerfile', 'Dockerfile')
            else:
                continue  # No build config, probably uses image
            
            # Resolve context path relative to compose file location
            resolved_context = (compose_dir / context_path).resolve()
            
            # Check if context exists
            if not resolved_context.exists():
                # Check if using wrong relative path
                # Common mistake: ./app/X when it should be ../app/X
                alt_path = (compose_dir.parent / context_path.lstrip('./')).resolve()
                if alt_path.exists():
                    issues.append({
                        "service": service_name,
                        "issue": "WRONG_RELATIVE_PATH",
                        "current": context_path,
                        "expected": f"../{context_path.lstrip('./')}",
                        "detail": f"Context '{context_path}' resolves to non-existent '{resolved_context}'. "
                                  f"Correct path should be '../{context_path.lstrip('./')}' which exists at '{alt_path}'"
                    })
                    
                    if fix:
                        # Auto-fix the path
                        fixed_path = f"../{context_path.lstrip('./')}"
                        if isinstance(build_config, str):
                            services[service_name]['build'] = fixed_path
                        else:
                            services[service_name]['build']['context'] = fixed_path
                        fixes_applied.append({
                            "service": service_name,
                            "old": context_path,
                            "new": fixed_path
                        })
                else:
                    issues.append({
                        "service": service_name,
                        "issue": "CONTEXT_NOT_FOUND",
                        "path": context_path,
                        "detail": f"Build context '{context_path}' does not exist"
                    })
            else:
                # Context exists, check Dockerfile
                dockerfile_path = resolved_context / dockerfile
                if not dockerfile_path.exists():
                    issues.append({
                        "service": service_name,
                        "issue": "DOCKERFILE_NOT_FOUND",
                        "path": f"{context_path}/{dockerfile}",
                    })
                else:
                    # Check for key source files
                    key_files = []
                    if service_name in ['frontend', 'web', 'ui']:
                        key_files = ['package.json', 'src/App.jsx', 'src/main.jsx', 'index.html']
                    elif service_name in ['backend', 'api', 'server']:
                        key_files = ['package.json', 'server.js', 'app.js', 'index.js']
                    
                    missing_files = []
                    found_files = []
                    for kf in key_files:
                        if (resolved_context / kf).exists():
                            found_files.append(kf)
                        else:
                            # Try alternative
                            pass  # Some files are optional
                    
                    valid_services.append({
                        "service": service_name,
                        "context": context_path,
                        "dockerfile": f"{context_path}/{dockerfile}",
                        "source_files": found_files[:5],  # Limit
                    })
        
        # Apply fixes if requested
        if fix and fixes_applied:
            try:
                with open(compose_file, 'w') as f:
                    yaml.dump(compose_data, f, default_flow_style=False, sort_keys=False)
            except Exception as e:
                return ToolResult.fail(f"Failed to write fixes: {e}")
        
        # Summary
        if issues:
            result_data = {
                "valid": False,
                "issues": issues,
                "valid_services": valid_services,
                "message": f"Found {len(issues)} issue(s) in docker-compose.yml",
            }
            if fixes_applied:
                result_data["fixes_applied"] = fixes_applied
                result_data["message"] += f". Applied {len(fixes_applied)} fix(es)."
            
            return ToolResult.fail(
                f"Docker compose validation failed: {result_data['message']}",
                data=result_data,
            )
        else:
            return ToolResult.ok(data={
                "valid": True,
                "services": valid_services,
                "message": "All Docker configurations are valid",
            })


class DockerInspectImageTool(BaseTool):
    """Inspect files inside a Docker image."""
    
    NAME = "docker_inspect_image"
    DESCRIPTION = """Check if specific files exist inside a built Docker image.

Useful for debugging when containers show stale/placeholder content.
Verifies that source code was actually included in the Docker build.

Example:
  docker_inspect_image(service="frontend", paths=["src/App.jsx", "dist/index.html"])
"""
    
    def __init__(self, *, workspace: Workspace):
        super().__init__(name=self.NAME, category=ToolCategory.RUNTIME)
        if workspace is None:
            raise ValueError(f"{self.NAME}: workspace is required (no bypass construction)")
        self.workspace = workspace
    
    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "description": "Service name to inspect"
                    },
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Paths to check inside the container"
                    },
                },
                "required": ["service"],
            },
        )
    
    async def execute(self, service: str, paths: List[str] = None) -> ToolResult:
        compose_file = _find_compose_file_global(self.workspace.base_root)
        if not compose_file:
            return ToolResult.fail("docker-compose.yml not found")
        
        # Default paths to check based on service
        if not paths:
            if service in ['frontend', 'web', 'ui']:
                paths = [
                    "/usr/share/nginx/html/index.html",
                    "/usr/share/nginx/html/assets",
                    "/app/src/App.jsx",
                    "/app/dist/index.html",
        ]
            elif service in ['backend', 'api', 'server']:
                paths = [
                    "/app/server.js",
                    "/app/package.json",
                    "/app/routes",
                ]
            else:
                paths = ["/app"]
        
        # Get container ID for the service
        try:
            result = subprocess.run(
                ["docker", "compose", "-f", str(compose_file), "ps", "-q", service],
                cwd=str(self.workspace.base_root),
                capture_output=True,
                text=True,
                timeout=30,
                encoding='utf-8',
                errors='replace',
            )
            container_id = result.stdout.strip()
            
            if not container_id:
                return ToolResult.fail(f"No running container for service '{service}'. Run docker_up first.")
            
            # Check each path
            found = []
            missing = []
            file_contents = {}
            
            for path in paths:
                check_result = subprocess.run(
                    ["docker", "exec", container_id, "test", "-e", path],
                    capture_output=True,
                    timeout=10,
                )
                
                if check_result.returncode == 0:
                    found.append(path)
                    
                    # For key files, get first few lines
                    if path.endswith(('.jsx', '.js', '.html', '.json')):
                        head_result = subprocess.run(
                            ["docker", "exec", container_id, "head", "-20", path],
                            capture_output=True,
                            text=True,
                            timeout=10,
                            encoding='utf-8',
                            errors='replace',
                        )
                        if head_result.returncode == 0:
                            file_contents[path] = head_result.stdout[:500]
                else:
                    missing.append(path)
            
            # Check for placeholder indicators
            is_placeholder = False
            placeholder_evidence = []
            
            for path, content in file_contents.items():
                if "scaffold" in content.lower() or "placeholder" in content.lower():
                    is_placeholder = True
                    placeholder_evidence.append(path)
            
            return ToolResult.ok(data={
                "service": service,
                "container_id": container_id[:12],
                "found_paths": found,
                "missing_paths": missing,
                "file_samples": file_contents,
                "is_placeholder": is_placeholder,
                "placeholder_evidence": placeholder_evidence,
                "recommendation": (
                    "REBUILD REQUIRED: Container has placeholder content. Run: docker_build(service='{}', no_cache=True) then docker_up(service='{}', force_recreate=True)".format(service, service)
                    if is_placeholder else
                    "Container appears to have actual source code"
                ),
            })
            
        except subprocess.TimeoutExpired:
            return ToolResult.fail("Command timed out")
        except Exception as e:
            return ToolResult.fail(f"Inspect error: {e}")


class DockerComposeResetTool(BaseTool):
    """Reset Docker Compose state to fix 'No such container' errors."""
    
    NAME = "docker_compose_reset"
    DESCRIPTION = """Fully reset Docker Compose state to fix stale container issues.

This tool solves the common "No such container: <id>" error by:
1. Stopping all containers (with orphan removal)
2. Removing all containers and networks for the project
3. Optionally removing volumes
4. Starting fresh with a unique project name

Use this when you see errors like:
- "Error response from daemon: No such container: 909e9ebe4cc0"
- Containers stuck in recreate loop
- Stale container references

Example:
  docker_compose_reset()  # Full cleanup and restart
  docker_compose_reset(keep_volumes=True)  # Keep database data
  docker_compose_reset(start=False)  # Just cleanup, don't start
"""
    
    def __init__(self, *, workspace: Workspace):
        super().__init__(name=self.NAME, category=ToolCategory.RUNTIME)
        if workspace is None:
            raise ValueError(f"{self.NAME}: workspace is required (no bypass construction)")
        self.workspace = workspace
    
    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "keep_volumes": {
                        "type": "boolean",
                        "description": "Keep data volumes (default: false, removes everything)"
                    },
                    "start": {
                        "type": "boolean",
                        "description": "Start containers after reset (default: true)"
                    },
                    "build": {
                        "type": "boolean",
                        "description": "Rebuild images with --no-cache (default: false)"
                    },
                },
                "required": [],
            },
        )
    
    async def execute(
        self,
        keep_volumes: bool = False,
        start: bool = True,
        build: bool = False,
    ) -> ToolResult:
        compose_file = _find_compose_file_global(self.workspace.base_root)
        if not compose_file:
            return ToolResult.fail("docker-compose.yml not found")
        
        import uuid
        import time
        
        steps_completed = []
        errors = []
        
        # Generate unique project name to avoid stale references
        project_name = f"gen_{uuid.uuid4().hex[:8]}"
        compose_dir = compose_file.parent
        
        try:
            # Step 1: Stop and remove all containers with orphan cleanup
            down_args = ["down", "--remove-orphans", "-t", "5"]
            if not keep_volumes:
                down_args.append("-v")
            
            result = _run_compose(compose_file, down_args, cwd=self.workspace.base_root, timeout=120)
            steps_completed.append(f"docker compose down (exit={result.returncode})")
            
            # Step 2: Prune any dangling containers for this directory
            prune_cmd = ["docker", "container", "prune", "-f"]
            subprocess.run(prune_cmd, capture_output=True, timeout=30)
            steps_completed.append("docker container prune")
            
            # Step 3: Small delay to ensure Docker releases resources
            await asyncio.sleep(2)
            steps_completed.append("wait 2s")
            
            if start:
                # Step 4: Build if requested
                if build:
                    build_result = _run_compose(
                        compose_file,
                        ["-p", project_name, "build", "--no-cache"],
                        cwd=self.workspace.base_root,
                        timeout=600,
                    )
                    if build_result.returncode != 0:
                        errors.append(f"Build failed: {build_result.stderr}")
                    else:
                        steps_completed.append(f"docker compose build --no-cache")
                
                # Step 5: Start with fresh project name
                up_result = _run_compose(
                    compose_file,
                    ["-p", project_name, "up", "-d", "--force-recreate"],
                    cwd=self.workspace.base_root,
                    timeout=180,
                )
                
                if up_result.returncode != 0:
                    errors.append(f"Start failed: {up_result.stderr}")
                else:
                    steps_completed.append(f"docker compose -p {project_name} up -d")
                
                # Step 6: Wait for containers to be running
                await asyncio.sleep(3)
                
                # Check status
                status_result = _run_compose(
                    compose_file,
                    ["-p", project_name, "ps"],
                    cwd=self.workspace.base_root,
                    timeout=30,
                )
                
                running_count = status_result.stdout.count("Up") if status_result.stdout else 0
                steps_completed.append(f"verify: {running_count} containers running")
            
            return ToolResult.ok(data={
                "success": len(errors) == 0,
                "project_name": project_name,
                "steps": steps_completed,
                "errors": errors if errors else None,
                "message": (
                    f"Docker Compose reset complete. Project: {project_name}"
                    if not errors else
                    f"Reset completed with {len(errors)} error(s)"
                ),
                "hint": "Use this project name for subsequent docker commands if needed",
            })
            
        except subprocess.TimeoutExpired:
            return ToolResult.fail(f"Reset timed out. Completed steps: {steps_completed}")
        except Exception as e:
            return ToolResult.fail(f"Reset error: {e}. Completed steps: {steps_completed}")


class WaitForServiceTool(BaseTool):
    """Wait for a service to become healthy."""
    
    NAME = "wait_for_service"
    DESCRIPTION = """Wait until a service URL responds with HTTP 200.

Use this AFTER docker_up to ensure services are ready before testing.
Prevents test failures due to services still starting up.

Example:
  wait_for_service(url="http://localhost:8083/health")
  wait_for_service(url="http://localhost:3001", timeout=120)
  wait_for_service(url="http://localhost:8083/api/health", expected_status=200)
"""
    
    def __init__(self, **kwargs):
        super().__init__(name=self.NAME, category=ToolCategory.RUNTIME)
    
    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL to check (e.g., http://localhost:8083/health)"
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Max seconds to wait (default: 60)"
                    },
                    "interval": {
                        "type": "integer",
                        "description": "Seconds between checks (default: 2)"
                    },
                    "expected_status": {
                        "type": "integer",
                        "description": "Expected HTTP status code (default: 200, also accepts 201-299)"
                    },
                },
                "required": ["url"],
            },
        )
    
    async def execute(
        self,
        url: str,
        timeout: int = 60,
        interval: int = 2,
        expected_status: int = 200,
    ) -> ToolResult:
        import time
        
        try:
            import httpx
        except ImportError:
            # Fallback to urllib
            import urllib.request
            import urllib.error
            
            start = time.time()
            attempts = 0
            last_error = None
            
            while time.time() - start < timeout:
                attempts += 1
                try:
                    req = urllib.request.Request(url, method='GET')
                    with urllib.request.urlopen(req, timeout=5) as response:
                        status = response.getcode()
                        if status == expected_status or (expected_status == 200 and 200 <= status < 300):
                            elapsed = time.time() - start
                            return ToolResult.ok(data={
                                "ready": True,
                                "url": url,
                                "status": status,
                                "elapsed_seconds": round(elapsed, 1),
                                "attempts": attempts,
                            })
                except urllib.error.HTTPError as e:
                    last_error = f"HTTP {e.code}"
                except urllib.error.URLError as e:
                    last_error = str(e.reason)
                except Exception as e:
                    last_error = str(e)
                
                await asyncio.sleep(interval)
            
            return ToolResult.ok(data={
                "ready": False,
                "url": url,
                "timeout": timeout,
                "attempts": attempts,
                "last_error": last_error,
                "message": f"Service not ready after {timeout}s ({attempts} attempts). Last error: {last_error}",
            })
        
        # Use httpx if available (better async support)
        start = time.time()
        attempts = 0
        last_error = None
        
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
            while time.time() - start < timeout:
                attempts += 1
                try:
                    response = await client.get(url)
                    if response.status_code == expected_status or (expected_status == 200 and 200 <= response.status_code < 300):
                        elapsed = time.time() - start
                        return ToolResult.ok(data={
                            "ready": True,
                            "url": url,
                            "status": response.status_code,
                            "elapsed_seconds": round(elapsed, 1),
                            "attempts": attempts,
                        })
                    else:
                        last_error = f"HTTP {response.status_code}"
                except httpx.ConnectError:
                    last_error = "Connection refused"
                except httpx.TimeoutException:
                    last_error = "Timeout"
                except Exception as e:
                    last_error = str(e)
                
                await asyncio.sleep(interval)
        
        return ToolResult.ok(data={
            "ready": False,
            "url": url,
            "timeout": timeout,
            "attempts": attempts,
            "last_error": last_error,
            "message": f"Service not ready after {timeout}s ({attempts} attempts). Last error: {last_error}",
        })


class EnvironmentStatusTool(BaseTool):
    """Check and manage environment status cache."""
    
    NAME = "check_environment"
    DESCRIPTION = """Check environment status and optionally reset failure cache.

Use this to:
- See which tools/services are unavailable (Docker, psql, etc.)
- Reset the failure cache to retry a failed operation
- Understand why certain operations are being skipped

Examples:
  check_environment()  # See current status
  check_environment(reset="docker_daemon")  # Force retry Docker operations
  check_environment(reset="all")  # Reset all caches
"""
    
    def __init__(self, **kwargs):
        super().__init__(name=self.NAME, category=ToolCategory.RUNTIME)
    
    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "reset": {
                        "type": "string",
                        "description": "Key to reset (e.g., 'docker_daemon', 'psql') or 'all' to reset everything"
                    }
                },
                "required": [],
            },
        )
    
    def execute(self, reset: str = None) -> ToolResult:
        if not env_cache:
            return ToolResult.ok(data={
                "info": "Environment cache not available",
                "status": {}
            })
        
        # Handle reset
        if reset:
            if reset.lower() == "all":
                env_cache.reset()
                return ToolResult.ok(data={
                    "reset": "all",
                    "info": "All environment caches reset. Operations will be retried.",
                    "status": {}
                })
            else:
                env_cache.reset(reset)
                return ToolResult.ok(data={
                    "reset": reset,
                    "info": f"Cache for '{reset}' reset. Will retry on next call.",
                    "status": env_cache.get_status()
                })
        
        # Get current status
        status = env_cache.get_status()
        
        # Build summary
        unavailable = [k for k, v in status.items() if not v.get("available", True)]
        
        return ToolResult.ok(data={
            "status": status,
            "unavailable": unavailable,
            "info": f"{len(unavailable)} services unavailable" if unavailable else "All services available",
            "hint": "Use check_environment(reset='key') to force retry" if unavailable else None
        })


def create_docker_tools(*, workspace: Workspace) -> List[BaseTool]:
    """Create all Docker tools."""
    return [
        DockerBuildTool(workspace=workspace),
        DockerUpTool(workspace=workspace),
        DockerDownTool(workspace=workspace),
        DockerLogsTool(workspace=workspace),
        DockerStatusTool(workspace=workspace),
        DockerRestartTool(workspace=workspace),
        DockerValidateTool(workspace=workspace),
        DockerInspectImageTool(workspace=workspace),
        DockerComposeResetTool(workspace=workspace),
        WaitForServiceTool(),
        EnvironmentStatusTool(),
    ]

