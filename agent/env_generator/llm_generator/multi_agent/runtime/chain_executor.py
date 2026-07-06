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


def _coerce_save(save: Any) -> Dict[str, Any]:
    """Coerce a step's ``save`` (canonical: ``{var: "response.dotpath"}``) from any
    shape the verifier authors into a dict, WITHOUT raising. Tolerates: a dict
    (pass-through), a JSON-string dict, a ``'var->path'`` / ``'var=>path'`` /
    ``'var:path'`` arrow/colon shorthand, or a bare ``'var'`` (-> ``{var: var}``).
    Anything unparseable returns ``{}`` (dropped, not crashed). Prevents the cryptic
    ``dict(<string>)`` failure that blocked chain registration (v10)."""
    if isinstance(save, Mapping):
        return dict(save)
    if isinstance(save, str):
        s = save.strip()
        if not s:
            return {}
        if s.startswith("{"):
            try:
                _p = json.loads(s)
                if isinstance(_p, Mapping):
                    return dict(_p)
            except Exception:
                pass
        for _sep in ("->", "=>", ":"):
            if _sep in s:
                _a, _, _b = s.partition(_sep)
                _a, _b = _a.strip(), _b.strip()
                if _a and _b:
                    return {_a: _b}
        return {s: s}
    return {}


# JWT response-field synonyms a verifier may (mis)use as the token save-path. The
# framework's auth skeleton returns the access token under "access_token"; any of
# these as a save VALUE on an /auth step is normalized to that canonical path so the
# saved var actually populates (else an /api step using it sends an empty bearer → 401).
_TOKEN_RESP_SYNONYMS = frozenset({
    "token", "access_token", "accesstoken", "jwt", "auth_token", "authtoken",
    "bearer_token", "bearertoken", "jwt_token", "id_token",
})


_SUCCESS_CODES = frozenset({200, 201, 202, 203, 204, 205, 206})
_CROSS_USER_DENIAL_CODES = frozenset({403, 404})


def _expect_codes(st: Mapping[str, Any]) -> List[int]:
    e = st.get("expect")
    if e is None:
        return []
    if not isinstance(e, (list, tuple)):
        e = [e]
    out: List[int] = []
    for c in e:
        try:
            out.append(int(c))
        except Exception:
            pass
    return out


def _is_cross_user_denial(st: Mapping[str, Any]) -> bool:
    """A step that asserts THIS actor must be DENIED access to a resource that EXISTS
    (403/404), NOT an auth-roundtrip 401 (no token) and NOT a success. The signature of
    a cross-user isolation probe: expect contains 403/404, no 2xx (and not 401-only)."""
    codes = _expect_codes(st)
    if not codes or any(c in _SUCCESS_CODES for c in codes):
        return False
    return any(c in _CROSS_USER_DENIAL_CODES for c in codes)


def _trailing_resource_var(path: Any) -> Optional[str]:
    """The path-param NAME of a by-id step's LAST segment — ``${note_id}`` / ``{id}`` /
    ``:id`` → the var. None for a collection or static path. Used to (a) recognise a
    by-id target and (b) match a denial step against an earlier DELETE of the SAME var."""
    segs = [s for s in str(path or "").rstrip("/").split("/") if s]
    if not segs:
        return None
    m = re.match(r"^\$\{([^}]+)\}$|^\{([^}]+)\}$|^:(.+)$", segs[-1])
    if not m:
        return None
    return next((g for g in m.groups() if g), None)


