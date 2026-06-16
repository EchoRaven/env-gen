"""Helpers that turn bundled test scripts into ready-to-seed ``user_gate`` dicts.

The env-gen run scripts (``run_facebook.sh``, …) seed ``user_gates`` via
POST ``/api/projects/<pid>/user_gates`` against the live monitor. This
module saves callers from hand-writing the ``code_check`` command line
for each bundled test — they just pick the env + API URL and get back
a gate dict ready to POST.

Example:

    from multi_agent.bundled_tests.gate_templates import oauth_contract_gate
    gate = oauth_contract_gate(env="slack", api_url="http://localhost:8034")
    # → POST .../user_gates with `gate`

The bundled tests themselves live in
``multi_agent/bundled_tests/oauth_contract/test_<env>.py`` and exit
``0`` on full pass / ``1`` on any failure, taking ``<ENV>_API_URL``
as input.
"""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Dict, List, Optional

# Absolute, on-disk root for the bundled OAuth contract tests. Resolved
# at import time so callers get a deterministic command that doesn't
# depend on cwd at gate-evaluation time.
_OAUTH_CONTRACT_DIR: Path = Path(__file__).parent / "oauth_contract"


def list_supported_envs() -> List[str]:
    """Return the sorted list of env names that have a bundled OAuth
    contract test script (``test_<env>.py``)."""
    if not _OAUTH_CONTRACT_DIR.exists():
        return []
    names: List[str] = []
    for f in _OAUTH_CONTRACT_DIR.glob("test_*.py"):
        # test_slack.py → "slack"
        names.append(f.stem[len("test_"):])
    return sorted(names)


def oauth_contract_gate(
    *,
    env: str,
    api_url: str,
    timeout: int = 120,
    python_bin: Optional[str] = None,
) -> Dict:
    """Build a ``user_gate`` dict that runs the OAuth contract test for *env*.

    Parameters
    ----------
    env:
        One of :func:`list_supported_envs` (e.g. ``"slack"``,
        ``"paypal"``, ``"atlassian"``). Raises ``ValueError`` otherwise.
    api_url:
        Base URL of the running env, e.g. ``http://localhost:8034``.
        Injected via the test script's expected env var
        ``<ENV>_API_URL`` (uppercase, with underscores intact).
    timeout:
        Gate-evaluation timeout in seconds. Defaults to ``120``.
    python_bin:
        Python interpreter to run the script with. Defaults to
        ``python3`` (the one on the monitor's PATH at gate-eval time).

    Returns
    -------
    dict
        ``{"name": ..., "type": "code_check", "params": {...}}`` —
        ready to POST to ``/api/projects/<pid>/user_gates``.
    """
    env_name = (env or "").strip().lower()
    if not env_name:
        raise ValueError("env must be non-empty")
    supported = list_supported_envs()
    if env_name not in supported:
        raise ValueError(
            f"No bundled OAuth contract test for env={env_name!r}. "
            f"Supported: {supported}"
        )
    if not api_url or not str(api_url).strip():
        raise ValueError("api_url must be non-empty")

    script = _OAUTH_CONTRACT_DIR / f"test_{env_name}.py"
    if not script.exists():
        raise ValueError(f"Bundled test script missing on disk: {script}")

    py = python_bin or "python3"
    # Env var convention from env-factory: <ENV_UPPER>_API_URL.
    env_var = f"{env_name.upper()}_API_URL"
    # Quote every interpolated value — code_check runs the command via
    # ``subprocess.run(cmd, shell=True)``; an api_url containing a space,
    # quote, semicolon, or backtick would otherwise be parsed by the
    # shell. Same for the script path (may live under a workspace with
    # spaces in the name).
    command = (
        f"{env_var}={shlex.quote(str(api_url))} "
        f"{shlex.quote(py)} {shlex.quote(str(script))}"
    )

    return {
        "name": f"OAuth contract: {env_name}",
        "type": "code_check",
        "params": {
            "command": command,
            "expect_exit": 0,
            "timeout": int(timeout),
        },
    }
