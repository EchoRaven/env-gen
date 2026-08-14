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
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .validation_runner import _http, _form_retry_warranted

try:
    from .control_plane import CONTROL_SURFACE_ENDPOINTS as _CONTROL_SURFACE
except Exception:  # pragma: no cover — keep chain_executor importable in isolation
    _CONTROL_SURFACE = []

# The FIXED control-plane infra endpoints that are contractually PUBLIC
# (control_plane.py, auth_required=False) — a denial probe against one is mis-authored.
_CONTROL_PLANE_PUBLIC = frozenset(
    (str(e.get("method", "GET")).upper(), str(e.get("path", "")).rstrip("/"))
    for e in (_CONTROL_SURFACE or []) if e.get("auth_required") is False)

# #554 — the FIXED control-plane TENANT-CREATE path(s): a POST to the tenants COLLECTION
# (no trailing {param}). Its body shape is NOT pinned by the contract and the server
# generates the PK when the client omits it, so a verifier-authored create must supply a
# deterministic id (and capture it as ${tenantId}) rather than 400 / leave later steps
# unresolved. Derived from the fixed surface (not a literal) so a DB-less / no-control-plane
# app has an empty set → byte-identical.
_CONTROL_PLANE_TENANT_CREATE = frozenset(
    str(e.get("path", "")).rstrip("/")
    for e in (_CONTROL_SURFACE or [])
    if str(e.get("method", "")).upper() == "POST"
    and str(e.get("path", "")).rstrip("/").endswith("/tenants"))

# #566x — the FIXED control-plane RESET path(s). Per the contract (control_plane.py):
# "scoped (X-Tenant-Id → that tenant's business rows) or FACTORY (no header)". A chain
# step that POSTs it bare therefore takes the FACTORY branch and DELETEs every business
# row — including the seeded catalog every OTHER chain reads its ${...} ids from. The
# step itself passes (200 is the correct answer), so the damage is invisible here and
# surfaces as misleading application-level 404s in every chain that runs AFTER it.
# Derived from the fixed surface (not a literal) → an app with no control plane yields
# an empty set and the guard below is inert. See _scoped_reset_header.
_CONTROL_PLANE_RESET = frozenset(
    str(e.get("path", "")).rstrip("/")
    for e in (_CONTROL_SURFACE or [])
    if str(e.get("method", "")).upper() == "POST"
    and str(e.get("path", "")).rstrip("/").endswith("/reset"))

# The control plane's fixed tenant-scope selector (control_plane.py contract,
# test_user_squad's isolation workflow, the bundled oauth contract tests).
_TENANT_SCOPE_HEADER = "X-Tenant-Id"


def _is_factory_reset(method: Any, path: Any) -> bool:
    """True iff (method, path) is the FIXED control-plane reset endpoint — which,
    called WITHOUT a tenant scope, factory-wipes the shared business fixture."""
    return (str(method or "").upper() == "POST"
            and str(path or "").split("?", 1)[0].rstrip("/") in _CONTROL_PLANE_RESET)


def _scoped_reset_header(chain_name: Any, own_tenant_id: Any,
                         last_reg_creds: Optional[Mapping[str, Any]]) -> Dict[str, str]:
    """The ``X-Tenant-Id`` scope to send a control-plane reset with, so it deletes
    THIS chain's own rows instead of factory-wiping the shared fixture.

    Preference order — most faithful to what the step meant, first:
      1. a tenant THIS chain created (its reset is unambiguously its own to do),
      2. the chain user's registered tenant (its own business rows),
      3. a deterministic per-chain synthetic id — no such tenant exists, so the
         handler deletes NOTHING and still answers 200: the endpoint stays covered
         and reachable, with zero blast radius.
    Never harvested from ``GET /api/v1/tenants``: the first row there is typically
    the DEFAULT tenant that OWNS the seed fixture — the very thing to protect."""
    scope = own_tenant_id or (last_reg_creds or {}).get("tenant_id")
    if not (scope and str(scope).strip()):
        _slug = re.sub(r"[^A-Za-z0-9_-]", "_", str(chain_name or "chain"))[:40]
        scope = f"_fwscope_{_slug}"
    return {_TENANT_SCOPE_HEADER: str(scope)}


def _is_control_plane_public(method: Any, path: Any) -> bool:
    """True iff (method, path) is a FIXED control-plane PUBLIC infra endpoint — a
    concrete request matched against the templates, ``{param}`` = any one segment."""
    m = str(method or "GET").upper()
    reqp = str(path or "").split("?", 1)[0].rstrip("/") or "/"
    rsegs = reqp.split("/")
    for pm, tmpl in _CONTROL_PLANE_PUBLIC:
        if pm != m:
            continue
        tsegs = (tmpl or "/").split("/")
        if len(tsegs) == len(rsegs) and all(
                t.startswith("{") or t == r for t, r in zip(tsegs, rsegs)):
            return True
    return False

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
# #289: public, idempotent social interaction verbs — anyone may perform these on any public
# item, so a cross-user "isolation" denial probe on them is a category error (they return 2xx).
# A WHITELIST so sensitive actions (transfer/promote/approve/delete/ban) keep their isolation.
_SOCIAL_ACTION_VERBS = frozenset({
    "like", "unlike", "save", "unsave", "favorite", "unfavorite", "fav", "unfav",
    "follow", "unfollow", "subscribe", "unsubscribe", "share", "repost", "unrepost",
    "bookmark", "unbookmark", "pin", "unpin", "watch", "unwatch",
})
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


_SELF_ACTION_PATH_RE = re.compile(r"^(?P<coll>.*/users)/(?P<id>[^/]+)/(?P<verb>[a-z_]+)$")


def _self_targeted_social_user_action(expect, path, own_user_id):
    """#299 — recognise a SUCCESS-expecting social action (follow/subscribe/…) on
    ``/…/users/<own_user_id>/<verb>``. Such a step can NEVER pass — the app
    correctly returns 400 "cannot follow yourself" — so business_chain wedges
    (r80 M2 live: POST /api/users/81/follow, 81=the registered chain user, 6/6
    attempts → NO-CONVERGENCE ABORT). The #81 avoid-self ladder only guards an
    UNRESOLVED placeholder; a target that RESOLVED to own_user_id (a saved var, or
    a literal that collides with the minted chain-user id) slips through.

    Returns ``(users_collection_path, current_id_str)`` so the caller can
    re-target a DIFFERENT user, or None. A deliberate self-deny test
    (``expect==[400]``, no 2xx) returns None — it SHOULD self-target."""
    if own_user_id is None:
        return None
    if not any(c in _SUCCESS_CODES for c in (expect or [])):
        return None
    m = _SELF_ACTION_PATH_RE.match(str(path or "").split("?", 1)[0].rstrip("/"))
    if not m:
        return None
    if m.group("verb") not in _SOCIAL_ACTION_VERBS:
        return None
    if str(m.group("id")) != str(own_user_id):
        return None
    return (m.group("coll"), m.group("id"))


_OAUTH_AUTHORIZE_RE = re.compile(r"/oauth/authorize\b")
_OAUTH_CODE_CHALLENGE_RE = re.compile(r"code_challenge", re.I)


try:  # the owner-column vocabulary the projector fills from _fw_owner_val
    from .route_projector import _OWNER_FK_NAMES as _OWNER_FK_NAMES
except Exception:  # pragma: no cover — keep chain_executor importable in isolation
    _OWNER_FK_NAMES = ("user_id", "author_id", "owner_id", "creator_id", "created_by",
                       "account_id", "profile_id")

_WHOLE_PLACEHOLDER_RE = re.compile(r"\$\{[^}]+\}")


def _drop_unresolved_owner_fks(body: Any) -> tuple:
    """#575 — a body OWNER-FK whose ``${var}`` never resolved must be OMITTED, not guessed.

    netflix r139, live: `m2_continue_watching_state` does `GET /api/profiles` → save
    `profileA<-items.0.id`, but the chain user registered seconds earlier and OWNS NOTHING, so
    the (correctly) owner-scoped read returns `{"items": []}` and the save starves. The body
    fallback then filled `${profileA}` from the global last-id pool with **another user's**
    profile (17), so a legitimate own-scope write went out as a cross-user one and #566s
    answered 403 "profile_id does not belong to the caller" — a FAKE IDOR manufactured by the
    harness, on three M2 chains at once.

    Omitting is strictly better than guessing: the projected create already fills an ABSENT
    owner FK with the caller's own value (`valid.setdefault(ofk, _fw_owner_val(...))`, #566s),
    which is exactly what the step meant. The path-side ladder has had this rung since #32
    ("a fresh chain user owns nothing → create a row"); the body side never did.

    Returns ``(body, [dropped keys])``; non-mapping bodies pass through untouched."""
    if not isinstance(body, Mapping):
        return body, []
    dropped = [k for k, v in body.items()
               if str(k) in _OWNER_FK_NAMES and isinstance(v, str)
               and _WHOLE_PLACEHOLDER_RE.fullmatch(v.strip())]
    if not dropped:
        return body, []
    return {k: v for k, v in body.items() if k not in dropped}, dropped


def _request_identity(step: Mapping[str, Any], method: Any, path: Any, body: Any) -> tuple:
    """#566z — what makes two chain steps THE SAME REQUEST: verb, full path INCLUDING the
    query string, the actor's auth ref, and the body. Query string and auth ref are part of
    the key deliberately: `?profile_id=<foreign>` or a different token is a DIFFERENT request
    and must keep every tooth of its isolation assertion."""
    try:
        _b = json.dumps(body, sort_keys=True) if body is not None else ""
    except Exception:
        _b = str(body)
    return (str(method or "").upper(), str(path or "").rstrip("/"),
            str(step.get("auth") or ""), _b)


def unsatisfiable_expectation_pairs(steps: Sequence[Mapping[str, Any]]) -> List[tuple]:
    """#586 — pairs of steps that ask ONE request to answer two different ways.

    Same rule as #570's runtime waiver, applied at REGISTRATION so the verifier is told while
    it can still fix the chain, instead of the framework silently waiving it on every run
    forever. Runtime waivers stay as the net for chains registered by an older framework
    (#59c) — and because a waiver can only ever be as safe as its evidence, the fewer that
    have to fire, the better.

    Returns ``[(i, j, "METHOD path")]`` where step ``i`` expects a 2xx and step ``j`` expects
    ONLY non-2xx for the SAME request identity (verb + path INCLUDING query + auth ref + body).
    A different actor, query string or body is a different identity and is never paired — that
    is what keeps a genuine cross-user probe out of this.

    ONLY non-mutating pairs with NO WRITE BETWEEN THEM count. Replaying this rule over all 1843
    authored chains on disk showed why: without that condition it flags 17 chains, and 14 of
    them PASS in practice — `DELETE /api/my-list/{id}` returning 204 then 404, `POST
    /api/profiles` returning 201 then 409. Those are idempotency and duplicate-rejection tests,
    and the SAME request legitimately answers differently because the state moved underneath
    it. "One request cannot return two statuses" is only true when nothing could have changed:
    both steps read, and nothing writes in between. That leaves exactly the r132/r135/r143
    shape — consecutive GETs of the same collection demanding both 200 and 400.

    Replaying the refined rule over the same 1843 chains rejects 5: r132 and r135 (both DIED on
    it), r138 and r143 (which "pass" ONLY because #570 waives the impossible step — their
    `autofilled` carries `unsatisfiable-duplicate-expectation-waived`), and r117.

    KNOWN HOLE, stated rather than hidden: r117 passes with no waiver, because a GET here is not
    always side-effect-free — `_fw_owner_val` AUTO-PROVISIONS the caller's owner row on read, so
    the first read can change what the second one sees. Such a chain is still self-contradictory
    and passes only by accident of ordering, and the rejection message tells the verifier how to
    express what it meant, so the trade is deliberate: 5 rejections in 1843 authored chains
    (0.3%), against a family that killed 2 runs outright and misled a lane into breaking 4 more
    chains in r132."""
    _writes = [i for i, st in enumerate(steps or [])
               if isinstance(st, Mapping)
               and str(st.get("method") or "GET").upper() not in ("GET", "HEAD", "OPTIONS")]
    succ: Dict[tuple, int] = {}
    deny: Dict[tuple, int] = {}
    for i, st in enumerate(steps or []):
        if not isinstance(st, Mapping):
            continue
        if str(st.get("method") or "GET").upper() not in ("GET", "HEAD"):
            continue          # a mutating step changes what the next answer may be
        _exp = st.get("expect")
        if _exp is None:
            codes: List[int] = []
        elif not isinstance(_exp, (list, tuple, set)):
            codes = [int(_exp)] if str(_exp).isdigit() else []
        else:
            codes = [int(x) for x in _exp if str(x).isdigit()]
        key = _request_identity(st, st.get("method") or "GET",
                                str(st.get("path") or ""), st.get("body"))
        if not codes or any(200 <= c < 300 for c in codes):
            succ.setdefault(key, i)
        else:
            deny.setdefault(key, i)
    out: List[tuple] = []
    for key, j in deny.items():
        i = succ.get(key)
        if i is None:
            continue
        lo, hi = (i, j) if i < j else (j, i)
        if any(lo < w < hi for w in _writes):
            continue          # something wrote in between — the answer may legitimately differ
        out.append((i, j, f"{key[0]} {key[1]}"))
    return sorted(out)


