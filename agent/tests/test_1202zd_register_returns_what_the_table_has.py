r"""#1202zd: register handed back four columns while the contract's prose promised the row.

#1202xe (mine, one day earlier) added this sentence to the `/auth/register` contract:

    "The `user` object IS the created row (`create_user` returns `dict(row)`), so it carries
     every column the contract declares on `users`"

It is FALSE. The projected SQL reads `RETURNING id, email, name, tenant_id`, in all 40
delivered app trees that carry the module. `dict(row)` is a dict of the RETURNING LIST, not
of the table — so the contract was lying about framework code, which is the #919 shape the
repo already names, and it was lying in the direction that makes a lane trust it.

★ THE TEST THAT WAS SUPPOSED TO GUARD IT ASSERTED A FRAGMENT, NOT A SEMANTIC. It checked
`"dict(row)" in body` and concluded "create_user returns the whole row". The fragment is
present and the conclusion is wrong; nothing about `dict(row)` distinguishes four columns
from thirty. Same family as #1202w1's "a name is not a use", one level up: a code fragment's
presence is not the meaning read into it.

MEASURED from the corpus's own verification-chain records (not from that comment): 294 steps
report `save FAILED`, and `user.username` is the most-missed concrete key at 77, with 31
`usernameA` and 23 `username` being the same shape under other variable names. The column is
THERE and is POPULATED — `create_user` backfills it from the email local-part — it simply was
not returned. A starved save then feeds #592's ladder, which fills the variable from an
unrelated last-id, and the next step 404s on an id nobody created.

THE FIX MAKES THE SENTENCE TRUE rather than softening it: RETURNING is now built from the
live table's columns. Credentials never come back — measured over the 159 corpus app trees
carrying a `users` model, its 33 distinct column names hold exactly two secrets,
`password_hash` (159) and `hashed_password` (1); no token, secret or api_key among them. The
wider substring filter is there so a response widened BY CONSTRUCTION cannot widen to a
credential the day a contract declares one.
"""
import ast
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

_TMPL = os.path.join(_AGENT, "env_generator", "llm_generator", "multi_agent", "runtime",
                     "oauth_as_templates", "oauth_store.py.tmpl")


def _src():
    with open(_TMPL, encoding="utf-8") as fh:      # #1202eu
        return fh.read()


def _create_user_node():
    for node in ast.walk(ast.parse(_src())):
        if isinstance(node, ast.FunctionDef) and node.name == "create_user":
            return node
    raise AssertionError("create_user is gone from the shipped store template")


def _run_the_derivation(existing):
    """Execute the RETURNING-list statements FROM THE TEMPLATE against a chosen column set.

    The real statements are compiled and run, not a copy of them retyped here — a copy would
    pass while the template said something else, which is the failure this ticket is about.
    """
    fn = _create_user_node()
    # The derivation sits inside `with self._conn() as conn:`, not at the function's top
    # level -- the first version of this walked `fn.body` only and found nothing, which is
    # the "0 hits means suspect the locator" rule applied to my own test.
    def _targets(n):
        if isinstance(n, ast.Assign):
            return {getattr(t, "id", "") for t in n.targets}
        if isinstance(n, ast.AugAssign):
            return {getattr(n.target, "id", "")}
        return set()

    # By ASSIGNMENT TARGET, not by "the name appears": `row = conn.execute(... _ret ...)`
    # mentions `_ret` too, and collecting it made the exec try to call a database.
    hits = [n for n in ast.walk(fn)
            if (_targets(n) & {"_ret", "_secret"})
            or (isinstance(n, ast.If) and "_ret" in ast.dump(n.test))]
    # drop any node contained in another (an `if` and the assignment inside it)
    wanted = [n for n in hits
              if not any(o is not n and o.lineno <= n.lineno
                         and getattr(o, "end_lineno", o.lineno) >= getattr(
                             n, "end_lineno", n.lineno) for o in hits)]
    wanted.sort(key=lambda n: n.lineno)
    assert wanted, "no RETURNING-list derivation found in create_user"
    mod = ast.Module(body=wanted, type_ignores=[])
    ast.fix_missing_locations(mod)
    ns = {"existing": set(existing)}
    exec(compile(mod, "<template>", "exec"), ns)          # noqa: S102 — the point of the test
    return ns["_ret"]


def test_a_declared_username_comes_back():
    """★ The 77 starved saves. `username` is populated by this very method and was dropped
    on the way out."""
    got = _run_the_derivation(
        {"id", "email", "name", "tenant_id", "password_hash", "username", "created_at"})
    assert "username" in got, got


