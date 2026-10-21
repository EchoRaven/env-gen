r"""#1203om: the guard's 401 never passes through CORSMiddleware, so a browser calls it CORS.

Starlette builds the middleware stack in REVERSE. The skeleton registers `CORSMiddleware`
immediately after `app = FastAPI()`; `_framework_auth_guard` is a `@app.middleware("http")`
added LATER, which makes the guard the OUTER layer. A response the guard returns without
awaiting `call_next` therefore skips CORS entirely — so a cross-origin tokenless call comes back
with no `Access-Control-Allow-Origin` and the browser reports a CORS FAILURE rather than a 401.

PROVEN against real Starlette 0.49 with that exact structure: ACAO is ABSENT with the
framework's order and PRESENT when CORS is the outer layer. (Three other hypotheses were tested
and disproved first: the preflight is fine — Starlette echoes the origin; `credentials:
'include'` appears in only 3 delivered frontends and r181 is not one; and `/api/auth/me` really
exists in r181's `custom_routes.py:342`.)

MEASURED WITH AST, not regex — a string scan of the guard body undercounted this at 64:
**101 of 101** delivered `main.py` files register CORS before a 4xx-returning guard, r190 and
r191 among them.

WHERE IT BECAME THE BLOCKER: r181's verifier wrote the same thing about FORTY-NINE times —
"CORS blocks GET http://localhost:8058/api/auth/me from http://localhost:8059" — and the run
died on `validation_ui_evidence_failed` + `deliverability_ui_flow_failed`, which the hold ledger
ranks as the corpus's two most common delivery blockers.

★ #1202zu ALREADY KNOWS THE RULE and applies it to LANE-installed middleware ("Starlette builds
the stack in reverse, so middleware added later runs OUTER, and one that returns a Response
without awaiting `call_next` answers the request with the guard never consulted"). This is the
other half: the framework's own guard.

★ FOUND BY READING NEAR-DUPLICATE LANE COMMENTS — a lane that says the same thing 49 times is
reporting something nobody fixed. Same instrument as #1203oj/#1203ok/#1203ol, a fourth cut.
"""
import ast
import re
import unittest
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime import backend_scaffold as BS


def _guard_template():
    """The injected guard's source text, from the module that writes it."""
    import inspect
    src = inspect.getsource(BS)
    i = src.index("async def _framework_auth_guard")
    j = src.index("# === end auth enforcement ===", i)
    return src[i:j]


def _guard_ast():
    """The guard as an AST.

    ★ TEXT ASSERTIONS ON THE TEMPLATE WERE NOT ENOUGH. Mutations OM4 (drop the credentials
    header), OM5 (`try:` -> `if True:`) and OM7 (stop deferring to `call_next`) all read MISSED
    against them, because the strings they quote appear elsewhere in the same function. The
    structure has to be read.
    """
    import ast as _a
    import textwrap
    return _a.parse(textwrap.dedent(_guard_template())).body[0]


def _the_401_block():
    """The `If` whose body builds the 401 response."""
    import ast as _a
    fn = _guard_ast()
    for node in _a.walk(fn):
        if isinstance(node, _a.If) and "_fw_401" in _a.dump(
                _a.Module(body=node.body, type_ignores=[])):
            return node
    raise AssertionError("the 401 branch was not found")