#591 — the MIRROR of #586. #586 rejects an expectation nothing can satisfy; this rejects one
# NOTHING CAN FALSIFY. A BUSINESS step whose `expect` accepts both a 2xx and 401/403 passes
# whether the app served the data or refused the caller, so it verifies nothing about access
# control — while still counting toward the green chain total the delivery gate reads.
#
# Measured over the arc's 1682 chains / 5861 business steps carrying an explicit expectation:
# 56 such steps in 16 runs, and they sit on exactly the resources every owner-scoping leak in
# this arc lived on — `/api/my-list` x26, `/api/titles/{id}/rating` x8, `/api/continue-watching`
# x6, `/api/profiles` x2. r133 (the #568 live cross-user leak) has 12; r142, one of the three
# *** MULTI-MILESTONE VALIDATED *** runs, has 13.
#
# Scope is deliberately narrow. CONTROL-PLANE paths are exempt: on /auth, /oauth, /api/v1/*,
# /health and /.well-known a chain legitimately means "this surface exists and answers sanely"
# and cannot know whether its user is an admin — 710 steps arc-wide accept a 2xx together with
# some 4xx, and 654 of them are exactly that. 409 (already exists) and 404 (already gone) are
# NOT denial codes and never trip this: `POST /auth/register [200,201,409]`, the single most
# common wide expectation in the arc, is untouched.
_UNDECIDABLE_DENIAL_CODES = (401, 403)
_CHAIN_CONTROL_PREFIXES = ("/auth", "/oauth", "/api/v1/", "/health", "/.well-known", "/mcp")


def undecidable_access_expectations(steps: Sequence[Mapping[str, Any]]) -> List[tuple]:
    """#591 — business steps that pass whether the request was served OR denied.

    Returns ``[(i, "METHOD path", sorted_codes)]``. A step is only reported when its expectation
    is EXPLICIT (an absent expect means "must succeed" and is decidable), names at least one 2xx
    AND at least one of 401/403, and targets a business path."""
    out: List[tuple] = []
    for i, st in enumerate(steps or []):
        if not isinstance(st, Mapping):
            continue
        path = str(st.get("path") or "")
        bare = path.split("?", 1)[0]
        if not bare or bare.startswith(_CHAIN_CONTROL_PREFIXES):
            continue
        _exp = st.get("expect")
        if _exp is None:
            continue
        if not isinstance(_exp, (list, tuple, set)):
            codes = [int(_exp)] if str(_exp).isdigit() else []
        else:
            codes = [int(x) for x in _exp if str(x).isdigit()]
        if not codes:
            continue
        if any(200 <= c < 300 for c in codes) and any(
                c in _UNDECIDABLE_DENIAL_CODES for c in codes):
            out.append((i, f"{str(st.get('method') or 'GET').upper()} {bare}",
                        sorted(set(codes))))
    return out


def _authored_success_identities(steps: Sequence[Mapping[str, Any]]) -> set:
    """#570 — the request identities the chain ITSELF expects to SUCCEED somewhere.

    #566z only waived a contradictory step when the identical request had ALREADY succeeded
    EARLIER in the chain, and its test pinned that order-dependence as deliberate ("no earlier
    success to contradict"). netflix r135 proved the reasoning wrong: steps [6][7][8] were the
    same request by the same actor expecting [400], [200], [403]. [8] was waived and [6] was
    not — purely because it sat before the success. The contradiction is a property of the
    AUTHORED CHAIN, not of execution order, and the waiver's safety (same actor, so no second
    identity is involved) does not depend on order either. Computed on the AUTHORED steps, so
    both sides of the comparison are pre-substitution and always agree.

    A step "expects success" when its expect list contains a 2xx or is absent (the default)."""
    out: set = set()
    for st in (steps or []):
        if not isinstance(st, Mapping):
            continue
        _exp = st.get("expect")
        if _exp is None:
            codes: List[int] = []
        elif not isinstance(_exp, (list, tuple, set)):
            codes = [int(_exp)] if str(_exp).isdigit() else []
        else:
            codes = [int(x) for x in _exp if str(x).isdigit()]
        if codes and not any(200 <= c < 300 for c in codes):
            continue
        out.add(_request_identity(st, st.get("method") or "GET",
                                  str(st.get("path") or ""), st.get("body")))
    return out


def _is_bare_self_scoped_read(step: Mapping[str, Any], method: Any, path: Any,
                              body: Any) -> bool:
    """#580 — an AUTHENTICATED read that names no foreign identifier can only ever return the
    caller's OWN scope, so demanding that it be REJECTED is unsatisfiable by construction.

    Seen in r132, r135, r139, r141 and r143 — the recurring shape is a chain asserting that a
    bare collection read must 400/403:

        [5] GET /api/continue-watching  auth=tokenA  expect=[400]   -> 200 {"items":[]}
        [6] GET /api/continue-watching  auth=tokenB  expect=[403]   -> 200 {"items":[]}

    The verifier means "no profile selected -> reject", but the framework's own contract does
    the opposite: `_fw_owner_val` resolves (and provisions) the caller's own scope, so the read
    succeeds with the caller's own — possibly empty — data. #566z/#570 cannot help here: no
    sibling step claims this request should succeed, so there is nothing to contradict.

    The proof that no cross-user access is being probed is in the REQUEST, not a heuristic: a
    GET with an auth ref, no query string, no path parameter and no body addresses exactly one
    scope — the caller's. Any of those carriers present (``?profile_id=10``,
    ``/api/x/{other}``, a body owner FK) means a foreign id COULD be named, and this returns
    False so the probe keeps every tooth."""
    if str(method or "").upper() != "GET":
        return False
    if not str(step.get("auth") or "").strip():
        return False            # unauthenticated -> a genuine 401 probe
    if body:
        return False
    raw = str(path or "")
    if "?" in raw or "#" in raw:
        return False            # a query string can carry a foreign id
    segs = [s for s in raw.split("/") if s]
    if not segs:
        return False
    # a trailing/embedded identifier segment (numeric, uuid-ish, or a leftover placeholder)
    for s in segs[1:]:
        if s.isdigit() or "${" in s or "{" in s or re.fullmatch(r"[0-9a-fA-F-]{8,}", s):
            return False
    return True


def _oauth_authorize_lacks_pkce(path, body) -> bool:
    """#301+#316 — a /oauth/authorize step that carries NO ``code_challenge`` cannot
    complete on a PKCE-enforced AS: it correctly 400/422s ("code_challenge with S256
    is required") and can NEVER pass — whether it is a fully BARE probe (#301, no flow
    params at all) OR a PARAMS-BEARING step that merely omits the PKCE challenge (#316,
    r86 final NO-CONVERGENCE ABORT: a framework-synthesized chain hit
    ``/oauth/authorize?response_type=code&client_id=..&redirect_uri=..&state=xyz`` → 400
    and, having client_id/response_type, was treated as NOT-bare → not tolerated → the
    business_chain gate never went green → 75min abort even though every real PKCE flow
    passed). Tolerate its 4xx so a synthesized probe can't wedge business_chain.

    The discriminator is the PKCE ``code_challenge``, NOT the presence of any flow
    param (that was #301's bug this fixes): a step that DOES carry ``code_challenge`` is
    the REAL PKCE flow and MUST pass — a 4xx there is a genuine bug, never tolerated.
    Same family as #281 (oauth Form) / #289 (denial probe) / #299 (self-follow)."""
    if not _OAUTH_AUTHORIZE_RE.search(str(path or "")):
        return False
    hay = str(path or "")
    try:
        if body:
            hay += " " + json.dumps(body)
    except Exception:
        pass
    return not _OAUTH_CODE_CHALLENGE_RE.search(hay)


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
        # #235 BOOTSTRAP-SYNONYM COLLAPSE (tiktok r25, live): the contract may name its
        # auth entry points signup/signin — r25's chains authored POST /api/auth/signup,
        # which bypassed EVERY auth invariant below (canonical save, expect-union,
        # body-default, auth-first reorder) exactly like the #79 /api-prefix bypass →
        # the token-minting step 401'd → business_chain failed for 108min →
        # NO-CONVERGENCE ABORT. Collapse the synonym to the canonical AS path (the
        # skeleton serves the synonym as an alias of the SAME handler, so this is a
        # pure spelling change) so all invariants apply.
        _bs_syn = re.match(r"^(?:/api)?/auth/(signup|signin)$", pth)
        if _bs_syn:
            pth = "/auth/" + {"signup": "register", "signin": "login"}[_bs_syn.group(1)]
            st["path"] = pth
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
            # #235: the bootstrap step MINTS the token — a verifier-authored
            # auth="token" on it is self-dependent (r25: unresolvable ${token}
            # sent as a garbage bearer on the chain's FIRST step). Always tokenless.
            st.pop("auth", None)
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
        # #321 (r90 M-final): the guard was `not body` — it filled only a MISSING/empty
        # body, so a step with a PARTIAL body that omits email/password (verifier modelled
        # a username/phone signup, or authored `{username: ...}`) still 422'd "email and
        # password are required" and wedged business_chain 6/6 attempts. setdefault the
        # required creds onto whatever body is there instead — fills the missing keys,
        # never clobbers authored ones; ${rand} keeps emails unique for isolation chains.
        if pth in ("/auth/register", "/auth/login"):
            _had_body = bool(isinstance(st.get("body"), Mapping) and st.get("body"))
            _ab: Dict[str, Any] = dict(st["body"]) if isinstance(st.get("body"), Mapping) else {}
            _ab.setdefault("email", "chain_${rand}@example.com")
            _ab.setdefault("password", "Chain123!x")
            # name is OPTIONAL — add it only when filling a fully-empty body (old bodyless
            # behavior); never enrich an AUTHORED body beyond the required creds, or an
            # authored {email,password} step would no longer round-trip byte-for-byte.
            if pth == "/auth/register" and not _had_body:
                _ab["name"] = "Chain Tester"
            st["body"] = _ab
        # #554 CONTROL-PLANE TENANT-CREATE BODY DEFAULT + SAVE (mirrors the #321 auth-body-
        # default just above): the tenant control plane is a FIXED framework contract that
        # pins method+path but NOT body shape; the body-tolerant framework handler generates
        # the PK when the body omits it (never 400). A verifier authors the create the natural
        # way — POST /api/v1/tenants {"name": ...} or body-less — with NO id, and later steps
        # reference ${tenantId} that NOTHING saves (POST /api/v1/admin/init-tenant, DELETE
        # /api/v1/tenants/${tenantId} both break). So setdefault a DETERMINISTIC id (from the
        # step index — no clock/random) onto the body AND save the created id as `tenantId` so
        # those later steps resolve. Byte-identical when N/A: the set is empty for a no-control-
        # plane app, and a create that already carries id/tenant_id keeps it (setdefault never
        # clobbers; the save still captures whatever id the server returns).
        if (pth in _CONTROL_PLANE_TENANT_CREATE
                and str(st.get("method", "")).upper() == "POST"):
            _tb = dict(st["body"]) if isinstance(st.get("body"), Mapping) else {}
            if not (_tb.get("id") or _tb.get("tenant_id")):
                _tb["id"] = f"tenant_{i}"
            st["body"] = _tb
            _tsave = dict(st.get("save") or {})
            _tsave.setdefault("tenantId", "id")
            st["save"] = _tsave
        _authored_auth = st.get("auth")          # #266: remember who asked for it
        if pth.startswith("/api/") and not st.get("auth"):
            st["auth"] = "token"
        # FIX #91 (instagram run-11, live): a step expecting EXACTLY {401} is an
        # UNAUTHENTICATED-DENIAL probe by definition — a valid token defeats its own
        # expectation. The verifier authored `auth:"token", expect:[401]` (and the
        # auto-bearer above would add auth anyway) → the CORRECT backend returns 200
        # → chain wedges forever. Strip the contradictory auth so the probe really
        # goes tokenless. Cross-user denial probes (403/404 expectations, intruder
        # tokens) are untouched — only the pure-{401} shape is tokenless semantics.
        _exp401 = st.get("expect")
        _exp401 = _exp401 if isinstance(_exp401, (list, tuple, set)) else (
            [_exp401] if _exp401 is not None else [])
        _codes401 = {int(x) for x in _exp401 if str(x).isdigit()}
        if _codes401 == {401}:
            st.pop("auth", None)
        elif (401 in _codes401
              and not (_codes401 & _SUCCESS_CODES)
              and str(_authored_auth or st.get("auth")) == "token"):
            # #266 (r57, live): the SAME contradiction, written the natural way. A probe
            # meaning "must be rejected" is usually authored expect=[401, 403] because an
            # app may answer either — which #91's exact-{401} test misses, so the
            # auto-bearer above stayed and the "anonymous" probe went out AUTHENTICATED.
            # r57: POST /api/videos/<id>/like -> 201 against expect=[401, 403], on an app
            # whose get_current_user correctly 401s without a token. 11 of 12 chains were
            # green and this one could not pass no matter what any lane did.
            # A CROSS-USER probe carries a different actor's token (auth="tokenB") and is
            # left alone: stripping it would still satisfy the assertion via 401 while
            # silently ending the isolation check that is its entire purpose.
            st.pop("auth", None)
        # #275 (r60, live): an anonymous LOGOUT is a legitimate no-op. The unauth_guard chain
        # asserted POST /api/auth/logout anon expect=[401, 403]; the app answered 200 and the
        # chain failed — but logout is an idempotent auth-control action ("end whatever session
        # you have"), and a correct app answers it 200/204 as readily as 401. resolve_endpoint_
        # auth (#271) already treats /auth/logout as anonymous-accessible, so app + framework
        # agree; only the probe is too strict and no lane can fix a correct logout. Widen a
        # denial probe on an idempotent control-surface endpoint to ALSO accept 2xx, so it
        # passes whether the app rejects OR no-ops. Real protected endpoints are untouched.
        _p275 = str(st.get("path") or "").lower().rstrip("/")
        _is_logout = _p275.endswith(("/logout", "/signout", "/sign-out", "/log-out"))
        if _is_logout and 401 in _codes401 and not (_codes401 & _SUCCESS_CODES):
            _widened = sorted(_codes401 | {200, 204})
            st["expect"] = _widened
        # FIX #289 (tiktok r74, live): the same principle for the SOCIAL-ACTION surface. A
        # like/save/follow/share is PUBLIC (#288 made those parents public) and idempotent —
        # there is NO per-user isolation to assert, so a cross-user denial probe on one
        # (POST /api/videos/{id}/like auth=tokenA expect=[404]) can never pass on a correct app
        # (it returns 201). r74's tenant_isolation_like wedged business_chain exactly this way,
        # with the whole frontend already green -> NO-CONVERGENCE ABORT. Widen a denial probe
        # (403/404, no 2xx) whose path TAIL is a WHITELISTED public social verb to also accept
        # 2xx. A whitelist -- NOT "any action suffix" -- so sensitive verbs (/transfer,/promote,
        # /approve,/delete,/ban) keep cross-user isolation and a real leak still fails.
        _tail289 = _p275.rsplit("/", 1)[-1] if "/" in _p275 else _p275
        if (_tail289 in _SOCIAL_ACTION_VERBS
                and (_codes401 & {403, 404}) and not (_codes401 & _SUCCESS_CODES)):
            st["expect"] = sorted(_codes401 | {200, 201, 204})
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
    # FIX #192a — framework-injected cross-user isolation probe. Empirical
    # (2026-07-18): the last 5 SUCCESS archives carry ZERO denial steps — a pure
    # 2xx sweep can't distinguish a tenancy-enforcing backend from one returning
    # dummy 2xx (smoke_feed_77: a cross-user MUTATE returned 200, ungated). When
    # the chain has no denial step but DOES register an authed user and create a
    # row on a bare /api/<coll> (id saved), append the framework's own probe:
    # intruder PUT on the standard item shape — served by the PROJECTED
    # owner-safe write handler BY CONSTRUCTION (writes stay projected), so a
    # legit app denies (403/404; 401 for token quirks) and a leaky one 2xxes and
    # fails honestly. Bare-collection creates ONLY: action paths (/x/{id}/like)
    # may hit custom handlers with body-validation-before-ownership (422 risk).
    try:
        _has_denial = any(
            (lambda _e: any(str(c) in ("401", "403") for c in (
                _e if isinstance(_e, (list, tuple, set)) else [_e])))(s.get("expect"))
            for s in out) or any(
            str(s.get("action", "")).startswith("framework_isolation_probe")
            for s in out)
        if not _has_denial:
            _probe_target = None
            for s in out:
                _p = str(s.get("path", "")).split("?", 1)[0].rstrip("/")
                _segs = [x for x in _p.strip("/").split("/") if x]
                if (str(s.get("method", "")).upper() == "POST"
                        and len(_segs) == 2 and _segs[0] == "api"
                        and not _segs[1].startswith("{")
                        and "$" not in _segs[1]
                        and s.get("auth")
                        and isinstance(s.get("save"), Mapping) and s["save"]):
                    _idvar = next(iter(s["save"].keys()))
                    _probe_target = (_p, str(_idvar))
                    break
            if _probe_target:
                _coll_path, _idvar = _probe_target
                if not any(_INTRUDER in (s.get("save") or {}) for s in out):
                    out.insert(0, {
                        "method": "POST", "path": "/auth/register",
                        "body": {"email": "intruder_${rand}@example.com",
                                 "password": "Chain123!x", "name": "Chain Intruder"},
                        "save": {_INTRUDER: "access_token"},
                        "expect": [200, 201, 409],
                    })
                out.append({
                    "action": "framework_isolation_probe_"
                              + _coll_path.rsplit("/", 1)[-1],
                    "method": "PUT",
                    "path": _coll_path + "/${" + _idvar + "}",
                    "auth": _INTRUDER, "body": {},
                    "expect": [401, 403, 404],
                })
    except Exception:
        pass  # best-effort: a probe-injection fault must never break authoring
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


