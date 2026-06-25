"""
Memory Bank - Structured Long-term Project Memory

Inspired by Cursor Memory Bank:
https://cursor.zone/faq/how-to-use-cursor-memory-bank.html

Complements utils/memory.py by providing file-based persistent project documentation.
AgentMemory handles conversation/event memory, MemoryBank handles project knowledge.

Structure:
    memory-bank/
    ├── project_brief.md      # Core requirements and goals
    ├── tech_context.md       # Technologies, dependencies, constraints
    ├── system_patterns.md    # Architecture, design patterns
    ├── active_context.md     # Current work focus, recent changes
    └── progress.md           # Completed features, known issues
"""

import logging
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime
import re

# In-context MEMORY budget (user 2026-06-24): sized generously / customizable, not a
# tiny hardcoded default — a large-context model has ample room for fuller memory.
# These module-level values are the FLOORS / env-override path used when the model
# is unknown in scope; when a model IS known the budgets are sized as a fraction of
# resolve_ctx_working_chars(model) (digest ~6%, notebook ~2.5%) via
# MemoryBank._resolve_char_budgets(). Override via
# ENVGEN_MEMORY_DIGEST_CHARS / ENVGEN_MEMORY_NOTEBOOK_CHARS.
# Floors are the prior hardcoded caps (16000 / 6000) so a small/unknown model still
# gets a generous default and we never go BELOW what shipped before.
_DIGEST_CHARS = max(16000, int(os.environ.get("ENVGEN_MEMORY_DIGEST_CHARS", "16000")))
_NOTEBOOK_CHARS = max(6000, int(os.environ.get("ENVGEN_MEMORY_NOTEBOOK_CHARS", "6000")))

# Fraction of the model's recommended WORKING char budget to spend on each
# in-context memory artifact. Digest is the always-injected orientation block;
# the notebook is the agent's own journal (a subset of the digest).
_DIGEST_BUDGET_FRACTION = 0.06
_NOTEBOOK_BUDGET_FRACTION = 0.025


@dataclass
class MemoryFile:
    """Represents a single memory file."""
    name: str
    path: Path
    content: str = ""
    last_updated: Optional[datetime] = None
    
    def load(self) -> str:
        """Load content from file."""
        if self.path.exists():
            self.content = self.path.read_text(encoding="utf-8")
            self.last_updated = datetime.fromtimestamp(self.path.stat().st_mtime)
        return self.content
    
    def save(self, content: str) -> None:
        """Save content to file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(content, encoding="utf-8")
        self.content = content
        self.last_updated = datetime.now()


@dataclass
class MemoryBank:
    """
    Memory Bank for persistent project knowledge.
    
    Provides structured storage for:
    - Project requirements and goals
    - Technical context and constraints
    - Architecture patterns and decisions
    - Current work focus and progress
    - Completed features and known issues
    """
    
    root_dir: Path
    memory_dir: Optional[Path] = None
    # Agent model name (optional). When provided, the in-context digest/notebook
    # char budgets are sized as a fraction of resolve_ctx_working_chars(model)
    # instead of the fixed floors — a 1M-context model gets a much larger digest.
    # TODO(memory-sizing): current MemoryBank() call sites (base.py /
    # agent_interaction_tools.py) do not yet pass `model`; thread the agent's
    # config.model_name through there so the budgets auto-size on big-window models.
    # Until then this stays None and we fall back to the env-override / floor path.
    model: Optional[str] = None
    _files: Dict[str, MemoryFile] = field(default_factory=dict)
    _logger: logging.Logger = field(default_factory=lambda: logging.getLogger("memory_bank"))
    
    # Core memory file definitions
    CORE_FILES = {
        "project_brief": {
            "filename": "project_brief.md",
            "description": "Core requirements and project goals",
            "template": """# Project Brief

## Overview
{project_name} - {description}

## Core Requirements
{requirements_block}

## Goals (project-specific)
- Deliver a working frontend + backend + database stack per specs.
- Ensure auth/login works with seeded users and core flows are testable.
- Provide smoke-testable APIs and UI based on design specs.

## Scope (adjust per project)
- In scope: stated features in requirements/specs.
- Out of scope: anything not in requirements/specs or marked optional.

## Success Criteria
- Services start (docker/local) and basic flows pass smoke tests.
- No critical 500s/404s on specified endpoints; UI aligns with design spec.
"""
        },
        "tech_context": {
            "filename": "tech_context.md",
            "description": "Technologies, dependencies, and constraints",
            "template": """# Technical Context