def _drop_auth_save_clobbers(steps: List[Dict[str, Any]]) -> None:
    """AUTH-SAVE CLOBBER GUARD (#59c, outlook run-44 live) — in place.

    A LATER auth step must not RE-BIND a token var that an EARLIER auth step
    with a DIFFERENT email already saves. run-44: the second register carried
    ``save: {"token_2": "access_token", "token": "access_token"}`` (the
    canonical-token setdefault below adds "token" to EVERY auth step) —
    silently overwriting user 1's token with user 2's. Every later "owner"
    step (auth=token) then acted AS USER 2, so the cross-user probe
    (auth=token_2) read a row its OWN identity created → 200 → the chain
    flagged a LEAK on a correctly-isolated app (live 2-user curl proved the
    isolation worked) and wedged business_chain for 12+ cycles. The clobbering
    save key is dropped (the step's own new var stays); a same-email re-login
    rebind is the same identity and left alone.

    Called from BOTH normalize_steps (registration-time) and execute_chain
    (runtime): chains persisted by an older framework carry the clobber in the
    STORED steps, and execute_chain runs the stored steps verbatim."""
    _auth_email_by_var: Dict[str, str] = {}
    for s in steps:
        if not isinstance(s, dict):
            continue
        if not (str(s.get("method", "")).upper() == "POST"
                and "/auth/" in str(s.get("path", ""))):
            continue
        _body = s.get("body")
        _email = str((_body or {}).get("email", "") if isinstance(_body, Mapping)
                     else "").strip().lower()
        _save = dict(_coerce_save(s.get("save")))
        for _k in list(_save.keys()):
            _first = _auth_email_by_var.get(_k)
            if _first and _email and _first != _email:
                _save.pop(_k, None)
            elif _email:
                _auth_email_by_var.setdefault(_k, _email)
        s["save"] = _save


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
                _parsed = None
                try:
                    _parsed = json.loads(_v)
                except Exception:
                    # A JSON-STRING body that embeds a BARE ${var} substitution token
                    # ('{"calendar_id": ${calendarId}}') is invalid JSON → json.loads
                    # fails → the body stays a STRING → the API 422s "Input should be a
                    # valid dictionary" (outlook events POST). Quote the bare ${...}
                    # tokens so it parses into a real dict; they become string VALUES
                    # the executor substitutes at run time (string-substitution in body).
                    try:
                        _q = re.sub(r'(?<!")(\$\{[^}]+\})(?!")', r'"\1"', _v)
                        _parsed = json.loads(_q)
                    except Exception:
                        _parsed = None
                if isinstance(_parsed, Mapping):
                    st["body"] = _parsed
        # SCHEMA TOLERANCE (2026-06-24): the verifier frequently authors `save` as a
        # STRING shorthand ('access_token->auth.token', 'token:access_token') or a
        # JSON string, not the canonical {var: "dot.path"} dict. The downstream
        # `dict(st["save"])` then threw a CRYPTIC "dictionary update sequence element
        # #0 has length 1; 2 is required", and the verifier burned ~7 of 10
        # register_verification_chain attempts guessing the format (v10). Coerce any
        # save shape to a dict here so it NEVER crashes registration — best-effort,
        # never raises. (Canonical dict still authoritative; string is a fallback.)
        if "save" in st:
            st["save"] = _coerce_save(st.get("save"))
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
        # CANONICAL AUTH PATH (#79, instagram-core opt6 abort): the OAuth AS is mounted at BOTH
        # "/" and "/api", so a verifier can author the auth round-trip at /api/auth/register|login
        # — a valid, equivalent endpoint. But EVERY auth invariant below (canonical save,
        # expect-union, body-default, ensure-user-before-login, auth-first reorder) keys on the
        # un-prefixed "/auth/*" form, so an /api-prefixed auth step bypassed ALL of them — most
        # damagingly the body-default, leaving a body-less POST /api/auth/register that the
        # framework AS 422'd ("email and password are required") every cycle → business_chain
        # failed for 75min → NO-CONVERGENCE ABORT (auth_and_profile chain, register step body=null).
        # Collapse to the canonical path (SAME handler, mounted at both) so all invariants apply —
        # mirrors the /oauth/register repoint just above.
        if pth in ("/api/auth/register", "/api/auth/login"):
            st["path"] = pth[len("/api"):]
            pth = st["path"]
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
            # TOKEN RESPONSE-PATH NORMALIZATION (run v21): verifiers author the token
            # save with a WRONG response path — save:{"tokenA": "token"} expecting a
            # response field "token", but the framework's auth skeleton returns the JWT
            # under "access_token" (there is NO "token" field). The var (tokenA) then
            # resolves to None, and the /api step using auth="tokenA" sends an EMPTY
            # bearer → 401 → business_chain fails (v21: 3/8 chains 401'd exactly this
            # way, while the chains that wrote "access_token" passed). The token ALWAYS
            # comes from access_token (a platform invariant of the OAuth2 skeleton), so
            # rewrite any save whose VALUE is a token synonym to the canonical
            # "access_token" path. Preserves multi-user identity (tokenA←A's token,
            # tokenB←B's), unlike a blanket repoint to the single canonical "token".
            for _k, _v in list(_save.items()):
                if str(_v).strip().lower() in _TOKEN_RESP_SYNONYMS:
                    _save[_k] = "access_token"
            _save.setdefault("token", "access_token")
            st["save"] = _save
        if pth == "/auth/register":
            # The framework's AS register returns 201 Created (200 on some platforms),
            # or 409 (user already exists → still loginable). Verifiers author the expect
            # INCONSISTENTLY — e.g. [200, 409] (FORGETTING 201) → the framework's 201
            # then fails the step and wedges an otherwise-correct chain (smoke-notes exp7:
            # notes_crud's whole CRUD flow failed only because register→201 ∉ [200,409]).
            # The exact success code is a framework FACT, not a verifier choice, so UNION
            # in all three rather than just appending 409. Per-step ${rand} keeps distinct
            # register steps distinct; re-registering the same identity 409s safely.
            _re = st.get("expect")
            _re = ([200, 201] if not _re else
                   list(_re) if isinstance(_re, (list, tuple)) else [_re])
            for _code in (200, 201, 409):
                if _code not in _re:
                    _re.append(_code)
            st["expect"] = _re
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
    # MULTI-ACTOR ISOLATION AUTO-FIX (smoke-notes exp7/exp9, ~2/3 of private-app runs):
    # the verifier authors a cross-user isolation probe (GET/PUT/DELETE /api/<res>/{id}
    # expecting 403/404 — "user B must NOT reach A's row") but leaves auth UNSET, so it
    # defaults to the canonical "token" = the LAST-registered user (usually the resource
    # OWNER) → it reads its OWN row → 200 ≠ 404 → false-fail → business_chain blocks
    # delivery though the APP is correctly scoped. The framework SUPPORTS per-step actor
    # auth (auth=<var> → that Bearer); the verifier just under-authors it. Route such a
    # step to a dedicated INTRUDER user (registered below, owns NOTHING) so it is
    # GUARANTEED a non-owner → the app's real 404 is observed. SAFE BY CONSTRUCTION:
    #   • Only a by-id DENIAL step (expect has 403/404, NO 2xx) whose auth is the canonical
    #     "token" (the main actor). An EXPLICIT distinct actor (auth=tokenB) is the verifier
    #     authoring it correctly → left UNTOUCHED. A 401-only auth-roundtrip → not a denial.
    #   • DELETION-EXCLUSION: skip when an earlier OWNER delete (expect 2xx) removed the SAME
    #     resource var — that "deleted → 404" check MUST stay the owner, else a FAILED delete
    #     is masked (the intruder would 404 on a still-existing row). Matched on the trailing
    #     path var, so a cross-user read of a DIFFERENT resource is still routed.
    #   • Acts only when CONFIDENT; otherwise byte-identical to prior behaviour. Idempotent.
    _drop_auth_save_clobbers(out)
    _INTRUDER = "__chain_intruder_token"
    _owner_deleted_vars: set = set()
    _used_intruder = False
    for s in out:
        _p = str(s.get("path", "")).rstrip("/")
        _var = _trailing_resource_var(_p)
        _denial = _is_cross_user_denial(s)
        if (_p.startswith("/api/") and s.get("auth") == "token" and _var
                and _denial and _var not in _owner_deleted_vars):
            s["auth"] = _INTRUDER
            _used_intruder = True
        # only an OWNER delete (success-expecting) actually removes the row → marks the var
        # "gone" so a later same-var 404 is treated as a deletion check, not cross-user.
        if str(s.get("method", "")).upper() == "DELETE" and _var and not _denial:
            _owner_deleted_vars.add(_var)
    if _used_intruder and not any(
            _INTRUDER in (s.get("save") or {}) for s in out):
        out.insert(0, {
            "method": "POST", "path": "/auth/register",
            "body": {"email": "intruder_${rand}@example.com",
                     "password": "Chain123!x", "name": "Chain Intruder"},
            "save": {_INTRUDER: "access_token"},
            "expect": [200, 201, 409],
        })
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
            if str(rec.get("kind") or "").lower() == "coverage":
                # Framework COVERAGE-completion chain (delivery_gate.complete_coverage_chain):
                # it references the endpoints no verifier chain touches so the delivery gate's
                # api-coverage check is satisfied by construction. It carries no request bodies
                # and must NEVER execute (executing it would fail api_smoke's business_chain).
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