def _missing_write_defect_chain(
    endpoints: List[Mapping[str, Any]],
    tables: Optional[Mapping[str, Any]],
    flows: Optional[Sequence[str]],
) -> Optional[Dict[str, Any]]:
    """R2(b): a chain of SYNTHETIC-DEFECT steps, one per state-bearing entity / feature
    flow the DECLARED contract can READ but not WRITE (the #557 classifier — the SAME
    detection the oracle + the route-projector heal share). ``synthesize_default_chain``
    today returns [] when the contract has no creatable collection, so a missing write-
    path is silently produced-nothing; this makes the gap surface as ``framework_defect``s
    on the chain gate (execute_chain records each without an HTTP call). Returns ``None``
    (⇒ output byte-identical) when no table/flow is supplied or nothing is missing."""
    if not tables and not flows:
        return None
    try:
        from .completeness_audit import (
            state_entities_missing_write, check_flow_no_write)
    except Exception:
        return None
    eps_dict = {i: dict(e) for i, e in enumerate(endpoints or [])
                if isinstance(e, Mapping)}
    steps: List[Dict[str, Any]] = []
    seen: set = set()

    def _slug(s: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", str(s or "").strip().lower()).strip("-")

    try:
        missing_state = state_entities_missing_write(dict(tables or {}), eps_dict)
    except Exception:
        missing_state = {}
    for entity, cols in sorted(missing_state.items()):
        key = _slug(entity)
        if not key or key in seen:
            continue
        seen.add(key)
        col_txt = ", ".join(cols) or "its state"
        steps.append({
            "action": f"framework_missing_write_path_{key}",
            "method": "POST", "path": f"/api/{key}", "synthetic_defect": True,
            "note": (f"state-bearing entity `{entity}` (mutable field(s): {col_txt}) has a "
                     f"GET but NO POST/PUT/PATCH endpoint — the feature can be READ but never "
                     f"WRITTEN (missing_write_path). Declare + implement a write endpoint for "
                     f"`{entity}` so its state can persist."),
        })
    try:
        flow_findings = check_flow_no_write(None, eps_dict, list(flows or []),
                                            dict(tables or {}))
    except Exception:
        flow_findings = []
    for r in flow_findings:
        flow = getattr(r, "flow", None) or ""
        key = _slug(flow)
        if not key or key in seen:
            continue
        seen.add(key)
        steps.append({
            "action": f"framework_missing_write_path_{key}",
            "method": "POST", "path": f"/api/{key}", "synthetic_defect": True,
            "note": (f"declared flow `{flow}` implies a mutation (verb "
                     f"`{getattr(r, 'missing_verb', None)}`) but no POST/PUT/PATCH endpoint "
                     f"backs it (missing_write_path) — the flow can be viewed but not performed."),
        })
    if not steps:
        return None
    return {"name": "framework_missing_write_paths", "steps": steps}


def synthesize_default_chain(
    endpoints: List[Mapping[str, Any]],
    *,
    tables: Optional[Mapping[str, Any]] = None,
    flows: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    """Project a default verification chain DETERMINISTICALLY FROM THE REGISTERED
    CONTRACT: register → for each business collection, create (saving the row id)
    → list → read-by-id → update → delete. This is generic projection (like
    ``_probe_body`` / route_projector), NOT a hand-rolled app-shaped journey — so
    it carries NO app bias and satisfies the generality principle. Used only as a
    FILL-IN when the verifier registered no usable chain.

    R2(b): when ``tables``/``flows`` is supplied, ALSO append a
    ``framework_missing_write_paths`` chain of synthetic-defect steps for every
    state-bearing entity / mutation flow the contract can READ but not WRITE (the
    #557 classifier) — so a MISSING write-path surfaces as a ``framework_defect`` on
    the chain gate instead of being silently produced-nothing. Returns [] only when
    the contract exposes no creatable business resource AND nothing is missing a write
    (then the verifier-authoring feedback path still applies); byte-identical to the
    prior behaviour when ``tables``/``flows`` is omitted or nothing is missing."""
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

    # R2(b): missing-write-path defects surface EVEN WHEN no creatable collection exists —
    # built separately (NOT through normalize_steps, which would mutate a synthetic step) so
    # they ride their own chain. `None` when nothing is missing → prior behaviour preserved.
    defect_chain = _missing_write_defect_chain(eps, tables, flows)
    out_chains: List[Dict[str, Any]] = []
    if made_any:
        norm, _errs = normalize_steps(steps)
        if norm:
            out_chains.append({"name": "framework_default_crud", "steps": norm})
    if defect_chain is not None:
        out_chains.append(defect_chain)
    return out_chains


def load_seed_ids(project_dir: Any) -> Dict[str, Any]:
    """FIX #144: {table → first explicit non-None row id} from the authored
    app/backend/seed_data.json. These ids are guaranteed present after every
    clean boot (#130/#135), making them a deterministic recovery source for
    literal-id 404s — immune to the collection-name mismatch that defeats
    live-list recovery (posts listed via /api/feed, not /api/posts)."""
    out: Dict[str, Any] = {}
    try:
        p = Path(project_dir) / "app" / "backend" / "seed_data.json"
        if not p.exists():
            return out
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, Mapping):
            return out
        for table, rows in data.items():
            if not isinstance(rows, list):
                continue
            # FIX #283 (tiktok r68, live): #144 assumed the authored seed DECLARES ids —
            # nothing ever enforced that. r68's seed carried 23 videos / 10 sounds / 5 users
            # with NOT ONE `id`, while the same file's FKs already assumed positional
            # autoincrement (videos[0].author_id=1 → users[0]; likes[0].video_id=2 →
            # videos[1]). load_seed_ids returned {} and the literal-id recovery ladder lost
            # its deterministic rung. So: an explicit id still WINS wherever one exists
            # (real data beats a guess, even if it appears in a later row); only when the
            # table declares none do we fall back to the id the DB is about to assign on a
            # clean boot — the row's 1-based position, exactly what the seed's own FKs point
            # at. Type-safe by construction: these ids are consumed ONLY to replace a NUMERIC
            # literal in a path, so a text/uuid-PK table is never reached this way.
            # A pure ASSOCIATION row (every column an FK: {follower_id, followee_id},
            # {user_id, video_id}) has a COMPOSITE pk and no `id` column at all — inventing
            # one would be fabricating a column that does not exist, so those tables stay
            # absent exactly as before. A row carrying real data columns (users: email/name,
            # videos: video_url/caption) is an id-bearing table whose seed merely omitted it.
            positional: Any = None
            for idx, row in enumerate(rows, start=1):
                if not isinstance(row, Mapping):
                    continue
                if row.get("id") is not None:
                    out[str(table)] = row["id"]
                    positional = None
                    break
                if positional is None and any(
                        not str(k).endswith("_id") for k in row):
                    positional = idx
            if positional is not None and str(table) not in out:
                out[str(table)] = positional
    except Exception:
        return {}
    return out


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
            # R2(b): also feed the TABLE contract so a state-bearing entity with no write
            # endpoint surfaces as a framework_defect (missing_write_path) even when the
            # contract has no creatable collection to project a CRUD chain from.
            tbls: Dict[str, Any] = {}
            try:
                tbl_path = Path(project_dir) / "shared" / "hubs" / "registryhub_tables.json"
                if tbl_path.exists():
                    tbl_data = json.loads(tbl_path.read_text(encoding="utf-8"))
                    tbls = {k: v for k, v in (tbl_data or {}).items()
                            if k != "_meta" and isinstance(v, Mapping)}
            except Exception:
                tbls = {}
            return synthesize_default_chain(eps, tables=tbls)
    except Exception:
        pass
    return out


def _is_idx(part: Any) -> bool:
    """#566m: True iff ``part`` is an integer list index (``0`` / ``-1`` / ``"2"``)."""
    s = str(part)
    return s.lstrip("-").isdigit()


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
        elif isinstance(cur, list) and _is_idx(part):
            # #566m: a numeric index into a BARE list — e.g. save "0.id" against a list
            # endpoint that ships a bare array (not the {items:[...]} envelope). r123's
            # GET /api/profiles returns `[ {id,...} ]`; the old resolver returned None here,
            # so `${pid}` fell back to a FOREIGN id (1) → profile-scoped reads 403'd
            # (business_chain "profile IDOR").
            i = int(part)
            if not (-len(cur) <= i < len(cur)):
                return None
            cur = cur[i]
        elif isinstance(cur, Mapping) and _is_idx(part):
            # #566m: a numeric index applied to a {items|data|results|rows:[...]} envelope.
            _env = next((cur[k] for k in ("items", "data", "results", "rows")
                         if isinstance(cur.get(k), list)), None)
            if _env is None:
                return None
            i = int(part)
            if not (-len(_env) <= i < len(_env)):
                return None
            cur = _env[i]
        else:
            return None
    return cur


def _dig(payload: Any, dotted: str) -> Optional[Any]:
    parts = str(dotted).split(".")
    # #566m: try the full path, then progressively STRIP leading segments. A verifier
    # routinely prefixes the save-path with a wrong wrapper/resource key — "items.0.id"
    # against a BARE list, "note.id"/"data.id"/"response.note.id" against {item:{id}}.
    # Stripping resolves "items.0.id" → "0.id" (bare list) and "note.id" → "id"; the LONGER
    # correct path always wins because it is tried first, so a real nested path is never
    # overridden. Subsumes the prior single-leaf fallback (last iteration is [parts[-1]]).
    for _start in range(len(parts)):
        val = _dig_path(payload, parts[_start:])
        if val is not None:
            return val
    return None


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
        # FIX #114 (run-30 STUCK, live-replayed): the platform register/login envelope
        # is {"access_token":…, "user":{"id":N}} — no top-level id/item/items — so the
        # chain's FIRST step captured nothing and the global-last-id rung starved; a
        # later action path whose every other rung dead-ends (no bare collection, not
        # a users resource) sent the LITERAL {id} → 422 → 7-cycle wedge → STUCK abort.
        # Accept the id of a nested one-level dict when the payload has EXACTLY ONE
        # such dict (unambiguous). Register precedes everything (authoring rule +
        # normalize's ensure-user-before-login), so last_id is now always populated.
        nested = [v["id"] for v in payload.values()
                  if isinstance(v, Mapping) and v.get("id") is not None]
        if len(nested) == 1:
            return nested[0]
    return None


# A path placeholder the verifier left unresolved: ``${msg_id}`` / ``${var.x}``, a
# bare ``{id}`` (never a substituted value, since saved vars are replaced first), or —
# FIX #89 (instagram run-8 live) — python-format EMPTY/positional braces ``{}``/``{0}``
# (the alpha-first-char requirement made the whole recovery ladder BLIND to them: the
# literal ``/api/posts/{}/like`` hit the int path param → 422 → 7-cycle wedge → STUCK).
_UNRESOLVED_PLACEHOLDER = re.compile(r"\$\{[^}]+\}|\{[a-zA-Z_][^}]*\}|\{\d*\}")
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
    # FIX #104 (instagram run-21 M3, live): a MIXED list (expect [200, 404] — "success
    # OR tolerated-404") disabled the all-2xx family rule, so an actual 201 wedged the
    # chain on a working flow. The verifier's success ARM is still family-toleranced:
    # a 2xx actual passes when the expect contains ANY 2xx member. Pure denial probes
    # ([401] / [403,404]) contain no 2xx and still reject every success status.
    return (isinstance(status, int) and 200 <= status < 300
            and any(isinstance(e, int) and 200 <= e < 300 for e in expect))


# A plain-string 4xx detail ('text is required', 'missing field email') — some
# hand-authored handlers raise HTTPException(400, "text is required") instead of
# letting Pydantic emit the structured 422 loc[] list. Extract the field name so a
# write step can still auto-fill it (observed v22: POST /api/posts/{id}/comments
# → 400 "text is required" — this backend's comment field is `text`, not `content`).
_REQUIRED_FIELD_RE = re.compile(
    r"(?:field\s+)?['\"]?([A-Za-z_]\w*)['\"]?\s+(?:is\s+)?required"
    r"|missing\s+(?:required\s+)?(?:field\s+)?['\"]?([A-Za-z_]\w*)",
    re.IGNORECASE)

# #411 (netflix r7/r8, live): a create step that inserted an explicit NULL for a
# required NO-DEFAULT column 400s with psycopg ``null value in column "X" violates
# not-null constraint`` (code 23502) — NOT a Pydantic 422, so _REQUIRED_FIELD_RE /
# the structured-422 branch miss it, and the chain wedges (r8: POST /api/my-list →
# 400 null title_id; the verifier omitted title_id because the endpoint's request
# schema never declared it). Recover column X so the fill+retry sends it. SKIP the
# DB-defaulted / system columns a handler must OMIT (id + created_at/updated_at and
# any *_at timestamp): filling those with a literal would fight the DDL DEFAULT (see
# #407/#409) — the fix there is the handler omitting them, not the chain sending one.
_NOT_NULL_COL_RE = re.compile(
    r'null value in column\s+\\?["\']?([A-Za-z_]\w*)', re.IGNORECASE)
_NULLFILL_SKIP_COLS = {"id", "created_at", "updated_at"}


def _notnull_missing_cols(body_text: "Optional[str]", method: str) -> "List[str]":
    """#411: required NO-DEFAULT columns a create OMITTED, named by a NOT-NULL 400
    (``null value in column "X"``, surfaced by backend_scaffold #411). Text scan —
    tolerates JSON-escaped (``\\"X``) or plain quotes and a non-JSON body. SKIPs the
    DB-defaulted / system cols a handler must OMIT (id + created_at/updated_at + any
    ``*_at``): filling those fights the DDL DEFAULT (#407/#409), the wrong fix."""
    out: "List[str]" = []
    if method not in ("POST", "PUT", "PATCH"):
        return out
    for _m in _NOT_NULL_COL_RE.finditer(body_text or ""):
        _c = _m.group(1)
        if (_c and _c not in out and _c.lower() not in _NULLFILL_SKIP_COLS
                and not _c.lower().endswith("_at")):
            out.append(_c)
    return out


# #272: framework-projected-defect classifier (Hatch design principle #5 — separate "my
# framework code is broken" from "the app the lane wrote is broken"). A projected handler is
# named ``_projected_*`` by route_projector, so a 5xx whose traceback names one is, by
# definition, a bug in framework-emitted code the lane cannot touch. #263/#270/#271 were all
# this shape and were recorded as ``broken`` app endpoints, sending lanes to fix handlers
# they never wrote. Narrow on purpose: only a 5xx + a ``_projected_`` traceback qualifies; a
# 4xx (a contract/data outcome) or a lane-authored traceback stays a normal app failure.
_PROJECTED_TRACEBACK_RE = re.compile(r"backend traceback:[^\n]*\b_projected_[a-z0-9_]+", re.I)


def _unknown_id_hint_682(status, body, note) -> str:
    """Name the id the step actually sent, when the server says it does not exist."""
    try:
        if status not in (403, 404) or not isinstance(body, Mapping):
            return ""
        low = str(note or "").lower()
        _absent = "not found" in low or "referenced resource" in low
        # #682b: the SAME root, one status along. r145's most frequent business_chain failure
        # (15 of them) was `403 {"detail":"profile_id does not belong to the caller"}` against an
        # expectation of [200, 201, 400, 404] — the chain used a profile it had not created, just
        # as the 404 case used a title id from the asset namespace. Both are an id the step did
        # not source from the system. The 403 wording must not suggest the SERVER is wrong: an
        # ownership refusal is correct behaviour, and the step is what needs changing.
        _foreign = status == 403 and ("does not belong" in low or "not owned" in low
                                      or "belong to the caller" in low)
        # #682c: a 400 that spells out the accepted values. r145's third stuck chain was
        # `POST /api/titles/1/rating -> 400 {"detail":"value must be up|down|love"}` against a
        # chain sending `value: 'like'`. The server named the answer and the chain still sat red
        # for 75 minutes: the backend re-registered the ENDPOINT schema twice, but nobody changed
        # the CHAIN. The enum exists only in custom_routes.py — the registered schema says
        # `value: 'str'`, and across the corpus only 1 of 4013 endpoint schemas declares an enum,
        # so the author could not have known it up front and cannot learn it except from here.
        # Naming the remedy matters as much as the values: re-registering under the SAME name
        # REPLACES a failing chain (registryhub only short-circuits when the stored one is
        # already passing with identical steps), and nothing had ever said so.
        _enum = None
        if status == 400:
            _m = re.search(r"must be\s+([A-Za-z0-9_]+(?:\s*\|\s*[A-Za-z0-9_]+)+)", str(note or ""))
            if _m:
                _enum = _m.group(1)
        if not (_absent or _foreign or _enum):
            return ""
        sent = [(k, v) for k, v in body.items()
                if re.search(r"(^|_)id$", str(k)) and not isinstance(v, (dict, list))
                and str(v).strip() and "${" not in str(v)]
        if not sent:
            return ""
        if _enum:
            _vals = [v for v in (body or {}).values()
                     if isinstance(v, str) and "${" not in v]
            _sent = f"you sent {_vals[0]!r}; " if _vals else ""
            return (f" — {_sent}the endpoint accepts only [{_enum}]. That set is enforced in the "
                    "implementation and is NOT in the registered schema, so re-register the "
                    "endpoint with the allowed values AND fix this step: re-registering a chain "
                    "under the SAME name replaces it while it is failing.")
        named = "; ".join(f"{k}={v!r}" for k, v in sent[:3])
        if _foreign:
            return (f" — you sent {named}, and this caller does not own it. The refusal is "
                    "CORRECT; the step is what is wrong. Create the resource as THIS actor in an "
                    "earlier step and `save` its id, or make this a deliberate cross-user denial "
                    "step that expects 403 alone.")
        return (f" — you sent {named}, and no such row exists. A hardcoded id is a guess: ids "
                "differ between the dataset, the seed and the staged ASSET names. Read one from "
                "an earlier step in this chain (list the collection, `save` an id from the "
                "response) instead of writing a literal.")
    except Exception:
        return ""


def _denial_scope_verdict_663(sent_body, body_text) -> str:
    """#663: a denial probe that SUCCEEDED — did the write cross an ownership boundary?

    "DENIAL-PROBE got success" is 20 of the current era's broken assertions (8 of the 13 most
    recent runs with a failing chain: r117/127/130/131/133/135/141/143), concentrated on
    GET /api/my-list, GET /api/continue-watching, POST /api/my-list and POST rating. #188 made
    the note honest about the ambiguity — "an auth/isolation hole, OR a mis-authored probe" —
    but left it unresolved, and the two ends of that OR are a P0 and a cosmetic:

        the server STORED the id the caller named        -> a cross-user write. P0.
        the server SUBSTITUTED the caller's own id       -> no data crossed; the request should
                                                            have been refused, not rebound.

    The evidence is already in hand and was being discarded: the resolved request body carries
    the id the prober sent, and the response carries the id that was stored. Comparing them
    decides it. Verified against r127's `rating_upsert_and_isolation`, whose step 5 is a
    correctly-authored `auth: tokenB` probe carrying A's profile_id — from the stored artifact
    alone the class could not be determined, which is precisely the gap.

    Returns "" when the comparison is not possible, so the note is never worse than before.
    """
    if not isinstance(sent_body, dict) or not body_text:
        return ""
    try:
        got = json.loads(body_text)
    except Exception:
        return ""
    for _k in ("item", "data", "result", "record"):
        if isinstance(got, dict) and isinstance(got.get(_k), dict):
            got = got[_k]
            break
    if not isinstance(got, dict):
        return ""
    echoed, swapped = [], []
    for k, v in sent_body.items():
        if k not in got or isinstance(v, (dict, list)) or v is None:
            continue
        try:
            same = str(v).strip() == str(got[k]).strip()
        except Exception:
            continue
        (echoed if same else swapped).append((k, v, got[k]))
    if echoed:
        return ("BOUNDARY CROSSED — the stored row kept the value the caller sent: "
                + "; ".join(f"{k}={v!r}" for k, v, _ in echoed)
                + ". Treat as a data-isolation hole, not a status-code nit. ")
    if swapped:
        return ("no data crossed — the server SUBSTITUTED its own value ("
                + "; ".join(f"{k}: sent {v!r}, stored {g!r}" for k, v, g in swapped)
                + "), so this is a WRONG STATUS, not a leak: a request naming another "
                  "owner's id must be refused, not silently rebound. ")
    return ""


def classify_endpoint_failure(status, body_text):
    """``"ok"`` | ``"framework_defect"`` | ``"broken"`` for one endpoint probe result."""
    try:
        code = int(status)
    except (TypeError, ValueError):
        code = 0
    if 200 <= code < 300:
        return "ok"
    if code >= 500 and isinstance(body_text, str) and _PROJECTED_TRACEBACK_RE.search(body_text):
        return "framework_defect"
    return "broken"


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
    # #411: seed with NOT-NULL columns the create omitted (scanned from the raw text so
    # it survives a non-JSON body / the json-parse early-return below).
    body: List[str] = _notnull_missing_cols(body_text, method)
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


# N-P0-3 (Netflix): string business keys a path param can be keyed by — captured
# alongside the numeric id so a ``${title_slug}``/``${username}`` placeholder resolves
# the way ``${title_id}`` already does. Netflix detail routes are ``/title/{slug}``,
# ``/watch/{slug}``, not ``/title/{id}``.
_STRING_KEY_FIELDS = ("slug", "username", "handle")


def _harvest_resource_ids(payload: Any, into: Dict[str, Any]) -> None:
    """FIX #83 (instagram run-3, live): harvest resource ids from a step's RESPONSE BODY.

    The verifier wires chains the way a human would — GET /api/feed, then act on
    ``${post_id}`` FROM the feed — but capture was envelope-only and keyed by the PATH's
    resource ('feed'), and content-feed apps have NO bare /api/posts collection, so list/
    create recovery dead-ended and the LITERAL ``${post_id}`` reached the int path param
    (422 → wedge → STUCK). Harvest instead: every top-level key whose value is a list of
    dicts with an ``id`` → ``into[singular(key)] = first id``; plus ONE level of nested
    dicts inside the first row ({"posts":[{"user":{"id":42}}]} → user=42) since nested
    actors (post author) are often the only source of a second resource's id. setdefault
    ONLY — an id captured from the chain's own create stays authoritative.

    N-P0-3: ALSO harvest a row's string business keys under ``<resource>_<field>``
    ({"titles":[{"id":7,"slug":"st"}]} → title=7, title_slug="st") so a chain that
    references ``${title_slug}`` — the natural placeholder for a ``/title/{slug}`` route —
    resolves it from the feed row, exactly as ``${title_id}`` already does."""
    if not isinstance(payload, Mapping):
        return

    def _singular(k: str) -> str:
        k = str(k).lower()
        return k[:-1] if k.endswith("s") and len(k) > 1 else k

    def _harvest_string_keys(prefix: str, row: Mapping) -> None:
        for f in _STRING_KEY_FIELDS:
            val = row.get(f)
            if val is not None and str(val).strip():
                into.setdefault(f"{prefix}_{f}", str(val))

    for k, v in payload.items():
        if isinstance(v, list) and v and isinstance(v[0], Mapping):
            row = v[0]
            if row.get("id") is not None:
                into.setdefault(_singular(k), row["id"])
            _harvest_string_keys(_singular(k), row)
            for k2, v2 in row.items():
                if isinstance(v2, Mapping) and v2.get("id") is not None:
                    into.setdefault(_singular(k2), v2["id"])
                    _harvest_string_keys(_singular(k2), v2)
        elif isinstance(v, Mapping) and v.get("id") is not None:
            into.setdefault(_singular(k), v["id"])
            _harvest_string_keys(_singular(k), v)


_ID_KEYS = ("id", "uuid", "pk")


def _ids_from_list_payload(payload: Any) -> list:
    """#263 — ids of the objects in a LIST-shaped response, under any key.

    A singular object (the /auth/register response) deliberately yields nothing: it is the
    exact payload whose id kept landing on by-id paths for other resources.
    """
    def _id_of(o):
        if not isinstance(o, Mapping):
            return None
        for k in _ID_KEYS:
            if o.get(k) is not None:
                return o[k]
        for k, v in o.items():
            if str(k).lower().endswith("_id") and v is not None:
                return v
        return None

    def _from_seq(seq):
        out = []
        for o in seq:
            i = _id_of(o)
            if i is not None:
                out.append(i)
        return out

    if isinstance(payload, list):
        return _from_seq(payload)
    if isinstance(payload, Mapping):
        for v in payload.values():
            if isinstance(v, list) and v and isinstance(v[0], Mapping):
                got = _from_seq(v)
                if got:
                    return got
    return []


def _pick_id_for_resource(resource: Any, seen_responses: list, last_id: Any) -> Any:
    """#263 — the id to use for a by-id path when no step saved the variable.

    Order: (1) a list from a response whose PATH names this resource, (2) the MOST RECENT
    list-shaped response — the collection a human would have read the id from ("GET the
    feed, then GET the first video") — and only then (3) the global last_id.

    r55 lost its whole 88-minute convergence budget because step (3) was reached directly:
    ``GET /api/v1/videos/${first_video_id}`` was filled with the USER id from
    /auth/register and answered 404 "video not found" on a WORKING app, 20 chains over.
    Rung (1) missed because the feed response is keyed ``items`` (not ``videos``) and rung
    (2) of the old ladder — a live LIST on ``/api/v1/videos`` — missed because this app has
    no bare collection, only ``/feed/foryou``.
    """
    res = str(resource or "").lower().rstrip("s")
    named, recent = None, None
    for path, payload in seen_responses:
        ids = _ids_from_list_payload(payload)
        if not ids:
            continue
        recent = ids[0]
        if res and res in str(path or "").lower():
            named = ids[0]
    if named is not None:
        return named
    if recent is not None:
        return recent
    return last_id


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
            # N-P0-3: a string business-key placeholder (${title_slug}/${user_username}/
            # ${x_handle}) resolves DIRECTLY — _harvest_resource_ids keys these under their
            # full "<resource>_<field>" name. Restricted to the known string-key suffixes so
            # a bare ${title} (ambiguous) and the numeric ${x_id} rule below are untouched.
            if (by_resource and any(var.endswith("_" + f) for f in _STRING_KEY_FIELDS)):
                direct = by_resource.get(var)
                if direct is not None and str(direct).strip():
                    return direct
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


# id-shaped param names: id, user_id, videoId (camelCase), pk, uuid — these stay
# with the #136 numeric-id ladder; everything else (username/handle/slug) is #245.
# #246: a CREATE step that violates a UNIQUE constraint is not a broken endpoint — the
# row already exists (chains RE-RUN every validation cycle, so a create with a fixed
# unique field goes green once and then red FOREVER). Detect from the server's own error.
_UNIQUE_ERR_RE = re.compile(r"unique|duplicate|already exist|integrity constraint", re.I)
_UNIQUE_FIELDS = ("username", "email", "slug", "handle", "code", "key", "name")


_ID_PARAM_RE = re.compile(r"(?:^|_|(?<=[a-z]))(?:id|pk|uuid)$", re.I)

# #323 — literals a verifier authors to MEAN "the current/authenticated user" instead of
# a real value: GET /api/users/Owner/favorites, /api/users/me/liked. On an OWNER-SCOPED
# resource (403 for any non-owner) the ONLY value that satisfies expect [200] is the chain
# user's OWN identity — recovering a DIFFERENT user (the #245 default) 403s forever.
_SELF_ALIAS = {
    "owner", "me", "self", "myself", "mine", "my", "current", "currentuser",
    "current_user", "current-user", "loggedin", "logged_in", "you",
}


def _extract_own_username(payload: Any) -> Any:
    """The chain user's own username/handle from an /auth/register (or /login) response —
    top-level or nested under ``user``. Owner-scoped self-view recovery targets THIS value."""
    if not isinstance(payload, Mapping):
        return None
    containers = [payload]
    _u = payload.get("user")
    if isinstance(_u, Mapping):
        containers.append(_u)
    for c in containers:
        for k in ("username", "handle", "slug", "user_name", "userName"):
            v = c.get(k)
            if v is not None and str(v).strip():
                return str(v)
    return None


def _registered_param_for_path(path: Any, endpoints: Any):
    """#245 (+#323) — match a LITERAL request path against the REGISTERED contract templates
    and return ``(collection_path, param_name, seg_index)`` for a ``{param}`` segment whose
    STATIC siblings all match, so recovery can fetch a real value of the RIGHT KIND and
    replace the RIGHT segment.

    Chains author a literal value (``/api/users/13``, ``/api/users/ProfileUser``) while the
    contract declares ``/api/users/{username}``. Knowing the param NAME is what lets recovery
    fetch a real value of the RIGHT KIND — the #136 ladder only recovers a numeric id, which
    is exactly wrong for a ``{username}`` param (r29: the id 500'd the handler; r33: 404).

    #323 (r92 M3 NO-CONVERGENCE, 75min): #245 only matched a TRAILING ``{param}`` — but a
    chain authored ``GET /api/users/Owner/favorites`` against ``/api/users/{username}/favorites``
    where the param is a MIDDLE segment, so #245 returned nothing and the invented "Owner"
    404'd forever. Now the ``{param}`` may be in ANY position: ``collection_path`` is the path
    UP TO it (for list recovery) and ``seg_index`` is its 0-based index (over non-empty
    segments) so the caller replaces THAT segment. Returns (None, None, -1) on no match. Pure."""
    if not path or not endpoints:
        return None, None, -1
    lit = [s for s in str(path).split("?", 1)[0].split("/") if s]
    if not lit:
        return None, None, -1
    # STATIC WINS: a literal that IS a registered static endpoint (/api/users/suggested)
    # must never be treated as a {param} value — rewriting it would mask a real failure
    # of that endpoint.
    _litp = "/" + "/".join(lit)
    for ep in endpoints or []:
        tplp = str((ep or {}).get("path") or "") if isinstance(ep, Mapping) else ""
        if tplp and "{" not in tplp and tplp.rstrip("/") == _litp.rstrip("/"):
            return None, None, -1
    for ep in endpoints or []:
        tpl = str((ep or {}).get("path") or "") if isinstance(ep, Mapping) else ""
        segs = [s for s in tpl.split("/") if s]
        if not segs or len(segs) != len(lit):
            continue
        for i, seg in enumerate(segs):
            if not (seg.startswith("{") and seg.endswith("}")):
                continue
            # every STATIC sibling must equal the literal (other {params} resolve on their
            # own); the matched param may sit in any position (trailing OR middle).
            if all(segs[j] == lit[j] for j in range(len(segs))
                   if j != i and not (segs[j].startswith("{") and segs[j].endswith("}"))):
                return "/" + "/".join(segs[:i]), seg[1:-1], i
    return None, None, -1


def _rows_of_payload(payload: Any) -> list:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, Mapping):
        items = payload.get("items")
        if isinstance(items, list):
            return items
        for k, v in payload.items():
            if str(k).lower() in ("errors", "error", "detail", "warnings"):
                continue
            if isinstance(v, list):
                return v
    return []


