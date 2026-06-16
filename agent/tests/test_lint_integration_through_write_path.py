"""R2 round-15 durable guard — integration test for the real
``write_workspace_file`` → ``enforce_dockerfile_classic_compat`` path.

WHY THIS FILE EXISTS
--------------------
``tests/test_dockerfile_lint.py`` (11 unit tests, all green) exercises the
lint module's pure surface — ``normalize_dockerfile``, ``scan_dockerfile``,
``enforce_dockerfile_classic_compat``. But the integration point that
gates EVERY Dockerfile the pipeline emits lives at
``shared.py`` line 249-256 inside ``write_workspace_file``. No test
exercised that REAL path. Consequence: when commit 006261ff used a single
``...`` relative import for ``enforce_dockerfile_classic_compat`` and that
import raised ``ValueError`` under the ``env_generator/llm_generator``-on-
sys.path test invocation, the lint silently went inert in 196 unit tests'
collection environment — and nothing went red.

The cascading ``try / except (ImportError, ValueError)`` in shared.py:36-39
fixes that specific bug, BUT a structural guard is still required: any
future refactor that breaks the import (renamed package, missing dep,
removed sibling) puts us right back in silent-failure territory.

GUARD SHAPE (durable, not bug-specific)
---------------------------------------
This module exercises the FULL production code path end-to-end:

  1. Import ``write_workspace_file`` via the canonical production package
     path ``env_generator.llm_generator.tools.canonical_file_tools.shared``.
     If the 3-dot relative import in shared.py is broken under prod
     sys.path, this file fails AT COLLECTION TIME with ImportError →
     CI red. Not silently skipped.

  2. Drive a real ``Workspace`` rooted at ``tempfile.mkdtemp()`` and call
     ``write_workspace_file(workspace, "Dockerfile", <buildkit-content>)``.
     Assert behaviour on the ``ToolResult`` AND on on-disk bytes — both
     legs of the contract must hold.

  3. Additionally assert that
     ``shared.enforce_dockerfile_classic_compat is not None`` and points
     to the real callable, so a future refactor that replaces the import
     with a ``None`` stub (or a try/except that swallows the import error)
     can't pass.

  4. A second test class re-imports via the TEST sys.path pattern
     (``tools.canonical_file_tools.shared``), so the fallback leg in
     shared.py is also continuously verified. Bug-history: the
     round-11 regression broke this leg specifically; without an
     explicit assertion, a future "cleanup" of the fallback branch
     would re-introduce the silent-failure window.

R2 ask: "补一个 durable guard, 关掉这个 CLASS". The integration tests
here exercise the real production code path so that any liveness
regression (broken import, missing dep, refactor that bypasses the
chokepoint) immediately surfaces — not just the specific 006261ff bug.
"""

from __future__ import annotations

import importlib
import sys
import tempfile
import unittest
from pathlib import Path

# === sys.path bootstrap ===
# CRITICAL: put agent/ on sys.path BEFORE env_generator/llm_generator/.
# This makes the canonical fully-qualified package name
# ``env_generator.llm_generator.tools.canonical_file_tools.shared``
# importable — which is what production uses. The 3-dot relative
# ``from ...multi_agent.dockerfile_lint import ...`` in shared.py
# only resolves correctly under THIS sys.path shape, so importing via
# this path verifies the production import survives.
#
# We ALSO append env_generator/llm_generator/ at the END so the
# secondary ``TestLintIntegrationFallbackImportPath`` class below can
# exercise the ``tools.canonical_file_tools.shared`` truncated form
# (the fallback branch in shared.py's cascading try/except).
ROOT = Path(__file__).resolve().parents[1]  # .../agent
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# Append (not insert) so the production-path import resolves the canonical
# full package name first; the truncated-path module is only loadable when
# explicitly importing ``tools.canonical_file_tools.shared``.
if str(LLM_DIR) not in sys.path:
    sys.path.append(str(LLM_DIR))


# === Production-path import (3-dot relative leg in shared.py) ===
# This single line is the load-bearing liveness check. If shared.py's
# Dockerfile-lint import is broken under the prod sys.path shape, this
# import errors and the entire test module fails to collect → CI red.
from env_generator.llm_generator.tools.canonical_file_tools import (  # noqa: E402
    shared as prod_shared,
)
from env_generator.llm_generator.workspace import Workspace  # noqa: E402


