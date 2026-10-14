"""Framework-owned post-milestone TEST-USER validation.

After a milestone delivers, simulate real users completing tasks across the channels a
user actually has, record per-step success, and write a feedback report — the automated
form of the hand-verification that exposed the route_projector bugs (the
username-as-post-id 500, the ``author_id=null`` create). A milestone should never ship a
broken contract silently again.

Channels:
  * **API test-user** — runs a realistic social-app journey (register → create post →
    read feed → view a user's posts → follow → comment → like → save → explore/reels →
    message) and flags any step that 4xx/5xx OR returns wrong data (e.g. a created post
    with a null owner, a user's-posts list that 500s). This is the high-signal channel:
    it would have caught both route_projector defects on the milestone they shipped.
  * **MCP test-user** — verifies the env's MCP server is COMPLETE (a tool per business
    endpoint) and importable, so the MCP surface a user/agent would drive is real.

  * **UI test-user** (mechanism #44) — a first-time-user FEEDBACK pass: the run's
    model looks at the latest captured screenshots (design/visual_gate/, produced by the
    visual-fidelity gate's real browser) and reports what a new user would find broken,
    empty, or confusing per screen. Advisory (never gates delivery); complements the
    visual gate, which scores reference SIMILARITY, not usability.

Web + screenshots are produced by the orchestrating layer with a real browser
(Playwright is intentionally not a gen-runtime dependency), not here.

Deterministic, best-effort, never raises into the delivery path. Writes
``test_user_reports/<version>.json`` under the project dir and returns the report.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from .validation_runner import _backend_host_port, _http  # reuse the boot/HTTP helpers
from .message_format import join_capped  # #1203jw/#1034: a count beside a cut list


class _EnvUnavailable(Exception):
    """Internal: env never came up — skip the journey, keep the report."""


def _norm(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path or "")


def _has(api_paths: set, path: str) -> bool:
    want = _norm(path)
    return any(_norm(p) == want for p in api_paths)


def _json(res: Dict[str, Any]) -> Any:
    try:
        return json.loads(res.get("body_text") or "")
    except Exception:
        return None


def _first_id(payload: Any) -> Optional[Any]:
    """Pull an id out of the varied create-response shapes apps return."""
    if isinstance(payload, dict):
        if "id" in payload:
            return payload["id"]
        for key in ("item", "post", "data", "result"):
            inner = payload.get(key)
            if isinstance(inner, dict) and "id" in inner:
                return inner["id"]
    return None


def _owner_value(payload: Any) -> Any:
    """Pull the owner FK (author_id/user_id) out of a create response."""
    obj = payload
    if isinstance(payload, dict):
        for key in ("item", "post", "data", "result"):
            if isinstance(payload.get(key), dict):
                obj = payload[key]
                break
    if isinstance(obj, dict):
        for k in ("author_id", "user_id", "owner_id"):
            if k in obj:
                return obj[k]
    return "__absent__"


def _unwrap_item(payload: Any) -> Any:
    """Dig the single row out of the canonical create/read envelopes ({item|data|…})."""
    if isinstance(payload, dict):
        for key in ("item", "post", "data", "result"):
            inner = payload.get(key)
            if isinstance(inner, dict):
                return inner
    return payload


def _list_items(payload: Any) -> List[Any]:
    """Rows out of the canonical list envelopes (bare list / {items|data|results})."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in ("items", "data", "results"):
            v = payload.get(k)
            if isinstance(v, list):
                return v
    return []


def _find_by_id(items: List[Any], new_id: Any,
                res_key: Any = None) -> Optional[Dict[str, Any]]:
    """The row whose id matches ``new_id`` (type-tolerant, mirrors #122's str-compare).

    #566k: a create returns the ENTRY id (POST /api/my-list → {"item":{"id": <my_list row>}}),
    but a DENORMALIZED list view keys items by the RELATED entity — e.g. GET /api/my-list returns
    titles (item `id` = title id) with the entry id under a `<table>_id` alias (`my_list_id`). So
    also match ``new_id`` against a resource-derived ``<res>_id`` alias, else a genuinely-persisted
    row reads as ABSENT (netflix r121: 13 false 'ABSENT' advisories on a working my-list/
    continue-watching whose write DID persist). Restricted to the resource's OWN alias (not any
    ``*_id``) so an unrelated FK that happens to equal ``new_id`` can't produce a false match."""
    if new_id is None:
        return None
    want = str(new_id)
    aliases = set()
    if res_key:
        k = str(res_key).strip().strip("/").replace("-", "_")
        for cand in (k, k[:-1] if k.endswith("s") else k):   # my_list / continue_watching (+ deplural)
            if cand:
                aliases.add(cand + "_id")
    for it in items or []:
        if not isinstance(it, dict):
            continue
        if it.get("id") is not None and (
                it.get("id") == new_id or str(it.get("id")) == want):
            return it
        for a in aliases:
            if it.get(a) is not None and (it.get(a) == new_id or str(it.get(a)) == want):
                return it
    return None


_EMPTY_VALUES = (None, "", 0, 0.0, False, [], {})


def _write_lost(written: Any, read: Any) -> bool:
    """R3(a): True iff a written state value did NOT take effect — we wrote a non-empty
    value but the read-back is a DEFAULT/EMPTY one (None/0/''/False/[]/{}). Catches a
    no-op write (e.g. a progress endpoint that ignores its body and always reads 0)
    WITHOUT flagging a server that legitimately NORMALIZES a value to another non-empty
    one (status -> 'pending'). Type-tolerant (str-compares) so 1 vs '1' is NOT a loss."""
    if written == read:
        return False
    try:
        if str(written) == str(read):
            return False
    except Exception:
        pass
    written_empty = any(written is e or written == e for e in _EMPTY_VALUES)
    read_empty = any(read is e or read == e for e in _EMPTY_VALUES)
    return (not written_empty) and read_empty


def _created_appears(payload: Any, res_label: str, new_id: Any,
                     state_fields: Optional[Mapping[str, Any]] = None,
                     res_key: Any = None):
    """R3(a): a REAL list-persistence assertion. The prior ``_appears`` ALWAYS returned
    True, so a created row that was ABSENT from the subsequent list never failed (a
    non-persisting write read as green). Now: when we created a row (``new_id`` known) it
    MUST appear in the list, and any state field it carries MUST hold the value we wrote —
    else BROKEN. When no id was captured the check is N/A → advisory True (byte-identical)."""
    items = _list_items(payload)
    if new_id is None:
        return True, f"{len(items)} {res_label} listed"  # not applicable — advisory
    found = _find_by_id(items, new_id, res_key=res_key)
    if found is None:
        # #566p: show WHAT the list returned so an ABSENT readback is diagnosable — an EMPTY list
        # means not-persisted OR the read is scoped to a different owner than the write (created
        # under uid A, read as uid B); a list of OTHER ids means a scope/owner mismatch, not a lost
        # write. (netflix r125: profiles created id=26/28/29 reported ABSENT — need this to tell apart.)
        _ids_1203jw = [it.get("id") for it in (items or []) if isinstance(it, dict)]
        # #1203jw: #1034's helper, because this is a COUNT beside a TRUNCATED list. The old
        # `[:8]` printed `list has 100 row(s), ids=[eight of them]` with no remainder, and
        # that is why r125's two findings cannot be judged today: 10 rows, 6 ids shown, no
        # marker. join_capped is the owner of "say what you cut" in this repo.
        _seen = join_capped(_ids_1203jw, len(_ids_1203jw), cap=8)
        # #1203jw: THE THIRD CAUSE. This sentence used to name exactly two -- a lost write or
        # an owner-scoped read -- and assert them. A bounded list WINDOW is the third, and the
        # corpus has it: netflix/tiktok r149 reported `created comments (id=296) is ABSENT`
        # against an ASCENDING list of 100 rows starting at id 1, so the row was almost
        # certainly on a later page, and the finding went to the lane as a persistence defect.
        # (r186's is the opposite and stays a real finding: ids 35,34,33,32,31 are DESCENDING,
        # so a created id=36 belongs at the HEAD of that window and is genuinely missing.)
        #
        # `total` decides it when the payload carries it, which the framework's own list
        # contract requires (#1202os/#1203j1: total is the COLLECTION size, not the page's).
        # The verdict stays False either way -- turning it into a pass would let a genuinely
        # lost write through on any paginated list, which is #1202xc's "traded one silence
        # for another". What changes is that the prose stops naming only causes that are
        # wrong here, so the lane is not sent to fix persistence that works.
        _cause_1203jw = ("the write did not persist, or the read is scoped to a different "
                         "owner than the write")
        try:
            _total_1203jw = payload.get("total") if isinstance(payload, Mapping) else None
            _n_1203jw = len(items or [])
            if _total_1203jw is not None and int(_total_1203jw) > _n_1203jw:
                _cause_1203jw = (
                    f"the list is a WINDOW (total={int(_total_1203jw)} but {_n_1203jw} "
                    f"returned), so absence from it does not show the write was lost — read "
                    f"the row by id, or sort newest-first, before concluding")
            elif (_n_1203jw >= 2 and _ids_1203jw
                  and all(isinstance(i, (int, str)) and str(i).isdigit() for i in _ids_1203jw)
                  and all(int(i) < int(new_id) for i in _ids_1203jw)
                  and all(int(_ids_1203jw[k]) <= int(_ids_1203jw[k + 1])
                          for k in range(len(_ids_1203jw) - 1))):
                _cause_1203jw = (
                    "every id returned is lower than this one and the page is ASCENDING, so "
                    "the row may be past the window rather than lost — read it by id, or "
                    "sort newest-first, before concluding; failing that, the write did not "
                    "persist or the read is owner-scoped")
        except (TypeError, ValueError, AttributeError):
            pass
        return False, (f"created {res_label} (id={new_id}) is ABSENT from the {res_label} list "
                       f"(list has {len(items or [])} row(s), ids={_seen}) — {_cause_1203jw}")
    if state_fields:
        mism = [f"{k}: wrote {v!r}, read back {found.get(k)!r}"
                for k, v in state_fields.items() if _write_lost(v, found.get(k))]
        if mism:
            return False, (f"created {res_label} state not persisted — "
                           + "; ".join(mism) + " (write is a no-op)")
        return True, f"created {res_label} appears with persisted state"
    return True, f"created {res_label} appears in the list"