def _recover_field_via_list(base: str, coll_path: str, field: str, token: Any,
                            avoid: Any = None) -> Any:
    """#245 — GET the collection and return a real row's ``field`` (the value the registered
    path param NAMES: username / handle / slug), not an id. ``avoid`` skips the chain user's
    own value so a follow/unfollow step never targets self. Best-effort → None."""
    if not coll_path or not field or "{" in coll_path or "${" in coll_path:
        return None
    try:
        r = _http("GET", base + coll_path, token=token, body=None)
        if not _status_ok(r.get("status"), [200]):
            return None
        for row in _rows_of_payload(json.loads(r.get("body_text") or "{}")):
            if not isinstance(row, Mapping):
                continue
            v = row.get(field)
            if v is None or not str(v).strip():
                continue
            if avoid is not None and str(v) == str(avoid):
                continue
            return v
    except Exception:
        return None
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


def _register_aux_user_id(base: str) -> Any:
    """FIX #100 (instagram run-18, live): LAST-RESORT id for a USERS-resource placeholder
    when every other rung starves (register 409'd with no id in the body, login carries
    no user object, NO /api/users collection exists, no prior list step). The platform AS
    is the one id source that exists BY CONSTRUCTION: mint a fresh AUXILIARY user and
    take its id from the response envelope, the nested user object, or the token's JWT
    ``sub`` claim (the AS mints sub=<user id> — a platform invariant). The aux user is
    guaranteed ≠ the chain user, so follow/unfollow-style actions get a REAL other user.
    Best-effort; never raises; None on any failure."""
    import base64
    try:
        _n = str(int(time.time() * 1000))[-9:]
        body = {"email": f"aux_{_n}@example.com", "password": "Chain123!x",
                "name": "Aux Chain", "username": f"aux_{_n}"}
        r = _http("POST", base + "/auth/register", body=body)
        if not _status_ok(r.get("status"), [200, 201]):
            return None
        try:
            p = json.loads(r.get("body_text") or "{}")
        except Exception:
            p = {}
        rid = _extract_resource_id(p)
        if rid is None and isinstance(p.get("user"), Mapping):
            rid = p["user"].get("id")
        if rid is None:
            tok = p.get("access_token") or p.get("token")
            if isinstance(tok, str) and tok.count(".") == 2:
                seg = tok.split(".")[1]
                seg += "=" * (-len(seg) % 4)
                try:
                    sub = json.loads(base64.urlsafe_b64decode(seg.encode())).get("sub")
                except Exception:
                    sub = None
                if sub is not None:
                    rid = int(sub) if str(sub).isdigit() else sub
        return rid
    except Exception:
        return None


