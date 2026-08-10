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
        _seen = [it.get("id") for it in (items or []) if isinstance(it, dict)][:8]
        return False, (f"created {res_label} (id={new_id}) is ABSENT from the {res_label} list "
                       f"(list has {len(items or [])} row(s), ids={_seen}) — the write did not "
                       f"persist, or the read is scoped to a different owner than the write")
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


def _mcp_test_user(project_dir: Path, business_eps: List[Mapping[str, Any]]) -> Dict[str, Any]:
    """Verify the env's MCP server is complete (a tool per endpoint) + importable."""
    out: Dict[str, Any] = {"server_found": False, "tools_expected": len(business_eps),
                           "tools_found": 0, "complete": False, "note": ""}
    try:
        srv_root = project_dir / "mcp_server"
        if not srv_root.exists():
            out["note"] = "no mcp_server/ — MCP surface not built"
            return out
        mains = list(srv_root.glob("*/main.py"))
        if not mains:
            out["note"] = "mcp_server/ present but no <env>/main.py"
            return out
        out["server_found"] = True
        src = mains[0].read_text(encoding="utf-8")
        # Count registered tools (FastMCP @mcp.tool / @app.tool / def tool_*).
        tools = len(re.findall(r"@\w+\.tool\b", src)) or len(re.findall(r"\basync def tool_\w+", src))
        out["tools_found"] = tools
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
    sfx = str(int(time.time()))[-6:]
    out: Dict[str, Any] = {"ran": True, "flows": []}
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
            for route, label in (("/signup", "signup"), ("/login", "login")):
                try:
                    await page.goto(frontend_base + route,
                                    wait_until="networkidle", timeout=20000)
                    async def _fill_visible_inputs():
                        for inp in await page.locator("input").all():
                            try:
                                if not await inp.is_visible():
                                    continue        # step-hidden field (e.g. password before step 1)
                            except Exception:
                                pass
                            ph = ((await inp.get_attribute("placeholder")) or "").lower()
                            typ = ((await inp.get_attribute("type")) or "").lower()
                            if "email" in ph or typ == "email" or "mobile" in ph:
                                await inp.fill(f"uiflow{sfx}@t.io")
                            elif "pass" in ph or typ == "password":
                                await inp.fill("UiFlow123!x")
                            elif "user" in ph:
                                await inp.fill(f"uiflow{sfx}")
                            elif "name" in ph:
                                await inp.fill("Ui Flow")
                            else:
                                await inp.fill(f"uiflow{sfx}")

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

                    def _on_resp(_r):
                        try:
                            if "/auth/" in _r.url:
                                _auth_resps.append(int(_r.status))
                        except Exception:
                            pass
                    try:
                        page.on("response", _on_resp)
                    except Exception:
                        pass
                    for _round in range(3):
                        await _fill_visible_inputs()
                        try:
                            await page.locator(
                                "button[type=submit], form button, button").first.click()
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
                    if ok:
                        _note = ""
                    elif not _auth_resps:
                        _note = ("submit sent NO /auth request — the form is not wired to the API "
                                 "(button has no handler / submit does nothing)")
                    elif all(s >= 400 for s in _auth_resps):
                        _note = (f"the form IS wired but /auth returned {sorted(set(_auth_resps))} "
                                 f"(login user not registered / bad credentials / backend error) — "
                                 f"not a wiring bug")
                    else:
                        _note = (f"/auth returned {sorted(set(_auth_resps))} but no token was stored "
                                 f"and no navigation — response shape or post-login handling issue")
                    out["flows"].append({
                        "flow": label, "ok": ok,
                        "token_stored": bool(token), "navigated": moved,
                        "auth_status": sorted(set(_auth_resps)), "note": _note})
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
    if not shots or llm is None:
        return {"ran": False, "reason": "no screenshots or no llm"}
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
        m = re.search(r"\{.*\}", text, re.DOTALL)
        data = json.loads(m.group(0)) if m else {}
        return {"ran": True,
                "screens": data.get("screens") or [],
                "top_issues": [str(x)[:300] for x in (data.get("top_issues") or [])][:8]}
    except Exception as exc:
        return {"ran": False, "reason": f"{type(exc).__name__}: {exc}"[:200]}


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
        broken = broken + _ui_broken
        if broken:
            verdict = "ISSUES"
        elif missing or not report["mcp"].get("complete", False):
            verdict = "PARTIAL"
        else:
            verdict = "PASS"
        report["summary"] = {
            "api_steps": len(steps),
            "api_passed": len(passed),
            "api_failed": len(broken),
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