def _readback_persisted(payload: Any, res_label: str,
                        state_fields: Mapping[str, Any]):
    """R3(a): write->read-back VALUE assertion for a state entity (GET-by-id after a
    create/update). A no-op write returns the field at its default/empty value ≠ what we
    wrote → BROKEN — the class the 2xx-reachability check can never see."""
    obj = _unwrap_item(payload)
    def _got(k):
        return obj.get(k) if isinstance(obj, dict) else None
    mism = [f"{k}: wrote {v!r}, read back {_got(k)!r}"
            for k, v in (state_fields or {}).items() if _write_lost(v, _got(k))]
    if mism:
        return False, (f"state value not persisted for {res_label} — "
                       + "; ".join(mism) + " (write is a no-op)")
    return True, f"state persisted for {res_label} ({', '.join(state_fields or {})})"


# #670: HTML input types Playwright's `fill()` refuses ("Input of type X cannot be filled")
# or that take a different API entirely (file). Generic HTML, no product literals.
_UNFILLABLE_INPUT_TYPES_670 = frozenset({
    "checkbox", "radio", "submit", "button", "reset", "image", "file", "hidden",
    "range", "color",
})


# #1203ip: the THIRD category of input. #670 split visible inputs into the ones
# `fill()` REFUSES outright (skipped above) and the ones it fills with text (the
# `else` in `_fill_visible_inputs`) — but `fill()` ACCEPTS these and then validates
# the VALUE, so the generic `uiflow<sfx>` string raises
#     Locator.fill: Error: Malformed value
# and, exactly like #670's checkbox, the throw escaped the per-input guard and
# aborted the WHOLE flow, so the run reported a UI signup failure. The app was fine.
#
# Measured over the 361 test-user reports on this machine: 11 ui_flow failures across
# 6 runs (r92, r140, r164, r178, r184, r185) carry this error. EVERY one is
# `flow=signup` and EVERY one resolved to an `input[type=date]`; r185's was the 5th
# input of a name/username/email/password/birthdate form, matching its
# `locator("input").nth(4)`. r184 and r185 are the two most recent complete runs, so
# this is live, not historical.
#
# Skipping them (what #670 does for range/color) is the WRONG treatment here: a signup
# form asks for a birthdate because it wants one, and a probe that leaves the field
# empty stops exercising the thing it exists to exercise. Fill each with a value of
# its own type instead. The date is ~30 years back so an age gate cannot reject it.
# Generic HTML input types, no product vocabulary — same discipline as #670 above.
_TYPED_INPUT_VALUES_1203ip = {
    "date": "1994-01-01",
    "datetime-local": "1994-01-01T09:00",
    "month": "1994-01",
    "week": "1994-W02",
    "time": "09:00",
    "number": "21",
}


def _register_or_login(base: str, email: str, name: str) -> Optional[str]:
    """Register a test user (or log in if they already exist) → access token."""
    pw = "TestUser!2024"
    # Send the FULL registration shape api_smoke uses — some apps make users.full_name
    # NOT NULL, so a {email,password,name}-only body fails and the harness would falsely
    # report 'auth broken' (instagram MM run #13). full_name + username cover the common
    # required columns.
    for path, body in (
        ("/auth/register", {"email": email, "password": pw, "name": name,
                            "full_name": name.title(), "username": name}),
        ("/auth/login", {"email": email, "password": pw}),
    ):
        res = _http("POST", f"{base}{path}", body=body)
        payload = _json(res) or {}
        token = payload.get("access_token") or payload.get("token")
        if not token and isinstance(payload.get("data"), dict):
            token = payload["data"].get("access_token")
        if token:
            return token
    return None


def _resource_label(base_col: str) -> str:
    """Human label for a collection path: ``/api/messages`` -> ``messages``."""
    seg = base_col.rstrip("/").split("/")[-1]
    return seg or "resource"


def _api_crud_journey(base: str, business_eps: List[Mapping[str, Any]], token: Optional[str],
                      rec, *, skip_bases=frozenset(), max_resources: int = 6) -> None:
    """Contract-derived, domain-agnostic CRUD journey (PIPELINE_HANDOFF §5/§8.4).

    The social steps above only fire for a social-shaped contract; a mail/docs/video app
    was left almost untested. Here we group the business endpoints into resource collections
    and, for each one that supports create, drive a real create -> list -> read -> update ->
    delete lifecycle as the logged-in user — bodies synthesised from the registered request
    schema (``validation_runner._probe_body``), path params filled by ``_path_with_params``.
    Only 5xx/auth/null-owner is BROKEN; 404/405 is a softer 'missing'. Skips collections the
    social block already covers so a social app isn't double-walked."""
    from .validation_runner import _probe_body, _path_with_params
    try:
        from .completeness_audit import _is_state_column
    except Exception:  # keep the journey working even if the classifier is unavailable
        _is_state_column = lambda name, type_=None: False  # noqa: E731

    cols: Dict[str, Dict[str, Any]] = {}

    def _col(p: str) -> Dict[str, Any]:
        return cols.setdefault(p, {"post": None, "list": False, "item_get": None,
                                   "item_update": None, "item_delete": None})

    for ep in business_eps or []:
        if not isinstance(ep, Mapping):
            continue
        path = str(ep.get("path") or "")
        method = str(ep.get("method") or "GET").upper()
        if not path.startswith("/api"):
            continue
        if not re.search(r"\{|\$\{|:[A-Za-z_]", path):       # collection-level (no params)
            c = _col(path)
            if method == "POST":
                c["post"] = ep
            elif method == "GET":
                c["list"] = True
            continue
        # item-level = base + exactly ONE trailing param segment (/api/messages/{id}).
        m = re.match(r"^(/api/[^/]+(?:/[^/{}$:]+)*)/(?:\{[^}]+\}|:\w+|\$\{[^}]+\})$", path)
        if not m:
            continue                                          # nested/social route — leave to the social block
        c = _col(m.group(1))
        if method == "GET":
            c["item_get"] = path
        elif method in ("PATCH", "PUT"):
            c["item_update"] = c["item_update"] or (method, path)
        elif method == "DELETE":
            c["item_delete"] = path

    done = 0
    for base_col in sorted(cols):
        if done >= max_resources:
            break
        c = cols[base_col]
        if not c["post"] or base_col in skip_bases:
            continue
        res = _resource_label(base_col)
        done += 1
        # Capture the create body ONCE so the write->read-back value assertion below
        # compares against exactly what we sent (not a fresh _probe_body call).
        _post_body = _probe_body(c["post"])
        # State fields in the body (progress/status/position/toggle/…) — the values a
        # persisting write must round-trip; reuses the #557 classifier (no product literals).
        _state_fields = {k: v for k, v in _post_body.items()
                         if isinstance(k, str) and _is_state_column(k, None)}
        cres = _http("POST", base + base_col, token=token, body=_post_body)

        def _owner_ck(payload, _res=res):
            obj = payload
            if isinstance(payload, dict):
                for k in ("item", "data", "result"):
                    if isinstance(payload.get(k), dict):
                        obj = payload[k]
                        break
            if isinstance(obj, dict):
                for k in ("author_id", "user_id", "owner_id", "created_by"):
                    if k in obj:
                        if obj[k] in (None, ""):
                            return False, f"created {_res} has null {k} — create not attributed to the user"
                        return True, f"{k}={obj[k]}"
            return True, "created"

        rec(f"create {res}", "POST", base_col, cres, _owner_ck)
        new_id = _first_id(_json(cres))

        if c["list"]:
            def _appears(payload, _res=res, _id=new_id, _sf=_state_fields, _bc=base_col):
                # R3(a): REAL persistence check — a created row absent from the list (or
                # present with a lost state value) is now BROKEN, not advisory-True.
                return _created_appears(payload, _res, _id, _sf, res_key=_bc)
            rec(f"list {res}", "GET", base_col, _http("GET", base + base_col, token=token), _appears)
        if new_id is not None and c["item_get"]:
            ip = _path_with_params(c["item_get"], str(new_id))
            # R3(a): for a STATE entity, assert the written value round-trips (GET-by-id);
            # for a non-state entity the check is N/A → None → byte-identical to before.
            _read_ck = ((lambda payload, _res=res, _sf=_state_fields:
                         _readback_persisted(payload, _res, _sf))
                        if _state_fields else None)
            rec(f"read {res}", "GET", c["item_get"],
                _http("GET", base + ip, token=token), _read_ck)
        if new_id is not None and c["item_update"]:
            um, upath = c["item_update"]
            ip = _path_with_params(upath, str(new_id))
            rec(f"update {res}", um, upath, _http(um, base + ip, token=token, body=_post_body))
        if new_id is not None and c["item_delete"]:
            ip = _path_with_params(c["item_delete"], str(new_id))
            rec(f"delete {res}", "DELETE", c["item_delete"], _http("DELETE", base + ip, token=token))


