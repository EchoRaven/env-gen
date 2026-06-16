"""Verifier-authored API chain executor (mechanism #48b-v2).

OWNERSHIP (user decision 2026-06-11/12): the VERIFIER owns the chain
DEFINITIONS — it REGISTERS them via the ``registryhub_register_verification_chain``
tool (boundary-validated, normalized on registration; NOT a loose file — round
35: file authoring drifted schema silently). The framework owns ONLY this
deterministic EXECUTOR. There is NO framework fallback chain (user decision):
zero registered chains is an AGENT deliverable gap — run_validation is tool-
blocked and the gate fails with authoring instructions, and the existing
feedback/retry loop drives the verifier to register one. A framework-authored
journey would be app-biased — exactly what the generality principle forbids.

Per-step shape (one registered chain = {name, steps:[...]}):

    {"action": "register", "method": "POST", "path": "/auth/register",
     "body": {"email": "c${rand}@t.io", "password": "Chain123!x"},
     "expect": [200, 201], "save": {"token": "access_token"}}
    {"action": "create", "method": "POST", "path": "/api/posts",
     "auth": "token", "body": {"caption": "chain ${rand}"}, "expect": [201]}

Semantics:
  * ``${rand}`` → one random-ish suffix per execution; ``${var}`` → a value
    saved by an earlier step (string substitution in path and body values).
  * ``save: {"<var>": "<dot.path>"}`` extracts from the step's JSON response.
  * ``auth: "<var>"`` sends ``Authorization: Bearer <value-of-var>``.
  * ``expect`` — list of acceptable status codes; default = any 2xx.
  * verdict per step: expected status → ok; 404/405 (and not expected) →
    ``missing`` (endpoint not built yet — soft); anything else → ``broken``.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from .validation_runner import _http

# Chains live in the REGISTRY (user design 2026-06-12) — registered via the
# registryhub_register_verification_chain tool with boundary validation, not
# written as a loose file (round 35: file authoring drifted schema silently).
CHAINS_STORE_RELPATH = Path("shared") / "hubs" / "registryhub_verification_chains.json"


def normalize_steps(steps: Any) -> "tuple[List[Dict[str, Any]], List[str]]":
    """Normalize step variants → canonical {method, path, body, expect, save,
    auth}. Returns (normalized, errors). SCHEMA TOLERANCE (round 35): accept
    {endpoint: "POST /x", payload: {...}}; PLATFORM-CONTRACT DEFAULTS: auth
    steps auto-save the token, /api/* steps auto-send the bearer."""
    out: List[Dict[str, Any]] = []
    errors: List[str] = []
    for i, st in enumerate(steps or []):
        if not isinstance(st, Mapping):
            errors.append(f"step[{i}] is not an object")
            continue
        st = dict(st)
        if not st.get("path") and st.get("endpoint"):
            parts = str(st["endpoint"]).strip().split(None, 1)
            if len(parts) == 2:
                st.setdefault("method", parts[0])
                st["path"] = parts[1]
            elif parts and parts[0].startswith("/"):
                st["path"] = parts[0]
        if not st.get("body") and isinstance(st.get("payload"), Mapping):
            st["body"] = st["payload"]
        # SCHEMA TOLERANCE (round 42): the verifier wrote body as a JSON STRING
        # ('{"email": "..."}') not an object. _http json.dumps()es it → the
        # backend receives a quoted string literal, not {email,password} → 422
        # "email and password required" → business_chain fails forever. Parse a
        # JSON-string body back to a dict (and a stringified payload likewise).
        for _k in ("body", "payload"):
            _v = st.get(_k)
            if isinstance(_v, str) and _v.strip().startswith("{"):
                try:
                    _parsed = json.loads(_v)
                    if isinstance(_parsed, Mapping):
                        st["body"] = _parsed
                except Exception:
                    pass
        if not (st.get("path") and st.get("method")):
            errors.append(f"step[{i}] lacks method+path (or endpoint='METHOD /path')")
            continue
        pth = str(st["path"]).rstrip("/")
        if pth in ("/auth/register", "/auth/login") and not st.get("save"):
            st["save"] = {"token": "access_token"}
        # AUTH BODY DEFAULT (round 47): an /auth/register|login step with NO body
        # (verifier authored the step from just an endpoint id, body=None) sends an
        # empty request → the framework AS returns 422 "email and password are
        # required" → business_chain fails forever → the milestone can never
        # deliver. The auth round-trip is a PLATFORM invariant (every app mints its
        # token from /auth/* with {email,password}, true regardless of domain), so
        # supply a framework-authored default body — mirrors the default-save above
        # so a body-less auth step can't permanently 422-block the chain.
        if pth in ("/auth/register", "/auth/login") and not (
                isinstance(st.get("body"), Mapping) and st.get("body")):
            _ab: Dict[str, Any] = {"email": "chain_${rand}@example.com",
                                   "password": "Chain123!x"}
            if pth == "/auth/register":
                _ab["name"] = "Chain Tester"
            st["body"] = _ab
        if pth.startswith("/api/") and not st.get("auth"):
            st["auth"] = "token"
        out.append(st)
    # AUTH-FIRST REORDER (round 45): the verifier wrote /api/* steps that use a
    # token BEFORE the /auth/register|login step that mints it → 401 "missing
    # token" → business_chain fails forever. "auth round-trip first" is a
    # PLATFORM invariant (every app's token comes from /auth/*, true regardless
    # of domain), so stably hoist the auth steps to the front — a verifier
    # ordering slip can never 401-block the chain again. Stable sort preserves
    # register-before-login and the relative order of the rest.
    out.sort(key=lambda st: 0 if str(st.get("path", "")).rstrip("/")
             in ("/auth/register", "/auth/login") else 1)
    return out, errors


def load_verifier_chains(project_dir: Any) -> List[Dict[str, Any]]:
    """Chains from the REGISTRY store (written via the registration tool).
    Deterministic file read so the validation runner needs no live hub."""
    path = Path(project_dir) / CHAINS_STORE_RELPATH
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for name, rec in (data or {}).items():
        if name == "_meta" or not isinstance(rec, Mapping):
            continue
        steps, _errs = normalize_steps(rec.get("steps") or [])
        if steps:
            out.append({"name": str(rec.get("name") or name), "steps": steps})
    return out


def _dig(payload: Any, dotted: str) -> Optional[Any]:
    parts = str(dotted).split(".")
    # ENVELOPE TOLERANCE (2026-06-13): the route projector wraps every business
    # response in the canonical {"item": {...}} (single) / {"items": [...]}
    # (list) envelope, but verifier-authored chains save dotted paths against the
    # bare row — e.g. POST /api/posts saves {"post_id": "id"} expecting {id:...},
    # not {item:{id:...}}. When the first segment isn't at the top level, descend
    # once through the canonical wrapper so the save resolves against the row.
    # Otherwise post_id stays unsaved → a later ${post_id} step sends a literal
    # "${post_id}" path param → 422 → the business_chain breaks forever (observed
    # live: POST /api/posts/${post_id}/likes → 422).
    if isinstance(payload, Mapping) and parts and parts[0] not in payload:
        item = payload.get("item")
        items = payload.get("items")
        if isinstance(item, Mapping) and parts[0] in item:
            payload = item
        elif (isinstance(items, list) and items
              and isinstance(items[0], Mapping) and parts[0] in items[0]):
            payload = items[0]
    cur = payload
    for part in parts:
        if isinstance(cur, Mapping) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _subst(value: Any, variables: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        for k, v in variables.items():
            value = value.replace("${" + k + "}", str(v))
        return value
    if isinstance(value, Mapping):
        return {k: _subst(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [_subst(v, variables) for v in value]
    return value


def execute_chain(base: str, chain: Mapping[str, Any]) -> Dict[str, Any]:
    """Run one chain; returns {name, steps: [...], broken: [...]}.
    Deterministic wiring; never raises."""
    variables: Dict[str, str] = {"rand": str(int(time.time() * 1000))[-7:]}
    recorded: List[Dict[str, Any]] = []
    for step in chain.get("steps") or []:
        method = str(step.get("method", "GET")).upper()
        path = str(_subst(step.get("path", ""), variables))
        body = _subst(step.get("body"), variables) if step.get("body") else None
        token = variables.get(str(step.get("auth"))) if step.get("auth") else None
        expect = [int(x) for x in (step.get("expect") or []) if str(x).isdigit()]
        res = _http(method, base + path, token=token, body=body)
        status = res.get("status")
        if expect:
            ok = status in expect
        else:
            ok = bool(status and 200 <= status < 300)
        kind = "ok"
        note = ""
        if not ok:
            note = (res.get("error") or res.get("body_text") or "")[:160]
            kind = "missing" if status in (404, 405) else "broken"
        entry = {"action": str(step.get("action") or path), "method": method,
                 "path": path, "status": status, "ok": ok, "kind": kind,
                 "note": note}
        recorded.append(entry)
        if ok and isinstance(step.get("save"), Mapping):
            try:
                payload = json.loads(res.get("body_text") or "{}")
            except Exception:
                payload = {}
            for var, dotted in step["save"].items():
                val = _dig(payload, dotted)
                if val is not None:
                    variables[str(var)] = str(val)
        if kind == "broken":
            break  # later steps would cascade-fail on missing variables
    broken = [f"{s['method']} {s['path']} → {s['status']} ({s['note']})"
              for s in recorded if s["kind"] == "broken"]
    return {"name": str(chain.get("name") or "chain"), "steps": recorded,
            "broken": broken}


AUTHORING_INSTRUCTIONS = (
    "no verification chains registered — the verifier must REGISTER them via "
    "the registryhub_register_verification_chain tool (one call per chain), "
    "designed from the registered contract + kickoff user_flows. Each step: "
    '{"action", "method", "path", "body" (${rand}/${var} substitution), '
    '"expect": [codes], "save": {"var": "dot.path"}, "auth": "var"}. '
    "Cover at minimum: an auth round-trip and each critical user flow.")


def run_chains(base: str, project_dir: Any,
               business_endpoints: List[Mapping[str, Any]]) -> Dict[str, Any]:
    """Execute the verifier's chains. No chains → the gate FAILS with the
    authoring instructions (agent feedback loop, not framework content)."""
    chains = load_verifier_chains(project_dir)
    if not chains:
        return {"source": "missing", "chains": [],
                "broken": [AUTHORING_INSTRUCTIONS], "total_steps": 0}
    results = [execute_chain(base, ch) for ch in chains]
    broken = [b for r in results for b in r["broken"]]
    total = sum(len(r["steps"]) for r in results)
    # Record pass/fail back onto the registry records (best-effort) — the
    # registry is the single place to see chain health (monitor renders it).
    try:
        from .json_store import JsonStore
        store = JsonStore(Path(project_dir) / CHAINS_STORE_RELPATH)
        for r in results:
            rec = (store.value() or {}).get(r["name"])
            if isinstance(rec, dict):
                rec = {**rec,
                       "status": "passing" if not r["broken"] else "failing",
                       "last_result": {"broken": r["broken"], "steps": r["steps"]},
                       "last_run_at": time.time()}
                store.update(lambda m, _rec=rec, _n=r["name"]: m.set(_n, _rec, "chain_executor"),
                             change_info={"agent": "chain_executor"})
    except Exception:
        pass
    return {"source": "verifier", "chains": results, "broken": broken,
            "total_steps": total}
