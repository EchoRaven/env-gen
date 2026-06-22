"""Verifier-authored API chain executor (mechanism #48b-v2).

OWNERSHIP (user decision 2026-06-11/12): the VERIFIER owns the chain
DEFINITIONS — it REGISTERS them via the ``registryhub_register_verification_chain``
tool (boundary-validated, normalized on registration; NOT a loose file — round
35: file authoring drifted schema silently). The framework owns this deterministic
EXECUTOR and a contract-projected FILL-IN default (``synthesize_default_chain``):
the verifier's chains stay AUTHORITATIVE whenever present, but when it registered
none, the framework projects a default register→CRUD chain DETERMINISTICALLY FROM
THE REGISTERED CONTRACT (generic, like ``_probe_body``/route_projector). This is
NOT the hand-rolled app-shaped journey the original no-fallback decision forbade —
a contract-projected chain carries no app bias — so business_chain (and the
delivery-gate RunHub run it gates) no longer dead-ends on a drifting agent while
the generality principle is preserved (2026-06-20).

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
import re
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
        # REPOINT MIS-TARGETED REGISTER (smoke-notes 2026-06-20): verifiers confuse
        # /oauth/register (RFC-7591 OAuth CLIENT registration — needs redirect_uris,
        # returns client_id, creates NO user) with USER registration. A step POSTing
        # {email,password} to /oauth/register both 400s (no redirect_uris) AND never
        # creates a user, so a later /auth/login 401s → business_chain fails forever.
        # When the body is clearly a user credential (email+password), repoint to the
        # real user endpoint so the round-trip can close.
        if pth == "/oauth/register" and isinstance(st.get("body"), Mapping) \
                and st["body"].get("email") and st["body"].get("password"):
            st["path"] = "/auth/register"
            pth = "/auth/register"
        # CANONICAL TOKEN SAVE: an /auth/* step ALWAYS saves the token under the
        # canonical var "token" — merged, never skipped when the verifier already
        # authored a custom save (e.g. {"commenter_token": "access_token"}). The
        # auto-auth below defaults unset /api/ steps to auth="token", and verifiers
        # frequently reference auth="token" on some steps while saving under a
        # different name on the auth step → "token" was never set → those steps
        # sent an EMPTY bearer → 401 → business_chain failed forever. Saving "token"
        # too makes the default/explicit token-auth resolve regardless of naming
        # (the custom var stays saved, so steps using it keep working).
        if pth in ("/auth/register", "/auth/login"):
            _save = dict(st.get("save") or {})
            _save.setdefault("token", "access_token")
            st["save"] = _save
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
    # CANONICAL TOKEN-AUTH: a verifier can reference auth="<var>" that no step
    # actually saves (it saved under a different name, or a bare "token" while the
    # auth step saved a custom name). Any /api/ step whose auth var is never saved
    # anywhere in the chain is repointed at the canonical "token" (guaranteed saved
    # by the /auth step above) so it can't send an empty bearer → 401.
    _saved = {v for s in out for v in (s.get("save") or {})}
    for s in out:
        a = s.get("auth")
        if a and a not in _saved and str(s.get("path", "")).rstrip("/").startswith("/api/"):
            s["auth"] = "token"
    # AUTH-PREPEND (PROPOSAL #40): if the chain uses token auth but has NO /auth step that
    # MINTS the token, synthesize the register step. Run #37 (recurring in #36): the
    # verifier's chain DESCRIPTION said "registers, logs in, creates a note…" but its STEPS
    # jumped straight to POST /api/notes auth="token" with NO register/login step → "token"
    # was never saved → every authed step sent an EMPTY bearer → 401 → business_chain failed
    # 6/6 forever (a manual register→POST curl on the SAME container returns 201, proving the
    # APP is fine and the CHAIN under-authored). The auth round-trip is a PLATFORM invariant
    # (the token always comes from /auth/register, regardless of domain), so synthesize the
    # missing step rather than depend on the verifier authoring it — mirrors the existing
    # auto-save / auth-first-reorder / auth-body-default platform fixes. Idempotent: only
    # when token-auth is referenced AND no step already mints "token".
    if any(s.get("auth") == "token" for s in out) and not any(
            "token" in (s.get("save") or {}) for s in out):
        out.insert(0, {
            "method": "POST", "path": "/auth/register",
            "body": {"email": "chain_${rand}@example.com",
                     "password": "Chain123!x", "name": "Chain Tester"},
            "save": {"token": "access_token"},
            "expect": [200, 201],
        })
    # ENSURE-USER-BEFORE-LOGIN (smoke-notes 2026-06-20): /auth/login authenticates
    # a user that a prior /auth/register must have CREATED. The canonical-save above
    # gives every login a save:{token}, which masks it from AUTH-PREPEND's "no
    # minting step" check — so a chain that logs in without ever registering a user
    # (verifier authored login-first, or registered via /oauth/register) 401s
    # forever. If a login step has no /auth/register anywhere, synthesize one using
    # the LOGIN's OWN credentials (so the just-created user matches what login sends)
    # — the reorder below then runs register first.
    _logins = [s for s in out if str(s.get("path", "")).rstrip("/") == "/auth/login"]
    if _logins and not any(
            str(s.get("path", "")).rstrip("/") == "/auth/register" for s in out):
        _lb = _logins[0].get("body") if isinstance(_logins[0].get("body"), Mapping) else {}
        out.insert(0, {
            "method": "POST", "path": "/auth/register",
            "body": {"email": (_lb or {}).get("email") or "chain_${rand}@example.com",
                     "password": (_lb or {}).get("password") or "Chain123!x",
                     "name": (_lb or {}).get("name") or "Chain Tester"},
            "save": {"token": "access_token"},
            "expect": [200, 201, 409],  # 409 = user already exists → still loginable
        })
    # AUTH-FIRST REORDER (round 45, hardened 2026-06-20): the verifier wrote /api/*
    # steps that use a token BEFORE the /auth/* step that mints it, OR authored
    # login BEFORE register → 401 → business_chain fails forever. "auth round-trip
    # first, register before login" is a PLATFORM invariant (every app's token comes
    # from /auth/register → /auth/login, regardless of domain). Rank register(0) <
    # login(1) < everything-else(2); a stable sort then GUARANTEES register precedes
    # login even when the verifier authored them in the wrong order (the old sort
    # gave both rank 0, so a stable sort preserved an authored login-first slip).
    def _auth_rank(st: Mapping[str, Any]) -> int:
        p = str(st.get("path", "")).rstrip("/")
        if p == "/auth/register":
            return 0
        if p == "/auth/login":
            return 1
        return 2
    out.sort(key=_auth_rank)
    return out, errors


_FIXED_ENDPOINT_KINDS = {"auth", "oauth", "infra", "spine"}


def _default_chain_body(ep: Mapping[str, Any]) -> Dict[str, Any]:
    """Generic request body from the endpoint's registered request schema —
    mirrors validation_runner._probe_body (domain-agnostic typed placeholders).
    Falls back to common text fields when no request schema is registered (a
    write needs SOME body); the projected handler drops fields the model lacks."""
    req = ((ep.get("schema") or {}).get("request")) or {}
    body: Dict[str, Any] = {}
    for field, typ in req.items():
        t = str(typ or "").lower()
        if any(x in t for x in ("[]", "list", "array")):
            body[field] = []
        elif any(x in t for x in ("dict", "object", "json", "{}")):
            body[field] = {}
        elif "bool" in t:
            body[field] = True
        elif any(x in t for x in ("float", "decimal", "double")):
            body[field] = 1.0
        elif any(x in t for x in ("int", "number")):
            body[field] = 1
        else:
            body[field] = "chain-${rand}"
    if not body:
        body = {"name": "chain-${rand}", "title": "chain-${rand}",
                "content": "chain-${rand}", "body": "chain-${rand}",
                "description": "chain-${rand}", "text": "chain-${rand}"}
    return body


def synthesize_default_chain(endpoints: List[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Project a default verification chain DETERMINISTICALLY FROM THE REGISTERED
    CONTRACT: register → for each business collection, create (saving the row id)
    → list → read-by-id → update → delete. This is generic projection (like
    ``_probe_body`` / route_projector), NOT a hand-rolled app-shaped journey — so
    it carries NO app bias and satisfies the generality principle. Used only as a
    FILL-IN when the verifier registered no usable chain. Returns [] when the
    contract exposes no creatable business resource (then the verifier-authoring
    feedback path still applies)."""
    eps = [e for e in (endpoints or []) if isinstance(e, Mapping)]
    by_key: Dict[tuple, Mapping[str, Any]] = {}
    for e in eps:
        m = str(e.get("method", "")).upper()
        p = str(e.get("path", "")).rstrip("/")
        if m and p:
            by_key[(m, p)] = e

    def _kind(e: Mapping[str, Any]) -> str:
        return str((e.get("metadata") or {}).get("kind") or "").lower()

    steps: List[Dict[str, Any]] = []
    reg = next((e for (m, p), e in by_key.items()
                if m == "POST" and p.endswith("/auth/register")), None)
    steps.append({
        "action": "register", "method": "POST",
        "path": (str(reg.get("path")) if reg else "/auth/register"),
        "body": {"email": "chain-${rand}@example.com",
                 "password": "Chain123!x", "name": "Chain Tester"},
        "expect": [200, 201, 409], "save": {"token": "access_token"}})

    made_any = False
    for (m, p), e in sorted(by_key.items()):
        # a business COLLECTION create: POST /api/<col> with no path param
        if m != "POST" or not p.startswith("/api/") or "{" in p or ":" in p:
            continue
        if _kind(e) in _FIXED_ENDPOINT_KINDS:
            continue
        col = p
        var = re.sub(r"[^a-z0-9]+", "_", col.strip("/").lower()) + "_id"
        steps.append({"action": f"create {col}", "method": "POST", "path": col,
                      "auth": "token", "body": _default_chain_body(e),
                      "expect": [200, 201], "save": {var: "id"}})
        made_any = True
        if ("GET", col) in by_key:
            steps.append({"action": f"list {col}", "method": "GET", "path": col,
                          "auth": "token", "expect": [200]})
        # item ops on the immediate child param path: /api/<col>/{id}
        item_paths = [pp for (mm, pp) in by_key
                      if pp.startswith(col + "/") and ("{" in pp or ":" in pp)
                      and pp.count("/") == col.count("/") + 1]
        for mm in ("GET", "PUT", "DELETE"):
            ip = next((pp for pp in item_paths if (mm, pp) in by_key), None)
            if not ip:
                continue
            sub = re.sub(r"(\{[^}]+\}|:[^/]+)$", "${" + var + "}", ip)
            st: Dict[str, Any] = {"action": f"{mm.lower()} {col}/id",
                                  "method": mm, "path": sub, "auth": "token"}
            if mm == "PUT":
                st["body"] = _default_chain_body(by_key[(mm, ip)])
                st["expect"] = [200]
            elif mm == "DELETE":
                st["expect"] = [200, 204]
            else:
                st["expect"] = [200]
            steps.append(st)

    if not made_any:
        return []
    norm, _errs = normalize_steps(steps)
    return [{"name": "framework_default_crud", "steps": norm}] if norm else []


