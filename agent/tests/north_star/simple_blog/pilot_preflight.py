"""Pilot interpreter preflight — D2 hard gate.

Purpose
-------
R1 round-14 finding: ``runner.py`` does ``import requests`` at module top
level. If the interpreter ``pilot_driver`` invokes for worker processes
lacks ``requests`` (or ``classifier``, or ``runner``), the chain
``from tests.north_star.simple_blog.runner import run_app`` raises
``ImportError``, ``run_app`` is unreachable, and the driver goes fully
inert — every arm appears to fixture-fail with no ``Verdict`` written to
``PILOT_VERDICT_SINK``, silently undercounting ITT.

This preflight subprocess-shells the EXACT interpreter path that workers
will use and chains every required import. ANY ``ImportError`` aborts the
driver before docker is touched.

Contract
--------

::

  python pilot_preflight.py --interpreter /path/to/python
  python pilot_preflight.py                      # uses $PILOT_PYTHON, then sys.executable

Exit codes:

  0  — every required module imported AND provider API key env var is set
  2  — at least one required import failed (stderr names the module)
  3  — provider API key env var is missing or empty (stderr names env var + provider)
  4  — other error (argument / env error, interpreter not found or not executable)

When invoked as a library: ``run_preflight(interpreter: str) -> None``
raises ``PreflightError`` on failure with a single-line ``str(exc)`` that
names the interpreter path + the first missing module.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

# Required modules. Tuples of (import-statement, human-readable label) so the
# error message can name the offender even if Python's traceback is truncated.
REQUIRED_IMPORTS: List[Tuple[str, str]] = [
    ("import requests", "requests"),
    ("from tests.north_star.simple_blog.runner import run_app", "runner.run_app"),
    ("from tests.north_star.simple_blog.runner import teardown", "runner.teardown"),
    (
        "from tests.north_star.simple_blog.runner import get_last_failure_context",
        "runner.get_last_failure_context",
    ),
    (
        "from tests.north_star.simple_blog.runner import get_last_verdict",
        "runner.get_last_verdict",
    ),
    ("from classifier import FailureContext", "classifier.FailureContext"),
    ("from classifier import classify", "classifier.classify"),
    ("from classifier import compute_itt_delta", "classifier.compute_itt_delta"),
    (
        "from classifier import synthesize_pass_verdict",
        "classifier.synthesize_pass_verdict",
    ),
    ("from classifier import append_to_sink", "classifier.append_to_sink"),
]

# ``tests/north_star`` is the directory containing ``classifier.py`` as a
# top-level module (not a package). ``conftest.py`` adjusts ``sys.path`` during
# pytest runs; ``pilot_driver`` workers must replicate that explicitly so the
# subprocess test mirrors the worker import shape.
_REPO_ROOT = Path(__file__).resolve().parents[3]  # .../env-gen/agent
_NORTH_STAR_DIR = _REPO_ROOT / "tests" / "north_star"

# Provider -> required API key env var. Mirrors the mapping baked into
# ``env_generator/llm_generator/main.py`` (the runner that actually issues
# HTTP calls). If the env var is unset/empty when the pipeline launches,
# ``main.py`` aborts with a one-line error; the preflight catches it earlier
# so we never spend setup work on a doomed run.
PROVIDER_ENV_VARS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "openai": "OPENAI_API_KEY",
}


class PreflightError(RuntimeError):
    """Raised by ``run_preflight()`` when the interpreter cannot import a
    required module. ``str(exc)`` is a single line: interpreter + module."""


def _resolve_interpreter(cli_value: Optional[str]) -> str:
    """Priority: ``--interpreter`` > ``$PILOT_PYTHON`` > ``sys.executable``.
    Returns absolute path; raises ``SystemExit(4)`` if nothing resolves."""
    candidate = cli_value or os.environ.get("PILOT_PYTHON") or sys.executable
    if not candidate:
        print(
            "preflight: no interpreter resolvable "
            "(pass --interpreter or set PILOT_PYTHON)",
            file=sys.stderr,
        )
        raise SystemExit(4)
    # Reject relative paths — workers may run from any cwd; the pin MUST be
    # absolute or there's no pin at all.
    if not os.path.isabs(candidate):
        which = shutil.which(candidate)
        if which is None:
            print(
                f"preflight: interpreter {candidate!r} not on PATH",
                file=sys.stderr,
            )
            raise SystemExit(4)
        candidate = which
    if not (os.path.isfile(candidate) and os.access(candidate, os.X_OK)):
        print(
            f"preflight: interpreter {candidate!r} not executable",
            file=sys.stderr,
        )
        raise SystemExit(4)
    return candidate


def _check_api_key(provider: str) -> Optional[str]:
    """Return an error message if the provider's API key env var is missing
    or empty; return ``None`` if the key is set and non-empty.

    Caller is expected to map a non-None return to ``SystemExit(3)``.
    """
    env_var = PROVIDER_ENV_VARS.get(provider)
    if env_var is None:
        # argparse already restricts --provider to PROVIDER_ENV_VARS keys, so
        # this branch is unreachable from the CLI; keep it as a guard for
        # library-mode callers that bypass argparse.
        return (
            f"preflight: unknown provider {provider!r} "
            f"(known: {sorted(PROVIDER_ENV_VARS)})"
        )
    value = os.environ.get(env_var)
    if not value:
        return (
            f"preflight: provider {provider!r} requires env var "
            f"{env_var!r} to be set and non-empty (currently "
            f"{'unset' if value is None else 'empty'})"
        )
    return None


def _build_check_script() -> str:
    """Return the ``-c`` script that imports every ``REQUIRED_IMPORTS`` entry
    under a ``sys.path`` that mirrors what ``pilot_driver`` workers see."""
    # ``sys.path`` is prepended in subprocess-side script so ``classifier``
    # (top-level module under ``tests/north_star``) is importable. We also
    # prepend repo root so ``from tests.north_star...`` works.
    lines = [
        "import sys",
        f"sys.path.insert(0, {str(_REPO_ROOT)!r})",
        f"sys.path.insert(0, {str(_NORTH_STAR_DIR)!r})",
    ]
    lines.extend(stmt for stmt, _label in REQUIRED_IMPORTS)
    lines.append("print('preflight-ok')")
    return "; ".join(lines)


_MISSING_MODULE_RE = re.compile(
    r"ModuleNotFoundError:\s*No module named\s*['\"]([^'\"]+)['\"]"
)


def run_preflight(interpreter: str, *, timeout_s: float = 10.0) -> None:
    """Subprocess-shell the pinned interpreter and run the chained imports.

    Raises ``PreflightError`` on any failure. Returns ``None`` on success.

    Caller (``pilot_driver``) is responsible for converting ``PreflightError``
    to ``sys.exit(non-zero)`` — we don't exit here so the function is
    testable.
    """
    if not (
        os.path.isabs(interpreter)
        and os.path.isfile(interpreter)
        and os.access(interpreter, os.X_OK)
    ):
        raise PreflightError(
            f"preflight: interpreter {interpreter!r} not an executable abs path"
        )
    script = _build_check_script()
    try:
        r = subprocess.run(
            [interpreter, "-c", script],
            capture_output=True,
            timeout=timeout_s,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        raise PreflightError(
            f"preflight: interpreter {interpreter!r} hung >{timeout_s}s on import"
        )
    if r.returncode == 0 and "preflight-ok" in r.stdout:
        return
    # Extract the missing module name if Python printed one.
    m = _MISSING_MODULE_RE.search(r.stderr or "")
    missing = m.group(1) if m else "(unparsed — see stderr below)"
    raise PreflightError(
        f"preflight: interpreter {interpreter!r} cannot import "
        f"{missing!r} (rc={r.returncode}). stderr:\n{r.stderr.strip()}"
    )


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--interpreter",
        default=None,
        help=(
            "Absolute path to Python interpreter to verify. Defaults to "
            "$PILOT_PYTHON then sys.executable."
        ),
    )
    p.add_argument(
        "--provider",
        default="anthropic",
        choices=sorted(PROVIDER_ENV_VARS.keys()),
        help=(
            "LLM provider whose API key env var must be set before "
            "generation starts. Default: anthropic. Mapping mirrors "
            "env_generator/llm_generator/main.py."
        ),
    )
    args = p.parse_args(argv)
    interpreter = _resolve_interpreter(args.interpreter)
    try:
        run_preflight(interpreter)
    except PreflightError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    # Imports are healthy — now refuse to green-light generation if the
    # provider's API key env var is unset or empty. This is the NEW exit-3
    # gate; without it, the pipeline would import cleanly and then crash in
    # main.py the moment it tries to read the key.
    key_err = _check_api_key(args.provider)
    if key_err is not None:
        print(key_err, file=sys.stderr)
        return 3
    env_var = PROVIDER_ENV_VARS[args.provider]
    print(
        f"preflight-ok interpreter={interpreter} "
        f"provider={args.provider} env_var={env_var}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