class TheGuardsOwn401CarriesTheHeaders(unittest.TestCase):
    @staticmethod
    def _header_assignments():
        """``{header: value-source}`` actually assigned on the 401 response, from the AST."""
        import ast
        out = {}
        for node in ast.walk(_the_401_block()):
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            tgt = node.targets[0]
            if not isinstance(tgt, ast.Subscript):
                continue
            if "_fw_401" not in ast.dump(tgt.value):
                continue
            key = getattr(tgt.slice, "value", None)
            if isinstance(key, str):
                out[key] = ast.dump(node.value)
        return out

    def test_all_three_headers_are_assigned(self):
        """AST, so dropping any ONE of them is caught (mutation OM4 removed the credentials
        header and the text assertions did not notice)."""
        got = self._header_assignments()
        for h in ("Access-Control-Allow-Origin", "Access-Control-Allow-Credentials", "Vary"):
            with self.subTest(header=h):
                self.assertIn(h, got, "the 401 no longer sets %s" % h)

    def test_the_origin_header_echoes_the_caller(self):
        self.assertIn("_fw_origin",
                      self._header_assignments()["Access-Control-Allow-Origin"])

    def test_it_only_adds_them_when_there_is_an_origin(self):
        """A same-origin or server-to-server call has no Origin; inventing one would be wrong.
        Read as STRUCTURE: the assignments sit under an `if` whose test is the origin."""
        import ast
        blk = _the_401_block()
        guards = [n for n in ast.walk(blk)
                  if isinstance(n, ast.If)
                  and "_fw_origin" in ast.dump(n.test)
                  and "Access-Control-Allow-Origin" in ast.dump(
                      ast.Module(body=n.body, type_ignores=[]))]
        self.assertTrue(guards, "the headers are set unconditionally")
        for g in guards:
            consts = [n.value for n in ast.walk(g.test)
                      if isinstance(n, ast.Constant) and isinstance(n.value, bool)]
            self.assertEqual(consts, [], "the condition carries a literal boolean")

    def test_the_header_write_cannot_cost_the_401(self):
        """#1201: the status is the point; a header that will not set must not raise. The
        enclosing `Try` comes from the AST -- `if True:` passed the text version (OM5)."""
        import ast
        blk = _the_401_block()
        tries = [n for n in ast.walk(blk) if isinstance(n, ast.Try)
                 and "Access-Control-Allow-Origin" in ast.dump(
                     ast.Module(body=n.body, type_ignores=[]))]
        self.assertTrue(tries, "the header write is unguarded")
        self.assertTrue(tries[0].handlers)

    def test_the_guard_still_returns_401_and_still_DEFERS_LAST(self):
        """OM7 replaced the final `return await call_next(request)` with another 401 and the
        text test passed, because that same line appears in the public-path branch above. The
        LAST statement of the function is the one that matters."""
        import ast
        fn = _guard_ast()
        last = fn.body[-1]
        self.assertIsInstance(last, ast.Return)
        self.assertIn("call_next", ast.dump(last),
                      "the guard no longer defers to the rest of the stack")
        self.assertIn("status_code=401", _guard_template())

    def test_it_does_not_reorder_the_middleware(self):
        """Reordering is the other possible fix and it is NOT taken: the order is split across
        two writers (the skeleton emits CORS, this module injects the guard later into the same
        file) and a re-registration would double the headers on every normal response."""
        g = _guard_template()
        self.assertNotIn("add_middleware", g)


class RealStarletteSaysSo(unittest.TestCase):
    """The mechanism, exercised rather than asserted."""

    @staticmethod
    def _client(patched):
        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import JSONResponse
        from fastapi.testclient import TestClient
        app = FastAPI()
        # the skeleton's own registration, in the skeleton's own place
        app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                           allow_methods=["*"], allow_headers=["*"])

        @app.middleware("http")
        async def guard(request, call_next):
            if not request.headers.get("authorization"):
                resp = JSONResponse(status_code=401, content={"detail": "missing or invalid token"})
                if patched:
                    origin = request.headers.get("origin")
                    if origin:
                        resp.headers["Access-Control-Allow-Origin"] = origin
                        resp.headers["Access-Control-Allow-Credentials"] = "true"
                        resp.headers["Vary"] = "Origin"
                return resp
            return await call_next(request)

        @app.get("/api/auth/me")
        def me():
            return {"ok": True}

        return TestClient(app)

    def setUp(self):
        try:
            import fastapi  # noqa: F401
        except Exception:
            self.skipTest("fastapi is not installed in this interpreter")

    def test_without_the_patch_the_401_has_no_cors_header(self):
        r = self._client(False).get("/api/auth/me",
                                    headers={"Origin": "http://localhost:8059"})
        self.assertEqual(r.status_code, 401)
        self.assertIsNone(r.headers.get("access-control-allow-origin"),
                          "the unpatched order stopped losing the header, so the mechanism "
                          "this ticket is about needs re-measuring")

    def test_with_the_patch_it_carries_the_caller_origin(self):
        r = self._client(True).get("/api/auth/me",
                                   headers={"Origin": "http://localhost:8059"})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.headers.get("access-control-allow-origin"),
                         "http://localhost:8059")
        self.assertEqual(r.headers.get("access-control-allow-credentials"), "true")

    def test_a_normal_response_is_not_double_headed(self):
        r = self._client(True).get("/api/auth/me",
                                   headers={"Origin": "http://localhost:8059",
                                            "Authorization": "Bearer x"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.headers.get_list("access-control-allow-origin")), 1)

    def test_a_call_with_no_origin_gets_no_invented_header(self):
        r = self._client(True).get("/api/auth/me")
        self.assertEqual(r.status_code, 401)
        self.assertIsNone(r.headers.get("access-control-allow-origin"))


