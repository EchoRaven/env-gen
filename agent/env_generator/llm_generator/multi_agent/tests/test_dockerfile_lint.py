"""Unit tests for the post-generation Dockerfile lint module.

Covers the two structural guarantees that make ``DOCKER_BUILDKIT=0``
viable for every generated app:

  1. Lone ``# syntax=docker/dockerfile:1`` directives are stripped
     (so the file behaves identically under BuildKit and classic).
  2. BuildKit-only constructs (``RUN --mount=type=...`` and inline
     heredocs in RUN/COPY/ADD) are hard-rejected before the bytes
     ever land in the workspace.

The jira-web ``app/database/Dockerfile`` shipped a real lone-directive
case (round-(d) finding); that exact pattern is exercised here.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Same sys.path bootstrap as agent/tests/test_attempt_4_output_path_gating.py
ROOT = Path(__file__).resolve().parents[4]  # .../agent
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.dockerfile_lint import (  # noqa: E402
    enforce_dockerfile_classic_compat,
    normalize_dockerfile,
    scan_dockerfile,
)


class DockerfileLintTests(unittest.TestCase):
    """Behavioural contract tests for the Dockerfile lint."""

    # ---------- normalize_dockerfile ----------

    def test_strips_lone_syntax_directive(self):
        """jira-web pattern: directive at top, blank line, then FROM."""
        src = (
            "# syntax=docker/dockerfile:1\n"
            "\n"
            "FROM postgres:16-alpine\n"
            "COPY init/*.sql /docker-entrypoint-initdb.d/\n"
            "ENV LANG=C.UTF-8\n"
        )
        out = normalize_dockerfile(src)
        self.assertNotIn("syntax=docker/dockerfile", out)
        self.assertTrue(out.startswith("FROM postgres:16-alpine"))
        # Body lines are preserved verbatim
        self.assertIn("COPY init/*.sql /docker-entrypoint-initdb.d/", out)
        self.assertIn("ENV LANG=C.UTF-8", out)

    def test_preserves_classic_dockerfile(self):
        """A directive-free, classic-builder Dockerfile is unchanged."""
        src = (
            "FROM node:18-alpine AS builder\n"
            "WORKDIR /app\n"
            "COPY app/frontend/package*.json ./\n"
            "RUN npm install\n"
            "COPY app/frontend ./\n"
            "RUN npm run build\n"
            "\n"
            "FROM nginx:alpine\n"
            "COPY --from=builder /app/dist /usr/share/nginx/html\n"
            "EXPOSE 3000\n"
            'CMD ["nginx", "-g", "daemon off;"]\n'
        )
        self.assertEqual(normalize_dockerfile(src), src)
        self.assertEqual(scan_dockerfile(src), [])

    def test_strip_handles_uppercase_and_extra_whitespace(self):
        """Real-world variants: ``# SYNTAX = docker/dockerfile:1.4``."""
        src = "#   SYNTAX = docker/dockerfile:1.4\nFROM alpine\n"
        out = normalize_dockerfile(src)
        self.assertEqual(out, "FROM alpine\n")

    # ---------- scan_dockerfile ----------

    def test_rejects_run_mount_cache(self):
        src = (
            "FROM node:18\n"
            "RUN --mount=type=cache,target=/root/.npm npm ci\n"
        )
        with self.assertRaises(ValueError) as ctx:
            enforce_dockerfile_classic_compat(src, "app/backend/Dockerfile")
        msg = str(ctx.exception)
        self.assertIn("--mount", msg)
        self.assertIn("app/backend/Dockerfile:2", msg)

    def test_rejects_run_mount_secret(self):
        src = (
            "FROM python:3.11\n"
            "RUN --mount=type=secret,id=pip pip install -r req.txt\n"
        )
        violations = scan_dockerfile(src, path="Dockerfile")
        self.assertEqual(len(violations), 1)
        self.assertIn("--mount=type=", violations[0])
        self.assertIn("Dockerfile:2", violations[0])

    def test_rejects_copy_mount(self):
        """COPY --mount is also BuildKit-only and must be caught."""
        src = (
            "FROM alpine\n"
            "COPY --mount=type=bind,source=.,target=/src /src /dst\n"
        )
        violations = scan_dockerfile(src)
        self.assertEqual(len(violations), 1)
        self.assertIn("--mount", violations[0])

    def test_rejects_heredoc_in_run(self):
        src = (
            "FROM debian:bookworm\n"
            "RUN <<EOF\n"
            "apt-get update\n"
            "apt-get install -y curl\n"
            "EOF\n"
        )
        with self.assertRaises(ValueError) as ctx:
            enforce_dockerfile_classic_compat(src, "Dockerfile")
        self.assertIn("heredoc", str(ctx.exception).lower())

    def test_rejects_heredoc_dash_variant(self):
        """The ``<<-EOF`` variant (tab-strip) is equally BuildKit-only."""
        src = "FROM alpine\nRUN <<-EOF\n echo hi\nEOF\n"
        violations = scan_dockerfile(src)
        self.assertEqual(len(violations), 1)
        self.assertIn("heredoc", violations[0].lower())

    # ---------- enforce_dockerfile_classic_compat ----------

    def test_strips_syntax_then_normalizes_correctly(self):
        """Combined: a clean file with a lone directive is normalised
        and accepted; the returned content is the directive-free body."""
        src = (
            "# syntax=docker/dockerfile:1\n"
            "FROM postgres:16-alpine\n"
            "COPY init/*.sql /docker-entrypoint-initdb.d/\n"
        )
        out = enforce_dockerfile_classic_compat(src, "app/database/Dockerfile")
        self.assertFalse(out.startswith("#"))
        self.assertTrue(out.startswith("FROM postgres:16-alpine"))
        self.assertNotIn("syntax=docker", out)

    def test_directive_plus_buildkit_construct_still_rejected(self):
        """Stripping the directive does NOT silently legalise a
        BuildKit-only RUN below it."""
        src = (
            "# syntax=docker/dockerfile:1\n"
            "FROM node:18\n"
            "RUN --mount=type=cache,target=/root/.npm npm ci\n"
        )
        with self.assertRaises(ValueError):
            enforce_dockerfile_classic_compat(src, "Dockerfile")

    def test_empty_content_is_noop(self):
        self.assertEqual(normalize_dockerfile(""), "")
        self.assertEqual(scan_dockerfile(""), [])
        self.assertEqual(enforce_dockerfile_classic_compat("", "Dockerfile"), "")


if __name__ == "__main__":
    unittest.main()