def _api_test_user(base: str, api_paths: set,
                   business_eps: Optional[List[Mapping[str, Any]]] = None) -> Dict[str, Any]:
    """Run a realistic two-user journey; record each step. Social-shaped contracts get the
    targeted social steps (which guard the instagram route_projector regressions); EVERY app
    additionally gets a generic contract-derived CRUD journey (``_api_crud_journey``)."""
    steps: List[Dict[str, Any]] = []

    def _declared_endpoint(method: str, path: str) -> bool:
        """#614 — is (method, path) in the CONTRACT? Param-name agnostic, so a recorded
        `/api/x/{id}` matches a declared `/api/x/{item_id}`."""
        want_m = str(method or "GET").upper()
        want_p = re.sub(r"\{[^}]*\}", "{}", _norm(path))
        for ep in (business_eps or []):
            if not isinstance(ep, Mapping):
                continue
            if str(ep.get("method") or "GET").upper() != want_m:
                continue
            if re.sub(r"\{[^}]*\}", "{}", _norm(str(ep.get("path") or ""))) == want_p:
                return True
        return False

    def rec(action: str, method: str, path: str, res: Dict[str, Any],
            check=None) -> Dict[str, Any]:
        status = res.get("status")
        ok = bool(status and 200 <= status < 400)
        note = ""
        # Distinguish a MISSING feature (404/405 — endpoint not implemented at this
        # milestone yet) from a BROKEN one (5xx / auth / wrong data). Missing is a
        # softer, milestone-timing signal; broken is a real defect. This sharpens the
        # verdict so early-milestone "not yet built" 404s don't read like breakage.
        kind = "ok"
        if not ok:
            note = (res.get("error") or res.get("body_text") or "")[:160]
            kind = "missing" if status in (404, 405) else "broken"
            # #614 — A 405 ON A DECLARED ENDPOINT IS A TIMING VERDICT, NOT A GAP. The smoke
            # runs against whatever the container is serving AT THAT MOMENT, and the projector
            # may not have emitted the handler yet.
            #
            # THE EVIDENCE IS THE CHAINS, not the timestamps. In r131/r120/r114/r101 the
            # verification chains later got 201 on the very same `POST /api/continue-watching`
            # the smoke had recorded as 405/missing — the endpoint demonstrably existed later.
            # A control run afterwards showed why the timestamps alone prove nothing: `main.py`
            # is newer than the report in 96% of runs REGARDLESS of verdict (260 of 278 `ok`
            # steps too), because the backend is re-projected on every heal tick. The original
            # note for this fix leaned on that 8-to-108-minute gap; it is context, not proof.
            #
            # This is why the caveat is scoped to 405 and NOT extended to 404: for 404s there
            # is no chain evidence, and the timestamp on its own cannot carry the claim.
            # The verdict was correct when written and stale by the time anything read it, but
            # it lands in the failure ledger as a missing feature and is never re-evaluated
            # (the #597 staleness class).
            #
            # Say so in the note rather than silently reclassifying: `missing` still fails the
            # step, and a genuinely absent endpoint reads exactly as before.
            if status == 405 and _declared_endpoint(method, path):
                note = ((note + " | ") if note else "") + (
                    "NOTE: this endpoint IS in the contract — a 405 means it is not being "
                    "served right now, most often because the projected handler had not been "
                    "emitted when this smoke ran. Re-check against the CURRENT backend before "
                    "dispatching it as a missing feature.")
        elif check:
            ok, note = check(_json(res))
            if not ok:
                kind = "broken"  # 2xx but wrong data (e.g. null owner) IS a real defect
        entry = {"action": action, "method": method, "path": path,
                 "status": status, "ok": ok, "kind": kind, "note": note}
        steps.append(entry)
        return entry

    tok_a = _register_or_login(base, "testuser_alpha@example.com", "alpha")
    if not tok_a:
        steps.append({"action": "register/login userA", "method": "POST",
                      "path": "/auth/register", "status": None, "ok": False,
                      "kind": "broken", "note": "could not obtain a token — auth broken"})
        return {"steps": steps, "actor": None}

    # Contract-derived CRUD journey — domain-agnostic, works for ANY app. (This replaced a
    # hardcoded instagram journey — posts/feed/follow/like/reels/DMs — that biased this
    # check to one domain and did nothing for mail/docs/video apps.) Regression coverage is
    # preserved without the social shape: the null-owner-on-create defect is caught here
    # generically by _api_crud_journey's owner check, and a 5xx on ANY route (incl. nested
    # sub-collections like /api/users/{id}/posts) is caught by api_smoke, which probes every
    # registered endpoint.
    _api_crud_journey(base, business_eps or [], tok_a, rec)

    return {"steps": steps, "actor": "alpha"}


def _count_mcp_tools_1203c7(src: str):
    """``(count, how)`` for ``@<obj>.tool`` decorators in a generated MCP server. #1203c7

    The regex this replaces (`@\\w+\\.tool\\b` over the raw source) matched the module
    DOCSTRING that `mcp_scaffold._SKELETON_HEADER` writes into every server -- "One @mcp.tool
    per backend endpoint" -- so every one of the 119 delivered servers counted exactly one
    phantom tool. `complete` is `tools >= expected`, so the phantom flipped the verdict for a
    server with `expected - 1` real tools: 38 reports sit on that boundary and ten of them read
    PASS with nothing else outstanding.

    A decorator is structure, so it is read as structure (#1202td: a regex ratchet has a blind
    spot by construction). Same scope as before -- an attribute named `tool` on any object,
    with or without a call -- so no server starts or stops counting for any other reason.

    `how` is returned for the note: a count whose method is invisible is the thing #1034 is
    about.
    """
    import ast as _ast1203c7
    try:
        tree = _ast1203c7.parse(src)
    except SyntaxError as _e1203c7:
        return 0, "main.py does NOT parse (%s line %s) — the server cannot be imported, so it " \
                  "exposes no tools; this is a generation defect, not a counting one" % (
                      type(_e1203c7).__name__, getattr(_e1203c7, "lineno", "?"))
    n = 0
    for _node in _ast1203c7.walk(tree):
        if not isinstance(_node, (_ast1203c7.FunctionDef, _ast1203c7.AsyncFunctionDef)):
            continue
        for _dec in _node.decorator_list:
            _f = _dec.func if isinstance(_dec, _ast1203c7.Call) else _dec
            if isinstance(_f, _ast1203c7.Attribute) and _f.attr == "tool":
                n += 1
                break
    return n, "counted %d @<obj>.tool decorator(s) by AST" % n


def _mcp_test_user(project_dir: Path, business_eps: List[Mapping[str, Any]]) -> Dict[str, Any]:
    """Verify the env's MCP server is complete (a tool per endpoint) + importable."""
    out: Dict[str, Any] = {"server_found": False, "tools_expected": len(business_eps),
                           "tools_found": 0, "complete": False, "note": ""}
    try:
        srv_root = project_dir / "mcp_server"
        if not srv_root.exists():
            # #616 — "NOT BUILT" IS A TIMING VERDICT TOO. Same shape as #614's 405: the probe
            # reports what exists AT THIS MOMENT, and the framework may not have scaffolded
            # yet. 9 runs recorded "MCP surface not built" while `mcp_server/` DOES exist on
            # disk, written 3 to 10 minutes AFTER the report in every one (r115 +6, r118 +6,
            # r121 +5, r125 +7, r127 +6, r128 +10, r133 +6, r134 +3, r142 +7).
            #
            # Here the timestamp DOES carry the claim, and a control says so: among reports
            # whose tree has an `mcp_server/`, the directory is newer than the report in 9/9
            # of the "missing" cases and only 1/10 of the cases where the probe FOUND it. That
            # separation is what `main.py` lacks (newer in 96% of runs regardless of verdict),
            # which is why #614 rests on chain evidence instead.
            #
            # `server_found` stays False — the probe must not claim to have seen something it
            # did not — but the note no longer reads as a permanent gap.
            out["note"] = ("no mcp_server/ AT THIS MOMENT — the framework scaffolds it "
                           "(write_mcp_server) and this probe may simply have run first; "
                           "re-check the tree before treating the MCP surface as unbuilt")
            return out
        mains = list(srv_root.glob("*/main.py"))
        if not mains:
            out["note"] = "mcp_server/ present but no <env>/main.py"
            return out
        out["server_found"] = True
        src = mains[0].read_text(encoding="utf-8")
        # #1203c7: count DECORATORS, not occurrences of the word. The old regex also matched
        # the scaffolder's own docstring ("One @mcp.tool per backend endpoint"), +1 on 119 of
        # 119 delivered servers, which flipped `complete` for every server holding exactly
        # `expected - 1` real tools.
        tools, _how1203c7 = _count_mcp_tools_1203c7(src)
        out["tools_found"] = tools
        out["counted_by_1203c7"] = _how1203c7
        out["complete"] = tools >= len(business_eps) and tools > 0
        out["note"] = (f"{tools} MCP tool(s) for {len(business_eps)} endpoint(s)"
                       if out["complete"] else
                       f"MCP surface INCOMPLETE: {tools} tool(s) for {len(business_eps)} endpoint(s)")
    except Exception as exc:
        out["note"] = f"mcp check error: {type(exc).__name__}: {exc}"
    return out


