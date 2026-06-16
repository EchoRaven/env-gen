"""
Post-generation Dockerfile lint — make ``DOCKER_BUILDKIT=0`` safe by construction.

R2 round-11 directive (Fix A durable companion): every Dockerfile emitted by
the multi-agent pipeline must be classic-builder compatible. Two failure modes
are observed in generated apps and must be removed structurally rather than by
agent discipline:

  * Lone ``# syntax=docker/dockerfile:1`` parser directives at the top of a
    Dockerfile. Harmless under BuildKit, but the classic builder treats the
    line as a comment AND any deferred-upgrade plan that flips
    ``DOCKER_BUILDKIT=0`` loses the directive's effect silently. Stripping
    the directive makes the file's semantics independent of the build engine.

  * BuildKit-only RUN/COPY ``--mount=type=...`` flags and inline heredoc
    (``<<EOF`` / ``<<-EOF``) bodies. These hard-fail the classic builder.
    We reject rather than rewrite because the intent is structural
    (BuildKit-only) and any "fix" would change the build's caching or
    secret-handling semantics in ways the agent did not approve.

Integration point: ``write_workspace_file`` in
``llm_generator/tools/canonical_file_tools/shared.py`` (around line 230,
right before ``_atomic_write_text``). Gating Dockerfile writes here means
EVERY agent + EVERY tool path that ends in a Dockerfile write is covered
in one place — no per-agent prompt to maintain, no missed code path.

The module is stdlib-only by design so it can be imported from any layer
without dragging extra deps into the file-tools surface.
"""

from __future__ import annotations

import re
from typing import List

_SYNTAX_DIRECTIVE_RE = re.compile(
    r"^\s*#\s*syntax\s*=\s*docker/dockerfile:[^\r\n]*\r?\n?",
    re.IGNORECASE,
)
_RUN_OR_COPY_MOUNT_RE = re.compile(
    r"^\s*(?:RUN|COPY)\b[^\n]*--mount\s*=\s*type\s*=",
    re.IGNORECASE | re.MULTILINE,
)
_HEREDOC_IN_INSTRUCTION_RE = re.compile(
    r"^\s*(?:RUN|COPY|ADD)\b[^\n]*<<-?\s*[\"']?[A-Za-z_][A-Za-z0-9_]*",
    re.IGNORECASE | re.MULTILINE,
)


def normalize_dockerfile(content: str) -> str:
    """Strip lone ``# syntax=docker/dockerfile:...`` parser directives.

    Parser directives must appear before any other content (including
    comments) to take effect; once stripped, the rest of the file is a
    plain Dockerfile that behaves identically under both BuildKit and
    the classic builder. Only directives at the very top of the file
    are removed — a stray ``# syntax=`` deeper down is already inert
    and left untouched so the lint stays minimal.
    """
    if not content:
        return content
    stripped = content
    while True:
        match = _SYNTAX_DIRECTIVE_RE.match(stripped)
        if not match:
            if stripped.startswith("\n"):
                stripped = stripped.lstrip("\n")
                continue
            break
        stripped = stripped[match.end():]
    return stripped


def scan_dockerfile(content: str, path: str = "Dockerfile") -> List[str]:
    """Return a list of BuildKit-only construct violations (empty if clean).

    Each violation is a human-readable string with the offending line
    number and a short reason — suitable for embedding in a ``ValueError``
    or a tool error message that the agent can act on.
    """
    if not content:
        return []
    violations: List[str] = []

    for match in _RUN_OR_COPY_MOUNT_RE.finditer(content):
        line_no = content.count("\n", 0, match.start()) + 1
        violations.append(
            f"{path}:{line_no}: BuildKit-only `--mount=type=...` on RUN/COPY "
            "(rejected: classic builder cannot execute this)."
        )

    for match in _HEREDOC_IN_INSTRUCTION_RE.finditer(content):
        line_no = content.count("\n", 0, match.start()) + 1
        violations.append(
            f"{path}:{line_no}: BuildKit-only heredoc (`<<EOF` / `<<-EOF`) "
            "inside RUN/COPY/ADD (rejected: classic builder cannot parse this)."
        )

    return violations


def enforce_dockerfile_classic_compat(content: str, path: str) -> str:
    """Normalize then scan; raise ``ValueError`` on any remaining violation.

    Returns the normalized content on success. Callers (the file-write
    tool) should substitute the returned content for the agent-provided
    content before committing the bytes to disk, so the file on disk
    matches what the scan validated.
    """
    normalized = normalize_dockerfile(content)
    violations = scan_dockerfile(normalized, path=path)
    if violations:
        raise ValueError(
            "Dockerfile rejected by classic-builder compatibility lint:\n  - "
            + "\n  - ".join(violations)
        )
    return normalized