class TestLintIntegrationThroughWritePath(unittest.TestCase):
    """IT1-IT5 — drive ``write_workspace_file`` end-to-end and assert
    the Dockerfile lint actually fires on the real path."""

    def setUp(self) -> None:
        # Real Workspace rooted at a fresh temp dir per test — no mocks,
        # no in-memory shim. The on-disk state is the source of truth.
        self._tmp = tempfile.mkdtemp(prefix="lint_integration_")
        self.workspace = Workspace(self._tmp)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    # ---------- IT5 (liveness) — checked first so failure is loud ----------

    def test_IT5_lint_symbol_is_bound_in_shared_module(self):
        """Load-bearing liveness: shared.py must actually have the lint
        function bound (not None, not a stub). If a future refactor
        replaces the cascading try/except with one that silently
        swallows ImportError, this assertion goes red immediately
        instead of letting the lint go inert."""
        self.assertTrue(
            hasattr(prod_shared, "enforce_dockerfile_classic_compat"),
            "shared.py must expose enforce_dockerfile_classic_compat — "
            "the cascading import at shared.py:36-39 is the load-bearing "
            "binding that integrates the Dockerfile lint into "
            "write_workspace_file. If this name is missing, the lint "
            "is inert and every Dockerfile write silently bypasses "
            "classic-builder compatibility checks.",
        )
        self.assertIsNotNone(prod_shared.enforce_dockerfile_classic_compat)
        self.assertTrue(callable(prod_shared.enforce_dockerfile_classic_compat))

    # ---------- IT1 — syntax directive stripped end-to-end ----------

    def test_IT1_syntax_directive_stripped_on_disk(self):
        """A Dockerfile with a lone ``# syntax=docker/dockerfile:1``
        directive must be written WITHOUT the directive. The pipeline
        relies on this so DOCKER_BUILDKIT=0 stays viable per-app.

        End-to-end assertion: read the bytes back from disk and confirm
        normalisation happened along the write path (not just that
        ``enforce_dockerfile_classic_compat`` would have returned the
        normalised content if called)."""
        buildkit_content = (
            "# syntax=docker/dockerfile:1\n"
            "FROM alpine\n"
            "RUN apk add curl\n"
        )
        result = prod_shared.write_workspace_file(
            self.workspace, "Dockerfile", buildkit_content
        )
        self.assertTrue(
            result.success,
            f"write should succeed (directive is normalised, not rejected); "
            f"got error: {result.error_message}",
        )

        on_disk = (Path(self._tmp) / "Dockerfile").read_text(encoding="utf-8")
        self.assertNotIn(
            "syntax=docker/dockerfile",
            on_disk,
            "Lone # syntax directive must be stripped before bytes hit disk. "
            "If this assertion fails, the lint integration at shared.py:249-256 "
            "is not firing on the real write path.",
        )
        self.assertTrue(
            on_disk.startswith("FROM alpine"),
            f"Normalised content should start with FROM, got: {on_disk[:80]!r}",
        )
        # Body preserved verbatim after the strip.
        self.assertIn("RUN apk add curl", on_disk)

    # ---------- IT2 — RUN --mount rejected, file NOT created ----------

    def test_IT2_run_mount_rejected_returns_error_and_leaves_no_file(self):
        """BuildKit-only ``RUN --mount=type=cache,...`` must be hard-rejected.
        The write must return ``ToolResult(success=False, ...)`` with an
        error mentioning ``--mount=type=``, AND the file must NOT exist on
        disk (the gate is supposed to fire BEFORE permanent state changes,
        but even if the atomic-write happened, the function unlinks on
        lint failure — assert both)."""
        buildkit_content = (
            "FROM alpine\n"
            "RUN --mount=type=cache,target=/root/.cache apk add curl\n"
        )
        result = prod_shared.write_workspace_file(
            self.workspace, "Dockerfile", buildkit_content
        )
        self.assertFalse(
            result.success,
            f"BuildKit --mount must be rejected; got success=True. "
            f"This means enforce_dockerfile_classic_compat did NOT fire — "
            f"the integration point at shared.py:249-256 is dead.",
        )
        self.assertIsNotNone(result.error_message)
        # Substring chosen to match the ValueError message emitted by
        # ``enforce_dockerfile_classic_compat`` — pins the error to the
        # lint module (not a generic write failure).
        self.assertIn("--mount=type=", result.error_message)
        # File must not be left dangling.
        self.assertFalse(
            (Path(self._tmp) / "Dockerfile").exists(),
            "Rejected Dockerfile write must not leave a partial file on disk. "
            "shared.py:275-279 explicitly unlinks new files on lint failure; "
            "if this assertion fails the lint is firing but the cleanup is broken.",
        )

    # ---------- IT3 — heredoc rejected ----------

    def test_IT3_heredoc_in_run_rejected_with_clear_error(self):
        """BuildKit-only heredoc bodies (``RUN <<EOF ... EOF``) must be
        hard-rejected with an error mentioning ``heredoc`` so the agent
        can act on the message."""
        buildkit_content = (
            "FROM alpine\n"
            "RUN <<EOF\n"
            "echo hi\n"
            "EOF\n"
        )
        result = prod_shared.write_workspace_file(
            self.workspace, "Dockerfile", buildkit_content
        )
        self.assertFalse(
            result.success,
            f"BuildKit heredoc must be rejected; got success=True. "
            f"Error message would have been: {result.error_message!r}",
        )
        self.assertIsNotNone(result.error_message)
        self.assertIn("heredoc", result.error_message.lower())
        self.assertFalse((Path(self._tmp) / "Dockerfile").exists())

    # ---------- IT4 — non-Dockerfile paths are NOT lint-gated ----------

    def test_IT4_non_dockerfile_path_is_not_dockerfile_lint_gated(self):
        """The Dockerfile lint must be SCOPED to Dockerfiles. Writing
        any other file (here: a Python module) must NOT trigger the
        Dockerfile classic-compat lint. Negative coverage — pins the
        ``file_path_resolved.name == "Dockerfile" or .suffix ==
        ".dockerfile"`` predicate at shared.py:249. If someone broadens
        that predicate by mistake, this test catches it.

        Content includes a ``RUN --mount=type=cache`` STRING (as part of
        Python source). If the lint were over-applied, this would be
        rejected. It must succeed."""
        py_content = (
            '"""Backend API stub."""\n'
            "# Sample comment containing the literal string\n"
            "# RUN --mount=type=cache,target=/root/.cache apk add curl\n"
            "# — present to confirm the lint does NOT scan non-Dockerfiles.\n"
            "def hello():\n"
            "    return 'hi'\n"
        )
        result = prod_shared.write_workspace_file(
            self.workspace, "app/backend/api.py", py_content
        )
        self.assertTrue(
            result.success,
            f"Writing app/backend/api.py must succeed — the Dockerfile lint "
            f"must not apply to .py files. Got error: {result.error_message}",
        )
        # File exists and content was preserved (no normalisation applied).
        on_disk_path = Path(self._tmp) / "app" / "backend" / "api.py"
        self.assertTrue(on_disk_path.exists())
        on_disk = on_disk_path.read_text(encoding="utf-8")
        # Critical: the ``--mount=type=cache`` string is preserved — proof
        # the Dockerfile lint did not touch this file.
        self.assertIn("--mount=type=cache", on_disk)
        self.assertIn("def hello():", on_disk)