async def _ui_auth_flow(frontend_base: str) -> Dict[str, Any]:
    """USAGE-LEVEL check (user decision 2026-06-11): drive the real signup
    form in a real browser like a person would — fill the visible inputs,
    click submit, and require a stored token or a navigation away. The 1.4.0
    release shipped a pixel-perfect signup page whose button had NO handler;
    every HTTP-level probe passed while no human could create an account."""
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:
        return {"ran": False, "reason": f"playwright unavailable: {exc}"}
    # #1203is: BOUND ONCE, OUTSIDE THE ROUTE LOOP, AND THAT PLACEMENT IS LOAD-BEARING.
    # The loop below drives `/signup` then `/login` through the SAME `_fill_visible_inputs`,
    # so both flows type the same values and the login finds the account the signup made.
    # Moving this inside the loop -- the obvious tidy-up, since nothing before the loop needs
    # it -- hands the two routes suffixes seconds apart, and every login then fails as
    # "login user not registered", a verdict this corpus really contains (19 of its 270
    # failed ui_flows).
    #
    # It is also what makes an UNDER-SPECIFIC field classification harmless, which is why it
    # is worth a sentence here. The placeholder chain below reads `placeholder` and `type` and
    # NOT `name`, while `test_user_runner._fill_visible_inputs` reads name too. Projected over
    # the 1967 inputs on auth pages in this corpus, 267 (13.6%) are classified GENERIC where
    # their `name` says otherwise -- 154 full-name, 50 email, 32 password, 31 username -- and
    # EVERY one of the 267 is GENERIC -> a specific role, never one role -> another. So the
    # reading is under-specific, not wrong, and an under-specific value still logs in because
    # BOTH flows produce it.
    #
    # Two causal hypotheses for the commonest ui_flow failure ("submit sent NO /auth
    # request", 93 of 270) were tested against the corpus and BOTH FAILED. A 2x2 of
    # mis-classified-email x client-side `@` validation puts the both-true cell at 7/19 = 37%
    # against 66/154 = 43% everywhere else; the mis-classified-password x client-side
    # password-rule cell is EMPTY (n=0), so that conjunction never occurs at all. Nothing is
    # changed here on a hypothesis the corpus refused. The invariant that makes it safe is
    # pinned by a test instead, because it is an accident of placement until something checks.
    sfx = str(int(time.time()))[-6:]
    out: Dict[str, Any] = {"ran": True, "flows": []}

    # #1203it: ONE OWNER FOR THE WATCHED SURFACE, AND THIS ONE IS A LIVE MISS.
    # All three listeners below tested `"/auth/" in url` -- the literal #1203g1
    # removed from `test_user_runner`, because it matches neither `/oauth/token`
    # (the framework's OWN OAuth2 token endpoint) nor `/api/oauth/*`. `lifecycle`
    # says of this exact constant that "six modules re-listed this surface and
    # all six omitted the same three"; this module was a seventh, and re-listed
    # it THREE times.
    #
    # #1203g1 could call its own fix drift-closing, because it measured 0
    # frontends calling /oauth/. THAT IS NO LONGER TRUE. instagram-core-r176's
    # `pages/LoginPage.jsx` logs in with
    #     window.location.assign(`/oauth/authorize?client_id=instagram-web...`)
    # and its login flow is recorded as "the login form issued NO auth request,
    # and the token in storage was left by an earlier flow". The form issued one;
    # these listeners could not see where it went. The app was fine.
    #
    # Imported from the runner's already-derived tuple rather than re-filtering
    # `FRAMEWORK_AUTH_SURFACE_PREFIXES_1202vl` here, so the "drop well-known"
    # rule has no second copy either (#1032). The import is LAZY because
    # `test_user_runner` imports THIS module at module level (#1203ip) and a
    # module-level import back would be a cycle. It is NOT wrapped: #1203g1's
    # own scar is a guarded import that silently left a hand-written copy in use,
    # so an ImportError here must be loud.
    from .test_user_runner import (
        _AUTH_OBSERVED_PREFIXES_1203G1 as _AUTH_SURFACE_1203it)

    # #1203iu: AND NOBODY WAS LISTENING FOR THE PAGE THROWING.
    # This probe attaches response / request / requestfailed and nothing else. A submit
    # handler that raises fires no request, stores no token and navigates nowhere -- which
    # is read three branches below as "submit sent NO /auth request -- the form is not
    # wired to the API". The JS error that actually stopped it is never recorded, so none
    # of those verdicts can be checked afterwards.
    #
    # This is #1203a6's argument one step further. Its words, about the same ladder: "NONE
    # of the 378 can be audited, because the record kept neither the URL nor whether a
    # request was even attempted. Playwright hands both facts over; nothing was asking for
    # them." Playwright hands the page errors over too.
    #
    # The reading is `page_error_fields_1202br`, lifted out of the browser manager rather
    # than written a third time (#1032): `str(error)` alone yields a minified bundle
    # location that names no source a lane can open, and #1202br paid for that lesson on
    # netflix-r33. Imported above the probe's own `try` so an ImportError is loud --
    # #1203it's note explains why that placement is not cosmetic, and #802 checks that this
    # very import resolves.
    from ...tools.browser._manager import page_error_fields_1202br

    def _is_auth_url_1203it(_u) -> bool:
        """Does this URL belong to the auth surface the framework serves?"""
        _s = str(_u or "")
        return any(_seg in _s for _seg in _AUTH_SURFACE_1203it)

    try:
        async with async_playwright() as pw:
            try:
                browser = await pw.chromium.launch(args=["--no-sandbox"])
            except Exception as _launch_exc:
                # #234: heal a missing browser binary once in-process, then retry.
                from ...tools.browser._bootstrap import heal_missing_browser
                if not heal_missing_browser(_launch_exc):
                    raise
                browser = await pw.chromium.launch(args=["--no-sandbox"])
            page = await (await browser.new_context(
                viewport={"width": 1380, "height": 900})).new_page()
            # #1203je: WAIT FOR THE FRONTEND, LIKE THE OTHER BROWSER WALK ALREADY DOES.
            #
            # `test_user_runner._wait_frontend_ready` exists for exactly this and its
            # docstring names the harm: "the delivery flow restarts the compose stack per
            # milestone, so the browser walk can fire while the FRONTEND container is DOWN /
            # rebuilding -> every goto raises net::ERR_CONNECTION_REFUSED -> ... a FALSE
            # 'unusable' that escape-ships a HEALTHY app (outlook run-28 v1.2.0, live)".
            # There are TWO browser walks and only that one called it.
            #
            # This is the LARGEST ui_flow failure cause in the corpus. Ranking the failing
            # `ui_flows` notes since 2026-09-15 by normalised text: `Page.goto:
            # net::ERR_CONNECTION_REFUSED at .../login` is first with 32 records across 25
            # runs, ahead of "submit sent NO /auth request" (28 / 22 runs) and the #1126b
            # landing check (17 / 9). It then reaches the lane as `UI login: Error: ...` in
            # `broken`, which makes the verdict ISSUES -- a verdict about the APP.
            #
            # IT IS NOT A PORT BUG, which was the first thing to rule out, because #1136 and
            # #1203ia are both that shape. For every run in the modern era carrying one of
            # these notes the port in the note EQUALS the host port `frontend` publishes in
            # that run's own compose (r176 8053:3000, r126 8006:3000, r127/r129/r130/r131
            # 8009:3000). Nothing was listening. And in 34 of those 52 reports the API half
            # had already walked (`api_steps > 0`), so the stack was up and the FRONTEND
            # specifically was not.
            #
            # The API half of this very function, 25 lines below where it is called, already
            # waits up to 240s on `/health` and says so instead of blaming the app ("if it
            # never comes up, say THAT instead of misdiagnosing the app"). This is the same
            # rule for the other half, and it reuses the owner rather than restating it
            # (#1032) -- including its calibrated budget, and #159's distinction between
            # "never served" and "served but not mounted": only NEVER SERVED skips, because
            # a served-but-blank app is a real defect this walk must still catch.
            try:
                from .test_user_runner import _wait_frontend_ready as _wfr_1203je
            except Exception as _imp1203je:          # #802 / #1203iu: never leave it unbound
                _wfr_1203je = None
            if _wfr_1203je is not None and not await _wfr_1203je(page, frontend_base):
                try:
                    await browser.close()
                except Exception:
                    pass
                return {"ran": False, "reason": (
                    "frontend at %s never served within the readiness budget — the "
                    "container is down or still building, so no flow was driven. This is "
                    "NOT a verdict about the app (#1203je)." % frontend_base)}
            for route, label in (("/signup", "signup"), ("/login", "login")):
                try:
                    await page.goto(frontend_base + route,
                                    wait_until="networkidle", timeout=20000)
                    async def _fill_visible_inputs() -> int:
                        """Fill every visible input; return how many were filled (#1203ix).

                        The count is the only way to see a MULTI-STEP form from out here: a
                        form that reveals its password field on the second round reports 1
                        then 2, and one that never advances reports 1, 1, 1.
                        """
                        _filled_1203ix = 0
                        for inp in await page.locator("input").all():
                            try:
                                if not await inp.is_visible():
                                    continue        # step-hidden field (e.g. password before step 1)
                            except Exception:
                                pass
                            ph = ((await inp.get_attribute("placeholder")) or "").lower()
                            typ = ((await inp.get_attribute("type")) or "").lower()
                            # #670: NEVER fill an input that cannot BE filled. The `else` below
                            # fills every unrecognised visible input with a text string, so a
                            # "Remember me" checkbox raised
                            #   Locator.fill: Input of type "checkbox" cannot be filled
                            # and — because only `is_visible()` is guarded, not the fill — the
                            # exception aborted the whole flow and the run was reported as
                            # "UI login: the form is not wired to the API". The app was fine.
                            #
                            # Measured: 12 of 66 test-user reports fail the login flow, and r128
                            # is exactly this. 10 of the 208 delivered login pages carry a
                            # checkbox, so every one of those is a false negative waiting to
                            # happen. Signup passes 66/66, which is why the asymmetry looked
                            # like a login-wiring bug rather than a probe bug.
                            #
                            # These are the standard HTML input types `fill()` rejects; skipping
                            # them cannot hide a real defect, because a form whose EMAIL or
                            # PASSWORD field is unfillable still fails exactly as before.
                            if typ in _UNFILLABLE_INPUT_TYPES_670:
                                continue
                            # #1203ip: TYPE decides before PLACEHOLDER. r185's field is
                            # `placeholder="Birthdate" type="date"` — the chain below reads
                            # placeholders, and "birthdate" matches none of them, so the field
                            # fell to the generic text `else` and threw. Asking the type first
                            # is also the only order that cannot be defeated by a placeholder
                            # that happens to say "name" or "mobile" on a typed field.
                            if typ in _TYPED_INPUT_VALUES_1203ip:
                                await inp.fill(_TYPED_INPUT_VALUES_1203ip[typ])
                                _filled_1203ix += 1
                            elif "email" in ph or typ == "email" or "mobile" in ph:
                                await inp.fill(f"uiflow{sfx}@t.io")
                                _filled_1203ix += 1
                            elif "pass" in ph or typ == "password":
                                await inp.fill("UiFlow123!x")
                                _filled_1203ix += 1
                            elif "user" in ph:
                                await inp.fill(f"uiflow{sfx}")
                                _filled_1203ix += 1
                            elif "name" in ph:
                                await inp.fill("Ui Flow")
                                _filled_1203ix += 1
                            else:
                                await inp.fill(f"uiflow{sfx}")
                                _filled_1203ix += 1
                        return _filled_1203ix

                    # Up to 3 fill+submit rounds so a legitimate MULTI-STEP auth form is not
                    # mis-reported as "form not wired". Netflix-style email-first login
                    # (LoginPage `single=true`) ADVANCES a step on the first submit WITHOUT
                    # calling the API and reveals the password field only then — a single click
                    # stores no token + does not navigate, which the old one-shot check read as
                    # a dead form. Re-fill the now-visible fields and submit again; stop as soon
                    # as a token is stored or the page navigates. Single-step forms succeed on
                    # round 1 (later rounds are a no-op once token/navigation is observed).
                    token, moved = None, False
                    # #566o: capture the auth network response so a FAILED login is diagnosed
                    # accurately. The LoginPage is often correctly wired (fetch('/auth/login') +
                    # token store), but the submit can still store no token — because the UI login
                    # user was never registered (401), or the response shape differs (2xx, no token).
                    # The old note ALWAYS said "form is not wired to the API", which misdiagnoses a
                    # wired form → agents chase a non-bug. Record /auth/* responses to tell the modes
                    # apart: no request = dead form; non-2xx = creds/backend; 2xx+no token = shape.
                    _auth_resps: list = []
                    # #1203a6: RECORD THE REQUESTS TOO, not only the responses.
                    #
                    # `_auth_resps` is empty in two situations that mean opposite things: the
                    # submit never fired a request, and the submit fired one that never got a
                    # response (connection refused while the stack was restarting, DNS, CORS
                    # preflight refused). Both landed in the "no request = dead form" branch
                    # below, so the note accused the form of being unwired either way.
                    # MEASURED over the 656 test_user_reports in the corpus: that note is by
                    # far the dominant verdict — 378 occurrences, against 13 for "wired but
                    # 4xx" and 37 for "no token" — and NONE of the 378 can be audited, because
                    # the record kept neither the URL nor whether a request was even attempted.
                    # Playwright hands both facts over; nothing was asking for them.
                    _auth_reqs: list = []
                    _auth_failed: list = []
                    # #1203iu: what the page threw, if anything, while this flow ran.
                    #
                    # Bound INSIDE the route loop, like the three lists above it, and that is
                    # what keeps it correct: the loop attaches its listeners per route and
                    # never detaches them, so by `/login` the `/signup` handlers are still
                    # live -- but they close over the `/signup` lists, which nothing reads
                    # again. Hoisting this list out of the loop (the tidy-up that `#1203is`
                    # warns about for `sfx`, in the opposite direction) would let the signup
                    # flow's errors be reported against the login flow. A test pins it here.
                    _page_errors_1203iu: list = []

                    def _on_pageerror_1203iu(_e):
                        try:
                            _f = page_error_fields_1202br(_e)
                            _msg = _f.get("message") or _f.get("text") or ""
                            if _msg:
                                _page_errors_1203iu.append(_msg[:200])
                        except Exception:
                            pass

                    def _on_resp(_r):
                        try:
                            if _is_auth_url_1203it(_r.url):
                                _auth_resps.append(int(_r.status))
                        except Exception:
                            pass

                    def _on_req_1203a6(_q):
                        try:
                            if _is_auth_url_1203it(_q.url):
                                _auth_reqs.append(str(_q.url))
                        except Exception:
                            pass

                    def _on_reqfail_1203a6(_q):
                        try:
                            if _is_auth_url_1203it(_q.url):
                                _f = getattr(_q, "failure", None)
                                _auth_failed.append("%s (%s)" % (
                                    _q.url, (_f if isinstance(_f, str) else
                                             getattr(_f, "error_text", None)) or "no error text"))
                        except Exception:
                            pass
                    try:
                        page.on("response", _on_resp)
                        page.on("request", _on_req_1203a6)
                        page.on("requestfailed", _on_reqfail_1203a6)
                        page.on("pageerror", _on_pageerror_1203iu)
                    except Exception:
                        pass
                    # #1203ix: HOW MANY ROUNDS RAN, AND WHAT EACH ONE COULD SEE.
                    #
                    # The loop below exists because a multi-step auth form advances without
                    # calling the API, and "submit sent NO /auth request" is the corpus's
                    # commonest ui_flow failure (93 of 270). Measured over the 173 runs with an
                    # auth page: those whose auth source calls `setMode(`/`setStep(`/`setStage(`
                    # emit that note in 49 of 89 runs (55%), against 24 of 84 (29%) for the
                    # ones that do not.
                    #
                    # #1203iy: THAT POOLED PAIR OVERSTATES IT, and the correction belongs
                    # here rather than in my memory of it. Split by domain, which is the
                    # obvious confound because multi-step auth is not evenly distributed:
                    #
                    #     tiktok    multi 23/53 = 43%   single 20/54 = 37%   (+6 points)
                    #     netflix   multi 26/33 = 79%   single  4/7 = 57%    (+22, n=7)
                    #
                    # netflix fails this note more at BOTH levels and is almost entirely
                    # multi-step, so most of the pooled gap is composition. The effect that
                    # survives is +6 points on the only comparison with real power on both
                    # sides. It still points the same way in both domains, which is why the
                    # counts below are worth having -- but "nearly twice the rate" was mine,
                    # pooled, and wrong.
                    #
                    # That is a correlate without a mechanism, and I falsified two candidates
                    # for it from the corpus alone: email-first forms with no password field
                    # (41% against 42%) and pages whose first button is a dismiss control
                    # (n=6). Telling the remaining stories apart needs to know what the loop
                    # SAW, and nothing recorded it: a form that reveals its password on round
                    # two reads 1 then 2, one that never advances reads 1, 1, 1, and one whose
                    # primary control could not be clicked reads a single entry.
                    #
                    # Record-only on purpose. #1203iw has just settled what this note says,
                    # and four tickets' tests locate that branch by its wording; these counts
                    # are for the next investigation, not for the lane, so they go where
                    # #1203a6 put the requests — beside the verdict, in the record.
                    _fill_rounds_1203ix: list = []
                    for _round in range(3):
                        _fill_rounds_1203ix.append(await _fill_visible_inputs())
                        # #1202py: a comma selector matches in DOCUMENT order, so `.first` of
                        # "button[type=submit], form button, button" was whichever button came
                        # first on the page — on tiktok-r126's login that is a nav or "Use QR
                        # code" button, the form was never submitted, and this reported "submit
                        # sent NO /auth request — the form is not wired" at 16:03 while the
                        # browser test-user, which tries the selectors in PRIORITY order, logged
                        # in with the same page at 16:08. One rule, the runner's.
                        try:
                            from .test_user_runner import _click_primary as _click_1202py
                            if not await _click_1202py(page):
                                break
                        except Exception:
                            break
                        await page.wait_for_timeout(2000)
                        token = await page.evaluate(
                            "() => localStorage.getItem('token') || "
                            "localStorage.getItem('access_token')")
                        moved = not page.url.rstrip("/").endswith(route)
                        if token or moved:
                            break
                    ok = bool(token) or moved
                    # #1203b6: per FLOW, not per walk. The note chain below is about to gain a
                    # "keep what a check above already said" guard, and without this the guard
                    # would read the PREVIOUS flow's note and attach `login`'s explanation to
                    # `signup`. Initialised here, beside the verdict it explains.
                    _note = ""
                    # #1126b: THE SECOND COPY of the post-login check. #1126 taught
                    # `test_user_runner` to ask where the login LANDED, not just that it left
                    # the auth route — and this copy never got it. It is weaker still: `or`,
                    # not `and`, so a stored token alone passes the flow no matter where the
                    # user ends up.
                    #
                    # netflix-local-r3 is the proof. Its LoginPage stores `access_token` and
                    # then does `window.location.href = '/'`, and App.jsx routes `/` to
                    # <LandingPage/> — the signed-OUT page, `Sign In` still in its header. This
                    # function recorded `{flow: signup, ok: True, token_stored: True,
                    # navigated: True}` and `ui_flows.passed = True`, while the walk's own
                    # ui_flow checks were failing with "/genres returned 200 but rendered
                    # login". Three runs in a row shipped that redirect (r1, r2, r3) and #1126
                    # fired zero times in r3 because the flow that runs here is not the one it
                    # was applied to. #665's lesson, again: the copy drifts from the original.
                    #
                    # Reuses `_landed_in_the_app_1126` rather than restating the rule — a THIRD
                    # copy is how this happened. Same two-signal conservatism: a login
                    # affordance still on screen AND a destination that is the site root or the
                    # page we came from. The `or` above is deliberately untouched; this only
                    # withdraws a claim of success that the landing contradicts.
                    if ok:
                        try:
                            from .test_user_runner import (
                                _landed_in_the_app_1126 as _landed1126,
                                _LOGIN_AFFORDANCE_JS as _AFF1126)
                            _aff = bool(await page.evaluate(_AFF1126))
                            _dest = page.url.split("?", 1)[0]
                            from urllib.parse import urlparse as _up1126
                            _dpath = _up1126(_dest).path or "/"
                            if not _landed1126(_dpath, route, _aff):
                                ok = False
                                # #1203gp: NAME THE FAULT THIS FLOW ACTUALLY HAS. `ok` is
                                # `bool(token) or moved`, so it is true in two cases that are
                                # not successes, and both used to be reported as a redirect
                                # problem. Split over the 16 corpus notes carrying #1126b:
                                #   * 4 had `auth_requests == 0` — the form issued NOTHING and
                                #     the token in storage was left by the signup flow that ran
                                #     first in the same browser context (r169's login flow:
                                #     `auth_requests: 0, auth_status: [], token_stored: true`);
                                #   * 2 had a 2xx and NO token stored (r168's login:
                                #     `auth_requests: 4, auth_status: [200], token_stored:
                                #     false`), reported as "SUCCEEDED (token=False)";
                                #   * 10 really did store a token after a request, and for
                                #     those the landing complaint is right.
                                # So 6 of 16 sent the reader at the redirect while the fault
                                # was upstream. The mirror of #1203g1, where a note contradicted
                                # the evidence printed beside it.
                                #
                                # The C-case wording is LEFT WORD FOR WORD: it is what catches
                                # netflix-local-r3, whose LoginPage stores access_token and then
                                # navigates to '/', a route App.jsx renders as the signed-OUT
                                # page. `ok = bool(token) or moved` is also untouched — #1126b
                                # says that `or` is deliberate, and this only changes wording.
                                if not _auth_reqs and not _auth_failed:
                                    _note = (
                                        "the login form issued NO auth request, and the token "
                                        "in storage was left by an earlier flow — so nothing "
                                        f"here logged in and {_dpath!r} is simply where you "
                                        "started. Wire the submit to the auth endpoint, then "
                                        "re-check the landing. (#1126b/#1203gp)")
                                elif not token:
                                    _note = (
                                        f"login returned {_auth_resps or 'no status'} but "
                                        f"stored NO token, and {_dpath!r} still shows a way to "
                                        "sign in — the request reached the API and the response "
                                        "was dropped. Store the token, then re-check the "
                                        "landing. (#1126b/#1203gp)")
                                else:
                                    _note = (
                                        f"login SUCCEEDED (token={bool(token)}) but landed on "
                                        f"{_dpath!r}, which still shows a way to sign in — the user "
                                        "is back on the signed-out page. Redirect to a route that "
                                        "requires auth, not to '/'. (#1126b)")
                        except Exception:
                            pass  # best-effort: a probe that throws must not fail a good login
                    if ok:
                        _note = ""
                    elif _note:
                        # #1203b6: A CHECK ABOVE ALREADY EXPLAINED THIS ONE. #1126b sets
                        # `ok = False` and writes the note that names the repair; this chain
                        # then ran because `ok` was False and replaced it with its own final
                        # `else`, which says "no token was stored and no navigation" about a
                        # record whose `token_stored` and `navigated` are both true. r144's
                        # signup flow is exactly that, and `browser_ui_unusable` held its last
                        # four green gate windows on it.
                        #
                        # The chain keeps its job -- explaining a failure that arrived with no
                        # explanation -- and stops outranking one that did.
                        pass
                    elif not _auth_resps and (_auth_reqs or _auth_failed):
                        # #1203a6: the form IS wired — it sent the request and got nothing back.
                        # Blaming the wiring here sends a lane to add a call that already
                        # exists; r142's signup page has a real <form onSubmit> doing
                        # `fetch('/auth/register')` and was told its submit "does nothing".
                        _why = (_auth_failed[0] if _auth_failed
                                else "the request was issued but no response arrived")
                        _note = ("the form IS wired — it sent %d /auth request(s) and NO response "
                                 "came back: %s. The app/backend was unreachable at this moment, "
                                 "which says nothing about the form. Check the stack is up before "
                                 "re-probing; do not add an api call to this page."
                                 % (len(_auth_reqs) or len(_auth_failed), _why))
                    elif not _auth_resps and _page_errors_1203iu:
                        # #1203iu: EVIDENCE BEFORE THE GUESS. When the page said what went
                        # wrong, that is the note, and the branch below is not reached at all.
                        #
                        # #1203iu left that branch asserting a mechanism on the grounds that
                        # removing it would be another guess. #1203iw then measured the
                        # mechanism -- 71 of the 73 runs that emitted it have a submit handler
                        # AND an auth call on an auth page -- and demoted it to the last of
                        # three numbered checks. So THIS branch is the one that still names a
                        # cause, and it only does so because the page named it.
                        _note = ("submit sent NO /auth request, and the page threw first: "
                                 "%s. The handler did not reach its api call; fix that error "
                                 "and re-probe. This says nothing about the wiring."
                                 % _page_errors_1203iu[0])
                    elif not _auth_resps:
                        # #1203iw: REPORT THE OBSERVATION, NOT A GUESS AT ITS CAUSE.
                        # Those are #612's words, and this is the one branch it left a guess
                        # in. #612 removed "the form is not wired to the API" from the other
                        # branches after checking the SERVER side -- `POST /auth/login`
                        # answered 200 in all 12 runs it had -- and kept it here, because
                        # "no request was seen" looked like evidence for it.
                        #
                        # The PAGE side says otherwise. Counting every run that emitted this
                        # note against its own frontend source: 71 of 73 have BOTH a submit
                        # handler and an auth call in a file whose name is auth-like, and 172
                        # of the corpus's 173 runs have a submit handler on an auth page at
                        # all -- the single run that has none never emitted this note. So the
                        # parenthetical named a mechanism that is absent in 71 of the 73
                        # cases it was written about, and #612 already recorded what that
                        # costs: "it lands in the failure ledger and sends the frontend lane
                        # to re-wire a form that is already wired."
                        #
                        # DEMOTED, NOT DELETED. The claim is the last thing to check rather
                        # than the stated cause, so a form that really has no handler still
                        # reads correctly at (3) -- and #612's, #1203a6's, #1203b6's and
                        # #1203g1's tests all locate this branch by that phrase, which is
                        # another reason deleting it would be the wrong shape of fix.
                        # #1203it and #1203iu are two reasons "no request seen" happens with
                        # the form wired: the listeners were watching `/auth/` while the app
                        # logged in through `/oauth/authorize`, and nothing listened for the
                        # page throwing at all.
                        #
                        # The counts stay in this comment and out of the note: the note is
                        # capped before it is read (#1202vx), so prose inside it would spend
                        # the budget the evidence needs.
                        _note = ("submit sent NO /auth request — no call to the auth surface "
                                 "was seen after the click. Check, in this order: (1) was the "
                                 "submit disabled, or did client-side validation reject the "
                                 "typed values; (2) does the handler reach its api call; "
                                 "(3) only then, whether the form is not wired to the API "
                                 "at all")
                    elif all(s >= 400 for s in _auth_resps):
                        _note = (f"the form IS wired but /auth returned {sorted(set(_auth_resps))} "
                                 f"(login user not registered / bad credentials / backend error) — "
                                 f"not a wiring bug")
                    else:
                        _note = (f"/auth returned {sorted(set(_auth_resps))} but no token was stored "
                                 f"and no navigation — response shape or post-login handling issue")
                    # #1203a6: the verdict's OWN EVIDENCE, so a reader can check it later.
                    # Without `url`/`auth_requests` the 378 "not wired" verdicts in the corpus
                    # are unfalsifiable after the fact — the same shape this project keeps
                    # finding: the decision is persisted and the grounds are not.
                    out["flows"].append({
                        "flow": label, "ok": ok,
                        "token_stored": bool(token), "navigated": moved,
                        "auth_status": sorted(set(_auth_resps)),
                        "url": str(getattr(page, "url", "") or (frontend_base + route)),
                        "auth_requests": len(_auth_reqs),
                        "auth_failed": _auth_failed[:3],
                        # #1203iu: persisted whether or not the note used it, so a verdict
                        # written without a page error is as auditable as one written with.
                        "page_errors": _page_errors_1203iu[:3],
                        # #1203ix: one entry per round that ran, holding the inputs it filled.
                        "fill_rounds": _fill_rounds_1203ix,
                        # #1203iz: THIS FLOW PASSED AND NOBODY LOGGED IN.
                        #
                        # `ok` is `bool(token) or moved`, and #1126b left that `or` deliberately
                        # untouched -- it withdraws success only when the LANDING contradicts
                        # it. A flow can therefore pass on navigation alone, and the record
                        # already proves one did: tiktok-web-r177, the run with the best
                        # delivery in the corpus (4 of 4 milestones, every closing gate green),
                        # has three such records --
                        #     signup  reqs=0  status=[]  token_stored=false  url=.../ 
                        #     login   reqs=0  status=[]  token_stored=false  url=.../
                        # Zero auth requests, no token, and the destination is the site root,
                        # which shows no login affordance -- so #1126b's landing check sees
                        # nothing wrong and the zero-request fact is never consulted. #1203gp
                        # counted four `auth_requests == 0` cases but only in the branch where
                        # the landing check had ALREADY withdrawn `ok`.
                        #
                        # Measured over the 522 ui_flow records: 252 passed, 26 of them with no
                        # token, and 22 of those 26 show no auth request either -- though 19 of
                        # the 26 predate #1203a6 and have no `auth_requests` field at all, so
                        # three records in one run is what is actually PROVEN today.
                        #
                        # RECORDED, NOT ACTED ON, and the reason is a real one: an app that
                        # logs in through a path outside the watched surface and sets an
                        # httpOnly cookie looks exactly like this from here, and withdrawing
                        # `ok` would turn its success into a false failure. #1126b's `or` is
                        # deliberate; this flag is what makes the class countable in the next
                        # runs instead of invisible, which is what #1203ix did for the rounds.
                        "passed_without_auth_1203iz": bool(
                            ok and not token and not _auth_resps
                            and not _auth_reqs and not _auth_failed),
                        "note": _note})
                except Exception as exc:
                    out["flows"].append({"flow": label, "ok": False,
                                         "note": f"{type(exc).__name__}: {exc}"[:160]})
            await browser.close()
    except Exception as exc:
        return {"ran": False, "reason": f"{type(exc).__name__}: {exc}"[:200]}
    out["passed"] = all(f.get("ok") for f in out["flows"]) if out["flows"] else False
    return out