## Technology Stack
- Frontend: {frontend_tech}
- Backend: {backend_tech}
- Database: {database_tech}

## Dependencies (adjust per package.json)
- Frontend: router/build tooling, lint tooling as applicable
- Backend: Express, JWT auth, PostgreSQL client, dotenv

## Development Setup
- Prefer docker compose when available
- Otherwise run backend + frontend locally with node + postgres

## Technical Constraints
- Keep paths within workspace root; no writes outside generated project
- Deterministic, testable APIs; clear error handling

## Environment Variables
- DATABASE_URL or DB_HOST/DB_USER/DB_PASSWORD/DB_NAME/DB_PORT
- PORT / CORS_ORIGIN / VITE_API_BASE (align UI/API ports)
- Provider keys (OPENAI_API_KEY etc.) if needed
"""
        },
        "system_patterns": {
            "filename": "system_patterns.md",
            "description": "Architecture and design patterns",
            "template": """# System Patterns

## Architecture Overview
- Generated project with app/frontend, app/backend, app/database, docker/
- REST API backend with JWT auth and PostgreSQL persistence
- SPA frontend consuming backend API

## Design Patterns
- Backend: route/controller separation, validation + centralized error handling
- Frontend: pages/components with shared layout, loading/error states

## Component Relationships
- Frontend routes -> pages -> components -> API client -> backend endpoints
- Backend routes -> controllers -> db queries -> postgres

## Key Technical Decisions
- Keep file operations within workspace; avoid duplicates/out-of-root writes
- Use consistent naming for routes/models; prefer schema-aligned field names