class TestLintIntegrationFallbackImportPath(unittest.TestCase):
    """Independent leg — exercise the FALLBACK import path in shared.py
    (``from multi_agent.dockerfile_lint import ...``) by importing the
    same shared module via the truncated ``tools.canonical_file_tools.shared``
    name. Pins shared.py:38-39 so a future "cleanup" of the fallback
    branch can't silently re-introduce the round-11 regression for the
    test-time sys.path shape.

    NB: under pytest's default sys.path manipulation, importing the
    fully-qualified ``env_generator.llm_generator.tools.canonical_file_tools.shared``
    and then ALSO importing ``tools.canonical_file_tools.shared`` creates
    TWO module objects (different package qualifications, same file).
    Both must successfully bind ``enforce_dockerfile_classic_compat`` —
    that's the contract this class enforces."""

    def test_fallback_import_path_also_binds_lint(self):
        """Force-load the module under its truncated package name and
        assert the fallback ``except (ImportError, ValueError)`` branch
        resolved the lint function. If shared.py:38-39 is ever removed
        or weakened, this test goes red."""
        # Clear any cached truncated-path module so importlib actually
        # executes the import (and hits the cascading try/except).
        sys.modules.pop("tools.canonical_file_tools.shared", None)
        try:
            test_shared = importlib.import_module(
                "tools.canonical_file_tools.shared"
            )
        except ImportError as exc:  # pragma: no cover — diagnostic
            self.fail(
                f"shared.py must be importable under the truncated "
                f"`tools.canonical_file_tools.shared` package name "
                f"(env_generator/llm_generator on sys.path). This is the "
                f"invocation pattern used by `pytest env_generator/...`. "
                f"ImportError: {exc}. If this fails, the round-11 "
                f"regression class (silent inert lint under unit-test "
                f"sys.path) is back."
            )
        self.assertTrue(
            hasattr(test_shared, "enforce_dockerfile_classic_compat"),
            "Truncated-path import of shared.py must still bind "
            "enforce_dockerfile_classic_compat. The fallback at "
            "shared.py:38-39 is the only thing making this work — if "
            "this assertion fails, the fallback branch is broken.",
        )
        self.assertIsNotNone(test_shared.enforce_dockerfile_classic_compat)
        self.assertTrue(callable(test_shared.enforce_dockerfile_classic_compat))

    def test_fallback_path_lint_actually_rejects_buildkit_content(self):
        """End-to-end through the FALLBACK-imported shared module:
        write a BuildKit Dockerfile and assert it is rejected. Pins the
        whole pipeline (not just the symbol binding) under the truncated
        package name."""
        sys.modules.pop("tools.canonical_file_tools.shared", None)
        test_shared = importlib.import_module(
            "tools.canonical_file_tools.shared"
        )
        from workspace import Workspace as TestWorkspace  # truncated path

        tmp = tempfile.mkdtemp(prefix="lint_integration_fallback_")
        try:
            ws = TestWorkspace(tmp)
            result = test_shared.write_workspace_file(
                ws,
                "Dockerfile",
                "FROM alpine\nRUN --mount=type=secret,id=foo apk add curl\n",
            )
            self.assertFalse(
                result.success,
                "Fallback-path write must also reject BuildKit content. "
                "If success=True, the lint is bound but not wired into "
                "write_workspace_file — a different kind of inert-lint "
                "regression.",
            )
            self.assertIn("--mount=type=", result.error_message)
            self.assertFalse((Path(tmp) / "Dockerfile").exists())
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