async def _ui_test_user(project_dir: Path, llm: Any) -> Dict[str, Any]:
    """First-time-user feedback over the latest visual-gate screenshots. One
    multimodal call; images ride the #41 compression cache. Best-effort."""
    shots = sorted((project_dir / "design" / "visual_gate").glob("*.png"))
    # #1203c9: NAME WHICH ONE. "no screenshots or no llm" is 23 of the 199 reports, and the two
    # causes have nothing in common: no screenshots means the visual gate has not produced any
    # yet (a timing fact, like #616's), no llm means the caller passed none (a wiring fact).
    if llm is None:
        return {"ran": False, "reason": "no llm was passed to the ui test-user (wiring, not "
                                        "timing — the screenshots are irrelevant here)"}
    if not shots:
        return {"ran": False, "reason": "no screenshots under design/visual_gate AT THIS MOMENT "
                                       "— the visual gate writes them; this probe may simply "
                                       "have run first"}
    try:
        from utils.llm import Message
        from .visual_fidelity import _b64
        parts: List[Dict[str, Any]] = [{"type": "text", "text": (
            "You are a brand-new user opening this web app for the first time. "
            "Below are screenshots of its screens (filename = screen name). For "
            "each screen report, as JSON: {\"screens\": [{\"name\": ..., "
            "\"works\": \"what is usable\", \"problems\": [\"empty areas, "
            "broken layout, placeholder text, missing data, confusing flows\"]}], "
            "\"top_issues\": [\"the 3-5 frictions to fix first\"]}. Judge "
            "usability and completeness as a USER (not visual style)."
        )}]
        for sh in shots[:8]:
            parts.append({"type": "text", "text": f"screen: {sh.stem}"})
            parts.append({"type": "image_url", "image_url": {
                "url": f"data:image/png;base64,{_b64(str(sh))}", "detail": "high"}})
        client = getattr(llm, "_client", llm)
        resp = await client.chat([Message.user_multimodal(parts)],
                                 temperature=0.0, max_tokens=3000)
        text = getattr(resp, "content", "") or ""
        _raw1203c9 = text
        m = re.search(r"\{.*\}", text, re.DOTALL)
        data = json.loads(m.group(0)) if m else {}
        return {"ran": True,
                "screens": data.get("screens") or [],
                "top_issues": [str(x)[:300] for x in (data.get("top_issues") or [])][:8]}
    except Exception as exc:
        # #1203c9: KEEP WHAT THE RUN PAID FOR. This is the most expensive single call in the
        # run (8 high-detail screenshots in one multimodal request) and the model's answer was
        # discarded whole whenever `json.loads` raised — 21 of 199 reports, every one of them
        # `Expecting ',' delimiter`, which is an unescaped quote or a missing comma in the
        # model's own JSON. No repair is attempted: guessing where a quote belonged would
        # invent findings. The failure stays a failure, with the same exception text; the
        # difference is that the words are on disk and the reason says so.
        _reason1203c9 = f"{type(exc).__name__}: {exc}"[:200]
        _raw1203c9 = locals().get("_raw1203c9") or ""
        _out1203c9 = {"ran": False, "reason": _reason1203c9}
        if _raw1203c9:
            try:
                _p1203c9 = Path(project_dir) / "logs" / "ui_test_user_raw_1203c9.txt"
                _p1203c9.parent.mkdir(parents=True, exist_ok=True)
                _p1203c9.write_text(_raw1203c9, encoding="utf-8")
                _out1203c9["raw_saved_to_1203c9"] = str(_p1203c9)
                _out1203c9["reason"] = (
                    _reason1203c9 + " — the model DID answer (%d chars); its words are kept at "
                    "logs/ui_test_user_raw_1203c9.txt and excerpted below, so the walk is not "
                    "lost" % len(_raw1203c9))[:400]
            except Exception:
                pass        # a failed save must not also lose the excerpt below
            _out1203c9["raw_excerpt_1203c9"] = _raw1203c9[:2000] + (
                "\n… (%d of %d chars not shown; full text in logs/)"
                % (len(_raw1203c9) - 2000, len(_raw1203c9)) if len(_raw1203c9) > 2000 else "")
        return _out1203c9


