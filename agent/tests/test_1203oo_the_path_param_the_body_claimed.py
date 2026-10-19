"""#1203oo — the MCP tool said the body takes a value that travels in the path.

`_body_fields_note_1202xt` turns the contract's `request` schema into one docstring line so
an agent handed `body: dict | None = None` knows the field names. The contract routinely
RESTATES a path parameter in `request`, and the note then called it a body field:

    POST /api/posts/{post_id}/likes.  Body fields: post_id (int)

`render_tool` has already made `post_id` a REQUIRED ARGUMENT of that tool and interpolates it
into the URL, so the note is wrong about where the value goes -- which is word for word what
`#1202xy` fixed one branch earlier for the contract's header fields. This is the third case of
the same confusion, and it is landed in the same shape: a bucket of its own, not a drop.

MEASURED over the 104 corpus contracts, writes (POST/PUT/PATCH) that have a request schema:

    writes with a request schema                             899
    advertise a path parameter as a body field                93, in 37 runs
    ...of which the note names NOTHING ELSE                   30, in 13 runs

r184, r187, r189 and r190 are among the 37, so this is live, not an old-era artifact.
Commonest names: `id` (40), `video_id` (37), `post_id` (8).

★ WHY IT STOPS AT `#1203j2` (a false sentence is its own defect) AND IS NOT A DATA BUG. Three
independent mechanisms, each measured rather than assumed, and each ratcheted below:
  * 92 of the 93 are served by a PROJECTED handler, and a projected nested create overwrites
    the parent key itself (`valid["<tfk>"] = _parent.id`), so a body copy of an FK cannot win;
  * the 7 PUT/PATCH cases are the ones that could re-key a row -- the projected update branch
    is `for k, v in valid.items(): setattr(obj, k, v)` and `hasattr(cls, "id")` is true -- and
    all 7 are SHADOWED by a lane handler for the same route in `custom_routes.py`, included
    hundreds of lines before the projected definition, and FastAPI serves the first match;
  * the only clients that actually put a path value in the body are the framework's own
    verification chains -- 27 steps in 14 runs out of 8,315 write steps that carry a body --
    and every one sends the SAME value in both places (`${video_id}`) and every one is an FK,
    never a child's own `id`.

★ The projector's own half is DELIBERATELY NOT FIXED: a projected create keeps a body `id`
(`valid` is filtered by `hasattr(cls, k)` and nothing drops the primary key), so `cls(**valid)`
would insert a caller-chosen PK and leave the sequence behind it. No corpus client does that,
and refusing it is not free -- a String `id` is a legitimate client-chosen key -- so `#647`
says no guard wider than the evidence. It is recorded because THIS note is what would have
told an agent to send it.
"""
from __future__ import annotations

import ast
import glob
import json
import os
import re
import sys
import unittest
from pathlib import Path

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _AGENT)
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.mcp_scaffold import (  # noqa: E402
    _body_fields_note_1202xt, _path_params, render_tool)

_CORPUS = os.path.join(os.path.dirname(_AGENT), "generated")


def _tool_fn(src, name):
    """The rendered tool as an AST node -- never a substring of the text."""
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name:
            return node
    return None


def _buckets(note):
    """The note parsed back into {label: {field names}} -- exact names, never substrings.

    ★ The first version of this check asked `"id" in body_part` and reported 29 leaks that
    were all `video_id` containing `id`. A substring is not a field name."""
    out = {"Body fields": set(), "Path": set(), "Headers": set()}
    for key in out:
        m = re.search(r"(?:^|\. )%s: (.*?)(?=(?:\. (?:Body fields|Path|Headers): )|$)" % key, note)
        if m:
            out[key] = {x.split(" (")[0].strip() for x in m.group(1).split(", ") if x.strip()}
    return out


# ── the shape, from the corpus endpoints that produced it ─────────────────────