## API Patterns
- JSON REST under /api/*
- Authorization: Bearer <token> for protected routes
"""
        },
        "active_context": {
            "filename": "active_context.md",
            "description": "Current work focus and recent changes",
            "template": """# Active Context

## Current Focus
Working on: initialization

## Recent Changes
- {timestamp}: [Change description]

## Next Steps
1. [Next action item]

## Active Decisions
[Decisions being considered]

## Blockers
[Current blockers if any]
"""
        },
        "progress": {
            "filename": "progress.md",
            "description": "Completed features and known issues",
            "template": """# Progress

## Completed Features
- [x] Initialized project and memory bank

## In Progress
- [ ] (update during generation)

## Known Issues
- (none yet)

## Test Status
[Testing progress]

## Deployment Status
[Deployment state]
"""
        },
        "notebook": {
            "filename": "notebook.md",
            "description": "Agent-writable working memory (journal). NOT framework-synced; NOT committed.",
            "template": """# Lane Notebook

> THIS FILE IS YOURS. You maintain it with `update_memory_bank(...)`; the framework
> never overwrites it, and it is NOT committed. It PERSISTS across all of your wakes —
> record here what your NEXT wake should not have to re-derive: decisions you made,
> gotchas you hit, where things live, and the next thing to do.
>
> The OTHER memory-bank files (project_brief / tech_context / system_patterns /
> active_context / progress) are FRAMEWORK-MAINTAINED and READ-ONLY to you — they hold
> the objective truth (your current focus + real progress). Read them via the
> auto-provided digest or `read_memory_bank`; do not hand-edit them.

## Decisions

## Gotchas & Issues

## Tech Notes

## Next / TODO

## Log
"""
        }
    }

    # The agent-WRITABLE half of the bank (free-form journal; framework never
    # auto-syncs it). Everything else in CORE_FILES is FRAMEWORK-SYNCED and
    # read-only to the lane. Kept as named constants so the read/write split is
    # visible in one place (user requirement: modifiable files != synced files).
    NOTEBOOK_KEY = "notebook"
    SYNCED_KEYS = ("project_brief", "tech_context", "system_patterns",
                   "active_context", "progress")
    
    def __post_init__(self):
        """Initialize memory files."""
        self.root_dir = Path(self.root_dir)
        self.memory_dir = Path(self.memory_dir) if self.memory_dir else self.root_dir / "memory-bank"
        self._initialize_files()
    
    def _initialize_files(self) -> None:
        """Initialize memory file objects."""
        for key, config in self.CORE_FILES.items():
            file_path = self.memory_dir / config["filename"]
            self._files[key] = MemoryFile(
                name=key,
                path=file_path,
            )
    
    def initialize(self, project_info: Dict[str, Any]) -> None:
        """
        Initialize memory bank with project information.
        
        Args:
            project_info: Dict containing project details like name, description, etc.
        """
        self._logger.info("Initializing Memory Bank")
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        
        requirements = project_info.get("requirements") or []
        if isinstance(requirements, str):
            # tolerate string input; split lines
            requirements = [r.strip("- ").strip() for r in requirements.splitlines() if r.strip()]

        requirements_block = "- " + "\n- ".join(requirements) if requirements else "- (not specified)"

        for key, config in self.CORE_FILES.items():
            file_path = self.memory_dir / config["filename"]
            
            if not file_path.exists():
                # Create from template
                content = config["template"].format(
                    project_name=project_info.get("name", "Project"),
                    description=project_info.get("description", ""),
                    frontend_tech=project_info.get("frontend", "React"),
                    backend_tech=project_info.get("backend", "Node.js"),
                    database_tech=project_info.get("database", "PostgreSQL"),
                    requirements_block=requirements_block,
                    timestamp=datetime.now().isoformat(),
                )
                self._files[key].save(content)
                self._logger.debug(f"Created {config['filename']}")
            else:
                # Opportunistically hydrate placeholders if the file still has template markers
                existing = self._files[key].load()
                if key == "project_brief" and "[List core requirements here]" in existing:
                    self._files[key].save(
                        existing.replace("- [List core requirements here]", requirements_block)
                    )

        # Always run a lightweight repair pass to remove common placeholders/noise
        self.repair(project_info)

    def repair(self, project_info: Optional[Dict[str, Any]] = None) -> None:
        """
        Repair/normalize existing memory bank files.

        This removes template placeholders and de-duplicates sections that can become
        noisy during long runs (e.g., repeated "Working on:" lines).
        Safe to call multiple times.
        """
        project_info = project_info or {}
        requirements = project_info.get("requirements") or []
        if isinstance(requirements, str):
            requirements = [r.strip("- ").strip() for r in requirements.splitlines() if r.strip()]
        requirements_block = "- " + "\n- ".join(requirements) if requirements else "- (not specified)"

        # project_brief: replace placeholders if present
        pb = self._files["project_brief"].load()
        if "- [List core requirements here]" in pb or "[List core requirements here]" in pb:
            pb = pb.replace("- [List core requirements here]", requirements_block)
        if "- [List project goals here]" in pb:
            pb = pb.replace("- [List project goals here]", "- Deliver the requested application with working frontend, backend, database, and validation coverage.")
        if "- In scope: [What's included]" in pb:
            pb = pb.replace("- In scope: [What's included]", "- In scope: stated requirements, generated app code, database schema/seed data, API contracts, UI flows, and validation.")
        if "- Out of scope: [What's excluded]" in pb:
            pb = pb.replace("- Out of scope: [What's excluded]", "- Out of scope: features not requested or explicitly marked optional.")
        if "- [Define success metrics]" in pb:
            pb = pb.replace("- [Define success metrics]", "- Core flows work end-to-end; services start via docker compose; no obvious runtime errors.")
        self._files["project_brief"].save(pb.strip() + "\n")

        # progress: remove placeholders
        prog = self._files["progress"].load()
        prog = prog.replace("- [x] [Feature 1]", "").replace("- [ ] [Feature 2]", "")
        prog = prog.replace("- [Issue 1]: [Description]", "- (none yet)")
        self._files["progress"].save("\n".join([ln.rstrip() for ln in prog.splitlines() if ln.strip() != ""]).strip() + "\n")

        # active_context: collapse Current Focus to a single line if it got spammed
        ac_lines = self._files["active_context"].load().splitlines()

        def _find_idx(header: str) -> Optional[int]:
            for i, ln in enumerate(ac_lines):
                if ln.strip() == header:
                    return i
            return None

        def _section_range(header: str) -> Optional[tuple[int, int]]:
            start = _find_idx(header)
            if start is None:
                return None
            end = len(ac_lines)
            for j in range(start + 1, len(ac_lines)):
                if ac_lines[j].startswith("## "):
                    end = j
                    break
            return start, end

        # Current Focus: keep only one meaningful line
        focus_rng = _section_range("## Current Focus")
        if focus_rng:
            start, end = focus_rng
            body = [ln.strip() for ln in ac_lines[start + 1 : end] if ln.strip()]
            body = [ln for ln in body if "[What's being worked on now]" not in ln]
            # Keep first "Working on:" line if present
            focus_line = next((ln for ln in body if ln.lower().startswith("working on:")), None) or (body[0] if body else "Working on: (unknown)")
            ac_lines = ac_lines[: start + 1] + [focus_line, ""] + ac_lines[end:]

        # Recent Changes: remove placeholder, de-dup, cap to last 10
        rc_rng = _section_range("## Recent Changes")
        if rc_rng:
            start, end = rc_rng
            body = [ln.strip() for ln in ac_lines[start + 1 : end] if ln.strip()]
            body = [ln for ln in body if "[Change description]" not in ln]
            # Keep only bullet lines
            body = [ln for ln in body if ln.startswith("- ")]
            # De-dup preserving order
            seen = set()
            deduped = []
            for ln in body:
                if ln not in seen:
                    seen.add(ln)
                    deduped.append(ln)
            deduped = deduped[:10]
            ac_lines = ac_lines[: start + 1] + (deduped + [""] if deduped else ["- (none yet)", ""]) + ac_lines[end:]

        # Next Steps: remove placeholder, ensure at least one item exists
        ns_rng = _section_range("## Next Steps")
        if ns_rng:
            start, end = ns_rng
            body = [ln.strip() for ln in ac_lines[start + 1 : end] if ln.strip()]
            body = [ln for ln in body if "[Next action item]" not in ln]
            # Keep only numbered items
            body = [ln for ln in body if ln[0:2].isdigit() or ln.startswith("1.")]
            if not body:
                body = ["1. (auto-updated during generation)"]
            else:
                body = body[:5]
            ac_lines = ac_lines[: start + 1] + body + [""] + ac_lines[end:]

        # Active Decisions: remove placeholder, keep simple marker
        ad_rng = _section_range("## Active Decisions")
        if ad_rng:
            start, end = ad_rng
            body = [ln.strip() for ln in ac_lines[start + 1 : end] if ln.strip()]
            body = [ln for ln in body if "[Decisions being considered]" not in ln]
            if not body:
                body = ["- (none)"]
            ac_lines = ac_lines[: start + 1] + body + [""] + ac_lines[end:]

        # Blockers: remove placeholder, keep simple marker
        bl_rng = _section_range("## Blockers")
        if bl_rng:
            start, end = bl_rng
            body = [ln.strip() for ln in ac_lines[start + 1 : end] if ln.strip()]
            body = [ln for ln in body if "[Current blockers if any]" not in ln]
            if not body:
                body = ["- (none)"]
            ac_lines = ac_lines[: start + 1] + body

        self._files["active_context"].save("\n".join(ac_lines).strip() + "\n")
    
    def load_all(self) -> Dict[str, str]:
        """
        Load all memory files.
        
        Returns:
            Dict mapping file keys to their content
        """
        contents = {}
        for key, mem_file in self._files.items():
            contents[key] = mem_file.load()
        return contents
    
    def get_context(self) -> str:
        """
        Get combined context from all memory files for LLM prompt.
        
        Returns:
            Formatted string with all memory bank contents
        """
        contents = self.load_all()
        
        sections = []
        for key, config in self.CORE_FILES.items():
            content = contents.get(key, "")
            if content:
                sections.append(f"## {config['description']}\n\n{self._strip_top_heading(content)}")
        
        return "\n\n---\n\n".join(sections)

    @staticmethod
    def _strip_top_heading(content: str) -> str:
        """
        Avoid nested headings in prompts.
        If the file starts with a single '# Title' line, strip it.
        """
        lines = content.splitlines()
        if not lines:
            return content
        if lines[0].startswith("# "):
            # drop first line and following single blank line
            rest = lines[1:]
            if rest and rest[0].strip() == "":
                rest = rest[1:]
            return "\n".join(rest).strip()
        return content.strip()
    
    def update(self, key: str, content: str) -> None:
        """
        Update a specific memory file.
        
        Args:
            key: Memory file key (e.g., 'active_context', 'progress')
            content: New content for the file
        """
        if key not in self._files:
            raise ValueError(f"Unknown memory file: {key}")

        self._files[key].save(content)
        self._logger.info(f"Updated {key}")

    def set_current_focus(self, focus: str) -> None:
        """Deterministically rewrite ONLY the ``## Current Focus`` section of
        active_context (preserving Recent Changes / Next Steps / Decisions / Blockers).

        The bank's active_context promised to be '(auto-updated during generation)' but
        nothing ever wrote it — agents read a frozen 'Working on: initialization' that
        contradicted their real phase, feeding drift/idle. The framework knows the live
        phase (agent._active_phase) + lane; this keeps the bank's STATE in sync so a
        read_memory_bank reflects where the run actually is. Best-effort; never raises."""
        try:
            ac = self._files.get("active_context")
            if ac is None:
                return
            lines = ac.load().splitlines()
            out, i, n = [], 0, len(lines)
            replaced = False
            while i < n:
                ln = lines[i]
                if ln.strip().lower() == "## current focus":
                    out.append(ln)
                    out.append(f"Working on: {focus}")
                    out.append("")
                    i += 1
                    # skip the old body up to the next "## " header (or EOF)
                    while i < n and not lines[i].lstrip().startswith("## "):
                        i += 1
                    replaced = True
                    continue
                out.append(ln)
                i += 1
            if not replaced:  # no section yet — prepend one
                out = ["## Current Focus", f"Working on: {focus}", ""] + out
            ac.save("\n".join(out).strip() + "\n")
        except Exception:
            pass

    def _set_section(self, file_key: str, header: str,
                     body_lines: List[str], max_items: int = 12) -> None:
        """Deterministically REPLACE the body of ``## <header>`` in ``file_key``
        with ``body_lines`` (truth-sync semantics: replace, not append — the
        section is a live snapshot of current state). Creates the section if
        absent. Best-effort; never raises. Mirrors ``set_current_focus``'s
        section-rewrite so framework state stays a single source of truth."""
        try:
            f = self._files.get(file_key)
            if f is None:
                return
            body = [str(b).strip() for b in (body_lines or []) if str(b).strip()][:max_items]
            if not body:
                body = ["(none)"]
            body = [b if b.startswith(("- ", "[", "1.", "2.", "3.", "4.", "5.",
                                       "6.", "7.", "8.", "9.")) else f"- {b}"
                    for b in body]
            lines = f.load().splitlines()
            out, i, n, replaced = [], 0, len(lines), False
            target = header.strip().lower()
            while i < n:
                ln = lines[i]
                if ln.strip().lower() == target:
                    out.append(ln)
                    out.extend(body)
                    out.append("")
                    i += 1
                    while i < n and not lines[i].lstrip().startswith("## "):
                        i += 1
                    replaced = True
                    continue
                out.append(ln)
                i += 1
            if not replaced:
                out = out + ["", header] + body + [""]
            f.save("\n".join(out).strip() + "\n")
        except Exception:
            pass

    def sync_framework_state(self, *, completed: Optional[List[str]] = None,
                             in_progress: Optional[List[str]] = None,
                             next_steps: Optional[List[str]] = None,
                             blockers: Optional[List[str]] = None,
                             known_issues: Optional[List[str]] = None) -> None:
        """FRAMEWORK auto-sync (authoritative hub truth → the READ-ONLY files):
        REPLACE the derived sections of active_context + progress so the digest
        reflects real progress / next / blockers without depending on the agent
        calling report_progress (whose feeder path was dead). Each arg is a live
        snapshot; pass None to leave a section untouched. Best-effort; never raises.
        Current Focus stays owned by ``set_current_focus``; the notebook stays the
        agent's own writable half — untouched here."""
        if next_steps is not None:
            self._set_section("active_context", "## Next Steps", next_steps)
        if blockers is not None:
            self._set_section("active_context", "## Blockers", blockers)
        if completed is not None:
            # DURABLE category: a real project ships >20 features; capping at 20
            # silently evicted the oldest and caused re-work. Keep a large cap so
            # completed work accumulates (only ephemeral Recent Changes stays small).
            self._set_section("progress", "## Completed Features", completed, max_items=200)
        if in_progress is not None:
            self._set_section("progress", "## In Progress", in_progress)
        if known_issues is not None:
            self._set_section("progress", "## Known Issues", known_issues)

    def append_to_progress(self, item: str, category: str = "completed") -> None:
        """
        Append an item to the progress file.
        
        Args:
            item: Item description
            category: One of 'completed', 'in_progress', 'issues'
        """
        current = self._files["progress"].load()
        # Remove placeholder entries if still present
        current = current.replace("- [x] [Feature 1]", "").replace("- [ ] [Feature 2]", "")
        current = current.replace("- [Issue 1]: [Description]", "").strip() + "\n"
        item = str(item or "").strip()
        if not item:
            return
        
        category_markers = {
            "completed": "## Completed Features",
            "in_progress": "## In Progress",
            "issues": "## Known Issues",
        }
        
        marker = category_markers.get(category)
        if marker and marker in current:
            # Find the section and append
            lines = current.split("\n")
            new_lines = []
            in_section = False
            added = False
            checkbox = "[x]" if category == "completed" else "[ ]"
            entry = f"- {checkbox} {item}"
            normalized_entry = entry.strip().lower()
            
            for line in lines:
                if line.strip().lower() == normalized_entry:
                    continue
                new_lines.append(line)
                if line.startswith(marker):
                    in_section = True
                    continue
                if in_section and line.startswith("## "):
                    if not added:
                        new_lines.insert(len(new_lines) - 1, entry)
                        added = True
                    in_section = False
                elif in_section and not added and line.startswith("-"):
                    # Insert right after the section header before the first list item
                    new_lines.insert(len(new_lines) - 1, entry)
                    added = True
            
            if not added:
                new_lines.append(entry)
            
            self._files["progress"].save("\n".join(new_lines))
    
    def update_active_context(self, focus: str = None, recent_change: str = None, next_step: str = None) -> None:
        """
        Update the active context file.
        
        Args:
            focus: Current work focus
            recent_change: Optional recent change to log
            next_step: Optional next step to add
        """
        current = self._files["active_context"].load()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        lines = current.split("\n")

        def _section_bounds(header: str) -> Optional[tuple[int, int]]:
            start = None
            for i, ln in enumerate(lines):
                if ln.strip() == header:
                    start = i
                    break
            if start is None:
                return None
            end = len(lines)
            for j in range(start + 1, len(lines)):
                if lines[j].startswith("## "):
                    end = j
                    break
            return start, end

        # Update Current Focus only when a new durable focus is provided.
        if focus:
            bounds = _section_bounds("## Current Focus")
            if bounds:
                start, end = bounds
                new_lines = lines[: start + 1] + [focus] + [""] + lines[end:]
                lines = new_lines

        # Update Recent Changes: prepend a bullet, keep last 10, remove placeholder
        if recent_change:
            bounds = _section_bounds("## Recent Changes")
            if bounds:
                start, end = bounds
                body = [ln for ln in lines[start + 1 : end] if ln.strip() and "[Change description]" not in ln]
                entry = f"- {timestamp}: {recent_change}"
                # Remove duplicates by change text rather than timestamp.
                def _change_text(line: str) -> str:
                    return re.sub(r"^-\s+\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\s*", "", line.strip()).strip().lower()

                new_change = str(recent_change).strip().lower()
                body = [ln for ln in body if _change_text(ln) != new_change]
                body.insert(0, entry)
                body = body[:10]
                lines = lines[: start + 1] + body + [""] + lines[end:]

        # Update Next Steps if provided (replace first item)
        if next_step:
            bounds = _section_bounds("## Next Steps")
            if bounds:
                start, end = bounds
                body = [ln for ln in lines[start + 1 : end] if ln.strip()]
                # Replace with a single next step line
                lines = lines[: start + 1] + [f"1. {next_step}"] + [""] + lines[end:]

        self._files["active_context"].save("\n".join(lines).strip() + "\n")

    def append_decision(self, decision: str) -> None:
        """Append a key technical/project decision to system_patterns.md."""
        # DURABLE category: decisions are rationale the agent must not lose mid-run;
        # capping at 20 evicted the earliest decisions. Large cap to accumulate.
        self._append_unique_bullet(
            key="system_patterns",
            section_header="## Key Technical Decisions",
            item=decision,
            max_items=200,
        )

    def append_tech_note(self, note: str) -> None:
        """Append a high-signal technical note to tech_context.md."""
        self._append_unique_bullet(
            key="tech_context",
            section_header="## Technical Constraints",
            item=note,
            max_items=20,
        )

    def append_notebook(
        self,
        *,
        focus: str = None,
        next_step: str = None,
        recent_change: str = None,
        completed: Optional[List[str]] = None,
        issues: Optional[List[str]] = None,
        decisions: Optional[List[str]] = None,
        tech_notes: Optional[List[str]] = None,
    ) -> List[str]:
        """Append the agent's OWN durable notes to its writable notebook
        (notebook.md) — the SEPARATE, agent-owned half of the bank. Never
        touches the framework-synced CORE files (active_context / progress /
        system_patterns / tech_context). De-duplicated + capped per section via
        ``_append_unique_bullet``. Returns the section names touched.

        This is the write target for the ``update_memory_bank`` tool: a lane
        edits ONLY its notebook; the synced files stay framework-owned and
        read-only (user requirement: modifiable files != auto-synced files)."""
        if self.NOTEBOOK_KEY not in self._files:
            return []
        touched: List[str] = []
        for d in (decisions or []):
            self._append_unique_bullet(self.NOTEBOOK_KEY, "## Decisions", d)
        if decisions:
            touched.append("Decisions")
        for it in (issues or []):
            self._append_unique_bullet(self.NOTEBOOK_KEY, "## Gotchas & Issues", it)
        if issues:
            touched.append("Gotchas & Issues")
        for t in (tech_notes or []):
            self._append_unique_bullet(self.NOTEBOOK_KEY, "## Tech Notes", t)
        if tech_notes:
            touched.append("Tech Notes")
        if next_step:
            self._append_unique_bullet(self.NOTEBOOK_KEY, "## Next / TODO", next_step)
            touched.append("Next / TODO")
        # focus / recent_change / completed form the running ## Log — the agent's
        # journal of what it did, so a later wake has continuity.
        log_bits: List[str] = []
        if focus:
            log_bits.append(f"focus: {focus}")
        if recent_change:
            log_bits.append(recent_change)
        log_bits.extend(f"done: {c}" for c in (completed or []))
        for b in log_bits:
            self._append_unique_bullet(self.NOTEBOOK_KEY, "## Log", b)
        if log_bits:
            touched.append("Log")
        return touched

    def _resolve_char_budgets(self) -> tuple[int, int]:
        """Return (digest_chars, notebook_chars) for the in-context memory.

        When ``self.model`` is known, size each as a fraction of the model's
        recommended working char budget (resolve_ctx_working_chars) — so a
        1M-context model gets a much fuller digest instead of the fixed cap.
        The module-level _DIGEST_CHARS / _NOTEBOOK_CHARS act as FLOORS (and the
        explicit env-override path), so we never go below what shipped before.
        Best-effort: if model_limits is unavailable, fall back to the floors."""
        digest, notebook = _DIGEST_CHARS, _NOTEBOOK_CHARS
        if self.model:
            try:
                from utils.model_limits import resolve_ctx_working_chars
                working = resolve_ctx_working_chars(self.model)
                digest = max(digest, int(working * _DIGEST_BUDGET_FRACTION))
                notebook = max(notebook, int(working * _NOTEBOOK_BUDGET_FRACTION))
            except Exception:
                pass
        return digest, notebook

    def get_notebook(self, max_chars: Optional[int] = None) -> str:
        """Return the agent's writable notebook content (trimmed)."""
        if max_chars is None:
            max_chars = self._resolve_char_budgets()[1]
        nb = self.get_file(self.NOTEBOOK_KEY) or ""
        # Drop the read-only-contract preamble (the > blockquote) from the
        # digest view — the agent already knows it owns this file.
        body = "\n".join(
            ln for ln in nb.splitlines()
            if not ln.lstrip().startswith(">") and not ln.startswith("# Lane Notebook")
        ).strip()
        if len(body) > max_chars:
            dropped = len(body) - max_chars
            marker = (f"\n\n>>> NOTEBOOK TRUNCATED: showing first {max_chars} of "
                      f"{len(body)} chars ({dropped} elided). Read notebook.md in "
                      f"full with read_memory_bank if you need the rest. <<<\n")
            keep = max(0, max_chars - len(marker))
            return body[:keep] + marker
        return body

    def _append_unique_bullet(self, key: str, section_header: str, item: str, max_items: int = 20) -> None:
        """Prepend a de-duplicated bullet to a markdown section."""
        if key not in self._files:
            raise ValueError(f"Unknown memory file: {key}")
        clean_item = str(item or "").strip()
        if not clean_item:
            return

        content = self._files[key].load()
        lines = content.splitlines()
        header_idx = next((i for i, line in enumerate(lines) if line.strip() == section_header), None)
        if header_idx is None:
            if lines and lines[-1].strip():
                lines.append("")
            lines.extend([section_header, ""])
            header_idx = len(lines) - 2

        end_idx = len(lines)
        for idx in range(header_idx + 1, len(lines)):
            if lines[idx].startswith("## "):
                end_idx = idx
                break

        entry = clean_item if clean_item.startswith("- ") else f"- {clean_item}"
        body = [line for line in lines[header_idx + 1 : end_idx] if line.strip()]
        normalized_entry = entry.strip().lower()
        body = [
            line for line in body
            if line.strip().lower() != normalized_entry and not line.strip().startswith("[")
        ]
        body.insert(0, entry)
        body = body[:max_items]
        lines = lines[: header_idx + 1] + body + [""] + lines[end_idx:]
        self._files[key].save("\n".join(lines).strip() + "\n")
    
    def get_file(self, key: str) -> Optional[str]:
        """Get content of a specific memory file."""
        if key in self._files:
            return self._files[key].load()
        return None
    
    def exists(self) -> bool:
        """Check if memory bank directory exists."""
        return self.memory_dir.exists()
    
    def get_summary(self) -> str:
        """
        Get a brief summary of memory bank status.
        
        Returns:
            Summary string for logging/display
        """
        if not self.exists():
            return "Memory Bank: Not initialized"
        
        files_status = []
        for key, mem_file in self._files.items():
            if mem_file.path.exists():
                size = mem_file.path.stat().st_size
                files_status.append(f"  - {key}: {size} bytes")
            else:
                files_status.append(f"  - {key}: missing")
        
        return f"Memory Bank: {self.memory_dir}\n" + "\n".join(files_status)

    def get_digest(self, max_chars: Optional[int] = None) -> str:
        """
        Return a concise, actionable digest of the Memory Bank.

        This is meant to be LLM-friendly: current focus, next step, recent changes,
        completed items, and current blockers/issues (without dumping full files).
        """
        if max_chars is None:
            max_chars = self._resolve_char_budgets()[0]
        if not self.exists():
            return "Memory Bank not initialized."

        def _read(key: str) -> str:
            return (self._files.get(key).load() if key in self._files else "") or ""

        active = _read("active_context")
        progress = _read("progress")
        tech = _read("tech_context")
        patterns = _read("system_patterns")

        def _section(md: str, header: str, max_lines: int = 50) -> str:
            # Extract section body between "## Header" and next "## "
            m = re.search(rf"^##\s+{re.escape(header)}\s*$([\s\S]*?)(?=^##\s+|\Z)", md, flags=re.MULTILINE)
            if not m:
                return ""
            body = m.group(1).strip()
            all_lines = [ln.rstrip() for ln in body.splitlines() if ln.strip()]
            shown = all_lines[:max_lines]
            # No silent drops: tell the agent the list is partial so it knows to
            # read the full file rather than assume it saw everything.
            if len(all_lines) > max_lines:
                shown.append(f"  …(showing latest {max_lines} of {len(all_lines)}; "
                             f"read the full section with read_memory_bank)")
            return "\n".join(shown).strip()

        focus = _section(active, "Current Focus")
        recent = _section(active, "Recent Changes")
        next_steps = _section(active, "Next Steps")
        completed = _section(progress, "Completed Features")
        # "Known Issues / Blockers" merges progress.Known Issues (open bugs) with
        # active_context.Blockers (dep-blocked tasks) — both are framework-synced.
        _issues = _section(progress, "Known Issues")
        _blockers = _section(active, "Blockers")
        issues = "\n".join([s for s in (_blockers, _issues) if s and s != "(none)"]).strip()
        decisions = _section(patterns, "Key Technical Decisions")

        # Pull a few high-signal tech lines (ports/compose paths often end up here)
        tech_lines = []
        for ln in tech.splitlines():
            if any(k in ln.lower() for k in ["docker", "compose", "port", "url", "vite", "express", "postgres", "database_url"]):
                tech_lines.append(ln.strip())
            if len(tech_lines) >= 12:
                break
        tech_block = "\n".join([ln for ln in tech_lines if ln]) or "(see tech_context.md)"

        notebook = self.get_notebook()

        out = "\n".join([
            "MEMORY BANK DIGEST",
            "",
            "── FRAMEWORK-MAINTAINED (read-only; the objective truth) ──",
            "",
            "Current Focus:",
            focus or "(unknown)",
            "",
            "Next Steps:",
            next_steps or "(none)",
            "",
            "Recent Changes:",
            recent or "(none)",
            "",
            "Known Issues / Blockers:",
            issues or "(none)",
            "",
            "Key Decisions:",
            decisions or "(none)",
            "",
            "Completed (recent):",
            completed or "(none)",
            "",
            "Tech Notes (high-signal):",
            tech_block,
            "",
            "── YOUR NOTEBOOK (you own this; write it with update_memory_bank; persists across your wakes) ──",
            "",
            notebook or "(empty — record decisions/gotchas/next-steps your future wakes will need)",
        ]).strip() + "\n"

        if len(out) > max_chars:
            dropped = len(out) - max_chars
            marker = (f"\n\n>>> DIGEST TRUNCATED: showing first {max_chars} of "
                      f"{len(out)} chars ({dropped} elided). Read the relevant "
                      f"memory-bank file in full with read_memory_bank. <<<\n")
            keep = max(0, max_chars - len(marker))
            return out[:keep] + marker
        return out