class WhatTheCorpusSays(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = Path(__file__).resolve().parents[2] / "generated"
        if not cls.corpus.is_dir():
            raise unittest.SkipTest("no generated/ corpus on this machine")

    @staticmethod
    def _order(path):
        """``(cors_line, [(guard_line, returns_4xx)])`` from the AST.

        AST because a string scan of the guard body answered 64 where the truth is 101 -- the
        guard has blank-line groups inside it and a `split("\\n\\n\\n")` window stopped before
        the 401.
        """
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            return None, []
        cors = None
        guards = []
        for n in ast.walk(tree):
            if isinstance(n, ast.Call):
                fn = getattr(n.func, "attr", getattr(n.func, "id", ""))
                if fn == "add_middleware" and n.args:
                    nm = getattr(n.args[0], "id", getattr(n.args[0], "attr", ""))
                    if nm == "CORSMiddleware":
                        cors = n.lineno if cors is None else min(cors, n.lineno)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not any(isinstance(d, ast.Call)
                           and getattr(d.func, "attr", "") == "middleware"
                           and d.args and isinstance(d.args[0], ast.Constant)
                           and d.args[0].value == "http"
                           for d in n.decorator_list):
                    continue
                early = False
                # #1203r8 (2026-10-21): A HOISTED RESPONSE STILL COUNTS.
                #
                # r46 builds the 401 into a local before returning it --
                #     _fw_401 = _FWJSONResponse(status_code=401, content={...})
                #     _fw_401.headers["Access-Control-Allow-Origin"] = _fw_origin
                #     return _fw_401
                # -- and it does that precisely so it can attach the CORS headers #1203om
                # asked for. Requiring the Response to BE the returned Call made that guard
                # invisible, and the corpus count fell to 101 of 102 with r46 as the lone
                # "exception" -- which read like the defect had been fixed somewhere.
                #
                # It had not: r46 still registers CORS at line 882 and the 401-returning guard
                # at 1018, which is the ordering this test measures. THE FRAMEWORK'S OWN REMEDY
                # WAS ERASING THE MEASUREMENT THAT JUSTIFIES IT, and every backend that adopts
                # the header-attaching fix would have eroded it further, silently, one run at a
                # time. Matching the PROPERTY (this middleware can answer 4xx) instead of one
                # SPELLING (the Response is the return expression) is what keeps it honest.
                _4xx_1203r8 = set()
                for _a in [x for x in ast.walk(n) if isinstance(x, ast.Assign)]:
                    _v = _a.value
                    if not isinstance(_v, ast.Call):
                        continue
                    _nm = getattr(_v.func, "id", getattr(_v.func, "attr", "")) or ""
                    if "Response" not in _nm:
                        continue
                    if any(kw.arg == "status_code" and isinstance(kw.value, ast.Constant)
                           and isinstance(kw.value.value, int)
                           and 400 <= kw.value.value < 500 for kw in _v.keywords):
                        for _t in _a.targets:
                            if isinstance(_t, ast.Name):
                                _4xx_1203r8.add(_t.id)
                for r in [x for x in ast.walk(n) if isinstance(x, ast.Return)]:
                    v = r.value
                    if isinstance(v, ast.Name) and v.id in _4xx_1203r8:
                        early = True
                        continue
                    if not isinstance(v, ast.Call):
                        continue
                    nm = getattr(v.func, "id", getattr(v.func, "attr", "")) or ""
                    if "Response" not in nm:
                        continue
                    for kw in v.keywords:
                        if (kw.arg == "status_code" and isinstance(kw.value, ast.Constant)
                                and isinstance(kw.value.value, int)
                                and 400 <= kw.value.value < 500):
                            early = True
                guards.append((n.lineno, early))
        return cors, guards

    def test_the_order_detector_discriminates_1203r8(self):
        """SYNTHETIC ANCHORS for `_order`, because the corpus cannot prove it discriminates.

        On today's corpus the `early` flag is True for all 102 backends -- which is exactly
        what this ticket claims, and therefore also exactly what a BROKEN detector that
        returned True unconditionally would produce. The two are indistinguishable from the
        corpus alone, so the negative cases have to be written by hand.

        The last case is the one that matters: a function that builds a 401 and returns
        SOMETHING ELSE must not count. Without it, "a 4xx is assigned somewhere in this
        function" would pass every case here and still be wrong."""
        import tempfile
        cases = [
            ("no 4xx anywhere", False, """
app.add_middleware(CORSMiddleware, allow_origins=["*"])
@app.middleware("http")
async def g(request, call_next):
    return await call_next(request)
"""),
            ("hoisted 500 is not a 4xx", False, """
app.add_middleware(CORSMiddleware, allow_origins=["*"])
@app.middleware("http")
async def g(request, call_next):
    boom = JSONResponse(status_code=500, content={})
    if bad: return boom
    return await call_next(request)
"""),
            ("hoisted 401 -- r46's shape, the whole point of #1203r8", True, """
app.add_middleware(CORSMiddleware, allow_origins=["*"])
@app.middleware("http")
async def g(request, call_next):
    deny = JSONResponse(status_code=401, content={})
    deny.headers["Access-Control-Allow-Origin"] = o
    if bad: return deny
    return await call_next(request)
"""),
            ("inline 403 -- the original shape must still count", True, """
app.add_middleware(CORSMiddleware, allow_origins=["*"])
@app.middleware("http")
async def g(request, call_next):
    if bad: return JSONResponse(status_code=403, content={})
    return await call_next(request)
"""),
            ("builds a 401 but returns a DIFFERENT name", False, """
app.add_middleware(CORSMiddleware, allow_origins=["*"])
@app.middleware("http")
async def g(request, call_next):
    deny = JSONResponse(status_code=401, content={})
    other = await call_next(request)
    return other
"""),
        ]
        d = Path(tempfile.mkdtemp())
        for label, want, src in cases:
            f = d / "m.py"
            f.write_text(src, encoding="utf-8")
            cors, guards = self._order(f)
            self.assertIsNotNone(cors, "%s: the CORS line must still be found" % label)
            self.assertEqual(len(guards), 1, "%s: expected exactly one guard" % label)
            self.assertEqual(guards[0][1], want,
                             "%s: `early` should be %s, got %s" % (label, want, guards[0][1]))

    def test_every_delivered_backend_has_the_order(self):
        """102 of 102 -- so this is not a product or era quirk.

        The count only stays truthful because `_order` sees a HOISTED 4xx response as well as
        an inline one (#1203r8): r46 hoists its 401 to attach CORS headers, and the earlier
        Call-only test read that as the defect having disappeared."""
        total = affected = 0
        for f in sorted(self.corpus.glob("*/app/backend/main.py")):
            cors, guards = self._order(f)
            if cors is None or not guards:
                continue
            total += 1
            if any(g[1] and g[0] > cors for g in guards):
                affected += 1
        if not total:
            self.skipTest("no delivered backends on this disk")
        self.assertEqual(affected, total,
                         "%d of %d delivered backends register CORS before a 4xx-returning "
                         "guard; the measurement said all of them" % (affected, total))

    def test_r181_is_the_run_where_it_blocked(self):
        """The gate ledger is where it shows, not a `*.log`.

        ★ My first count of "930 CORS mentions in r181" globbed `logs/*.log` AND `logs/*.jsonl`
        together; the `.log` files hold none of them. The gate ledger holds 84 -- the DELIVERY
        decisions that name it -- which is the number that matters anyway.
        """
        f = self.corpus / "tiktok-web-r181" / "logs" / "delivery_gate.jsonl"
        if not f.is_file():
            self.skipTest("r181 has no gate ledger on this disk")
        n = len(re.findall(r"CORS", f.read_text(encoding="utf-8", errors="ignore")))
        self.assertGreaterEqual(n, 50,
                                "r181's gate ledger was measured at 84 CORS mentions, found "
                                "%d" % n)

    def test_the_lane_said_it_over_and_over(self):
        """The instrument that found this: a near-duplicate comment is a lane reporting
        something nobody fixed."""
        import json
        f = self.corpus / "tiktok-web-r181" / "shared" / "hubs" / "workhub_comments.json"
        if not f.is_file():
            self.skipTest("r181 has no comment store on this disk")
        d = json.load(open(f, errors="ignore"))
        n = sum(1 for v in d.values()
                if isinstance(v, dict) and "CORS" in str(v.get("body") or ""))
        self.assertGreaterEqual(n, 20,
                                "r181's verifier wrote ~49 CORS comments; found %d" % n)


if __name__ == "__main__":
    unittest.main()
