"""RunHub probe planner — pure functions, no IO.

`plan_probe(endpoint_dict, base_url, example_body=None)` returns either:
  - `ProbePlan(method, url, headers, body)` — ready to execute
  - `ProbeSkip(reason)` — endpoint should not be probed (auth, destructive, draft)

`classify_probe_result(status_code, body_excerpt, auth_required, transport_error)`
returns a `ProbeOutcome(verdict, severity, note)`.

Verdict matrix:
  2xx, 3xx                            -> pass
  401, 403 when auth_required=True    -> pass
  401, 403 when auth_required=False   -> fail (P2)
  404                                 -> fail (P1)  (route not wired)
  4xx (other)                         -> fail (P2)
  5xx                                 -> fail (P1)
  transport_error="timeout"           -> fail (P1)
  transport_error="connection_refused"-> fail (P0)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Union


@dataclass
class ProbePlan:
    method: str
    url: str
    body: Optional[Dict[str, Any]] = None
    headers: Dict[str, str] = field(default_factory=lambda: {"accept": "application/json"})


@dataclass
class ProbeSkip:
    reason: str  # "auth_required" | "destructive" | "not_defined"


@dataclass
class ProbeOutcome:
    verdict: str          # "pass" | "fail"
    severity: str = "P3"  # P0 | P1 | P2 | P3
    note: str = ""


_DESTRUCTIVE = {"DELETE"}


def plan_probe(
    endpoint: Dict[str, Any],
    base_url: str,
    example_body: Optional[Dict[str, Any]] = None,
) -> Union[ProbePlan, ProbeSkip]:
    status = (endpoint.get("status") or "defined")
    if status != "defined":
        return ProbeSkip(reason="not_defined")

    method = (endpoint.get("method") or "GET").upper()
    path = endpoint.get("path") or "/"
    auth_required = bool(endpoint.get("auth_required"))

    if method in _DESTRUCTIVE:
        return ProbeSkip(reason="destructive")

    # POST/PUT/PATCH require auth -> skip; GET still probes (401 will be tolerated at classify).
    if method in ("POST", "PUT", "PATCH") and auth_required:
        return ProbeSkip(reason="auth_required")

    body: Optional[Dict[str, Any]] = None
    if method in ("POST", "PUT", "PATCH"):
        body = example_body if example_body is not None else {}

    url = base_url.rstrip("/") + (path if path.startswith("/") else "/" + path)
    return ProbePlan(method=method, url=url, body=body)


def classify_probe_result(
    status_code: Optional[int],
    body_excerpt: str,
    auth_required: bool,
    transport_error: Optional[str] = None,
    headers: Optional[dict] = None,
) -> ProbeOutcome:
    if transport_error == "connection_refused":
        return ProbeOutcome(verdict="fail", severity="P0",
                            note="connection refused — service not running")
    if transport_error == "timeout":
        return ProbeOutcome(verdict="fail", severity="P1",
                            note="probe timed out")
    if transport_error:
        return ProbeOutcome(verdict="fail", severity="P1",
                            note=f"transport error: {transport_error}")

    if status_code is None:
        return ProbeOutcome(verdict="fail", severity="P1",
                            note="no status code received")
    if 200 <= status_code < 400:
        return ProbeOutcome(verdict="pass")
    if status_code in (401, 403) and auth_required:
        return ProbeOutcome(verdict="pass", note="auth-protected as expected")
    if status_code == 404:
        return ProbeOutcome(verdict="fail", severity="P1",
                            note="route not wired (404 on declared endpoint)")
    # #1001: a 405 on a registered, implemented endpoint is a CONTRACT violation, not an
    # oddity. It fell through to the P2 catch-all below as "unexpected status 405", which is
    # what r162's backend lane was working from while nine open tasks piled up behind it.
    #
    # Two things are wrong with that. The severity buried a delivery blocker underneath the
    # P0s the lane already held; and the note carried no fact, so the task said "reproduce
    # POST … returning 405" instead of showing it.
    #
    # HTTP requires a 405 to carry `Allow:` naming the methods the server DOES accept, which
    # is precisely the missing diagnosis — the app bound some methods for this path and not
    # this one. #1000 preserved that header at capture; this quotes it.
    if status_code == 405:
        _allow = ""
        try:
            for _k, _v in (headers or {}).items():
                if str(_k).lower() == "allow":
                    _allow = str(_v).strip()
                    break
        except Exception:
            _allow = ""
        _note = ("405: the path exists but this METHOD is not bound"
                 + (f" — the app accepts [{_allow}]. Compare that list against the route "
                    f"declaration; the handler is registered somewhere the app never loaded, "
                    f"or is bound under a different method/prefix." if _allow
                    else " (no Allow header returned, which itself violates HTTP)"))
        return ProbeOutcome(verdict="fail", severity="P1", note=_note)
    if 500 <= status_code < 600:
        return ProbeOutcome(verdict="fail", severity="P1",
                            note=f"server error {status_code}")
    return ProbeOutcome(verdict="fail", severity="P2",
                        note=f"unexpected status {status_code}")


__all__ = [
    "ProbePlan", "ProbeSkip", "ProbeOutcome",
    "plan_probe", "classify_probe_result",
]
