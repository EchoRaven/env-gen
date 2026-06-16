"""
Skill discovery and prompt injection helpers for configurable agents.

Inspired by OpenClaw's skill model:
- skills live in AgentSkills-style folders containing `SKILL.md`
- agents get an explicit allowlist via config
- the system prompt receives a compact available-skills section
- the model reads the full skill file on demand with normal file tools
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
import os
import shutil


MODULE_DIR = Path(__file__).resolve().parent
BUNDLED_SKILLS_DIR = MODULE_DIR / "bundled_skills"
GLOBAL_SKILLS_DIR = Path.home() / ".env-gen" / "skills"
PROJECT_AGENT_SKILLS_DIRNAME = ".agents/skills"
WORKSPACE_SKILLS_DIRNAME = "skills"
SKILL_FILE_NAME = "SKILL.md"


@dataclass(frozen=True)
class SkillDefinition:
    """Resolved skill visible to an agent."""

    name: str
    description: str
    file_path: str
    source: str
    instructions: str


def _parse_frontmatter(text: str) -> Tuple[Dict[str, str], str]:
    """Parse a minimal AgentSkills-style frontmatter block."""
    if not text.startswith("---\n"):
        return {}, text

    closing = text.find("\n---\n", 4)
    if closing == -1:
        return {}, text

    raw_frontmatter = text[4:closing]
    body = text[closing + len("\n---\n") :]
    data: Dict[str, str] = {}
    for raw_line in raw_frontmatter.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip().strip('"').strip("'")
        data[key.strip()] = value
    return data, body.strip()


def _discover_skill_dirs(root: Path) -> List[Path]:
    """Return direct child folders containing a SKILL.md file."""
    if not root.exists() or not root.is_dir():
        return []

    results: List[Path] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if (child / SKILL_FILE_NAME).exists():
            results.append(child)
            continue
        # Support one grouping level like OpenClaw's grouped skills.
        for nested in sorted(child.iterdir()):
            if nested.is_dir() and (nested / SKILL_FILE_NAME).exists():
                results.append(nested)
    return results


def _load_skill_dir(skill_dir: Path, *, workspace_root: Path, source: str) -> Optional[SkillDefinition]:
    skill_file = skill_dir / SKILL_FILE_NAME
    if not skill_file.exists():
        return None

    text = skill_file.read_text(encoding="utf-8")
    frontmatter, instructions = _parse_frontmatter(text)
    name = (frontmatter.get("name") or skill_dir.name).strip()
    description = (frontmatter.get("description") or "No description provided.").strip()
    try:
        rel_path = str(skill_file.resolve().relative_to(workspace_root.resolve()))
    except Exception:
        rel_path = str(skill_file)

    return SkillDefinition(
        name=name,
        description=description,
        file_path=rel_path.replace("\\", "/"),
        source=source,
        instructions=instructions,
    )


def _normalize_skill_name(name: str) -> str:
    cleaned = str(name or "").strip().lower().replace("_", "-").replace(" ", "-")
    # Path-traversal guard: refuse parent-relative paths and path separators
    # so a skill name can never escape its expected directory.
    cleaned = cleaned.replace("..", "").replace("/", "-").replace("\\", "-")
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-")


def _resolve_skill_root(workspace_root: Path, scope: str) -> Path:
    scope_normalized = str(scope or "project-agent").strip().lower()
    workspace_root = Path(workspace_root)
    if scope_normalized == "global":
        return Path(os.getenv("ENV_GEN_GLOBAL_SKILLS_DIR", str(GLOBAL_SKILLS_DIR))).expanduser()
    if scope_normalized == "workspace":
        return workspace_root / WORKSPACE_SKILLS_DIRNAME
    if scope_normalized == "project-agent":
        return workspace_root / PROJECT_AGENT_SKILLS_DIRNAME
    raise ValueError("scope must be one of: 'global', 'workspace', or 'project-agent'")


def _serialize_skill_markdown(name: str, description: str, instructions: str) -> str:
    body = (instructions or "").strip()
    return (
        f"---\n"
        f"name: {name}\n"
        f"description: {description.strip()}\n"
        f"---\n\n"
        f"{body}\n"
    )


def sync_bundled_skills_into_workspace(workspace_root: Path) -> None:
    """
    Materialize bundled skills into `/.agents/skills` inside the workspace.

    Agents can only read files within their workspace through normal file tools,
    so bundled framework skills are copied into a project-agent skill directory
    if the workspace does not already provide them.
    """

    workspace_root = Path(workspace_root)
    target_root = workspace_root / PROJECT_AGENT_SKILLS_DIRNAME
    target_root.mkdir(parents=True, exist_ok=True)

    if not BUNDLED_SKILLS_DIR.exists():
        return

    for skill_dir in _discover_skill_dirs(BUNDLED_SKILLS_DIR):
        relative_dir = skill_dir.relative_to(BUNDLED_SKILLS_DIR)
        target_dir = target_root / relative_dir
        target_skill_file = target_dir / SKILL_FILE_NAME
        if target_skill_file.exists():
            continue
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(skill_dir, target_dir, dirs_exist_ok=True)


def discover_workspace_skills(workspace_root: Path) -> Dict[str, SkillDefinition]:
    """
    Discover effective skills using OpenClaw-like precedence.

    Highest precedence wins:
    1. `<workspace>/skills`
    2. `<workspace>/.agents/skills`
    3. global `~/.env-gen/skills`
    """

    workspace_root = Path(workspace_root)
    sync_bundled_skills_into_workspace(workspace_root)

    effective: Dict[str, SkillDefinition] = {}
    global_root = Path(os.getenv("ENV_GEN_GLOBAL_SKILLS_DIR", str(GLOBAL_SKILLS_DIR))).expanduser()
    roots = [
        ("global", global_root),
        ("project-agent", workspace_root / PROJECT_AGENT_SKILLS_DIRNAME),
        ("workspace", workspace_root / WORKSPACE_SKILLS_DIRNAME),
    ]
    for source, root in roots:
        for skill_dir in _discover_skill_dirs(root):
            skill = _load_skill_dir(skill_dir, workspace_root=workspace_root, source=source)
            if not skill:
                continue
            effective[skill.name] = skill
    return effective


def list_skill_summaries(workspace_root: Path) -> List[SkillDefinition]:
    """List all effective skills visible in a workspace."""
    return sorted(discover_workspace_skills(workspace_root).values(), key=lambda item: item.name)


def get_skill(workspace_root: Path, skill_name: str) -> Optional[SkillDefinition]:
    """Return one resolved skill by name."""
    normalized = _normalize_skill_name(skill_name)
    if not normalized:
        return None
    skills = discover_workspace_skills(workspace_root)
    for key, skill in skills.items():
        if _normalize_skill_name(key) == normalized:
            return skill
    return None


def upsert_skill(
    workspace_root: Path,
    *,
    name: str,
    description: str,
    instructions: str = "",
    scope: str = "project-agent",
    append: bool = False,
) -> SkillDefinition:
    """
    Create or update a workspace-visible skill.

    - `description` maps to the SKILL.md frontmatter summary
    - `instructions` is the markdown body
    - `append=True` appends to existing instructions instead of replacing them
    """

    normalized_name = _normalize_skill_name(name)
    if not normalized_name:
        raise ValueError("Skill name is required")
    if not str(description or "").strip():
        raise ValueError("Skill description/summary is required")

    workspace_root = Path(workspace_root)
    target_root = _resolve_skill_root(workspace_root, scope)
    target_dir = target_root / normalized_name
    target_file = target_dir / SKILL_FILE_NAME
    target_dir.mkdir(parents=True, exist_ok=True)

    current = get_skill(workspace_root, normalized_name)
    current_instructions = current.instructions if current else ""
    next_instructions = (instructions or "").strip()
    if append and next_instructions:
        if current_instructions.strip():
            next_instructions = f"{current_instructions.rstrip()}\n\n{next_instructions}"
    elif not next_instructions and current_instructions:
        next_instructions = current_instructions

    target_file.write_text(
        _serialize_skill_markdown(
            name=normalized_name,
            description=str(description).strip(),
            instructions=next_instructions,
        ),
        encoding="utf-8",
    )

    resolved = get_skill(workspace_root, normalized_name)
    if not resolved:
        raise RuntimeError(f"Failed to load skill after writing: {normalized_name}")
    return resolved


def resolve_agent_skill_allowlist(
    *,
    workspace_root: Path,
    root_defaults: Optional[Iterable[str]],
    profile_skills: Optional[Iterable[str]],
) -> List[SkillDefinition]:
    """Resolve the final skill set for one agent profile."""

    all_skills = discover_workspace_skills(workspace_root)
    skills_by_normalized_name = {
        _normalize_skill_name(name): skill
        for name, skill in all_skills.items()
    }
    if profile_skills is None:
        requested = list(root_defaults or [])
    else:
        requested = list(profile_skills)

    resolved: List[SkillDefinition] = []
    missing: List[str] = []
    for skill_name in requested:
        normalized = str(skill_name).strip()
        skill = skills_by_normalized_name.get(_normalize_skill_name(normalized))
        if skill:
            resolved.append(skill)
        else:
            missing.append(normalized)
    if missing:
        raise ValueError(
            f"Configured skills not found in workspace skill registry: {missing}. "
            f"Available skills: {sorted(all_skills.keys())}"
        )
    return resolved


def build_available_skills_prompt(
    skills: List[SkillDefinition],
    primary_names: Optional[Iterable[str]] = None,
) -> str:
    """Render the available-skills catalog (Claude-Code / OpenClaw style).

    Every workspace skill appears here as ``name + description + path``
    so the agent can discover the full inventory at a glance and decide
    when to call ``get_skill(name=...)`` to load the full body on
    demand. Full skill bodies are intentionally NOT pre-injected — this
    catalog is the entry point, not the content.

    ``primary_names``: optional list of skill names that this agent's
    profile marks as primary. They're rendered under a separate
    "Your primary skills" header so the model knows what its role
    expects it to lean on; the rest land under "Also available".
    """
    if not skills:
        return ""

    primary_set = {str(n).strip() for n in (primary_names or []) if str(n).strip()}
    primary: List[SkillDefinition] = []
    others: List[SkillDefinition] = []
    for s in skills:
        (primary if s.name in primary_set else others).append(s)

    def _render(items: List[SkillDefinition]) -> List[str]:
        out: List[str] = []
        for skill in items:
            out.append(f"- `{skill.name}`: {skill.description}")
            out.append(f"  path: `{skill.file_path}`")
        return out

    lines = [
        "<available_skills>",
        "These skills are operating procedures, not background lore. When a",
        "task is covered by a skill, you MUST call `get_skill(name=...)` to",
        "load its full body and follow it BEFORE you act. If `get_skill` is",
        "unavailable, read the listed `SKILL.md` path with `read(file_path=...)`.",
        "",
        "Your **primary** skills below are MANDATORY for your role: consult the",
        "relevant one before acting on the work it covers. Do not rationalize",
        "skipping it — these thoughts are red flags that mean STOP and load the",
        "skill first:",
        "  - \"this is a simple change, I'll just do it\"",
        "  - \"I'll write it first and check the skill later\"",
        "  - \"I roughly remember what this skill says\"",
        "",
    ]
    if primary:
        lines.append("## Your primary skills (MANDATORY — consult before acting)")
        lines.extend(_render(primary))
        lines.append("")
    if others:
        lines.append("## Also available (load on demand if relevant)")
        lines.extend(_render(others))
    lines.append("</available_skills>")
    return "\n".join(lines)
