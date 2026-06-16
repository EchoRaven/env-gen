"""Human-in-the-loop approval gate (Claude-Code-style permission modes).

A per-env ``approval_mode`` lets a human VERIFY structural pipeline decisions
before they take effect:

  - ``auto`` (default): no approvals — the pipeline runs autonomously (today's
    behavior, byte-for-byte).
  - ``ask``: gated actions PAUSE — the engine writes an approval request to the
    hub, the agent's tool call blocks until a human approves/rejects it in the
    Env Forge UI, then proceeds (approve) or revises (reject + feedback).

Cross-process by design: the ENGINE (this process) writes requests and polls for
decisions; the Env Forge backend (a separate process) reads requests and writes
decisions. Both sides talk through one small on-disk store under the env's hub
dir — no shared memory, no new socket.

EXTENSIBLE: gated action types live in ``GATED_ACTIONS`` as
``(action_type, predicate)`` pairs. Add a type by appending one entry; nothing
else changes. (Milestone creation is orchestrator-internal, not a tool, so it is
gated via a separate orchestrator hook — see ``request_milestone_approval``.)
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# ── store layout ─────────────────────────────────────────────────────────────
_CONFIG_NAME = "approval_config.json"   # {"mode": "auto"|"ask"}
_APPROVALS_DIR = "approvals"            # one <id>.json per request (no list-clobber)

_PENDING = "pending"
_APPROVED = "approved"
_REJECTED = "rejected"
_AUTO = "auto_approved"  # timeout fallback so an unattended run never wedges

# Default wait before auto-approving a pending request (configurable per-env via
# approval_config.json "timeout_sec"). In `ask` mode a human is presumably
# watching; this is only a safety net against a forgotten approval wedging a run.
_DEFAULT_TIMEOUT_SEC = 1800.0
_POLL_SEC = 2.0


def hub_dir(hubs: Any) -> Optional[Path]:
    """The env's hub store dir, from a HubRegistry (engine side)."""
    if hubs is None:
        return None
    d = getattr(hubs, "_store_dir", None)
    if d:
        return Path(d)
    base = getattr(hubs, "base_dir", None)
    return (Path(base) / "shared" / "hubs") if base else None


# ── config (mode) ────────────────────────────────────────────────────────────
def read_config(store: Path) -> Dict[str, Any]:
    try:
        p = Path(store) / _CONFIG_NAME
        if p.is_file():
            return json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception:
        pass
    return {}


def read_mode(store: Optional[Path]) -> str:
    if not store:
        return "auto"
    return str(read_config(store).get("mode") or "auto").lower()


def write_config(store: Path, *, mode: Optional[str] = None,
                 timeout_sec: Optional[float] = None) -> Dict[str, Any]:
    """Set the approval config (used by the Env Forge backend's mode toggle)."""
    store = Path(store)
    store.mkdir(parents=True, exist_ok=True)
    cfg = read_config(store)
    if mode is not None:
        cfg["mode"] = "ask" if str(mode).lower() == "ask" else "auto"
    if timeout_sec is not None:
        cfg["timeout_sec"] = float(timeout_sec)
    (store / _CONFIG_NAME).write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg


# ── gated-action registry (EXTENSIBLE) ───────────────────────────────────────
def _is_task_create(tool: str, args: Dict[str, Any]) -> bool:
    return tool == "workhub_task" and str(args.get("action") or "").lower() == "create"


def _is_gate_create(tool: str, args: Dict[str, Any]) -> bool:
    # "gate" = a validation/acceptance gate: a verification chain.
    return tool == "registryhub_register_verification_chain"


# (action_type, predicate). Append here to gate a new structural action.
GATED_ACTIONS: Tuple[Tuple[str, Callable[[str, Dict[str, Any]], bool]], ...] = (
    ("task", _is_task_create),
    ("gate", _is_gate_create),
)


def classify(tool_name: str, args: Dict[str, Any]) -> Optional[str]:
    """The gated action type for a tool call, or None if not gated."""
    for atype, pred in GATED_ACTIONS:
        try:
            if pred(tool_name, args or {}):
                return atype
        except Exception:
            continue
    return None