def load_verifier_chains(project_dir: Any) -> List[Dict[str, Any]]:
    """Chains from the REGISTRY store (written via the registration tool).
    Deterministic file read so the validation runner needs no live hub. When the
    verifier registered no usable chain, FILL IN a contract-projected default
    (``synthesize_default_chain``) so business_chain — and the delivery-gate
    RunHub run it gates — no longer depends on a drifting agent. Verifier chains
    stay authoritative whenever present (fill-in, never supplement)."""
    path = Path(project_dir) / CHAINS_STORE_RELPATH
    out: List[Dict[str, Any]] = []
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        for name, rec in (data or {}).items():
            if name == "_meta" or not isinstance(rec, Mapping):
                continue
            steps, _errs = normalize_steps(rec.get("steps") or [])
            if steps:
                out.append({"name": str(rec.get("name") or name), "steps": steps})
    if out:
        return out
    # FILL-IN: no usable verifier chain → project a default from the contract.
    try:
        eps_path = Path(project_dir) / "shared" / "hubs" / "registryhub_endpoints.json"
        if eps_path.exists():
            eps_data = json.loads(eps_path.read_text(encoding="utf-8"))
            eps = [v for k, v in (eps_data or {}).items()
                   if k != "_meta" and isinstance(v, Mapping)]
            return synthesize_default_chain(eps)
    except Exception:
        pass
    return out


