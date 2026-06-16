"""User-defined deliverability gates (Cutover 39).

Each gate is a small typed rule the operator authored via the UI.
``evaluate_gate(gate, reg, workspace)`` is the single entry point used by
``deliver_project_call`` (live monitor server) to extend the deliverability
report with user-provided blockers.

Gate types are a fixed enum -- no arbitrary code execution. To add a new
gate type, register an evaluator function below and add it to
``VALID_GATE_TYPES``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, Optional

_logger = logging.getLogger(__name__)

VALID_GATE_TYPES = {"file_exists", "endpoint_exists", "mcp_tool_exists", "visual_similarity", "code_check", "predicate"}

# Operator-configured environment variable pointing at the YAML allowlist.
# The file MUST live OUTSIDE the agent workspace (e.g. /etc/envgen/...);
# anything under the workspace is agent-writable and would re-open the RCE.
ALLOWLIST_PATH_ENV = "ENVGEN_ALLOWED_CODE_CHECKS_FILE"

# Module-level cache of the allowlist path, pinned at monitor-server startup
# (Phase 0.2 RE-FIX C: defense-in-depth against an in-process attacker who
# might try to repoint the allowlist via ``os.environ`` assignment after the
# trust boundary has already been established). The cache is OPT-IN: until
# ``freeze_allowlist_path()`` is invoked (production startup), the loader
# continues to read the live env var so tests can manipulate it freely.
_ALLOWLIST_PATH_CACHE: Optional[str] = None
_ALLOWLIST_PATH_INITIALIZED: bool = False


def freeze_allowlist_path() -> None:
    """Pin the allowlist path at monitor-server startup. After this
    is called, subsequent env-var changes are ignored -- defense in
    depth against later in-process attackers."""
    global _ALLOWLIST_PATH_CACHE, _ALLOWLIST_PATH_INITIALIZED
    if _ALLOWLIST_PATH_INITIALIZED:
        _logger.warning("freeze_allowlist_path called twice; ignoring")
        return
    _ALLOWLIST_PATH_CACHE = os.environ.get(ALLOWLIST_PATH_ENV, "").strip()
    _ALLOWLIST_PATH_INITIALIZED = True
    _logger.info(
        "allowlist path frozen at: %s",
        _ALLOWLIST_PATH_CACHE or "(unset)",
    )

# Interpreters and shells that, if used as argv[0], would re-enable
# agent-controlled command execution (e.g. ``/bin/sh -c "<payload>"`` or
# ``/usr/bin/python -c "<payload>"``). Even though ``subprocess.run`` is
# called with ``shell=False``, an interpreter at argv[0] still interprets
# its own argument string -- so we must reject these at the allowlist layer.
_INTERPRETER_DENYLIST = frozenset({
    "sh", "bash", "zsh", "ksh", "csh", "tcsh", "dash", "ash", "fish", "rbash",
    "python", "python2", "python3",
    "ruby", "perl", "node", "nodejs", "lua", "php", "deno", "bun",
    "awk", "gawk", "tcl", "tclsh", "wish",
    "powershell", "pwsh",
})


def _is_interpreter(argv0_basename: str) -> bool:
    """Return True if ``argv0_basename`` looks like an interpreter/shell.

    Strips trailing digits and dots so versioned names like ``python3.11``
    or ``python3`` collapse onto ``python``.
    """
    base = (argv0_basename or "").lower()
    # Peel off ".11", ".0", "3", "2.7" style version suffixes one char at a
    # time. The loop terminates because each step removes a character.
    while base and (base[-1].isdigit() or base.endswith(".")):
        base = base[:-1]
    base = base.rstrip(".")
    return base in _INTERPRETER_DENYLIST


def _validate_code_check_argv(argv) -> Optional[str]:
    """Validate the ``command_argv`` of a code_check allowlist entry.

    Returns ``None`` if argv is acceptable, else a human-readable error
    string. Rules:

    * argv must be a non-empty list/tuple of strings.
    * argv[0] must be an absolute path.
    * argv[0]'s basename must not be a known interpreter/shell (so that an
      operator cannot smuggle in ``/bin/sh -c "<agent string>"``).
    * No path component of argv[0] may itself be an interpreter name
      (defense against e.g. ``/opt/python/bin/runner`` shipping a wrapper
      that execs an interpreter).
    """
    if not isinstance(argv, (list, tuple)) or not argv:
        return "argv must be a non-empty list"
    argv0 = argv[0]
    if not isinstance(argv0, str) or not argv0:
        return "argv[0] must be a non-empty string"
    p = Path(argv0)
    if not p.is_absolute():
        return f"argv[0] must be an absolute path (got {argv0!r})"
    if _is_interpreter(p.name):
        return (
            f"argv[0] {argv0!r} is an interpreter; wrap your command in a "
            f"script and invoke the script by absolute path"
        )
    # Reject suspicious shells via path content (e.g. /opt/bin/bash, even if
    # the basename was renamed). Compare lowercased components so casing
    # tricks don't slip past on case-insensitive filesystems.
    for part in p.parts:
        if part.lower() in _INTERPRETER_DENYLIST:
            return f"argv[0] {argv0!r} contains interpreter name in path"
    return None


def validate_gate(gate: dict) -> Optional[str]:
    """Return None if gate is valid, else an error message."""
    t = (gate or {}).get("type")
    if t not in VALID_GATE_TYPES:
        return "unknown gate type"
    if not (gate.get("name") or "").strip():
        return "name required"
    params = gate.get("params") or {}
    if t == "file_exists":
        if not (params.get("path") or "").strip():
            return "params.path required"
    elif t == "endpoint_exists":
        if not (params.get("method") or "").strip():
            return "params.method required"
        if not (params.get("path") or "").strip():
            return "params.path required"
    elif t == "mcp_tool_exists":
        if not (params.get("name") or "").strip():
            return "params.name required"
    elif t == "visual_similarity":
        if not (params.get("page_id") or "").strip():
            return "params.page_id required"
        if "min_similarity" not in params:
            return "params.min_similarity required"
        ms = params.get("min_similarity")
        if not isinstance(ms, (int, float)) or isinstance(ms, bool):
            return "params.min_similarity must be a number"
        if ms < 0.0 or ms > 1.0:
            return "params.min_similarity must be between 0 and 1"
    elif t == "code_check":
        if not (params.get("command") or "").strip():
            return "params.command required"
    return None


def _eval_file_exists(params: dict, reg, workspace: Path) -> dict:
    path_str = (params.get("path") or "").strip()
    # Defense: reject path traversal -- keep within workspace
    if not path_str or ".." in Path(path_str).parts or Path(path_str).is_absolute():
        return {"passed": False, "message": f"invalid path: {path_str!r}"}
    target = Path(workspace) / path_str
    try:
        target_resolved = target.resolve()
        workspace_resolved = Path(workspace).resolve()
        target_resolved.relative_to(workspace_resolved)
    except Exception:
        return {"passed": False, "message": f"invalid path (escapes workspace): {path_str!r}"}
    if target.exists():
        return {"passed": True, "message": f"file exists: {path_str}"}
    return {"passed": False, "message": f"file not found: {path_str}"}


def _norm_path_params(path: str) -> str:
    """Canonicalize BOTH param styles to {param}: ':id' (express/spec style)
    and '{id}' (openapi style) must compare equal — live 2026-06-11: 14
    registered endpoints failed their gates purely on ':id' vs '{id}'."""
    import re as _re
    return _re.sub(r":(\w+)", r"{\1}", path or "")


def _eval_endpoint_exists(params: dict, reg, workspace: Path) -> dict:
    method = (params.get("method") or "").strip().upper()
    path = _norm_path_params((params.get("path") or "").strip())
    # RegistryHub exposes ``get_endpoints()`` which returns a dict keyed by
    # "METHOD PATH". (There is no ``list_endpoints()``.)
    endpoints = {}
    try:
        if hasattr(reg.registryhub, "get_endpoints"):
            endpoints = reg.registryhub.get_endpoints() or {}
        elif hasattr(reg.registryhub, "list_endpoints"):
            endpoints = reg.registryhub.list_endpoints() or {}
    except Exception:
        endpoints = {}
    for ep_id, ep in endpoints.items():
        if not isinstance(ep, dict):
            continue
        if ((ep.get("method") or "").upper() == method
                and _norm_path_params(ep.get("path") or "") == path):
            status = (ep.get("status") or "").lower()
            if status == "deprecated":
                return {"passed": False, "message": f"endpoint {method} {path} is deprecated"}
            return {"passed": True, "message": f"endpoint registered: {method} {path}"}
    return {"passed": False, "message": f"endpoint not registered: {method} {path}"}


def _eval_mcp_tool_exists(params: dict, reg, workspace: Path) -> dict:
    name = (params.get("name") or "").strip()
    tools: Dict[str, dict] = {}
    try:
        mcp = getattr(reg, "mcp_registry", None)
        if mcp is not None and hasattr(mcp, "get_mcp_tools"):
            tools = mcp.get_mcp_tools() or {}
    except Exception:
        tools = {}
    for tool in tools.values():
        if not isinstance(tool, dict):
            continue
        if tool.get("tool_name") == name or tool.get("name") == name:
            return {"passed": True, "message": f"mcp tool registered: {name}"}
    return {"passed": False, "message": f"mcp tool not registered: {name}"}


def _eval_visual_similarity(params: dict, reg, workspace: Path) -> dict:
    page_id = (params.get("page_id") or "").strip()
    min_sim = float(params.get("min_similarity") or 0.0)
    gate = getattr(reg, "gate_registry", None)
    review = gate.get_visual_review(page_id) if gate is not None else None
    if not review:
        return {"passed": False, "message": f"no visual review for page {page_id}"}
    metadata = review.get("metadata") or {}
    # similarity_score may live on the review record directly or, more
    # commonly, on the latest entry in ``metadata.review_history``.
    score = metadata.get("similarity_score")
    if score is None:
        score = review.get("similarity_score")
    if score is None:
        history = (
            metadata.get("review_history")
            or review.get("review_history")
            or metadata.get("history")
            or review.get("history")
            or []
        )
        for entry in reversed(history):
            if isinstance(entry, dict) and entry.get("similarity_score") is not None:
                score = entry["similarity_score"]
                break
    if score is None:
        return {"passed": False, "message": f"visual review for {page_id} has no similarity_score"}
    if score >= min_sim:
        return {"passed": True, "message": f"similarity {score} >= {min_sim}"}
    return {"passed": False, "message": f"similarity {score} < {min_sim}"}


def _load_allowed_code_checks(workspace: Path) -> dict:
    """Load the operator-managed code_check allowlist.

    The allowlist path is read from the environment variable
    :data:`ALLOWLIST_PATH_ENV` (``ENVGEN_ALLOWED_CODE_CHECKS_FILE``). The
    file MUST live OUTSIDE any agent workspace (typically under
    ``/etc/envgen/`` or another operator-owned directory); the ``workspace``
    argument is retained only so the signature stays stable for callers and
    so the runner can still pin ``cwd=workspace`` for subprocess execution.

    Returns a dict mapping ``key -> entry``. ``entry`` is a dict that MUST
    contain:

    * ``command_argv``: ``list[str]`` -- the argv to execute (no shell).
    * ``timeout_seconds``: ``int`` in [1, 600].

    Optional:

    * ``description``: human-readable description (ignored by the runner).
    * ``allowed_in_cwd_pattern``: regex (reserved for future use).

    Fail-closed contract: returns ``{}`` (no checks runnable) when

    * ``ENVGEN_ALLOWED_CODE_CHECKS_FILE`` is unset or empty;
    * the configured path is missing or is not a regular file;
    * the file is unreadable or malformed YAML;
    * the parsed document is not a mapping.

    Individual entries that fail validation are silently dropped so the gate
    cleanly rejects them with "key not in allowlist".
    """
    import yaml

    # Phase 0.2 RE-FIX C: once ``freeze_allowlist_path()`` has been called
    # (production monitor-server startup), the cached value wins -- a later
    # in-process attacker cannot repoint the allowlist by mutating
    # ``os.environ``. Pre-freeze (e.g. during unit tests) we still read the
    # live env var so per-test fixtures keep working.
    if _ALLOWLIST_PATH_INITIALIZED:
        path_str = _ALLOWLIST_PATH_CACHE or ""
    else:
        path_str = os.environ.get(ALLOWLIST_PATH_ENV, "").strip()
    if not path_str:
        # FAIL-CLOSED: operator never wired up an allowlist path -> no
        # code_check is ever runnable. This is intentional. Note the
        # ``workspace`` argument is unused for path resolution and kept
        # only for caller-signature stability.
        del workspace  # documents that the parameter is intentionally unused here
        return {}
    path = Path(path_str)
    if not path.exists() or not path.is_file():
        # FAIL-CLOSED on missing/non-regular file (broken symlink, dir, etc.).
        return {}
    try:
        text = path.read_text()
    except (FileNotFoundError, OSError):
        return {}
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return {}
    if not isinstance(data, dict):
        return {}

    valid: dict = {}
    for key, entry in data.items():
        if not isinstance(key, str) or not key.strip():
            continue
        if not isinstance(entry, dict):
            continue
        argv = entry.get("command_argv")
        if not isinstance(argv, list) or not argv:
            continue
        if not all(isinstance(x, str) for x in argv):
            continue
        # Argv hardening: argv[0] must be an absolute path to a non-interpreter
        # binary (Phase 0.2 fix #2). An operator allowlist entry like
        # ``["/bin/sh", "-c", "<agent string>"]`` is silently dropped here.
        argv_err = _validate_code_check_argv(argv)
        if argv_err is not None:
            _logger.warning(
                "code_check allowlist entry %r dropped: %s", key, argv_err
            )
            continue
        timeout = entry.get("timeout_seconds")
        if not isinstance(timeout, int) or isinstance(timeout, bool):
            continue
        if timeout < 1 or timeout > 600:
            continue
        valid[key] = {
            "command_argv": list(argv),
            "timeout_seconds": int(timeout),
            "description": entry.get("description"),
            "allowed_in_cwd_pattern": entry.get("allowed_in_cwd_pattern"),
        }
    return valid


def _eval_predicate(params: dict, reg, workspace: Path) -> dict:
    """Verifier-authored acceptance predicate as a deliverability gate.

    A predicate passes iff (a) a SUCCESSFUL validation run exists in RunHub
    (the deterministic api_smoke suite — boot, auth, per-endpoint probes,
    response shapes, write persistence — is the enforcement evidence), and
    (b) every /api/... path the predicate references is a registered,
    non-deprecated endpoint. This makes each named acceptance criterion an
    individually-visible line item backed by enforced runtime checks."""
    import re as _re
    desc = str(params.get("description") or "").strip()
    runs = []
    try:
        runhub = getattr(reg, "runhub", None)
        if runhub is not None and hasattr(runhub, "list_runs"):
            runs = runhub.list_runs(limit=50) or []
    except Exception:
        runs = []
    ok_run = any(
        str(r.get("status", "")).lower() in ("passed", "success", "succeeded", "ok")
        for r in runs if isinstance(r, dict))
    if not ok_run:
        return {"passed": False,
                "message": f"predicate '{desc[:80]}': no successful validation run recorded yet"}
    missing = []
    try:
        endpoints = reg.registryhub.get_endpoints() or {}
    except Exception:
        endpoints = {}
    known = {str(ep.get("path")) for ep in endpoints.values() if isinstance(ep, dict)
             and str(ep.get("status", "")).lower() != "deprecated"}
    for path in _re.findall(r"/api/[A-Za-z0-9_{}:/-]+", desc):
        norm = path.rstrip(".,;")
        if norm not in known:
            missing.append(norm)
    if missing:
        return {"passed": False,
                "message": f"predicate '{desc[:60]}': referenced endpoint(s) not registered: {missing}"}
    return {"passed": True,
            "message": f"predicate '{desc[:80]}': validation run passed + referenced endpoints registered"}


def _eval_code_check(params: dict, reg, workspace: Path) -> dict:
    """Run an allowlisted check in the workspace and gate on its result.

    ``params["command"]`` is a KEY (not a shell string) into the operator's
    allowlist file. The path to that file is taken from the environment
    variable ``ENVGEN_ALLOWED_CODE_CHECKS_FILE`` and MUST live outside any
    agent-writable workspace tree. The allowlist maps
    ``key -> {command_argv: list[str], timeout_seconds: int,
    description?: str, allowed_in_cwd_pattern?: regex}``.

    The runner executes ``subprocess.run(argv, shell=False, cwd=workspace,
    timeout=entry["timeout_seconds"], ...)``. Because ``shell=False``, argv
    elements are passed as literal arguments -- shell metacharacters in the
    argv (``$(...)``, ``;``, ``|``, backticks) are NOT interpreted.

    Gating semantics are unchanged from before: pass on (a) exit code matches
    ``expect_exit`` (default 0) and (b) optional ``expect_contains`` substring
    appears in combined stdout+stderr.

    To add a new check an operator authors the allowlist entry and commits the
    YAML; the LLM agent (or any other caller) can only reference existing
    keys -- it cannot smuggle a new command string through the gate.
    """
    import subprocess

    key = (params.get("command") or "").strip()
    if not key:
        return {"passed": False, "message": "params.command required"}

    allowlist = _load_allowed_code_checks(workspace)
    if key not in allowlist:
        return {
            "passed": False,
            "message": (
                f"command {key!r} not in workspace allowlist; "
                f"add to the operator allowlist YAML referenced by "
                f"${ALLOWLIST_PATH_ENV}"
            ),
        }
    entry = allowlist[key]
    argv = entry["command_argv"]
    timeout = entry["timeout_seconds"]

    # Defense in depth: re-validate argv just before exec. If a future
    # refactor weakens ``_load_allowed_code_checks`` (or somebody constructs
    # an allowlist dict in-process), this second gate still refuses to invoke
    # an interpreter/shell or a relative argv[0].
    argv_err = _validate_code_check_argv(argv)
    if argv_err is not None:
        _logger.warning(
            "code_check %r refused at exec time: %s", key, argv_err
        )
        return {
            "passed": False,
            "message": f"command {key!r} failed argv validation: {argv_err}",
            "details": {"command": key, "argv": list(argv)},
        }

    expect_exit = params.get("expect_exit", 0)
    try:
        expect_exit = int(expect_exit)
    except (TypeError, ValueError):
        expect_exit = 0
    expect_contains = (params.get("expect_contains") or "").strip()

    try:
        proc = subprocess.run(
            argv,
            shell=False,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {
            "passed": False,
            "message": f"command timed out after {timeout}s",
            "details": {"command": key, "argv": list(argv), "timeout": timeout},
        }
    except FileNotFoundError as e:
        return {
            "passed": False,
            "message": f"command failed to run: {e}",
            "details": {"command": key, "argv": list(argv)},
        }
    except Exception as e:
        return {"passed": False, "message": f"command failed to run: {e}"}

    combined = (proc.stdout or "") + (proc.stderr or "")
    # Keep details bounded -- gate reports are surfaced in the UI.
    tail = combined[-2000:]
    details = {
        "command": key,
        "argv": list(argv),
        "exit_code": proc.returncode,
        "expected_exit": expect_exit,
        "output_tail": tail,
    }

    if proc.returncode != expect_exit:
        return {
            "passed": False,
            "message": f"exit {proc.returncode} != expected {expect_exit}",
            "details": details,
        }
    if expect_contains and expect_contains not in combined:
        details["expect_contains"] = expect_contains
        return {
            "passed": False,
            "message": f"output missing expected text: {expect_contains!r}",
            "details": details,
        }
    msg = f"command passed (exit {proc.returncode})"
    if expect_contains:
        msg += f", output contains {expect_contains!r}"
    return {"passed": True, "message": msg, "details": details}


_EVALUATORS: Dict[str, Callable[[dict, Any, Path], dict]] = {
    "file_exists": _eval_file_exists,
    "endpoint_exists": _eval_endpoint_exists,
    "mcp_tool_exists": _eval_mcp_tool_exists,
    "visual_similarity": _eval_visual_similarity,
    "code_check": _eval_code_check,
    "predicate": _eval_predicate,
}


def evaluate_gate(gate: dict, reg, workspace: Path) -> dict:
    """Run a gate. Returns ``{passed, message, details?}``."""
    t = (gate or {}).get("type")
    fn = _EVALUATORS.get(t)
    if fn is None:
        return {"passed": False, "message": f"unknown gate type: {t}"}
    params = gate.get("params") or {}
    try:
        return fn(params, reg, workspace)
    except Exception as e:
        return {"passed": False, "message": f"evaluator crashed: {e}"}