class PathIsNotABody(unittest.TestCase):

    def test_a_path_param_restated_in_the_request_is_named_as_a_path_value(self):
        """instagram-core-r175's `POST /api/users/{id}/follow` states `id` and `following_id`."""
        ep = {"method": "POST", "path": "/api/users/{id}/follow",
              "schema": {"request": {"id": "int", "following_id": "int"}}}
        b = _buckets(_body_fields_note_1202xt(ep))
        self.assertEqual(b["Body fields"], {"following_id"})
        self.assertEqual(b["Path"], {"id"})

    def test_a_note_that_would_have_named_only_path_params_says_no_body_fields(self):
        """The 30-case shape: `POST /api/posts/{post_id}/likes. Body fields: post_id (int)`
        was a sentence with no true content, about a body that takes nothing."""
        ep = {"method": "POST", "path": "/api/posts/{post_id}/likes",
              "schema": {"request": {"post_id": "int"}}}
        note = _body_fields_note_1202xt(ep)
        self.assertNotIn("Body fields", note)
        self.assertEqual(note, "Path: post_id (int)")

    def test_the_real_body_fields_are_untouched(self):
        """googlemaps-r16's `POST /api/places/{place_id}/reviews` -- five real fields."""
        ep = {"method": "POST", "path": "/api/places/{place_id}/reviews",
              "schema": {"request": {"rating": "int", "text": "string", "place_id": "int"}}}
        b = _buckets(_body_fields_note_1202xt(ep))
        self.assertEqual(b["Body fields"], {"rating", "text"})
        self.assertEqual(b["Path"], {"place_id"})

    def test_all_three_buckets_coexist_in_a_stable_order(self):
        """netflix-local-r3's rating endpoint carries a header, a path restatement and a body."""
        ep = {"method": "POST", "path": "/api/titles/{id}/rating",
              "schema": {"request": {"value": "string", "X-Profile-Id": "header string?",
                                     "id": "int"}}}
        note = _body_fields_note_1202xt(ep)
        self.assertEqual(note, "Body fields: value (string). Path: id (int). "
                               "Headers: X-Profile-Id (header string?)")

    def test_an_endpoint_with_no_path_params_renders_exactly_as_before(self):
        ep = {"method": "POST", "path": "/api/auth/signup",
              "schema": {"request": {"email": "string", "password": "string"}}}
        self.assertEqual(_body_fields_note_1202xt(ep),
                         "Body fields: email (string), password (string)")

    def test_a_non_string_type_still_reports_what_it_is(self):
        """A path param declared as a nested object keeps #1202xt's typing rules."""
        ep = {"method": "PUT", "path": "/api/x/{key}",
              "schema": {"request": {"key": {"a": 1}, "other": ["s"]}}}
        b = _buckets(_body_fields_note_1202xt(ep))
        self.assertEqual(b["Path"], {"key"})
        self.assertIn("key (object)", _body_fields_note_1202xt(ep))
        self.assertEqual(b["Body fields"], {"other"})

    def test_an_express_style_param_counts_too(self):
        """`_path_params` reads `:id` as well as `{id}`, and so must this."""
        ep = {"method": "POST", "path": "/api/posts/:post_id/comments",
              "schema": {"request": {"post_id": "int", "text": "string"}}}
        b = _buckets(_body_fields_note_1202xt(ep))
        self.assertEqual(b["Path"], {"post_id"})
        self.assertEqual(b["Body fields"], {"text"})

    def test_the_name_differs_only_in_case_is_still_a_body_field(self):
        """★ No case folding. The corpus has a `{videoId}` path, and a contract that declares
        two names is talking about two things -- only the one the path actually BINDS moves.
        A dict is case-sensitive, so `VideoId` would reach the handler as its own key and
        folding it into the path bucket would stop the agent from ever being told to send it.

        ★ The first version of this test used `videoId` vs `video_id`, which a case-folding
        mutation passes unharmed (`video_id` is not `videoid`). It took a pair differing ONLY
        in case to make the comparison load-bearing -- mutation OO7."""
        ep = {"method": "POST", "path": "/api/videos/{videoId}/comments",
              "schema": {"request": {"videoId": "int", "VideoId": "int",
                                     "video_id": "int", "text": "string"}}}
        b = _buckets(_body_fields_note_1202xt(ep))
        self.assertEqual(b["Path"], {"videoId"})
        self.assertEqual(b["Body fields"], {"VideoId", "video_id", "text"})