def _dig_path(payload: Any, parts: List[str]) -> Optional[Any]:
    # ENVELOPE TOLERANCE (2026-06-13): the route projector wraps every business
    # response in the canonical {"item": {...}} (single) / {"items": [...]}
    # (list) envelope, but verifier-authored chains save dotted paths against the
    # bare row — e.g. POST /api/posts saves {"post_id": "id"} expecting {id:...},
    # not {item:{id:...}}. When the first segment isn't at the top level, descend
    # once through the canonical wrapper so the save resolves against the row.
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


def _dig(payload: Any, dotted: str) -> Optional[Any]:
    parts = str(dotted).split(".")
    val = _dig_path(payload, parts)
    if val is None and len(parts) > 1:
        # LEAF FALLBACK (2026-06-20): the verifier often prefixes the save-path
        # with a wrong wrapper/resource key — save {"note_id": "note.id"} or
        # {"id": "data.id"} where the canonical response is {item:{id}}. The full
        # path misses (no "note"/"data" key), so resolve the LEAF field alone
        # (with envelope descent). Closes the save-path-prefix class: id /
        # item.id / note.id / response.note.id all resolve. Only fires when the
        # explicit path already failed, so a real nested path is never overridden.
        val = _dig_path(payload, [parts[-1]])
    return val