def _status_ok(status: Any, expect: List[int]) -> bool:
    """A step passes when its status is in the authored ``expect`` list, or — when no
    ``expect`` was authored — any 2xx.

    SUCCESS-FAMILY TOLERANCE (outlook run-26 + run-29, 2026-07-01): when EVERY authored
    expect is a 2xx, the verifier's intent is "this write/read SUCCEEDS" — but it GUESSES
    the exact success code and handlers legitimately differ (rsvp create → 201 vs authored
    [200]; delete → 204 vs [200]). Strict membership failed the WHOLE business_chain forever
    on a WORKING flow (run-29: rsvp 201-vs-[200] wedged 4+ validation cycles; run-26 M3
    flagged the same class) — so an all-2xx expectation accepts any 2xx. An expect list
    carrying ANY non-2xx (isolation probes [403,404], redirect checks, mixed [200,404])
    keeps EXACT matching — a 200 must never satisfy an expected-denial probe."""
    if not expect:
        return bool(status and 200 <= status < 300)
    if status in expect:
        return True
    return (isinstance(status, int) and 200 <= status < 300
            and all(isinstance(e, int) and 200 <= e < 300 for e in expect))


# A plain-string 4xx detail ('text is required', 'missing field email') — some
# hand-authored handlers raise HTTPException(400, "text is required") instead of
# letting Pydantic emit the structured 422 loc[] list. Extract the field name so a
# write step can still auto-fill it (observed v22: POST /api/posts/{id}/comments
# → 400 "text is required" — this backend's comment field is `text`, not `content`).
_REQUIRED_FIELD_RE = re.compile(
    r"(?:field\s+)?['\"]?([A-Za-z_]\w*)['\"]?\s+(?:is\s+)?required"
    r"|missing\s+(?:required\s+)?(?:field\s+)?['\"]?([A-Za-z_]\w*)",
    re.IGNORECASE)


def _missing_required_fields(body_text: Optional[str],
                             method: str) -> "tuple[List[str], List[str]]":
    """``(body_fields, query_fields)`` the LIVE handler reports MISSING from a 4xx,
    so a chain step can auto-fill exactly what's required even when the endpoint's
    REGISTERED request schema is empty (contract drift — v19: POST
    /api/posts/{id}/comments has request:{} yet 422s "field required"). Structured
    FastAPI 422 buckets each ``detail[].loc`` by its frame (``body``/``form`` →
    body, ``query`` → query param, e.g. v22 GET /api/search/users → 422 missing
    ``query.q``). A plain-STRING detail ('text is required') is attributed to the
    BODY for a write method (only writes carry one). Domain-agnostic: reads the
    server's own error, never app knowledge."""
    body: List[str] = []
    query: List[str] = []
    try:
        d = json.loads(body_text or "{}")
    except Exception:
        return body, query
    det = d.get("detail") if isinstance(d, Mapping) else None
    if isinstance(det, list):
        for e in det:
            if not isinstance(e, Mapping):
                continue
            if str(e.get("type", "")).lower() not in ("missing", "value_error.missing"):
                continue
            loc = e.get("loc")
            if not (isinstance(loc, (list, tuple)) and loc):
                continue
            frame = str(loc[0])
            # ``loc == ["body"]`` (#70): the WHOLE body is missing because the step
            # sent null/no body — there is NO field name to fill (filling a field
            # literally named "body" is wrong). Skip; the caller re-probes with {}
            # to surface the field-level 422 (loc == ["body","<field>"]).
            if frame in ("body", "form") and len(loc) == 1:
                continue
            seg = (loc[1] if len(loc) > 1 and frame in ("body", "query", "form")
                   else loc[-1])
            if not (isinstance(seg, str) and seg):
                continue
            if frame == "query":
                if seg not in query:
                    query.append(seg)
            elif seg not in body:
                body.append(seg)
    elif isinstance(det, str) and method in ("POST", "PUT", "PATCH"):
        for m in _REQUIRED_FIELD_RE.finditer(det):
            f = m.group(1) or m.group(2)
            # never treat an auth/permission word as a missing body field (a 401/403
            # message like "missing or invalid token" is NOT a body-shape problem).
            if f and f.lower() not in ("token", "authorization", "auth", "bearer", "credentials") \
                    and f not in body:
                body.append(f)
    return body, query


