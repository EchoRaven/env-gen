r"""#1203fv: the framework's own /auth/login omitted the `user` its /auth/register returns.

`/auth/register` and `/auth/login` are both framework-owned -- the generated `main.py` header
says so verbatim: "The OAuth2 AS (/oauth/*, /auth/register|login) is framework-owned ... Do not
hand-edit". Register answers with

    {"access_token", "token_type", "expires_in", "user"}   201

and login answered with the same minus `user`. The asymmetry is indefensible on its own terms:
a client that stores the user object at registration had nothing to re-read after a login. And
it contradicts the generated contracts -- 27 corpus runs register this endpoint with
`schema.response.user`, r164 included.

It also read only `email` / `username`, while 27 runs declare `schema.request.identifier` (as a
REQUIRED field, no `?`) -- the single-field shape a login form actually posts. `identifier`
appears nowhere in the framework's own code.

What the gap cost, measured:

  * 22 runs' backend lanes added a SECOND `@router.post("/auth/login")` in `custom_routes.py`
    to shadow the framework handler -- r138, r139, r144, r153, r154, r159, r161, r163 among
    them. r163's two P0s say it outright: "POST /auth/login rejects valid tenant user
    registered through POST /auth/register" and "rejects valid credentials with 401 instead of
    creating authenticated session", both closed with "POST /auth/login now accepts
    identifier/email/username ... and returns a session item with user object" -- in
    custom_routes.py.
  * `deliverability_guard_tampering` then BLOCKS the delivery for that shadow (r161, live:
    "custom_routes.py:45 inserts a route ahead of the framework's at index 0 — shadows the
    guarded handler the projector built for that path").
  * 321 bug tasks across 87 runs name `auth/login` in their title.

So the framework's handler changes, not the gate and not the lanes. Both additions are strictly
additive: `user` is a new response key, and `identifier` is tried only AFTER the explicit
fields, so a body naming `email` or `username` keeps its exact old meaning.

LOCAL-ONLY (agent/tests/ gitignored).
"""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.oauth_scaffold import render_oauth_module  # noqa: E402

SRC = render_oauth_module("oauth_routes.py")


def _handler(name: str):
    """The AST of one nested handler in the rendered module."""
    tree = ast.parse(SRC)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError("%s is not in the rendered AS module" % name)


def _returned_keys(fn) -> set:
    """Every string key of every dict literal this handler returns inside a JSONResponse."""
    keys = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Call):
            continue
        for arg in node.value.args:
            if isinstance(arg, ast.Dict):
                keys |= {k.value for k in arg.keys
                         if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    return keys


class TheTemplateStillParses(unittest.TestCase):
    def test_the_rendered_module_is_valid_python(self):
        """It is copied VERBATIM (`render_oauth_module` reads the file and returns it), so a
        syntax slip here ships a backend that cannot import."""
        ast.parse(SRC)

    def test_it_is_rendered_verbatim_not_formatted(self):
        """The template's own code contains `.format()`-escaped CSS braces; if the renderer ever
        started formatting the whole file, the dict literals below would break."""
        self.assertIn('{"access_token": token', SRC)


class LoginAnswersLikeRegister(unittest.TestCase):
    def test_login_returns_the_user_object(self):
        self.assertIn("user", _returned_keys(_handler("auth_login")))

    def test_register_already_did_and_still_does(self):
        """The shape login is matching. If register ever stops sending it, this patch's premise
        is gone and the test says so rather than silently diverging."""
        self.assertIn("user", _returned_keys(_handler("auth_register")))

    def test_the_two_agree_on_the_session_envelope(self):
        want = {"access_token", "token_type", "expires_in", "user"}
        for name in ("auth_register", "auth_login"):
            self.assertTrue(want <= _returned_keys(_handler(name)),
                            "%s: %s" % (name, sorted(_returned_keys(_handler(name)))))


class LoginAcceptsTheIdentifierShape(unittest.TestCase):
    def _body_keys(self, fn) -> set:
        return {n.args[0].value for n in ast.walk(fn)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "get" and getattr(n.func.value, "id", "") == "body"
                and n.args and isinstance(n.args[0], ast.Constant)
                and isinstance(n.args[0].value, str)}

    def test_it_reads_identifier_as_well_as_email_and_username(self):
        keys = self._body_keys(_handler("auth_login"))
        for k in ("identifier", "email", "username", "password"):
            self.assertIn(k, keys, sorted(keys))

    def test_the_explicit_fields_are_still_tried_first(self):
        """Additive, not a re-interpretation: a body naming `email` must resolve exactly as it
        did before, so the identifier lookups come after both explicit ones."""
        fn = _handler("auth_login")
        lines = {}
        for n in ast.walk(fn):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr in ("verify_user_password", "verify_user_by_username")
                    and n.args and isinstance(n.args[0], ast.Name)):
                lines.setdefault(n.args[0].id, []).append(n.lineno)
        self.assertIn("identifier", lines, lines)
        self.assertIn("email", lines)
        self.assertIn("username", lines)
        self.assertGreater(min(lines["identifier"]), max(lines["email"]))
        self.assertGreater(min(lines["identifier"]), max(lines["username"]))

    def test_identifier_is_tried_against_both_lookups(self):
        """An identifier may be either an email or a username; trying only one would leave half
        the shape failing for a reason the caller cannot see."""
        fn = _handler("auth_login")
        attrs = {n.func.attr for n in ast.walk(fn)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.args and getattr(n.args[0], "id", "") == "identifier"}
        self.assertEqual(attrs, {"verify_user_password", "verify_user_by_username"}, attrs)

    def test_the_tenant_header_fallback_survives(self):
        """An earlier fix (a user registered into tenant B logging in as `default`) lives in the
        same handler; this patch must not disturb it."""
        self.assertIn("x-tenant-id", SRC)


if __name__ == "__main__":
    unittest.main()