def _subst(value: Any, variables: Mapping[str, str], bare: bool = False) -> Any:
    if isinstance(value, str):
        for k, v in variables.items():
            sv = str(v)
            # ``${var.<k>}`` (a var-namespaced form some verifiers author, live
            # smoke-notes 2026-06-20: login body email "${var.user_email}", note
            # path "/api/notes/${var.note_id}") is accepted alongside the plain
            # ``${<k>}``. The namespaced form is replaced first; neither is a
            # substring of the other, so order only matters for the bare pass.
            value = value.replace("${var." + k + "}", sv).replace("${" + k + "}", sv)
            # bare {var} (OpenAPI path-param style) is ALSO accepted, but only on
            # PATHS (bare=True): verifiers routinely author "/api/notes/{id}"
            # instead of "/api/notes/${id}" — the literal "{id}" then reaches the
            # backend int path param → 422 → business_chain breaks forever
            # (observed live: GET/PUT /api/notes/{id}). The ${...} forms are
            # replaced FIRST so an already-correct "${id}" leaves no bare "{id}"
            # behind. Bodies are NOT bare-substituted: a JSON string leaf may
            # legitimately contain a "{rand}"/"{id}" literal and must not change.
            if bare:
                value = value.replace("{var." + k + "}", sv).replace("{" + k + "}", sv)
        return value
    if isinstance(value, Mapping):
        return {k: _subst(v, variables, bare) for k, v in value.items()}
    if isinstance(value, list):
        return [_subst(v, variables, bare) for v in value]
    return value


def _extract_resource_id(payload: Any) -> Any:
    """Best-effort id from a canonical response envelope — ``{item:{id}}`` (single),
    ``{id}`` (bare), or ``{items:[{id}]}`` (list, first row). Used to auto-capture
    the 'current resource id' as a chain runs, so a later get/update/delete step can
    fall back to it when the verifier referenced an unsaved path variable."""
    if isinstance(payload, Mapping):
        item = payload.get("item")
        if isinstance(item, Mapping) and item.get("id") is not None:
            return item["id"]
        if payload.get("id") is not None:
            return payload["id"]
        items = payload.get("items")
        if isinstance(items, list) and items and isinstance(items[0], Mapping) \
                and items[0].get("id") is not None:
            return items[0]["id"]
    return None


# A path placeholder the verifier left unresolved: ``${msg_id}`` / ``${var.x}`` or a
# bare ``{id}`` (never a substituted value, since saved vars are replaced first).
_UNRESOLVED_PLACEHOLDER = re.compile(r"\$\{[^}]+\}|\{[a-zA-Z_][^}]*\}")
# Variable names a step REFERENCES: ${var}, ${var.name}, or bare {name} (path-param style).
_VAR_REF = re.compile(r"\$\{(?:var\.)?(\w+)\}|\{(\w+)\}")


def _step_refs(step: Mapping[str, Any]) -> set:
    """Variable names a step depends on (path + body placeholders + its auth var) — used to
    decide whether a step is reachable after an earlier step failed to save a variable."""
    text = str(step.get("path") or "")
    if step.get("body") is not None:
        try:
            text += " " + json.dumps(step.get("body"))
        except Exception:
            text += " " + str(step.get("body"))
    refs = {m.group(1) or m.group(2) for m in _VAR_REF.finditer(text)}
    refs.discard("rand")  # the framework always supplies ${rand}
    if step.get("auth"):
        refs.add(str(step.get("auth")))
    return refs