_BODY_DOLLAR_VAR = re.compile(r"\$\{[^}]+\}")


def _resource_from_path(path: Any) -> Optional[str]:
    """The SINGULAR resource a step's path targets as a COLLECTION:
    ``/api/calendars`` -> ``'calendar'``. None for a by-id / path-param / non-collection
    tail (``/api/calendars/5``, ``/api/events/${id}``) so only real collection
    steps register a per-resource id. Naive singularize (strip trailing 's') — good
    enough to match a ``<resource>_id`` FK field (calendars->calendar matches calendar_id)."""
    segs = [s for s in str(path or "").split("?", 1)[0].rstrip("/").split("/")
            if s and s.lower() != "api"]
    if not segs:
        return None
    last = segs[-1]
    if not re.match(r"^[A-Za-z][\w-]*$", last) or last.isdigit():
        return None  # path param (${id}/{id}/:id) or numeric id → not a collection
    return last[:-1] if last.endswith("s") and len(last) > 1 else last


def _resolve_unresolved_dollar_vars(value: Any, last_id: Any,
                                    by_resource: Optional[Mapping[str, Any]] = None) -> Any:
    """BODY counterpart of execute_chain's path UNRESOLVED-VARIABLE FALLBACK. A
    verifier-authored body that references a ``${var}`` no prior step saved — a nested
    FK like ``{"calendar_id": "${calendar_id}"}`` with no ``save:{calendar_id:...}`` —
    otherwise leaves the literal token, which reaches the column (POST /api/events →
    ``invalid input syntax for type integer: "${calendar_id}"`` → 500) → business_chain
    wedges FOREVER on a functionally-correct app (outlook 2026-06-30).

    RESOURCE-AWARE (outlook run-8): a WHOLE-value ``${<resource>_id}`` placeholder
    resolves to THAT resource's last-created id from ``by_resource`` (e.g.
    ``${calendar_id}`` -> the last POST /api/calendars id) — NOT the GLOBAL ``last_id``,
    which may be an unrelated row created in between (a message POST right before the
    event made last_id the MESSAGE id -> events_calendar_id_fkey VIOLATION). Falls back
    to ``last_id`` when the resource was never created. Taken RAW so an INTEGER FK column
    gets an int. The ``${...}`` form is always touched; a BARE ``{name}`` is touched ONLY
    when it is a WHOLE-value FK token ending in ``_id`` (``{folder_id}``/``{cal_id}`` —
    unambiguously a substitution ref the verifier authored, outlook run-11 M3: a bare
    ``{folder_id}`` body leaf reached the int column → 500). A bare ``{id}``/``{rand}`` or a
    non-``_id`` bare token stays a possible literal (see _subst) and is left alone."""
    if isinstance(value, str):
        m = (re.fullmatch(r"\$\{([^}]+)\}", value.strip())
             or re.fullmatch(r"\{([A-Za-z_]\w*_id)\}", value.strip()))
        if m:
            var = m.group(1).strip()
            if by_resource and var.endswith("_id"):
                res = var[:-3]
                rid = by_resource.get(res)
                if rid is None:
                    rid = by_resource.get(res + "s")  # tolerate a plural-keyed map
                if rid is not None:
                    return rid
            return last_id
        if _BODY_DOLLAR_VAR.search(value):
            return _BODY_DOLLAR_VAR.sub(str(last_id), value)
        return value
    if isinstance(value, Mapping):
        return {k: _resolve_unresolved_dollar_vars(v, last_id, by_resource) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_unresolved_dollar_vars(v, last_id, by_resource) for v in value]
    return value


def _collection_path_of(path: Any) -> str:
    """COLLECTION path for a by-id path with an UNRESOLVED placeholder: the prefix before
    the FIRST ${x}/{x}/:x segment. ``/api/messages/${message_id}`` -> ``/api/messages``;
    FIX #81 (instagram live): ALSO the ACTION-SUFFIX shape ``/api/posts/${post_id}/like``
    -> ``/api/posts`` and the nested collection ``/api/events/${event_id}/attendees`` ->
    ``/api/events`` — a mid-path placeholder previously left the path parametrised, so
    list/create recovery was guard-skipped and the step fell to the global last_id (the
    chain user's OWN register id → follow-YOURSELF 400) or the literal token (422).
    Returns the input unchanged when no placeholder (``/api/messages/search`` untouched)."""
    p = str(path or "").split("?", 1)[0].rstrip("/")
    segs = p.split("/")
    for i, s in enumerate(segs):
        if s.startswith("${") or s.startswith("{") or s.startswith(":"):
            return "/".join(segs[:i]) or "/"
    return p