def test_the_credential_never_comes_back():
    got = _run_the_derivation({"id", "email", "name", "tenant_id", "password_hash"})
    assert "password_hash" not in got, got


def test_the_other_spelling_of_the_credential_is_caught():
    """`hashed_password` occurs once in the corpus; a name-equality filter would ship it."""
    got = _run_the_derivation({"id", "email", "hashed_password"})
    assert "hashed_password" not in got, got


def test_a_credential_a_contract_has_not_declared_yet_is_still_excluded():
    """★ The filter is a bound on what a widened response CAN contain, not a list of the
    columns seen so far — the corpus has no `token`/`secret`/`api_key` on `users` today."""
    got = _run_the_derivation(
        {"id", "email", "reset_token", "api_key_hash", "client_secret", "bio"})
    for leaked in ("reset_token", "api_key_hash", "client_secret"):
        assert leaked not in got, (leaked, got)
    assert "bio" in got, got


def test_the_four_always_present_columns_come_first():
    """Anything reading the response positionally, and every existing consumer, sees what it
    saw before at the front."""
    got = _run_the_derivation(
        {"id", "email", "name", "tenant_id", "username", "bio", "password_hash"})
    assert got[:4] == ["id", "email", "name", "tenant_id"], got


def test_the_rest_is_ordered_so_two_runs_agree():
    """A set iterates in hash order; an unsorted tail would make the emitted SQL differ
    between processes for no reason."""
    a = _run_the_derivation({"id", "email", "zeta", "alpha", "mid"})
    b = _run_the_derivation({"mid", "alpha", "zeta", "email", "id"})
    assert a == b, (a, b)
    assert a[a.index("email") + 1:] == sorted(a[a.index("email") + 1:]), a


def test_a_table_with_nothing_returnable_still_returns_something():
    """`RETURNING` with an empty list is a SyntaxError, and an app whose users table is all
    credential-named would otherwise take the backend down on register."""
    got = _run_the_derivation({"password_hash"})
    assert got == ["id"], got


def test_a_missing_standard_column_is_not_invented():
    """RETURNING names a column that does not exist → the insert raises and register 409s."""
    got = _run_the_derivation({"id", "email"})
    assert "name" not in got and "tenant_id" not in got, got


def test_the_returning_clause_is_derived_and_not_a_literal():
    """★ The mutation this ticket exists to make impossible: a fixed column list that reads
    correct and silently drops whatever the app actually declared."""
    fn = _create_user_node()
    for node in ast.walk(fn):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            v = node.value
            if "RETURNING" in v:
                assert "{}" in v or "{" in v, (
                    "the RETURNING clause is a literal again: %r" % v)
                assert "email" not in v, (
                    "the RETURNING clause names columns literally again: %r" % v)


def test_the_contract_summary_now_states_what_the_code_does():
    """The pairing #1202xe meant to guard, restated so it can actually fail: the summary must
    describe the LIVE TABLE and must name the exclusion."""
    from multi_agent.runtime.oauth_scaffold import AS_CONTRACT_ENDPOINTS
    e = [x for x in AS_CONTRACT_ENDPOINTS if x["path"] == "/auth/register"][0]
    s = e["summary"].lower()
    assert "users" in s and "column" in s, e["summary"]
    assert "password" in s, "the exclusion is unnamed, so 'every column' reads as including it"
    assert "every column" in s, e["summary"]


def test_the_declared_response_shape_is_still_the_four_always_present_keys():
    """`response` is machine-read — it becomes `schema["response"]` on the registration — and
    widening it would make every consumer that iterates the shape expect columns a given app
    may not have. The four stay; the summary carries the rest."""
    from multi_agent.runtime.oauth_scaffold import AS_CONTRACT_ENDPOINTS
    e = [x for x in AS_CONTRACT_ENDPOINTS if x["path"] == "/auth/register"][0]
    assert sorted(e["response"]["user"]) == ["email", "id", "name", "tenant_id"]


def test_the_username_backfill_is_still_there():
    """The fix only returns what the row has; `username` is populated by this method, and
    without the backfill the widened response would carry a null."""
    assert 'cols["username"] =' in _src()


# ── the row must still be renderable ──────────────────────────────────────────────