def _summary(action_type: str, tool_name: str, args: Dict[str, Any]) -> str:
    a = args or {}
    if action_type == "task":
        return f"Create task: {a.get('title') or '(untitled)'}" + (
            f" → {a.get('assignee')}" if a.get("assignee") else "")
    if action_type == "gate":
        return f"Create gate (verification chain): {a.get('name') or a.get('chain_id') or '(unnamed)'}"
    return f"{action_type}: {tool_name}"


# ── request / decision store (per-request files) ─────────────────────────────
def _approvals_path(store: Path) -> Path:
    p = Path(store) / _APPROVALS_DIR
    p.mkdir(parents=True, exist_ok=True)
    return p


def _write_request(store: Path, rec: Dict[str, Any]) -> None:
    (_approvals_path(store) / f"{rec['id']}.json").write_text(
        json.dumps(rec, indent=2, default=str), encoding="utf-8")


def _read_request(store: Path, req_id: str) -> Optional[Dict[str, Any]]:
    try:
        p = _approvals_path(store) / f"{req_id}.json"
        if p.is_file():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def list_requests(store: Optional[Path], *, status: Optional[str] = None) -> List[Dict[str, Any]]:
    """All approval requests (optionally filtered by status). Used by Env Forge."""
    if not store:
        return []
    out: List[Dict[str, Any]] = []
    d = Path(store) / _APPROVALS_DIR
    if not d.is_dir():
        return []
    for f in d.glob("*.json"):
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if status is None or rec.get("status") == status:
            out.append(rec)
    out.sort(key=lambda r: r.get("created_at", 0))
    return out


def record_decision(store: Path, req_id: str, *, approve: bool,
                    feedback: str = "", decided_by: str = "") -> Optional[Dict[str, Any]]:
    """Approve/reject a pending request (called by the Env Forge backend)."""
    rec = _read_request(Path(store), req_id)
    if not rec or rec.get("status") != _PENDING:
        return None
    rec["status"] = _APPROVED if approve else _REJECTED
    rec["feedback"] = feedback
    rec["decided_by"] = decided_by
    rec["decided_at"] = time.time()
    _write_request(Path(store), rec)
    return rec


# ── the engine-side gate ─────────────────────────────────────────────────────
async def enforce(hubs: Any, agent_id: str, tool_name: str, tool_args: Dict[str, Any],
                  *, poll_sec: float = _POLL_SEC,
                  sleep: Callable[[float], Any] = asyncio.sleep) -> Optional[Any]:
    """Gate a tool call in `ask` mode. Returns:

      - ``None``  → proceed (auto mode, not a gated action, approved, or
                    auto-approved on timeout);
      - ToolResult(success=False, ...) → REJECTED — the message carries the
        reviewer's feedback so the agent revises and retries.

    Best-effort: any store error falls through to ``None`` (never blocks the
    pipeline on an approval-store glitch). ``sleep`` is injectable for tests.
    """
    store = hub_dir(hubs)
    if read_mode(store) != "ask":
        return None
    action_type = classify(tool_name, tool_args)
    if not action_type:
        return None

    req_id = "appr_" + uuid.uuid4().hex[:12]
    rec = {
        "id": req_id,
        "action_type": action_type,
        "tool": tool_name,
        "agent": agent_id,
        "summary": _summary(action_type, tool_name, tool_args),
        "args": tool_args,
        "status": _PENDING,
        "created_at": time.time(),
    }
    try:
        _write_request(store, rec)
    except Exception:
        return None  # store unwritable → don't wedge; proceed

    timeout = float(read_config(store).get("timeout_sec") or _DEFAULT_TIMEOUT_SEC)
    waited = 0.0
    while waited < timeout:
        await sleep(poll_sec)
        waited += poll_sec
        cur = _read_request(store, req_id) or rec
        st = cur.get("status")
        if st == _APPROVED:
            return None
        if st == _REJECTED:
            from utils.tool import ToolResult
            fb = (cur.get("feedback") or "").strip()
            return ToolResult(
                success=False,
                error_message=(
                    f"'{action_type}' action REJECTED by the human reviewer"
                    + (f": {fb}" if fb else ".")
                    + " Revise per the feedback and try again (or proceed differently)."),
            )
    # Timeout → auto-approve so an unattended run never wedges; leave a record.
    try:
        cur = _read_request(store, req_id) or rec
        if cur.get("status") == _PENDING:
            cur["status"] = _AUTO
            cur["decided_at"] = time.time()
            _write_request(store, cur)
    except Exception:
        pass
    return None