def describe_non_pass_1038(summary: Any, mcp: Any = None) -> str:
    """Name whatever actually produced a non-PASS test-user verdict.

    #1038: the delivery-time log printed ONLY `summary["broken"]`. But the verdict ladder is

        broken            -> ISSUES
        missing or MCP    -> PARTIAL
        neither           -> PASS

    so PARTIAL is *defined* as "broken is empty". Every PARTIAL report therefore printed
    ``BROKEN: []`` and named nothing — 84 of them across r1-r175, 100% of the PARTIAL
    verdicts, at the delivery cut, where the whole point is to say what a new user would hit.

    Lives beside the summary it formats so the two shapes cannot drift apart, which is how
    #1032's two normalisers came to disagree.
    """
    summary = summary if isinstance(summary, Mapping) else {}
    mcp = mcp if isinstance(mcp, Mapping) else {}
    bits = []
    for label, key, cap in (("BROKEN", "broken", 6), ("MISSING (404/405)", "missing", 6)):
        vals = summary.get(key) or []
        try:
            vals = list(vals)
        except Exception:
            vals = []
        if vals:
            shown = "; ".join(str(v) for v in vals[:cap])
            hidden = len(vals) - min(cap, len(vals))
            bits.append(f"{label}: {shown}"
                        + (f" (+{hidden} more not shown)" if hidden > 0 else ""))
    # ★ `"mcp_complete" in summary`, not `.get(..., False)`: an ABSENT key means the MCP probe
    # did not report, and answering "INCOMPLETE (None/None tools)" would state as a finding
    # something nobody measured. An empty container is not a fact — the trap this very fix
    # exists to close, reproduced once inside the fix itself.
    if "mcp_complete" in summary and not summary.get("mcp_complete"):
        note = mcp.get("note")
        bits.append("MCP surface INCOMPLETE (%s/%s tools%s)" % (
            mcp.get("tools_found"), mcp.get("tools_expected"), f"; {note}" if note else ""))
    # #1203jc: say that the API half was never exercised, on EVERY report where it was
    # not -- including the ones that already name a UI or MCP finding. A reader deciding
    # whether the app works needs to know the journey contributed no evidence either way;
    # without it the ladder's own fallback below would answer "no cause recorded (report a
    # framework defect)" for `NOT_WALKED`, whose cause is known and is not a defect.
    if summary.get("api_steps") == 0:
        bits.append("API JOURNEY NOT WALKED (0 of 0 steps) -- no business collection "
                    "supported a create at this point, so the contract-derived journey "
                    "had nothing to drive; api_smoke covers the reads. Not a verdict "
                    "about the app")
    # #1203je: the other half. Named separately because the two have nothing in common:
    # an empty API journey is a CONTRACT fact about this milestone, while a UI walk that
    # did not run is an ENVIRONMENT fact about this moment.
    if summary.get("ui_walk_ran_1203je") is False:
        bits.append("UI WALK DID NOT RUN (%s) -- no browser flow was driven, so the UI "
                    "contributed no evidence either way. Not a verdict about the app"
                    % (str(summary.get("ui_walk_reason_1203je") or "reason not recorded")))
    # #1035's lesson: the cause slot must never render empty.
    return "; ".join(bits) or (
        "no cause recorded — the verdict was not PASS but nothing was flagged broken, "
        "missing or MCP-incomplete (report a framework defect)")