def _json_safe():
    """The template's own `_json_safe_row_1202zd`, compiled from the shipped source."""
    for node in ast.walk(ast.parse(_src())):
        if isinstance(node, ast.FunctionDef) and node.name == "_json_safe_row_1202zd":
            mod = ast.Module(body=[node], type_ignores=[])
            ast.fix_missing_locations(mod)
            ns = {}
            exec(compile(mod, "<template>", "exec"), ns)      # noqa: S102
            return ns["_json_safe_row_1202zd"]
    raise AssertionError("the row coercion is gone from the shipped store template")


def test_a_timestamp_column_does_not_take_register_down():
    """★ THE REGRESSION THIS TICKET NEARLY SHIPPED. `created_at` is a `timestamp`, psycopg3
    hands back a `datetime`, and the register handler renders with
    `fastapi.responses.JSONResponse` — plain `json.dumps`, no encoder. Widening RETURNING
    without this would have 500'd every register on all 159 corpus app trees, every one of
    which declares `created_at`. Nothing in the suite would have caught it; only a live run
    would, and there is no live run to be had."""
    import datetime
    import json
    out = _json_safe()({"id": 1, "created_at": datetime.datetime(2026, 9, 29, 12, 0)})
    assert out["created_at"] == "2026-09-29T12:00:00", out
    json.dumps(out)          # the actual requirement


def test_the_coercion_is_the_one_the_projected_handlers_use():
    """#1032: `main.py`'s projected CRUD handlers all render a row with
    `v.isoformat() if hasattr(v, "isoformat") else v`. A second spelling here would be a
    second authority on the same question."""
    src = _src()
    body = src.split("def _json_safe_row_1202zd", 1)[1].split("\ndef ", 1)[0]
    assert "isoformat" in body, body[:400]


def test_the_types_json_already_takes_are_untouched():
    """The four existing keys must serialise exactly as they did — this ticket widens the
    row, it does not restate the values already in it."""
    row = {"id": 7, "email": "a@b.c", "name": "A", "tenant_id": "default",
           "verified": True, "followers_count": 0, "bio": None}
    assert _json_safe()(row) == row


def test_a_container_column_passes_through():
    """psycopg3 gives `jsonb` back as a list/dict, which json.dumps handles; stringifying it
    would hand the client a Python repr."""
    row = {"prefs": {"dark": True}, "tags": ["a", "b"]}
    assert _json_safe()(row) == row


def test_a_type_the_coercion_does_not_know_degrades_instead_of_raising():
    """★ The user's standing rule is no fallback that MASKS a failure. This one does not mask
    anything: a `numeric` (Decimal) or `uuid` column becomes a readable string instead of
    taking register down, and the value is still there to read."""
    import decimal
    import json
    import uuid
    u = uuid.uuid4()
    out = _json_safe()({"balance": decimal.Decimal("1.50"), "ref": u})
    assert out["balance"] == "1.50" and out["ref"] == str(u), out
    json.dumps(out)


def test_an_empty_row_is_not_a_crash():
    assert _json_safe()({}) == {}
    assert _json_safe()(None) == {}


def test_create_user_actually_returns_through_the_coercion():
    """★ I have tested a helper and not its caller often enough to check for it by reflex.
    Every test above compiles `_json_safe_row_1202zd` out of the template and runs it
    directly, so deleting the CALL would leave all of them green while register 500s on the
    first app with a timestamp column. Three properties: the call exists, it is in
    `create_user`, and it is what the return hands back."""
    fn = _create_user_node()
    returns = [n for n in ast.walk(fn) if isinstance(n, ast.Return)]
    assert returns, "create_user no longer returns anything"
    wired = False
    for r in returns:
        for node in ast.walk(r):
            if isinstance(node, ast.Call) and getattr(
                    node.func, "id", "") == "_json_safe_row_1202zd":
                wired = True
    assert wired, (
        "create_user's return does not pass the row through the coercion; a `timestamp` "
        "column then reaches `json.dumps` and every register 500s")


def test_the_sibling_reader_is_left_alone_on_purpose():
    """`get_user_by_id` keeps its four columns. Not an oversight and not "fixing one reader
    of two": that method feeds `/oauth/token`, where the row is used to sign a JWT and never
    reaches a client. Pinned so a later widening is a decision rather than a drift."""
    src = _src()
    assert "SELECT id, email, name, tenant_id FROM users WHERE id = %s" in src, (
        "get_user_by_id's projection changed -- if it now returns the app's columns too, the "
        "reason recorded in #1202zd no longer holds and the note should be revisited")
