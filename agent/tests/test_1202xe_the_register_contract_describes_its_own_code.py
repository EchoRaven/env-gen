"""#1202xe: the framework's declared /auth/register response contradicted its own code.

Three sources described the user object and no two agreed:

  the DECLARATION   `AS_CONTRACT_ENDPOINTS` -> {"id", "email", "name", "tenant_id"}
  the IMPLEMENTATION `oauth_store.create_user` ends `return dict(row)` -- the whole created
                    row -- and backfills `username` from the email prefix when the contract
                    declares that column
  the VERIFIER      reads the contract's `users` TABLE (r135 declares username, display_name,
                    avatar_url, bio, the counts, verified) and authors `save: user.username`

`run_kickoff` records that a backend draft copies this `response` VERBATIM into its own
registration, so a lane narrows its handler to the four declared keys and the row's other
columns stop coming back. The save then starves, #592's ladder fills the variable from an
unrelated last-id, and the next step 404s on an id nobody created.

MEASURED over the corpus's chain records: 278 steps report `save FAILED`, and 174 of them are
on POST /auth/register -- the single largest source. The most-missed key is `user.username`,
74 times across 14 runs. Time-sliced it is live: present in every run r124..r137, though down
from 81 occurrences in r125 to 1-6 per run now.

The fix is prose, not shape. `response` is machine-read -- it becomes `schema["response"]` on
the registration -- so a documentation key inside it would land in anything that iterates the
shape. The four keys stay exactly as they were; `summary` now says they are what the user
ALWAYS has rather than all it has.

What this file actually guards is the pairing: if `create_user` stops returning the row, or
the summary stops saying so, the two descriptions have drifted again and one of them is lying.
"""
import ast
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.oauth_scaffold import AS_CONTRACT_ENDPOINTS  # noqa: E402

# The SHIPPED store, not the module that copies it out: `oauth_scaffold` writes this template
# into the app as `oauth_store.py`, so the template is what `create_user` actually is.
_OAUTH_STORE_SRC = os.path.join(
    _AGENT, "env_generator", "llm_generator", "multi_agent", "runtime",
    "oauth_as_templates", "oauth_store.py.tmpl")


def _register_entry():
    got = [e for e in AS_CONTRACT_ENDPOINTS if e["path"] == "/auth/register"]
    assert len(got) == 1, got
    return got[0]


def _read(path):
    with open(path, encoding="utf-8") as fh:      # #1202eu
        return fh.read()


def test_the_declared_shape_is_unchanged():
    """★ The four keys are the contract; this ticket corrects the DESCRIPTION, not the shape.

    Anything that iterates `schema["response"]["user"]` must see exactly what it saw before.
    """
    assert sorted(_register_entry()["response"]["user"]) == [
        "email", "id", "name", "tenant_id"]


def test_the_response_carries_no_prose_key():
    """A documentation key inside a machine-read shape is the bug this avoided."""
    for key, val in _register_entry()["response"]["user"].items():
        assert key.isidentifier(), "non-field key in the declared shape: %r" % key
        assert isinstance(val, str) and val, (key, val)


def test_the_summary_says_which_columns_come_back():
    """★ #1202zd rewrote what this guards. The sentence it used to check -- "the `user`
    object IS the created row" -- was FALSE: the projected SQL said
    `RETURNING id, email, name, tenant_id`. The template now derives RETURNING from the live
    table, so the summary can describe the TABLE, and this test holds it to that."""
    summary = _register_entry()["summary"]
    low = summary.lower()
    assert "users" in low and "column" in low, summary
    assert "every column" in low, "the summary no longer says the response is the row"
    assert "password" in low, (
        "the exclusion is unnamed, so 'every column' reads as including the credential")


def test_the_implementation_returns_what_the_table_has():
    """★ THIS TEST USED TO ASSERT A FRAGMENT AND READ A SEMANTIC INTO IT. It checked
    `"dict(row)" in body` and concluded "create_user returns the whole row" -- while the very
    next line of that body read `RETURNING id, email, name, tenant_id`. The fragment was
    present and the conclusion was false, in all 40 delivered trees, and the contract summary
    it was guarding repeated the falsehood to every lane that read it (#1202zd).

    `dict(row)` says nothing about WHICH columns; the RETURNING list does. So that is what
    this now reads. Behavioural coverage of the derivation lives in
    test_1202zd_register_returns_what_the_table_has.py, which compiles these very statements
    and runs them against a chosen column set."""
    src = _read(_OAUTH_STORE_SRC)
    assert "def create_user" in src, "create_user is no longer in the shipped store template"
    tail = src.split("def create_user", 1)[1]
    body = tail.split("\n    def ", 1)[0]
    assert "dict(row)" in body, "create_user no longer returns the fetched row at all"
    assert "RETURNING id, email, name, tenant_id" not in body, (
        "the RETURNING clause is a fixed four-column literal again -- the response then "
        "drops `username` and every other column the app declared, which is the 77 starved "
        "`user.username` saves this ticket measured")
    assert "existing" in body.split("RETURNING", 1)[1][:400] or "_ret" in body, (
        "the RETURNING list is no longer derived from the live table's columns")


def test_the_username_backfill_the_summary_relies_on_is_still_there():
    """The summary promises the contract's declared columns; `username` is the one the
    framework fills itself, and it is the most-missed save key (74, 14 runs)."""
    src = _read(_OAUTH_STORE_SRC)
    # The ASSIGNMENT, not the word -- `username` also appears in the method's docstring, and a
    # test that matches prose stays green while the behaviour it describes is deleted.
    assert 'cols["username"] =' in src, (
        "the emitted store no longer BACKFILLS username; the 74 starved saves were for it, "
        "and the summary promises the contract's declared columns come back")


def test_login_is_not_claimed_to_return_a_user():
    """/auth/login declares no `user` at all, and that is correct -- it returns a token. A
    summary edit must not blur the two."""
    login = [e for e in AS_CONTRACT_ENDPOINTS if e["path"] == "/auth/login"][0]
    assert "user" not in login["response"], login["response"]