def run_test_user_validation(
    project_dir: Any,
    business_endpoints: List[Mapping[str, Any]],
    *,
    version: str = "",
    base_url: Optional[str] = None,
    compose_file: Optional[Any] = None,
    llm: Any = None,
) -> Dict[str, Any]:
    """Run the post-milestone test-user validation against an ALREADY-RUNNING app.

    ``base_url`` (e.g. ``http://localhost:3001``) overrides discovery; otherwise the
    backend host port is resolved from the compose project. Returns a report and writes
    it to ``test_user_reports/<version>.json``. Never raises."""
    project_dir = Path(project_dir)
    report: Dict[str, Any] = {"version": version or "unknown", "api": {}, "mcp": {},
                              "summary": {}}
    try:
        api_paths = {ep.get("path") for ep in (business_endpoints or [])
                     if isinstance(ep, Mapping) and ep.get("path")}

        base = base_url
        if not base:
            cf = Path(compose_file) if compose_file else (project_dir / "docker" / "docker-compose.yml")
            port = _backend_host_port(cf, cf.parent) if cf.exists() else None
            base = f"http://localhost:{port}" if port else "http://localhost:3001"

        # Round 32 (1.3.0 report): the journey ran while the validation cycle
        # was still rebuilding the env — register hit a dead socket and the
        # whole report read "auth broken". Wait for the backend first; if it
        # never comes up, say THAT instead of misdiagnosing the app.
        import time as _time
        _up = False
        _deadline = _time.time() + 240
        while _time.time() < _deadline:
            # module _http (tests monkeypatch it; raw urllib bypassed the
            # mock and slept the suite for 20 minutes). ANY status (even
            # 404) proves the socket serves.
            try:
                h = _http("GET", base + "/health", timeout=4)
            except Exception:
                h = {"status": None}
            if h.get("status") is not None:
                _up = True
                break
            _time.sleep(5)
        if not _up:
            report["summary"] = {"verdict": "ENV_UNAVAILABLE",
                                 "error": f"backend at {base} not reachable within 240s"}
            raise _EnvUnavailable()  # falls through to the shared persist
        api = _api_test_user(base, api_paths, list(business_endpoints or []))
        report["api"] = api
        report["mcp"] = _mcp_test_user(project_dir, list(business_endpoints or []))
        # usage-level: drive the real UI auth forms in a browser
        try:
            import asyncio as _aio2
            _cf = Path(compose_file) if compose_file else (
                project_dir / "docker" / "docker-compose.yml")
            from .validation_runner import _service_host_port as _shp
            _fe_port = _shp(_cf, _cf.parent, "frontend") if _cf.exists() else None
            if _fe_port:
                report["ui_flows"] = _aio2.run(
                    _ui_auth_flow(f"http://localhost:{_fe_port}"))
            else:
                report["ui_flows"] = {"ran": False, "reason": "no frontend port"}
        except RuntimeError:
            report["ui_flows"] = {"ran": False, "reason": "event loop unavailable"}
        if llm is not None:
            import asyncio as _aio
            try:
                report["ui"] = _aio.run(_ui_test_user(project_dir, llm))
            except RuntimeError:
                # already inside a loop (orchestrator runs this in a thread —
                # normally loop-free; guard anyway)
                report["ui"] = {"ran": False, "reason": "event loop unavailable"}

        steps = api.get("steps", [])
        passed = [s for s in steps if s.get("ok")]
        broken = [f"{s['method']} {s['path']} → {s.get('status')} ({s.get('note')})"
                  for s in steps if s.get("kind") == "broken"]
        missing = [f"{s['method']} {s['path']} → {s.get('status')}"
                   for s in steps if s.get("kind") == "missing"]
        # ISSUES = a real defect (5xx/auth/wrong-data) a user would hit. PARTIAL = only
        # softer gaps — missing/not-yet-implemented endpoints (404/405) or an incomplete
        # MCP surface — but nothing actually broken. PASS = everything works + MCP complete.
        _uifl = report.get("ui_flows") or {}
        _ui_broken = [f"UI {f['flow']}: {f.get('note')}"
                      for f in _uifl.get("flows", []) if not f.get("ok")]
        # #1203je: DID THE UI WALK CONTRIBUTE EVIDENCE AT ALL?
        #
        # `_ui_broken` is derived from `flows`, so a walk that never ran leaves it empty and
        # looks exactly like a walk that passed. That mattered little while `ran: False`
        # meant only "playwright unavailable" / "no frontend port" -- 2 reports in the whole
        # corpus, both July, and BOTH recorded PASS. #1203je makes it common: the 32
        # ERR_CONNECTION_REFUSED records across 25 runs become `ran: False` instead of flow
        # failures, so without this the fix would trade a FALSE ISSUES for a FALSE PASS --
        # #1202xc's shape, which I withdrew for exactly that.
        #
        # `ran` alone is the signal because it is faithful: over all 263 reports with a
        # `ui_flows` object, `ran: True` carries exactly 2 flows every time and `ran: False`
        # carries 0 every time. A `flows`-is-empty clause would be a rule for a world the
        # corpus does not show. Default True for an object that predates the key, so old
        # shapes are not retro-judged.
        _ui_ran_1203je = bool(_uifl.get("ran", True))
        # #1203c6: KEEP THE API-ONLY COUNT BEFORE THE REBINDING. `broken` becomes
        # API + UI on the next line, and `api_failed` below used to read it -- so a run
        # whose API was entirely green reported one or two API failures (118 of 198
        # persisted reports, 96 runs; r146 M1.1 says api_steps=2, api_passed=2,
        # api_failed=2 with both steps ok). The combined list is still what the verdict
        # ladder and `describe_non_pass_1038` consume; only the COUNT was wrong.
        _api_broken_1203c6 = len(broken)
        _ui_broken_1203c6 = len(_ui_broken)
        broken = broken + _ui_broken
        if broken:
            verdict = "ISSUES"
        elif missing or not report["mcp"].get("complete", False):
            verdict = "PARTIAL"
        elif not steps or not _ui_ran_1203je:
            # #1203jc: A PASS MUST NOT BE A CLAIM ABOUT A JOURNEY THAT NEVER RAN.
            #
            # `broken` and `missing` are both derived FROM `steps`, so an empty journey
            # empties both and the ladder fell through to its strongest claim. Measured
            # over the 263 persisted reports: 121 walked 0 steps, and 33 of those were
            # recorded PASS -- 33 of the 42 PASS verdicts in the whole corpus, 79%. The
            # log sentence those produce reads "PASS -- 0/0 API journey steps OK + MCP
            # surface complete", which asserts the journey was OK.
            #
            # 0 steps is LEGITIMATE and is not what is being fixed. `_api_crud_journey`
            # drives a create->list->read->update->delete from each collection that
            # supports create, so a read-heavy early milestone has nothing to start from
            # (api_smoke probes every registered endpoint separately and covers the
            # reads). tiktok-web-r185 is the whole timeline: its first business
            # collection POST (`/api/notifications`) was registered at 18:48:58 and the
            # v1.0.0 and v1.1.0 walks ran at 17:51 and 18:29 -- before one existed. The
            # three `/api/v1/*` collections that DID exist are `is_business() == False`.
            # So the journey behaved correctly and only the verdict lied.
            #
            # Placed LAST so it changes exactly the false PASS and nothing else: a real
            # finding still wins. r185 is the case that matters -- its UI signup failure
            # keeps ISSUES even though the API journey walked nothing, because an empty
            # journey is an absence of evidence and never a reason to downgrade evidence
            # somebody did collect.
            verdict = "NOT_WALKED"
        else:
            verdict = "PASS"
        report["summary"] = {  # NOTE (#1038): `describe_non_pass_1038` below formats this
            "api_steps": len(steps),
            "api_passed": len(passed),
            "api_failed": _api_broken_1203c6,          # #1203c6: API only
            "ui_flows_failed_1203c6": _ui_broken_1203c6,
            # #1203je: published because `describe_non_pass_1038` takes the SUMMARY, not
            # the report, and a cause slot that cannot see the reason prints nothing.
            "ui_walk_ran_1203je": _ui_ran_1203je,
            "ui_walk_reason_1203je": str(_uifl.get("reason") or "")[:200],
            "api_missing": len(missing),
            "mcp_complete": report["mcp"].get("complete", False),
            "broken": broken,
            "missing": missing,
            "verdict": verdict,
        }
    except _EnvUnavailable:
        pass  # summary already set; persist below
    except Exception as exc:  # never break delivery
        report["summary"] = {"verdict": "ERROR", "error": f"{type(exc).__name__}: {exc}"}

    try:
        out_dir = project_dir / "test_user_reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{(version or 'latest').replace('/', '_')}.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8")
    except Exception:
        pass
    return report