class TheToolAlreadyTakesIt(unittest.TestCase):
    """The reason the note was wrong: the value has a home already."""

    def test_the_rendered_tool_takes_the_path_param_as_a_required_argument(self):
        ep = {"method": "POST", "path": "/api/posts/{post_id}/likes",
              "schema": {"request": {"post_id": "int"}}}
        src = render_tool(ep)
        fn = _tool_fn(src, "post_posts_by_post_id_likes")
        self.assertIsNotNone(fn, src)
        args = [a.arg for a in fn.args.args]
        self.assertIn("post_id", args)
        self.assertIn("body", args)
        # required: the path arg carries no default, `body` does
        n_def = len(fn.args.defaults)
        required = args[:len(args) - n_def]
        self.assertIn("post_id", required, ast.unparse(fn.args))
        self.assertNotIn("body", required, ast.unparse(fn.args))

    def test_the_docstring_the_agent_reads_carries_the_corrected_note(self):
        ep = {"method": "POST", "path": "/api/posts/{post_id}/likes",
              "schema": {"request": {"post_id": "int"}}}
        doc = ast.get_docstring(_tool_fn(render_tool(ep), "post_posts_by_post_id_likes")) or ""
        self.assertIn("Path: post_id (int)", doc)
        self.assertNotIn("Body fields", doc)


# ── the corpus ratchets ───────────────────────────────────────────────────────

def _write_eps():
    """(run, method, path, request) for every corpus write endpoint with a request schema."""
    out = []
    for f in sorted(glob.glob(os.path.join(_CORPUS, "*", "shared", "hubs",
                                           "registryhub_endpoints.json"))):
        run = os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(f))))
        try:
            d = json.loads(Path(f).read_text(encoding="utf-8"))
        except Exception:
            continue
        eps = d if isinstance(d, list) else (d.get("endpoints") if isinstance(d, dict) else None)
        if isinstance(eps, dict):
            eps = list(eps.values())
        if eps is None and isinstance(d, dict):
            eps = list(d.values())
        for ep in eps or []:
            if not isinstance(ep, dict):
                continue
            if str(ep.get("method", "")).upper() not in ("POST", "PUT", "PATCH"):
                continue
            req = (ep.get("schema") or {}).get("request") if isinstance(ep.get("schema"), dict) else None
            if isinstance(req, dict) and req:
                out.append((run, ep))
    return out