def _recover_id_via_list(base: str, coll_path: str, token: Any, avoid: Any = None) -> Any:
    """RECOVERY for an unresolvable path var: GET the resource collection and return a real
    row's id. Seed data populates every business collection, so a chain step that targets a
    resource it never CREATED (no prior POST to capture an id from) still hits a LIVE row
    instead of sending the literal ``${x_id}`` → 404 (outlook run-22). FIX #81: ``avoid`` =
    the chain user's OWN registered id — an action on the users collection (follow/unfollow)
    must not target SELF (400 "cannot follow yourself", instagram live) — prefer a row whose
    id differs; the only row still wins over a literal. Best-effort: never raises; returns
    None on any failure, an empty collection, or a still-parametrised path."""
    if not coll_path or "${" in coll_path or "{" in coll_path or ":" in coll_path.split("/")[-1]:
        return None
    try:
        r = _http("GET", base + coll_path, token=token, body=None)
        if not _status_ok(r.get("status"), [200]):
            return None
        payload = json.loads(r.get("body_text") or "{}")
        if avoid is not None:
            rows = payload.get("items") if isinstance(payload, Mapping) else payload
            if isinstance(rows, list):
                for row in rows:
                    rid = row.get("id") if isinstance(row, Mapping) else None
                    if rid is not None and str(rid) != str(avoid):
                        return rid
        return _extract_resource_id(payload)
    except Exception:
        return None


def _recover_id_via_create(base: str, coll_path: str, token: Any) -> Any:
    """LAST-RESORT recovery when even the list is EMPTY: create a row and use ITS id.

    The list recovery above assumed seed data populates every collection — but reads are
    OWNER-SCOPED, and the chain runs as a FRESHLY-REGISTERED user who owns NOTHING: the
    verifier's ``save: items.0.id`` finds an empty list AND the list recovery sees the same
    empty list → the literal ``{message_id}`` reaches the typed path param → 422 → the whole
    business_chain wedges forever on a working backend (outlook run-29 M3 STUCK-ABORT, live:
    3 of 6 chains died exactly here). POST a minimal row to the collection — auto-filling the
    required fields the server itself names in its 400/422 (mirrors the step loop's
    MISSING-FIELD AUTO-REPAIR) — and return the created id. Best-effort; never raises."""
    if not coll_path or "${" in coll_path or "{" in coll_path or ":" in coll_path.split("/")[-1]:
        return None
    try:
        body: Dict[str, Any] = {}
        r = _http("POST", base + coll_path, token=token, body=body)
        if not _status_ok(r.get("status"), []):
            if r.get("status") not in (400, 422):
                return None
            miss_b, _miss_q = _missing_required_fields(r.get("body_text"), "POST")
            if not miss_b:
                return None
            body = {f: "chain-recover" for f in miss_b}
            r = _http("POST", base + coll_path, token=token, body=body)
            if not _status_ok(r.get("status"), []):
                return None
        return _extract_resource_id(json.loads(r.get("body_text") or "{}"))
    except Exception:
        return None


def _reverify_denial_via_fresh_intruder(base, method, path, body, expect) -> bool:
    """#78: a cross-user DENIAL step (expect 403/404) got a 2xx (apparent leak). Register a
    GUARANTEED-fresh intruder and re-run the SAME request as them. The recurring false-positive
    (outlook run-64 read, smoke-feed write; both live-confirmed the backend is CORRECT) is the
    probe running as the resource's OWNER via a stale / owner-colliding / empty intruder token
    → the op legitimately succeeds → false "leak/hack" → 7-cycle stuck → abort. A brand-new
    intruder is DEFINITELY a different principal: if THEY are denied, the original 2xx was a
    probe-setup artifact, NOT a real cross-user leak. Returns True iff a REAL leak is confirmed
    (the fresh intruder ALSO succeeds) — so this can NEVER mask a real leak; conservative
    (returns True = keep the leak verdict) on any error or if a fresh token can't be obtained."""
    try:
        import uuid as _uuid
        _email = "reverify_%s@example.com" % _uuid.uuid4().hex[:14]
        _reg = _http("POST", base + "/auth/register",
                     body={"email": _email, "password": "Reverify123!x", "name": "Reverify"})
        _tok = None
        try:
            _tok = (json.loads(_reg.get("body_text") or "{}") or {}).get("access_token")
        except Exception:
            _tok = None
        if not _tok:
            return True  # no fresh intruder → cannot disprove → keep the leak verdict (safe)
        _r = _http(method, base + path, token=_tok,
                   body=(body if isinstance(body, Mapping) else None))
        return not _status_ok(_r.get("status"), expect)  # real leak iff NOT denied
    except Exception:
        return True  # any failure → conservative → keep the leak verdict