def _response_has_rows(body_text) -> bool:
    """#566v: True iff a list response carries at least one ROW. Used to tell a real cross-user READ
    leak (a fresh intruder's owner-scoped GET returns the FOREIGN owner's rows) from a SECURE override
    (the app ignored the foreign owner param and returned the caller's OWN — empty — view). Only a
    CLEARLY-EMPTY list envelope (items/data/results/rows == [] or a bare []) counts as no-rows; anything
    ambiguous (unparseable, a non-list/object payload, an unrecognized envelope) returns True so a leak
    is NEVER masked."""
    try:
        _b = json.loads(body_text or "")
    except Exception:
        return True  # unparseable → cannot prove empty → conservative (keep the leak verdict)
    if isinstance(_b, list):
        return len(_b) > 0
    if isinstance(_b, Mapping):
        for _k in ("items", "data", "results", "rows"):
            _v = _b.get(_k)
            if isinstance(_v, list):
                return len(_v) > 0
        return True  # no recognized list envelope → could be a single-object leak → conservative
    return True


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
        if _status_ok(_r.get("status"), expect):
            return False  # fresh intruder DENIED → original 2xx was a probe artifact → not a leak
        # #566v: a fresh intruder (who owns NO data) got 2xx on a cross-user READ denial probe. This
        # is a REAL leak ONLY if the response carries the FOREIGN owner's ROWS; an EMPTY list means the
        # app securely scoped it to the intruder's own (empty) view (it ignored the foreign owner param
        # — a valid secure implementation the verifier's strict 403 expectation over-penalizes, which
        # made the lane oscillate own-403 ↔ cross-user-200 and wedge, netflix r130). Reads only; a
        # WRITE that succeeds as a fresh intruder is still a real leak.
        if str(method or "").upper() == "GET":
            return _response_has_rows(_r.get("body_text"))
        return True  # non-GET 2xx as a fresh intruder → real leak
    except Exception:
        return True  # any failure → conservative → keep the leak verdict