class TheCorpus(unittest.TestCase):

    def setUp(self):
        if not os.path.isdir(_CORPUS):
            self.skipTest("no corpus on this disk")
        self.eps = _write_eps()
        # ★ ON4's lesson: a ratchet that looked at nothing would SKIP, and a skip passes.
        # Assert the population before any verdict about it.
        self.assertGreater(len(self.eps), 800,
                           "only %d write endpoints scanned -- the reader stopped working, "
                           "and a verdict from it would be about nothing" % len(self.eps))

    def test_no_note_in_the_corpus_names_a_path_param_as_a_body_field(self):
        leaks = []
        for run, ep in self.eps:
            pp = set(_path_params(str(ep.get("path") or "")))
            if not pp:
                continue
            b = _buckets(_body_fields_note_1202xt(ep))
            bad = b["Body fields"] & pp
            if bad:
                leaks.append((run, ep.get("method"), ep.get("path"), sorted(bad)))
        self.assertEqual(leaks, [], "a path parameter is still advertised as a body field")

    def test_the_measurement_in_the_comment_is_what_the_shipped_code_says(self):
        """★ #1203j2: the numbers beside the decision have to be the ones its own predicate
        produces. The scan that FOUND this lead counted delivered servers' docstrings and
        answered 45 in 21 runs; this counts the contract, which is the input the note reads."""
        runs, clashing, only_path, only_runs = set(), 0, 0, set()
        for run, ep in self.eps:
            pp = set(_path_params(str(ep.get("path") or "")))
            req = (ep.get("schema") or {}).get("request")
            clash = {n for n in req if str(n) in pp}
            if not clash:
                continue
            clashing += 1
            runs.add(run)
            b = _buckets(_body_fields_note_1202xt(ep))
            if not b["Body fields"] and not b["Headers"]:
                only_path += 1
                only_runs.add(run)
        self.assertEqual((len(self.eps), clashing, len(runs), only_path, len(only_runs)),
                         (899, 93, 37, 30, 13))

    def test_the_modern_era_is_in_the_population(self):
        """Not an old-era artifact: r184/r187/r189/r190 each carry at least one."""
        hit = set()
        for run, ep in self.eps:
            pp = set(_path_params(str(ep.get("path") or "")))
            req = (ep.get("schema") or {}).get("request")
            if any(str(n) in pp for n in req):
                hit.add(run)
        for r in ("tiktok-web-r184", "tiktok-web-r187", "tiktok-web-r189", "tiktok-web-r190"):
            self.assertIn(r, hit)