def execute_chain(base: str, chain: Mapping[str, Any]) -> Dict[str, Any]:
    """Run one chain; returns {name, steps: [...], broken: [...]}.
    Deterministic wiring; never raises."""
    # ${rand} mints a UNIQUE value PER STEP (the prompt's contract: "${rand} mints a
    # unique value, ${var} reuses a saved one"). It used to be minted ONCE per execution
    # — so the canonical multi-user pattern (register user A → … → register user B), which
    # the verifier prompt mandates and few-shots, gave BOTH registers the SAME
    # ${rand} email → step 2 collided on the unique-email constraint (409) → its token was
    # never saved → every downstream step skipped → business_chain_failing FOREVER on a
    # functionally-correct app (run v12: chain `post_creation_and_visibility`). Fresh per
    # STEP (not per occurrence) keeps a single step's email+username consistent while
    # making distinct steps distinct; cross-step REUSE is via ${var} (saved), per the prompt.
    _rand_base = str(int(time.time() * 1000))[-7:]
    variables: Dict[str, str] = {}
    recorded: List[Dict[str, Any]] = []
    last_id: Any = None
    last_id_by_resource: Dict[str, Any] = {}  # resource -> its last-created id (FK resolution, fix #10)
    last_reg_creds: Dict[str, Any] = {}  # creds of the last successful /auth/register → reused if a later /auth/login 401s
    own_user_id: Any = None  # the chain user's own id (from /auth/register) — recovery must not target SELF (FIX #81)
    unsatisfied: set = set()  # vars an earlier BROKEN step failed to save → its dependents are unreachable
    # #59c: STORED chains (registered by an older framework, or hand-edited) can
    # carry the auth-save clobber in their persisted steps — normalize-time
    # guarding alone can't reach them, so guard the runtime copy too.
    _steps = [dict(s) if isinstance(s, Mapping) else s
              for s in (chain.get("steps") or [])]
    _drop_auth_save_clobbers(_steps)
    for idx, step in enumerate(_steps):
        variables["rand"] = f"{_rand_base}{idx:02d}"
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
        token = variables.get(str(step.get("auth"))) if step.get("auth") else None
        if _UNRESOLVED_PLACEHOLDER.search(path):
            # Resolve a surviving ${x_id}/{x_id} path placeholder in order: (1) the id of the
            # SAME resource captured earlier (last_id_by_resource), (2) the most recent captured
            # id (last_id), (3) RECOVERY — a live LIST GET on the resource's collection (seed
            # data populates it), taking a real row's id. Without (3), a chain that GETs/updates/
            # deletes a resource it never CREATED first (outlook run-22: GET /api/messages/
            # ${message_id} with no prior POST) sent the LITERAL token → 404 → business_chain
            # wedged forever on a functionally-correct, SEEDED app. Untouched when wired correctly.
            _pcoll = _collection_path_of(step.get("path"))
            _pres = _resource_from_path(_pcoll)
            _is_denial = _is_cross_user_denial(step)
            # (1) SAME-RESOURCE captured id — always the correct id for this path.
            _rid = (last_id_by_resource.get(_pres) if _pres else None)
            # (2) RECOVERY on the CORRECT collection — MUST come BEFORE the global
            #     last_id fallback (#66, run-51 auth_and_inbox_flow live): the
            #     global last_id is the most-recent id from ANY prior step — e.g.
            #     the USER id from GET /api/auth/me or a FOLDER id from GET
            #     /api/folders — so using it for GET /api/messages/{message_id}
            #     read /api/messages/<user-or-folder-id> → 404 → business_chain
            #     wedged on a correct app. Recovery targets THIS collection (a real
            #     seeded row or a freshly-created one), so it is the right resource.
            #     #59b: a CROSS-USER-DENIAL step recovers with a NON-prober token
            #     (else create-recovery mints its own row → the probe reads it →
            #     200 false leak); no such token → skip recovery.
            if _rid is None:
                _rtoken, _can_recover = token, True
                if _is_denial:
                    _rtoken, _can_recover = None, False
                    _auth_name = str(step.get("auth") or "")
                    for _vn, _vv in variables.items():
                        if (_vn != _auth_name and "token" in str(_vn).lower()
                                and isinstance(_vv, str) and _vv):
                            _rtoken, _can_recover = _vv, True
                            break
                if _can_recover:
                    _rid = _recover_id_via_list(base, _pcoll, _rtoken, avoid=own_user_id)
                    if _rid is None:
                        # even the list is empty — owner-scoped reads + a fresh
                        # chain user own NOTHING (run-29 M3): create a row (#32).
                        _rid = _recover_id_via_create(base, _pcoll, _rtoken)
            # (3) GLOBAL last_id — absolute last resort, NON-denial only. Usually
            #     the WRONG resource (a same-resource id would have won at (1)),
            #     kept only for the rare ambiguous case. A denial step must NEVER
            #     fall here — the global last_id is the prober's own most-recent
            #     id → reading it → 200 false leak; leave the literal (404s,
            #     tolerated by the denial expectation).
            if _rid is None and not _is_denial:
                _rid = last_id
            if _rid is not None:
                path = _UNRESOLVED_PLACEHOLDER.sub(str(_rid), path)
        # #67 (outlook run-53, live): UNSATISFIABLE-BY-DATA read. A positive GET
        # by-id whose placeholder STILL can't resolve — the chain user owns no
        # rows (owner-scoped empty list) AND the collection has NO POST to create
        # one (run-53: POST /api/messages → 405, the agent registered only GET
        # /api/messages this run) — is not a backend defect: the endpoint is
        # reachable (api_smoke proved it) and correctly 404s a non-existent id;
        # the chain just authored a read with no data to read. Sending the
        # LITERAL ${x} → 404 → business_chain wedged 7 cycles on a correct app.
        # SKIP it (recorded, not broken) instead. DENIAL steps still send the
        # literal (their 404 is the desired pass, #59b); non-GET writes still run
        # (a write with an unresolved FK should fail honestly, caught elsewhere).
        # placeholder check FIRST: it is True only when the resolution block above
        # ran (same path), which is where _is_denial is defined — so referencing
        # _is_denial after it is always safe (short-circuit).
        if (_UNRESOLVED_PLACEHOLDER.search(path)
                and method == "GET" and not _is_denial):
            recorded.append({
                "action": str(step.get("action") or step.get("path") or ""),
                "method": method, "path": str(step.get("path") or ""),
                "status": None, "ok": True, "kind": "skipped",
                "note": ("skipped — unsatisfiable by data: the chain user owns no "
                         + str(_pres or "row") + " and the collection cannot create one "
                         "(no POST / empty list). Endpoint reachability is proven by "
                         "api_smoke; this read has no data to target.")})
            continue
        body = _subst(step.get("body"), variables) if step.get("body") else None
        # BODY UNRESOLVED-VARIABLE FALLBACK — the body counterpart of the path fallback
        # above. A nested-FK body the verifier referenced but never saved (e.g.
        # {"calendar_id": "${calendar_id}"} after POST /api/calendars) otherwise sends
        # the literal "${calendar_id}" to an int column → 500 → business_chain wedges
        # forever on a correct app. Resolve a surviving ${...} to the most recent
        # captured resource id (untouched when the chain is wired correctly).
        if body is not None and last_id is not None:
            body = _resolve_unresolved_dollar_vars(body, last_id, last_id_by_resource)
        # (``token`` resolved above, before the path fallback that may need it for recovery.)
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
        ok = _status_ok(status, expect)
        autofilled: List[str] = []
        # MISSING-FIELD AUTO-REPAIR (2026-06-24): a write step can 422 because the
        # LIVE handler requires a body field the chain didn't send — either the
        # verifier under-authored the body, OR (observed v19: POST
        # /api/posts/{id}/comments) the endpoint's REGISTERED request schema is
        # empty so neither the verifier nor the framework's schema-driven default
        # (`_default_chain_body`) could know the field, yet the handler still
        # requires it → business_chain regresses the moment the api_coverage
        # remediation makes the verifier add a chain hitting that endpoint. The 422
        # names the exact missing field(s) in detail[].loc, so read that ground
        # truth, fill a placeholder for each (a string — the common case for these
        # CRUD bodies: content/text/caption), merge WITHOUT overriding authored
        # keys, and retry ONCE. Domain-agnostic (reads the server's own error) and
        # mirrors the auth-body-default / unresolved-var fallbacks. A wrong-typed or
        # genuinely-broken field still surfaces: the retry either resolves it or the
        # original failure is recorded (the type-mismatch retry just 422s again).
        if not ok and status in (400, 422):
            # #70 (outlook run-58, live): the step sent NO body but the handler
            # requires one (e.g. POST /api/events/{id}/rsvp needs {"response":...})
            # → FastAPI reports loc:["body"] "Field required" with NO field name,
            # so the fill below has nothing to target and the chain wedges. Re-probe
            # once with an empty {} to surface the FIELD-level 422
            # (loc:["body","response"]) whose field names the fill can then use.
            # Safe: an endpoint that takes no body ignores {}.
            if not isinstance(body, Mapping) and method in ("POST", "PUT", "PATCH"):
                _probe = _http(method, base + path, token=token, body={})
                if _probe.get("status") in (400, 422):
                    res = _probe
                body = {}
            _miss_body, _miss_query = _missing_required_fields(res.get("body_text"), method)
            _miss_body = [f for f in _miss_body
                          if not (isinstance(body, Mapping) and f in body)]
            # a required QUERY param the step didn't send (v22: GET /api/search/users
            # → missing `q`) — append it to the path's query string. Skip any already
            # present in the path so an authored `?q=` is never doubled.
            _qs_present = (path.split("?", 1)[1] if "?" in path else "")
            _miss_query = [f for f in _miss_query if (f + "=") not in _qs_present]
            if _miss_body or _miss_query:
                _filler = f"chain-{variables.get('rand', '0')}"
                _repaired = dict(body) if isinstance(body, Mapping) else (
                    body if not _miss_body else {})
                for f in _miss_body:
                    _repaired[f] = _filler
                _rpath = path
                if _miss_query:
                    _rpath += ("&" if "?" in _rpath else "?") + "&".join(
                        f"{f}={_filler}" for f in _miss_query)
                _res2 = _http(method, base + _rpath, token=token, body=_repaired)
                if _status_ok(_res2.get("status"), expect):
                    res, status, ok = _res2, _res2.get("status"), True
                    body = _repaired
                    if _miss_query:
                        path = _rpath
                    autofilled = _miss_body + [f"query:{f}" for f in _miss_query]
        # LOGIN-CREDS CARRY-FORWARD (run v22): a /auth/login that 401s "invalid
        # credentials" right after a /auth/register almost always means the chain
        # authored the login with ${rand}-based creds that DON'T match the register
        # — ${rand} mints PER STEP (the v12 multi-user fix), so register's
        # user_<base>00 and login's user_<base>01 differ → that user never existed.
        # The auth round-trip is a platform invariant (you log in with the creds you
        # just registered), so retry the login with the most recent successful
        # register's ACTUAL (substituted) email/username/password. Idempotent; only
        # when the login isn't already expected to fail. Mirrors the
        # ensure-user-before-login / auth-body-default fixes.
        if (not ok and status in (400, 401)
                and str(step.get("path", "")).rstrip("/") == "/auth/login"
                and last_reg_creds):
            _lb = dict(body) if isinstance(body, Mapping) else {}
            for _ck in ("email", "username", "password"):
                if last_reg_creds.get(_ck):
                    _lb[_ck] = last_reg_creds[_ck]
            _res3 = _http(method, base + path, token=token, body=_lb)
            if _status_ok(_res3.get("status"), expect):
                res, status, ok, body = _res3, _res3.get("status"), True, _lb
                autofilled = (autofilled or []) + ["login-creds<-register"]
        # AUTH AUTO-ATTACH (#34, outlook run-29 M3): a step that FORGOT its `auth` ref
        # (verifier authored `save: {token: access_token}` on the register but no
        # `auth: token` on the writes) hits the endpoint UNAUTHENTICATED → 401 → chain
        # broken forever on a working backend. When an expected-success step 401/403s
        # WITHOUT an auth ref and a token was saved earlier, retry once WITH it — adopt
        # the retry ONLY if it passes the authored expectation, so an isolation probe
        # that EXPECTS 401/403 (status ∈ expect → ok → no retry) is never disturbed.
        if (not ok and status in (401, 403) and not step.get("auth")
                and str(step.get("path", "")).rstrip("/") not in ("/auth/login", "/auth/register")):
            _tok2 = (variables.get("token") or variables.get("access_token")
                     or next((v for k, v in reversed(list(variables.items()))
                              if "token" in k.lower() and v), None))
            if _tok2 and _tok2 != token:
                _res5 = _http(method, base + path, token=_tok2, body=body)
                if _status_ok(_res5.get("status"), expect):
                    res, status, ok = _res5, _res5.get("status"), True
                    autofilled = (autofilled or []) + ["auth<-saved-token"]
        kind = "ok"
        note = ""
        if not ok:
            note = (res.get("error") or res.get("body_text") or "")[:160]
            if status in (404, 405):
                # 404/405 is normally 'missing' (endpoint not built yet → soft, so the
                # whole chain isn't failed on a not-yet-implemented endpoint). BUT a 404
                # from a BUILT route carries a CUSTOM detail (e.g. {"detail":"User not
                # found"}), unlike Starlette's default {"detail":"Not Found"} for an
                # UNREGISTERED path — that is a REAL flow failure (the endpoint exists and
                # rejected the request), so it must count as 'broken'. Without this a chain
                # ships status='passing' while its user-scoped steps 404 (V29 coverage_chain
                # bug: 4× '404 User not found' steps, yet broken=[] / status='passing').
                _built_404 = False
                if status == 404:
                    _bt = (res.get("body_text") or "").strip()
                    _d = _bt
                    if _bt.startswith("{"):
                        try:
                            _d = (json.loads(_bt) or {}).get("detail")
                        except Exception:
                            _d = _bt
                    _built_404 = isinstance(_d, str) and _d.strip().lower() not in ("not found", "")
                kind = "broken" if _built_404 else "missing"
            else:
                kind = "broken"
                # #78: a cross-user DENIAL step got a 2xx (apparent leak). Re-verify with a
                # GUARANTEED-fresh intruder before failing the gate — the recurring
                # false-positive (run-64, smoke-feed) is the probe running as the OWNER via a
                # stale/colliding intruder token. If a brand-new intruder is DENIED, the 2xx was
                # a probe artifact, not a real leak. Cannot mask a real leak (a genuine leak →
                # the fresh intruder ALSO succeeds → stays broken).
                if (isinstance(status, int) and 200 <= status < 300
                        and _is_cross_user_denial(step)
                        and not _reverify_denial_via_fresh_intruder(base, method, path, body, expect)):
                    kind = "skipped"
                    note = ("cross-user denial re-verified with a FRESH intruder → DENIED; the "
                            f"original {status} was a stale/owner-colliding probe token, not a "
                            "real cross-user leak (#78)")
        entry = {"action": str(step.get("action") or path), "method": method,
                 "path": path, "status": status, "ok": ok, "kind": kind,
                 "note": note}
        if autofilled:
            entry["autofilled"] = autofilled
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
                    # ALSO index by resource so a later FK body field (`${calendar_id}`)
                    # resolves to the RIGHT parent, not whatever was created most recently
                    # (fix #10: a message POST between the calendar and the event made the
                    # global last_id the message id -> events_calendar_id_fkey violation).
                    _res = _resource_from_path(path)
                    if _res:
                        last_id_by_resource[_res] = _cid
                    # The chain user's OWN id — a later recovery on an action path
                    # (follow/unfollow) must prefer a DIFFERENT row (FIX #81).
                    if str(step.get("path", "")).rstrip("/").endswith("/auth/register"):
                        own_user_id = _cid
            except Exception:
                pass
            # Capture the SUBSTITUTED creds of a successful /auth/register so a later
            # /auth/login that 401s (mismatched ${rand}, see carry-forward above) can
            # retry with the identity that actually exists.
            if str(step.get("path", "")).rstrip("/") == "/auth/register" \
                    and isinstance(body, Mapping):
                last_reg_creds = {_k: body[_k] for _k in ("email", "username", "password")
                                  if body.get(_k)}
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
            # But do NOT poison a var an EARLIER step already saved (e.g. a broken
            # register-B step that re-declares save:{token} must not invalidate the valid
            # tokenA captured by register-A → downstream auth=tokenA steps were wrongly
            # skipped, run v12). Only newly-unprovided keys become unsatisfied.
            if isinstance(step.get("save"), Mapping):
                unsatisfied.update(str(k) for k in step["save"].keys()
                                   if str(k) not in variables)
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