def execute_chain(base: str, chain: Mapping[str, Any],
                  seed_ids: Optional[Mapping[str, Any]] = None,
                  endpoints: Optional[List[Mapping[str, Any]]] = None,
                  projected: Optional[set] = None) -> Dict[str, Any]:
    """Run one chain; returns {name, steps: [...], broken: [...]}.
    Deterministic wiring; never raises. ``seed_ids`` (#144): {resource →
    known-present id from seed_data.json}, a recovery rung for literal-id
    404s (see the FIX #136 block)."""
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
    seen_responses: List[Any] = []           # #263: (path, payload) of each step, for list-id recovery
    last_reg_creds: Dict[str, Any] = {}  # creds of the last successful /auth/register → reused if a later /auth/login 401s
    own_user_id: Any = None  # the chain user's own id (from /auth/register) — recovery must not target SELF (FIX #81)
    own_tenant_id: Any = None  # #566x: a tenant THIS chain created → the scope its reset may safely wipe
    succeeded_requests: set = set()  # #566z: identities that ALREADY answered 2xx in THIS chain
    own_username: Any = None  # #323: the chain user's OWN username — owner-scoped self-view recovery targets THIS
    unsatisfied: set = set()  # vars an earlier BROKEN step failed to save → its dependents are unreachable
    # FIX #188: var → step-action whose OK response lacked the save path — the
    # silent-capture-failure class behind the "GET x → 200 marked failed" triage
    # confusion (225x across logs): the 200 step LOOKED fine, downstream broke.
    save_failed_by_var: Dict[str, str] = {}
    # #59c: STORED chains (registered by an older framework, or hand-edited) can
    # carry the auth-save clobber in their persisted steps — normalize-time
    # guarding alone can't reach them, so guard the runtime copy too.
    _steps = [dict(s) if isinstance(s, Mapping) else s
              for s in (chain.get("steps") or [])]
    _drop_auth_save_clobbers(_steps)
    # #570: order-independent companion to #566z's runtime set (see _authored_success_identities).
    _authored_success = _authored_success_identities(_steps)
    # FIX #91 runtime guard (same #59c rationale — STORED chains bypass normalize):
    # a step expecting EXACTLY {401} is an unauthenticated-denial probe; an authored
    # (or auto-attached) auth ref contradicts its own expectation — the correct
    # backend then 200s and the chain wedges forever (run-11 live: GET /api/feed
    # auth:'token' expect:[401]). Strip it so the probe really goes tokenless.
    for _s in _steps:
        if isinstance(_s, dict):
            _e = _s.get("expect")
            _e = _e if isinstance(_e, (list, tuple, set)) else ([_e] if _e is not None else [])
            if {int(x) for x in _e if str(x).isdigit()} == {401}:
                _s.pop("auth", None)
    for idx, step in enumerate(_steps):
        variables["rand"] = f"{_rand_base}{idx:02d}"
        method = str(step.get("method", "GET")).upper()
        # R2(b): a SYNTHETIC-DEFECT step is a contract gap KNOWN at synthesis time (a
        # state-bearing/feature-inventory entity with NO write endpoint — synthesize_default_
        # chain emits it). It is not an app call: record it directly as a `framework_defect`
        # (never executed over HTTP — the endpoint does not exist) so the gap SURFACES through
        # the SAME #272 framework-defect path a projected-handler 5xx uses (framework work, not
        # a lane dispatched to fix code it never wrote), instead of being silently absent.
        if step.get("synthetic_defect"):
            recorded.append({
                "action": str(step.get("action") or "framework_missing_write_path"),
                "method": method if step.get("method") else "",
                "path": str(step.get("path") or ""),
                "status": None, "ok": False, "kind": "framework_defect",
                "note": str(step.get("note")
                            or "declared feature has no write endpoint (missing_write_path)"),
            })
            continue
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
                    if _rid is None and _pres in ("user",):
                        # FIX #100: users-resource placeholder with NO source anywhere
                        # → mint an auxiliary user via the platform AS (id from the
                        # envelope or the JWT sub claim); guaranteed ≠ chain user.
                        _rid = _register_aux_user_id(base)
            # (3) GLOBAL last_id — absolute last resort, NON-denial only. Usually
            #     the WRONG resource (a same-resource id would have won at (1)),
            #     kept only for the rare ambiguous case. A denial step must NEVER
            #     fall here — the global last_id is the prober's own most-recent
            #     id → reading it → 200 false leak; leave the literal (404s,
            #     tolerated by the denial expectation).
            if _rid is None and not _is_denial:
                # #263: before the blind global last_id, try an id from a LIST a prior
                # step actually returned. r55 lost its entire convergence budget here:
                # GET /api/v1/videos/${first_video_id} was filled with the USER id from
                # /auth/register (last_id) and answered 404 "video not found" on a WORKING
                # app, across 20 chains. Rung (1) missed because the feed response is keyed
                # `items`, and list-recovery missed because this app has no bare
                # /api/v1/videos collection — only /feed/foryou. A foreign id on a by-id
                # path is a guaranteed 404 that reads exactly like an application bug.
                _rid = _pick_id_for_resource(_pres, seen_responses, last_id)
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
            # #188: when the starving var traces to an upstream OK-step whose save
            # captured nothing, SAY so — the capture bug (envelope/field-name
            # drift) is the actionable root, not "no data".
            _sf_hint = ""
            for _uv in re.findall(r"\$\{(\w+)\}", str(path)):
                if save_failed_by_var.get(_uv):
                    _sf_hint = (" NOTE: ${" + _uv + "} save failed at step '"
                                + save_failed_by_var[_uv]
                                + "' (response lacked the save path) — fix that "
                                "capture, not this read.")
                    break
            recorded.append({
                "action": str(step.get("action") or step.get("path") or ""),
                "method": method, "path": str(step.get("path") or ""),
                "status": None, "ok": True, "kind": "skipped",
                "note": ("skipped — unsatisfiable by data: the chain user owns no "
                         + str(_pres or "row") + " and the collection cannot create one "
                         "(no POST / empty list). Endpoint reachability is proven by "
                         "api_smoke; this read has no data to target." + _sf_hint)})
            continue
        body = _subst(step.get("body"), variables) if step.get("body") else None
        # BODY UNRESOLVED-VARIABLE FALLBACK — the body counterpart of the path fallback
        # above. A nested-FK body the verifier referenced but never saved (e.g.
        # {"calendar_id": "${calendar_id}"} after POST /api/calendars) otherwise sends
        # the literal "${calendar_id}" to an int column → 500 → business_chain wedges
        # forever on a correct app. Resolve a surviving ${...} to the most recent
        # captured resource id (untouched when the chain is wired correctly).
        # #575: strip an unresolved OWNER FK BEFORE the generic fallback can guess one — a
        # foreign owner id turns the caller's own write into a fake cross-user attempt (403).
        # …but NEVER on a cross-user DENIAL step (#575b, self-review). There the unresolved
        # owner FK IS the probe: dropping it sends the write into the CALLER's own scope, the
        # app correctly answers 201, and the probe reports a leak that never happened. Leaving
        # the literal makes the backend reject it, which is what the denial expectation wants —
        # the same convention the path-side ladder has followed since #59b.
        if _is_cross_user_denial(step):
            _dropped_owner_fks = []
        else:
            body, _dropped_owner_fks = _drop_unresolved_owner_fks(body)
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
        # FIX #188: record which authored variables are STILL unresolved in the
        # outgoing request (path/body literal ${...}, or an auth ref no step
        # captured) — a later failure on this step names them + their cause
        # instead of surfacing a bare status the reader can't act on.
        _unres_vars = set(re.findall(r"\$\{(\w+)\}", str(path)))
        try:
            if body is not None:
                _unres_vars |= set(re.findall(r"\$\{(\w+)\}", json.dumps(body)))
        except Exception:
            pass
        _auth_ref = str(step.get("auth") or "")
        if _auth_ref and _auth_ref not in variables:
            _unres_vars.add(_auth_ref)
        # #592 — ATTRIBUTE A LADDER SUBSTITUTION TO THE CAPTURE THAT FAILED. #188 explains a
        # failure when the variable stayed literal; it is silent in the worse case, where the
        # ladder DID produce a value. r130's `my_list_add_and_readback` is the shape:
        #
        #   [2] GET  /api/titles   save {titleId: items.0.id}  -> 200 ok, note "save FAILED"
        #   [3] POST /api/my-list  {"title_id": "${titleId}"}  -> 404 "referenced resource
        #                                                          not found"
        #
        # The catalog was empty (r130's #566x reset), so `items.0.id` captured nothing, the
        # ladder filled ${titleId} with an unrelated id, and the 404 named the FK. Step [2] is
        # recorded ok=True, so every reader — the gate, the dispatcher, and the lane — chases a
        # foreign-key bug two steps away from the real cause. #566x removed ONE producer of the
        # empty collection; the misattribution survives every other producer.
        #
        # Annotation only, deliberately NOT reclassification (the #587 precedent): turning this
        # into a framework defect would move genuine app bugs off the lane and leave them
        # unowned. The step still fails; it just says whose fault it is.
        _authored_vars = set(re.findall(r"\$\{(\w+)\}", str(step.get("path") or "")))
        try:
            if step.get("body") is not None:
                _authored_vars |= set(
                    re.findall(r"\$\{(\w+)\}", json.dumps(step.get("body"))))
        except Exception:
            pass
        # `v not in variables` is the discriminator, not an extra safety net: the ladder
        # substitutes into the outgoing path/body WITHOUT writing to `variables`. So a var
        # present there was really captured — by a LATER step that succeeded where an earlier
        # one failed — and its stale `save_failed_by_var` entry must not annotate this step.
        _ladder_filled = sorted(v for v in (_authored_vars - _unres_vars)
                                if save_failed_by_var.get(v) and v not in variables)
        # #566x (netflix r130, live — 10/10 failing chains were AFTER the reset chain,
        # 0 before it): a bare POST to the control-plane reset takes its FACTORY branch
        # and DELETEs every business row, including the seeded catalog. The step passes
        # (200 is correct), then every LATER chain in the same pass reads an empty
        # collection: its `save: {titleId: items.0.id}` captures nothing, the
        # placeholder ladder fills the gap with an unrelated id, and the writes come
        # back 404 "referenced resource not found" — read by the gate as an application
        # defect and dispatched to a lane that has nothing to fix. Deterministic every
        # pass, so the gate can never see all chains green in ONE eval → wedge.
        # Send it tenant-SCOPED: the endpoint stays covered, the fixture survives.
        _headers: Optional[Dict[str, str]] = None
        _scope_note: Optional[str] = None
        if _is_factory_reset(method, path):
            _headers = _scoped_reset_header(chain.get("name"), own_tenant_id,
                                            last_reg_creds)
            _scope_note = f"reset-scoped->{_headers[_TENANT_SCOPE_HEADER]}"
        res = _http(method, base + path, token=token, body=body, headers=_headers)
        status = res.get("status")
        # FIX #281 (tiktok r66, live): the step sent JSON but the endpoint declares FORM
        # fields — the framework's own scaffolded oauth_routes.py does exactly that for
        # POST /oauth/authorize (email/password/client_id = Form(...)), the correct OAuth2
        # shape. FastAPI calls every form field "missing from body", so the step 400s
        # forever and the chain-step schema has NO way to say "urlencode this": the verifier
        # was dispatched to fix a defect it had no power to fix, wedging business_chain
        # through all 6 validation attempts → no successful run → NO-CONVERGENCE ABORT at
        # 76min on an app whose endpoint was FINE. Retry ONCE form-encoded when the response
        # bears that exact signature (it names as missing-from-body a field we DID send);
        # a genuinely absent field keeps its teeth (see _form_retry_warranted).
        if not _status_ok(status, expect) and _form_retry_warranted(
                body, status, res.get("body_text") or ""):
            _fres = _http(method, base + path, token=token, body=body, form=True)
            if _status_ok(_fres.get("status"), expect):
                res, status = _fres, _fres.get("status")
        ok = _status_ok(status, expect)
        autofilled: List[str] = []
        if _scope_note:
            autofilled.append(_scope_note)  # #566x: SAY it in the record, never silently
        for _dk in _dropped_owner_fks:      # #575: likewise — never a silent body edit
            autofilled.append(f"owner-fk-omitted:{_dk}")
        for _lv in _ladder_filled:          # #592: likewise — the substitution is on the record
            autofilled.append(f"ladder-filled-after-failed-save:{_lv}")
        # #301+#316: a /oauth/authorize step lacking the PKCE code_challenge (bare OR
        # params-bearing) correctly 400/422s on a working AS and can never pass —
        # tolerate it so a synthesized probe doesn't wedge business_chain (r82 M2 +
        # r86 final both STUCK 75min on this; #316 widened #301 from "no flow params"
        # to "no code_challenge"). A code_challenge-bearing step is the real flow and
        # must pass on its own merits.
        if not ok and status in (400, 422) and _oauth_authorize_lacks_pkce(path, body):
            ok = True
            autofilled.append("oauth-authorize-incomplete-tolerated")
        # #566z (netflix r132, live): the verifier authored the SAME request TWICE for the
        # SAME actor with mutually exclusive expectations — [200] then [400] on a bare
        # GET /api/continue-watching. It meant "with no profile selected → 400", which a
        # chain step cannot express: steps carry method/path/body/auth and NO headers. One
        # request cannot be answered two ways, so the step can never pass.
        # Left standing it does not merely wedge — it MISTEACHES the lane. r132: chasing the
        # 400, the backend made the endpoint REQUIRE an X-Profile-Id header the harness
        # cannot send, so every legitimate 200-expecting step across 5 chains began failing
        # with "X-Profile-Id header is required" (1 failing chain → 5). That is the exact
        # "owner-scoping oscillation" logged against r126–r130: an unsatisfiable authored
        # expectation is its engine, not lane incompetence.
        # Waive it as MIS-AUTHORED. This CANNOT mask a cross-user leak by construction: the
        # waiver fires only when the actor is IDENTICAL to one already entitled to a 2xx on
        # that exact request, so no second identity is involved. A different auth ref, query
        # string or body yields a different identity and keeps every tooth.
        # #570 widens the evidence from "already succeeded EARLIER" to "the chain expects this
        # very request to succeed ANYWHERE" — r135 wedged because the contradictory step sat
        # BEFORE its twin. Both keys require the same actor, so neither can hide a leak.
        if (not ok and isinstance(status, int) and 200 <= status < 300
                and expect and not any(200 <= e < 300 for e in expect)
                and (_request_identity(step, method, path, body) in succeeded_requests
                     or _request_identity(step, step.get("method") or "GET",
                                          str(step.get("path") or ""),
                                          step.get("body")) in _authored_success)):
            ok = True
            autofilled.append("unsatisfiable-duplicate-expectation-waived")
        # #580: the same class without a sibling to contradict — a bare AUTHENTICATED read
        # naming no foreign identifier addresses only the caller's own scope, so a non-2xx
        # expectation on it can never be met by an owner-scoping framework. Proven from the
        # request itself (no query, no id segment, no body), so a probe that COULD name a
        # foreign id is untouched.
        # …and ONLY when the response carries NO ROWS. The request shape proves no foreign id
        # was NAMED; it cannot prove none was RETURNED. An unscoped collection read hands every
        # actor the same rows, and that is exactly how the r131/r133 leaks were caught — by a
        # bare read (`GET /api/my-list` as tokenB returned user A's row). Waiving on shape
        # alone would have hidden the very defect #568 fixed; this project's own test suite
        # caught that before it shipped. Rows present -> keep the leak verdict (§5 hard rule).
        if (not ok and isinstance(status, int) and 200 <= status < 300
                and expect and not any(200 <= e < 300 for e in expect)
                and _is_bare_self_scoped_read(step, method, path, body)
                and not _response_has_rows(res.get("body_text"))):
            ok = True
            autofilled.append("bare-self-scoped-empty-read-waived")
        # netflix r11: a verifier-authored DENIAL probe (expect has no 2xx, e.g.
        # [401,403]) against a CONTROL-PLANE public infra endpoint (control_plane.py:
        # /api/v1/tenants etc., auth_required=False) is MIS-AUTHORED — that endpoint is
        # contractually PUBLIC (the login TenantPicker fetches GET /api/v1/tenants pre-
        # auth), so a 2xx is CORRECT, not an auth hole, and the verifier can't "fix" it
        # without breaking login → business_chain wedges forever (r11: 6× GET
        # /api/v1/tenants → 200 vs expected [401,403] = permanent business_chain_failing).
        # Scoped to the 6 FIXED control-plane paths, so a denial probe on a real BUSINESS
        # endpoint keeps its teeth (a genuine cross-tenant/isolation leak still fails).
        if (not ok and isinstance(status, int) and 200 <= status < 300
                and expect and not any(200 <= e < 300 for e in expect)
                and _is_control_plane_public(method, path)):
            ok = True
            autofilled.append("control-plane-public-denial-probe-waived")
        # FIX #136 (instagram run-52/58/60 — 3rd occurrence of the class): a verifier-
        # authored step with a LITERAL numeric id (POST /api/posts/4/repost) 404s when
        # the seed doesn't reach that id — the ${placeholder} recovery ladder above
        # never fires for literals, so the authored id went out verbatim and the chain
        # wedged 7 post-cap cycles on a functionally-correct app (run-60: seed had
        # posts 1-2, the chain hardcoded 4; the backend "fixed" the live DB but not
        # seed_data.json, so every clean-boot regressed it). If a NON-denial step
        # fails with 404 and its AUTHORED path (not a substituted one — a substituted
        # id was really captured and must fail honestly) carries a literal numeric id
        # segment, retry ONCE with a recovered REAL id (same-resource captured id ->
        # live list recovery -> global last_id). Positive semantics preserved: the
        # retry exercises the same happy path against an id that EXISTS; a genuinely
        # broken endpoint fails the retry too and is recorded as before.
        if (not ok and status == 404
                and re.search(r"/\d+(?=/|$)", str(step.get("path") or ""))
                and not _is_cross_user_denial(step)):
            _lcoll = re.split(r"/\d+(?=/|$)", str(step.get("path") or "").split("?", 1)[0])[0]
            _lres = _resource_from_path(_lcoll)
            _lid = last_id_by_resource.get(_lres) if _lres else None
            if _lid is None and _lcoll:
                _lid = _recover_id_via_list(base, _lcoll, token, avoid=own_user_id)
            if _lid is None and seed_ids:
                # FIX #144 (run-66 M2, 4th occurrence of the literal-id class):
                # live-list recovery is defeated when the resource's list lives
                # at a different collection (posts listed via /api/feed) — but
                # the authored seed ids are guaranteed present after every
                # clean boot (#130/#135). Deterministic, no network. seed
                # tables are PLURAL ('posts'); _resource_from_path singularizes
                # ('post') — try both. The collection tail itself ('posts'
                # from /api/posts/9/like) covers steps whose _lres is None.
                _coll_tail = _lcoll.rstrip("/").rsplit("/", 1)[-1] if _lcoll else ""
                for _k in (_lres, f"{_lres}s" if _lres else None,
                           _coll_tail or None):
                    if _k and seed_ids.get(_k) is not None:
                        _lid = seed_ids[_k]
                        break
            if _lid is None:
                _lid = last_id
            if _lid is not None and str(_lid).strip():
                _lpath = re.sub(r"/\d+(?=/|$)", "/" + str(_lid), path, count=1)
                if _lpath != path:
                    _res3 = _http(method, base + _lpath, token=token, body=body)
                    if _status_ok(_res3.get("status"), expect):
                        res, status, ok = _res3, _res3.get("status"), True
                        path = _lpath
                        autofilled.append(f"literal-id->{_lid}")
        # FIX #299 (tiktok r80 M2, live): a SUCCESS-expecting social action whose
        # target is the chain user's OWN id can never pass — the app CORRECTLY
        # 400s "cannot follow yourself" — so business_chain wedges (r80: POST
        # /api/users/81/follow, 81=the registered chain user, 6/6 attempts →
        # NO-CONVERGENCE ABORT on a functionally-correct app). The #81 avoid-self
        # ladder only guards an UNRESOLVED placeholder; a target that RESOLVED to
        # own_user_id slips through. Mirror #136: on a self-action 400, retry ONCE
        # against a recovered DIFFERENT user (a deliberate self-deny test expects
        # [400] and is NOT matched — see _self_targeted_social_user_action).
        if not ok and status == 400:
            _self = _self_targeted_social_user_action(expect, path, own_user_id)
            if _self is not None:
                _ucoll, _cur = _self
                _other = _recover_id_via_list(base, _ucoll, token, avoid=own_user_id)
                if _other is None:
                    _other = _register_aux_user_id(base)
                if _other is not None and str(_other) != str(own_user_id):
                    _spath = re.sub(r"/users/[^/]+/", "/users/" + str(_other) + "/",
                                    path, count=1)
                    if _spath != path:
                        _res5 = _http(method, base + _spath, token=token, body=body)
                        if _status_ok(_res5.get("status"), expect):
                            res, status, ok = _res5, _res5.get("status"), True
                            path = _spath
                            autofilled.append(f"self-social->{_other}")
        # #245 PARAM-AWARE RECOVERY (r27/r29/r33 — the top recurring business_chain
        # killer). The contract declares GET /api/users/{username}; chains author a
        # literal id (/api/users/13 → 500 when the handler types the param as a string,
        # or 404) or an invented name (/api/users/ProfileUser → 404). The #136 ladder
        # only recovers NUMERIC ids and only on 404, so NONE of these were reachable —
        # 15 broken steps across three runs, every one of them this shape. Match the
        # authored literal against the REGISTERED template; when the param is not
        # id-shaped, recover a real value of THAT FIELD from the collection and retry
        # once. A genuinely broken endpoint fails the retry too and is recorded as before.
        if not ok and status in (404, 500) and not _is_cross_user_denial(step):
            _pcoll, _pname, _pidx = _registered_param_for_path(step.get("path"), endpoints)
            if _pname and _pidx >= 0 and not _ID_PARAM_RE.search(_pname):
                # #323: replace the segment at the {param} POSITION (not always the last),
                # preserving the query string — fixes MIDDLE-param recovery
                # (/api/users/Owner/favorites → /api/users/<real>/favorites).
                _bare = str(path).split("?", 1)[0]
                _query = str(path)[len(_bare):]
                _psegs = [s for s in _bare.split("/") if s]
                if 0 <= _pidx < len(_psegs):
                    _lit_seg = str(_psegs[_pidx]).strip().lower()
                    _self_val = own_username if own_username is not None else own_user_id
                    # A literal that MEANS the current user ("Owner", "me", our own
                    # username/id) → recover to SELF; on an OWNER-SCOPED resource
                    # (favorites/liked) any OTHER user 403s, so SELF is the only 200.
                    _is_self_alias = (
                        _lit_seg in _SELF_ALIAS
                        or (own_username is not None and _lit_seg == str(own_username).lower())
                        or (own_user_id is not None and _lit_seg == str(own_user_id).lower())
                    )
                    # candidate identities, best-first; deduped, non-None only.
                    _cands: list = []
                    if _is_self_alias and _self_val is not None:
                        _cands.append(_self_val)
                    _other = _recover_field_via_list(base, _pcoll, _pname, token,
                                                     avoid=own_user_id)
                    if _other is not None:
                        _cands.append(_other)
                    # Owner-scoped resources 403 for a non-owner even when the literal
                    # wasn't an obvious self-alias → always keep SELF as a fallback.
                    if _self_val is not None and _self_val not in _cands:
                        _cands.append(_self_val)
                    for _pval in _cands:
                        if str(_psegs[_pidx]) == str(_pval):
                            continue
                        _try = list(_psegs)
                        _try[_pidx] = str(_pval)
                        _ppath = "/" + "/".join(_try) + _query
                        if _ppath == path:
                            continue
                        _res4 = _http(method, base + _ppath, token=token, body=body)
                        if _status_ok(_res4.get("status"), expect):
                            res, status, ok = _res4, _res4.get("status"), True
                            path = _ppath
                            autofilled.append(f"param:{_pname}->{_pval}")
                            break
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
        # #246 UNIQUE-CONSTRAINT RETRY (r35 M2): the verifier authored
        # POST /api/users {"username": "${u3_name}"} where NO step saves u3_name, so the
        # value is constant across cycles — the create succeeded once and then returned
        # 400 "integrity constraint violated" on every later cycle, wedging business_chain
        # permanently. Chains re-run each validation cycle, so ANY create whose unique key
        # does not vary is red forever. Uniquify the unique-ish fields and retry ONCE
        # (domain-agnostic: reads the server's own error, mirrors the 422 field repair).
        if (not ok and status in (400, 409) and method == "POST"
                and isinstance(body, Mapping) and body
                and _UNIQUE_ERR_RE.search(str(res.get("body_text") or ""))):
            import uuid as _uuid
            _sfx = _uuid.uuid4().hex[:6]
            _ubody, _uchanged = dict(body), False
            for _uf in _UNIQUE_FIELDS:
                _uv = _ubody.get(_uf)
                if isinstance(_uv, str) and _uv.strip():
                    if "@" in _uv:
                        _lp, _, _dom = _uv.partition("@")
                        _ubody[_uf] = f"{_lp}_{_sfx}@{_dom}"
                    else:
                        _ubody[_uf] = f"{_uv}_{_sfx}"
                    _uchanged = True
            if _uchanged:
                _res5 = _http(method, base + path, token=token, body=_ubody)
                if _status_ok(_res5.get("status"), expect):
                    res, status, ok = _res5, _res5.get("status"), True
                    body = _ubody
                    autofilled.append(f"unique-suffix:{_sfx}")
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
                    # #411: an FK/id column needs an INTEGER, not the string filler — a
                    # seeded parent row is id 1 (tables seed ids 1..N), satisfying both the
                    # FK and NOT-NULL; the string filler would just re-fail on type/FK.
                    _repaired[f] = 1 if f.endswith("_id") else _filler
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
            for _ck in ("email", "username", "password", "tenant_id"):
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
            # FIX #188 honesty: a pure-DENIAL probe (expect has no 2xx) that got a
            # success must SAY so — the raw "→ 200 ({body})" read as nonsense in
            # 225x of triage lines and hid the real meaning (the request was not
            # rejected: an auth/isolation hole, or a mis-authored probe).
            if (expect and isinstance(status, int) and 200 <= status < 300
                    and not any(200 <= e < 300 for e in expect)):
                note = ("DENIAL-PROBE got success — the request was NOT rejected "
                        f"(expected denial {expect}). "                       # #663
                        + _denial_scope_verdict_663(body, res.get("body_text"))
                        + note)
            # FIX #188 causality: the request went out with unresolved variables —
            # name each one and (when known) the upstream step whose save failed,
            # so the reader chases the CAPTURE bug, not this step's status.
            if _unres_vars:
                _hints = []
                for _v in sorted(_unres_vars):
                    _src = save_failed_by_var.get(_v)
                    _hints.append(
                        f"${{{_v}}} save failed at step '{_src}'" if _src
                        else f"${{{_v}}} never captured by any prior step")
                note = "unresolved " + "; ".join(_hints) + " — " + note
            # #592: the var WAS filled — by the ladder, standing in for a save that failed
            # upstream. Name that step, or this status gets blamed on the endpoint.
            if _ladder_filled:
                note = ("SUBSTITUTED " + "; ".join(
                    f"${{{_v}}} save failed at step '{save_failed_by_var[_v]}' (response "
                    f"lacked the save path) — the ladder sent an UNRELATED id"
                    for _v in _ladder_filled) +
                    " — fix that capture, not this endpoint. " + note)
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
                # #272: a 5xx whose traceback names a framework-projected handler is a
                # FRAMEWORK defect (route_projector emitted it, the lane cannot fix it) — do
                # not record it as a broken APP endpoint that dispatches a lane to chase code
                # it never wrote. It still fails the step (the chain did not pass), but under
                # a distinct kind the gate/dispatcher can route to the framework, not a lane.
                _fdef = classify_endpoint_failure(status, res.get("body_text"))
                if _fdef == "framework_defect":
                    kind = "framework_defect"
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
        # #682: a 404 on a write says "not found" and never says WHAT was not found.
        # r145 died on exactly this: business_chain never went green in 75 minutes because two
        # chains posted `title_id: 'movie-1003596'` and got 404 "title not found". That id is
        # real — it is an ASSET id from design_system.json — but the seeded titles are
        # 'tv-stranger-signals'-shaped and design/dataset/titles.json uses integers, so three id
        # vocabularies were in play and the verifier picked the one that is not in the database.
        # The contract could not have told it: the registered schema says `title_id: 'str'`.
        #
        # The step's own request body holds the answer and the line never quoted it. Naming the
        # field and the value turns "title not found" into something the author can act on.
        # In the corpus the same shape is POST /api/my-list -> "referenced resource not found"
        # x26, the largest single broken-assertion class after the denial probes.
        #
        # NOT a registration-time rule: I measured hardcoded `*_id` literals across the 3492
        # stored chains first, and they fail at 5% — exactly the same rate as chains without
        # them, with 392 PASSING chains using one. Rejecting them would have cost real work and
        # caught nothing. The value only becomes wrong once the server says so.
        note = note + _unknown_id_hint_682(status, body, note)
        entry = {"action": str(step.get("action") or path), "method": method,
                 "path": path, "status": status, "ok": ok, "kind": kind,
                 "note": note}
        if expect:
            entry["expect"] = list(expect)  # #188: the broken line shows intent
        if autofilled:
            entry["autofilled"] = autofilled
        recorded.append(entry)
        if ok:
            # #566z: remember what this actor already got a 2xx for. Recorded AFTER the
            # waiver check above, so a step can never waive ITSELF.
            if isinstance(status, int) and 200 <= status < 300:
                succeeded_requests.add(_request_identity(step, method, path, body))
            # Auto-capture the current resource id (id / item.id / items[0].id) from
            # EVERY successful step — feeds the unresolved-variable fallback above so a
            # later get/update/delete step can target a real row even when the verifier
            # didn't wire an explicit save. Never overrides an explicit save.
            try:
                _payload = json.loads(res.get("body_text") or "{}")
                # FIX #83: list/nested ids in the body (a feed's posts + their authors)
                # resolve later ${x_id} refs when no bare collection endpoint exists.
                # setdefault-only — never clobbers an explicitly created/captured id.
                _harvest_resource_ids(_payload, last_id_by_resource)
                # #263: remember the RESPONSE ITSELF (path + payload) so a later
                # by-id path can draw an id from a LIST a prior step returned —
                # the feed a human would have read the id from. Bounded to the
                # last 40 responses so a long chain cannot grow this without end.
                try:
                    seen_responses.append((str(step.get("path") or ""), _payload))
                    del seen_responses[:-40]
                except Exception:
                    pass
                # #566x: a tenant THIS chain created is a scope its own reset may
                # safely wipe. Prefer the server's echoed id; fall back to the id the
                # step ASKED for (the contract does not pin the create's response
                # shape, and r130's `save: {tid: item.tenant_id}` captured nothing).
                if str(path).split("?", 1)[0].rstrip("/") in _CONTROL_PLANE_TENANT_CREATE:
                    _tid = _extract_resource_id(_payload)
                    if _tid is None and isinstance(body, Mapping):
                        _tid = body.get("tenant_id") or body.get("id")
                    if _tid is not None and str(_tid).strip():
                        own_tenant_id = _tid
                _cid = _extract_resource_id(_payload)
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
                        # #323: remember our OWN username so an owner-scoped self-view
                        # step (/api/users/Owner/favorites) can recover to SELF, not a
                        # different user (which the app 403s). Prefer the response's
                        # username; fall back to the register body's username.
                        _own = _extract_own_username(_payload)
                        if not _own and isinstance(body, Mapping):
                            for _k in ("username", "handle", "slug", "user_name"):
                                if body.get(_k) and str(body.get(_k)).strip():
                                    _own = str(body.get(_k)); break
                        if _own:
                            own_username = _own
            except Exception:
                pass
            # Capture the SUBSTITUTED creds of a successful /auth/register so a later
            # /auth/login that 401s (mismatched ${rand}, see carry-forward above) can
            # retry with the identity that actually exists.
            if str(step.get("path", "")).rstrip("/") == "/auth/register" \
                    and isinstance(body, Mapping):
                # FIX #101 (run-19 live): tenant_id carried too — a verifier that puts
                # ${rand} in BOTH register and login mints different emails AND
                # different tenants per step; the retry with the register's email/
                # password but the login's OWN tenant still 401s on a multi-tenant AS.
                last_reg_creds = {_k: body[_k]
                                  for _k in ("email", "username", "password", "tenant_id")
                                  if body.get(_k)}
        if ok and isinstance(step.get("save"), Mapping):
            try:
                payload = json.loads(res.get("body_text") or "{}")
            except Exception:
                payload = {}
            _save_failed: List[str] = []  # #188: silent-capture-failure surfacing
            for var, dotted in step["save"].items():
                _captured = False
                val = _dig(payload, dotted)
                if val is not None:
                    variables[str(var)] = str(val)
                    _captured = True
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
                        _captured = True
                if not _captured and str(var) not in variables:
                    # #188: the step SUCCEEDED but captured nothing for this var —
                    # today this is silent, and the first visible symptom is a
                    # baffling downstream failure (the "200 marked failed" triage
                    # class). Record it on THIS entry + index it for the causal
                    # hint on whichever later step starves. Diagnostic only.
                    _save_failed.append(f"{var}<-{dotted}")
                    save_failed_by_var[str(var)] = str(
                        step.get("action") or step.get("path") or "")
            if _save_failed:
                entry["save_failed"] = [f.split("<-", 1)[0] for f in _save_failed]
                entry["note"] = ((entry["note"] + " | ") if entry["note"] else "") + (
                    "save FAILED (response lacks the path): "
                    + ", ".join(_save_failed))
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
    # #188: broken lines carry the authored expectation — "GET x → 200 ({body})"
    # with a hidden expect [401] read as nonsense in 225x of triage lines.
    def _fmt(s):
        return (f"{s['method']} {s['path']} → {s['status']} "
                + (f"(expected {s['expect']}; {s['note']})" if s.get("expect")
                   else f"({s['note']})")
                + _projected_owner_note(projected, s.get("method"), s.get("path")))
    broken = [_fmt(s) for s in recorded if s["kind"] == "broken"]
    # #272: framework-projected defects are reported SEPARATELY so the gate can surface them
    # as framework work, not fold them into `broken` where a lane would be dispatched to fix
    # code it never wrote.
    framework_defects = [_fmt(s) for s in recorded if s["kind"] == "framework_defect"]
    return {"name": str(chain.get("name") or "chain"), "steps": recorded,
            "broken": broken, "framework_defects": framework_defects}


