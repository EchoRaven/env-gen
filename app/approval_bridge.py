"""Env Forge ↔ approval-gate bridge.

Reads/sets a generation's per-env approval mode and lists/decides approval
requests by reusing the ENGINE's approval module against the env's hub dir
(``<generated_dir>/shared/hubs``). Mirrors ``chat_bridge``: the engine root is
added to ``sys.path`` lazily on first use, so the Env Forge backend doesn't hard-
depend on the engine being importable at startup.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Engine package root: <repo>/agent (this file is <repo>/app/approval_bridge.py).
_ENGINE_ROOT = str(Path(__file__).resolve().parents[1] / "agent")


class ApprovalBridgeError(RuntimeError):
    """A user-facing problem (no generated dir / unknown request / bad mode)."""


def _approval_mod():
    if _ENGINE_ROOT not in sys.path:
        sys.path.insert(0, _ENGINE_ROOT)
    from env_generator.llm_generator.multi_agent.runtime import approval
    return approval


def _store(generated_dir: str) -> Path:
    if not generated_dir:
        raise ApprovalBridgeError("environment has no generated_dir yet")
    return Path(generated_dir) / "shared" / "hubs"


def get_mode(generated_dir: str) -> Dict[str, Any]:
    """Current approval config (defaults to auto when nothing is set yet)."""
    if not generated_dir:
        return {"mode": "auto", "timeout_sec": None}
    A = _approval_mod()
    store = _store(generated_dir)
    cfg = A.read_config(store) if store.is_dir() else {}
    return {"mode": str(cfg.get("mode") or "auto"), "timeout_sec": cfg.get("timeout_sec")}


def set_mode(generated_dir: str, mode: str) -> Dict[str, Any]:
    if mode not in ("auto", "ask"):
        raise ApprovalBridgeError("mode must be 'auto' or 'ask'")
    A = _approval_mod()
    cfg = A.write_config(_store(generated_dir), mode=mode)  # write_config mkdirs the hub store
    return {"mode": cfg.get("mode"), "timeout_sec": cfg.get("timeout_sec")}


def list_requests(generated_dir: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
    if not generated_dir:
        return []
    A = _approval_mod()
    store = _store(generated_dir)
    if not store.is_dir():
        return []
    return A.list_requests(store, status=status)


def decide(generated_dir: str, req_id: str, approve: bool, feedback: str, by: str) -> Dict[str, Any]:
    A = _approval_mod()
    rec = A.record_decision(_store(generated_dir), req_id, approve=approve,
                            feedback=feedback, decided_by=by)
    if rec is None:
        raise ApprovalBridgeError("approval request not found or already decided")
    return rec