class WhyItIsNotADataBug(unittest.TestCase):
    """The three mechanisms the decision rests on. If one stops holding, this says so."""

    def setUp(self):
        if not os.path.isdir(_CORPUS):
            self.skipTest("no corpus on this disk")

    def _route_re(self, method, path):
        seg = re.sub(r"\{(\w+)\}", lambda m: r"\{%s(?::\w+)?\}" % m.group(1),
                     re.escape(path).replace("\\{", "{").replace("\\}", "}"))
        return re.compile(r'@(?:app|router)\.%s\(\s*["\']%s["\']' % (method.lower(), seg))

    def test_every_rekeyable_update_is_shadowed_by_a_lane_handler(self):
        """The 7 PUT/PATCH cases are the only ones whose projected body could re-key a row,
        and each is registered AFTER the lane's own handler for the same route, which FastAPI
        matches first."""
        checked = []
        for run, ep in _write_eps():
            m = str(ep.get("method", "")).upper()
            if m not in ("PUT", "PATCH"):
                continue
            path = str(ep.get("path") or "")
            pp = set(_path_params(path))
            req = (ep.get("schema") or {}).get("request")
            if not any(str(n) in pp for n in req):
                continue
            bdir = os.path.join(_CORPUS, run, "app", "backend")
            main = os.path.join(bdir, "main.py")
            custom = os.path.join(bdir, "custom_routes.py")
            if not (os.path.exists(main) and os.path.exists(custom)):
                continue
            rx = self._route_re(m, path)
            msrc = Path(main).read_text(encoding="utf-8", errors="replace")
            csrc = Path(custom).read_text(encoding="utf-8", errors="replace")
            mm, cm = rx.search(msrc), rx.search(csrc)
            if not (mm and cm):
                continue
            inc = re.search(r"include_router\(\s*_custom_router", msrc)
            self.assertIsNotNone(inc, "%s: no _custom_router include to order against" % run)
            self.assertLess(inc.start(), mm.start(),
                            "%s %s %s: the projected handler is registered BEFORE the lane "
                            "router, so the re-keyable body reaches the DB" % (run, m, path))
            checked.append((run, m, path))
        self.assertEqual(len(checked), 7,
                         "expected the 7 measured PUT/PATCH cases, scanned %d: %r"
                         % (len(checked), checked))

    def test_the_only_clients_that_send_it_send_the_same_value_and_only_an_fk(self):
        """The framework's own verification chains: 27 write steps in 14 runs repeat a path
        token in the body, every one with the identical `${var}` on both sides, and not one of
        them sends a child's own `id`."""
        tok = re.compile(r"\$\{(\w+)\}|\{(\w+)\}")
        steps, hits, runs, disagree, bare_id = 0, 0, set(), [], []
        for f in sorted(glob.glob(os.path.join(_CORPUS, "*", "shared", "hubs",
                                               "registryhub_verification_chains.json"))):
            run = os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(f))))
            try:
                d = json.loads(Path(f).read_text(encoding="utf-8"))
            except Exception:
                continue
            for cid, ch in (d.items() if isinstance(d, dict) else []):
                if cid == "_meta" or not isinstance(ch, dict):
                    continue
                for st in ch.get("steps") or []:
                    if not isinstance(st, dict):
                        continue
                    if str(st.get("method", "")).upper() not in ("POST", "PUT", "PATCH"):
                        continue
                    body = st.get("body")
                    if not isinstance(body, dict) or not body:
                        continue
                    steps += 1
                    path = str(st.get("path") or "")
                    params = {a or b for a, b in tok.findall(path)}
                    for k in body:
                        if k not in params:
                            continue
                        hits += 1
                        runs.add(run)
                        if body[k] != "${%s}" % k:
                            disagree.append((run, cid, path, k, body[k]))
                        if k == "id":
                            bare_id.append((run, cid, path))
        self.assertGreater(steps, 8000, "only %d chain write steps read" % steps)
        self.assertEqual((hits, len(runs)), (27, 14))
        self.assertEqual(disagree, [], "a chain sends a DIFFERENT value in the body than in "
                                       "the path, so which one wins now decides the row")
        self.assertEqual(bare_id, [], "a chain sends a child's own `id` in a create body, "
                                      "which the projector passes straight to cls(**valid)")

    def test_a_delivered_projected_create_still_keeps_a_body_primary_key(self):
        """★ The deliberately-unlanded half, pinned by RUNNING the delivered filter rather
        than by reading the projector: instagram-core-r175's own
        `POST /api/users/{id}/follow` is the endpoint whose note said `Body fields: id (int)`.
        Its body-to-row filter is executed here with a body that carries `id`, and `id`
        survives into the dict that reaches `Follow(**valid)`.

        If the projector ever learns to drop a primary key, this goes red -- which is the
        point: the trade-off above should be re-decided, not forgotten."""
        main = os.path.join(_CORPUS, "instagram-core-r175", "app", "backend", "main.py")
        if not os.path.exists(main):
            self.skipTest("r175 is not on this disk")
        src = Path(main).read_text(encoding="utf-8", errors="replace")
        fn = None
        for node in ast.walk(ast.parse(src)):
            if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == "_projected_post_api_users_id_follow_1"):
                fn = node
                break
        self.assertIsNotNone(fn, "the projected follow handler is not in r175's main.py")
        # every statement up to the parent lookup -- that is the whole body->row filter
        pre = []
        for st in fn.body:
            if isinstance(st, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == "_parent" for t in st.targets):
                break
            pre.append(st)
        self.assertGreaterEqual(len(pre), 3, ast.unparse(fn)[:400])

        class Follow:          # the attributes `hasattr` is asked about
            id = None
            follower_id = None
            following_id = None

        env = {"body": {"id": 5, "following_id": 3}, "isinstance": isinstance,
               "hasattr": hasattr, "Follow": Follow, "_coerce_body": lambda c, v: v}
        exec(compile(ast.Module(body=pre, type_ignores=[]), "<r175>", "exec"), env)
        self.assertEqual(env["valid"], {"id": 5, "following_id": 3},
                         "the delivered filter now drops the primary key -- re-read the "
                         "#1203oo trade-off before changing this expectation")


if __name__ == "__main__":
    unittest.main()