AUTHORING_INSTRUCTIONS = (
    "no verification chains registered — the verifier must REGISTER them via "
    "the registryhub_register_verification_chain tool (one call per chain), "
    "designed from the registered contract + kickoff user_flows. Each step: "
    '{"action", "method", "path", "body" (${rand}/${var} substitution), '
    '"expect": [codes], "save": {"var": "dot.path"}, "auth": "var"}. '
    "Cover at minimum: an auth round-trip and each critical user flow.")


_PROJECTED_ROUTE_RE = re.compile(
    r'@app\.(get|post|put|patch|delete)\(\s*"([^"]+)"[^)]*\)\s*\n\s*def\s+_projected_', re.I)


def projected_routes(project_dir: Any) -> set:
    """#587 — ``{(METHOD, path)}`` served by a FRAMEWORK-projected handler, read from the
    generated ``main.py``.

    `classify_endpoint_failure` can only call a failure a framework defect when it sees a 5xx
    WITH a ``_projected_`` traceback ("narrow on purpose", #272). Three real defects this arc
    were 2xx and carried no traceback at all — `GET /api/my-list` and
    `GET /api/continue-watching` returning ANOTHER account's rows from an unscoped projected
    read (#566y, #568). Each failed as "DENIAL-PROBE got success", was classified `broken`, and
    was dispatched to the lane — whose own correct handler was shadowed and who cannot edit
    `main.py`. `backend_audit` already states the principle (FIX #201: a projected stub "the
    lane CANNOT edit", so telling it to replace the handler is non-actionable); the chain
    executor simply had no way to know which routes those are. It does now: `run_chains`
    receives `project_dir`.

    Used ONLY to annotate the failure message — deliberately not to reclassify. Reclassifying a
    4xx/2xx as a framework defect would route genuine app bugs on projected routes away from the
    lane and leave them unowned; naming the owner costs nothing and is what the dispatcher and
    the reader actually lacked. Best-effort: any fault returns an empty set."""
    try:
        main = Path(project_dir) / "app" / "backend" / "main.py"
        src = main.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return set()
    return {(m.group(1).upper(), m.group(2)) for m in _PROJECTED_ROUTE_RE.finditer(src)}