def execute_chain(base: str, chain: Mapping[str, Any]) -> Dict[str, Any]:
    """Run one chain; returns {name, steps: [...], broken: [...]}.
    Deterministic wiring; never raises."""
    variables: Dict[str, str] = {"rand": str(int(time.time() * 1000))[-7:]}
    recorded: List[Dict[str, Any]] = []
    last_id: Any = None
    unsatisfied: set = set()  # vars an earlier BROKEN step failed to save → its dependents are unreachable
    for step in chain.get("steps") or []:
        method = str(step.get("method", "GET")).upper()
        # A broken step no longer aborts the whole chain (it used to `break`, so only the
        # FIRST failure was ever reported). Continue, but SKIP a step that depends on a
        # variable a broken step was supposed to save — it would cascade-fail on a missing
        # var and add noise. Independent later steps still run, so every real failure shows.
        _dep = _step_refs(step) & unsatisfied
        if _dep:
            recorded.append({
                "action": str(step.get("action") or step.get("path") or ""),
                "method": method, "path": str(step.get("path") or ""),
                "status": None, "ok": False, "kind": "skipped",
                "note": "skipped — depends on " + ", ".join(sorted(_dep)) + " from a failed earlier step"})
            continue
        path = str(_subst(step.get("path", ""), variables, bare=True))
        # UNRESOLVED-VARIABLE FALLBACK: verifier-authored chains routinely reference a
        # path var they never saved (outlook run #6: GET /api/messages/${msg_id} with no
        # prior save:{msg_id:...}). The literal "${msg_id}"/"{msg_id}" then reaches the
        # int path param → 422 → business_chain fails FOREVER on a functionally-correct
        # app (the endpoint works fine with a real id). If a placeholder survives
        # substitution, use the most recent resource id captured from a prior step's
        # response — the id a correctly-wired chain would have saved. Untouched when the
        # chain is wired correctly (no leftover placeholder) or no id seen yet.
        if last_id is not None and _UNRESOLVED_PLACEHOLDER.search(path):
            path = _UNRESOLVED_PLACEHOLDER.sub(str(last_id), path)
        body = _subst(step.get("body"), variables) if step.get("body") else None
        token = variables.get(str(step.get("auth"))) if step.get("auth") else None
        # ``expect`` tolerated as a scalar (verifier authored ``expect: 201``
        # instead of ``[201]``; iterating the int crashed the WHOLE runner →
        # business_chain failed for every chain → no delivery, smoke run #10).
        _exp = step.get("expect")
        if _exp is None:
            _exp = []
        elif not isinstance(_exp, (list, tuple, set)):
            _exp = [_exp]
        expect = [int(x) for x in _exp if str(x).isdigit()]
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
        if ok:
            # Auto-capture the current resource id (id / item.id / items[0].id) from
            # EVERY successful step — feeds the unresolved-variable fallback above so a
            # later get/update/delete step can target a real row even when the verifier
            # didn't wire an explicit save. Never overrides an explicit save.
            try:
                _cid = _extract_resource_id(json.loads(res.get("body_text") or "{}"))
                if _cid is not None:
                    last_id = _cid
            except Exception:
                pass
        if ok and isinstance(step.get("save"), Mapping):
            try:
                payload = json.loads(res.get("body_text") or "{}")
            except Exception:
                payload = {}
            for var, dotted in step["save"].items():
                val = _dig(payload, dotted)
                if val is not None:
                    variables[str(var)] = str(val)
                elif "." not in str(dotted) and str(dotted) not in variables:
                    # REVERSED-MAPPING TOLERANCE: the contract is
                    # save:{var_name: response_dotted_path}, but verifiers often
                    # invert it — save:{"id": "note_id"} meaning "save var note_id
                    # from response field id" — so the forward dig (response."note_id")
                    # misses, var "id" never feeds a later ${note_id}, and the chain
                    # 422s forever. When the forward path is absent AND the value
                    # lives under the VAR name instead, save under the dotted token.
                    # Guards: fires only when forward resolution already failed (a
                    # correct mapping is never disturbed) AND the dotted token is not
                    # already a set variable (never CLOBBER a value an earlier step
                    # captured correctly — a later reversed slip can't overwrite it).
                    rev = _dig(payload, str(var))
                    if rev is not None:
                        variables[str(dotted)] = str(rev)
        if kind == "broken":
            # Don't abort — just mark the vars this step was supposed to provide as
            # unsatisfied, so ONLY its dependents are skipped; independent steps run on.
            if isinstance(step.get("save"), Mapping):
                unsatisfied.update(str(k) for k in step["save"].keys())
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