def _projected_owner_note(proj: set, method: Any, path: Any) -> str:
    """#587 — ' [framework-projected route: …]' when this route is served by projected code."""
    if not proj:
        return ""
    p = str(path or "").split("?", 1)[0]
    m = str(method or "GET").upper()
    if (m, p) in proj:
        return (" [FRAMEWORK-PROJECTED route — served by a _projected_ handler in main.py; "
                "the lane cannot edit it, fix the projector/contract]")
    # a by-id shape: /api/x/7 vs the emitted /api/x/{id}
    for (pm, pp) in proj:
        if pm != m or "{" not in pp:
            continue
        rx = "^" + re.escape(pp).replace(r"\{", "{").replace("{", "{").split("{")[0]
        if p.startswith(rx.lstrip("^")) and p.count("/") == pp.count("/"):
            return (" [FRAMEWORK-PROJECTED route — served by a _projected_ handler in main.py; "
                    "the lane cannot edit it, fix the projector/contract]")
    return ""


def run_chains(base: str, project_dir: Any,
               business_endpoints: List[Mapping[str, Any]]) -> Dict[str, Any]:
    """Execute the verifier's chains. No chains → the gate FAILS with the
    authoring instructions (agent feedback loop, not framework content)."""
    chains = load_verifier_chains(project_dir)
    if not chains:
        return {"source": "missing", "chains": [],
                "broken": [AUTHORING_INSTRUCTIONS], "total_steps": 0}
    _seed_ids = load_seed_ids(project_dir)  # #144: literal-id recovery rung
    _projected = projected_routes(project_dir)      # #587
    results = [execute_chain(base, ch, seed_ids=_seed_ids,
                          endpoints=list(business_endpoints or []),
                          projected=_projected)
               for ch in chains]
    broken = [b for r in results for b in r["broken"]]
    framework_defects = [b for r in results for b in r.get("framework_defects", [])]
    total = sum(len(r["steps"]) for r in results)
    # Record pass/fail back onto the registry records (best-effort) — the
    # registry is the single place to see chain health (monitor renders it).
    try:
        from .json_store import JsonStore
        store = JsonStore(Path(project_dir) / CHAINS_STORE_RELPATH)
        for r in results:
            rec = (store.value() or {}).get(r["name"])
            if isinstance(rec, dict):
                _fd = r.get("framework_defects") or []
                # #272: a chain whose ONLY failures are framework-projected defects is not the
                # lane's to fix — mark it framework_blocked, not failing (which would dispatch a
                # lane) and not passing (which would hide a real framework bug).
                _status = ("passing" if not r["broken"] and not _fd
                           else "failing" if r["broken"]
                           else "framework_blocked")
                rec = {**rec,
                       "status": _status,
                       "last_result": {"broken": r["broken"], "framework_defects": _fd,
                                       "steps": r["steps"]},
                       "last_run_at": time.time()}
                store.update(lambda m, _rec=rec, _n=r["name"]: m.set(_n, _rec, "chain_executor"),
                             change_info={"agent": "chain_executor"})
    except Exception:
        pass
    return {"source": "verifier", "chains": results, "broken": broken,
            "framework_defects": framework_defects, "total_steps": total}
