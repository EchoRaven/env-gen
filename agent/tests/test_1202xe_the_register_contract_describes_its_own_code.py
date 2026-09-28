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


def test_the_summary_says_the_user_is_the_row():
    """★ The correction. Without it the declaration understates its own implementation."""
    summary = _register_entry()["summary"]
    low = summary.lower()
    assert "row" in low, summary
    assert "create_user" in summary, "the summary does not name the code it describes"
    assert "password_hash" in summary, (
        "the one column that must NOT come back is unnamed, so 'the whole row' reads as "
        "including the secret")


def test_the_implementation_still_returns_the_whole_row():
    """★ The pairing. The summary is only true while `create_user` returns `dict(row)`.

    Read off the EMITTED source in oauth_scaffold, which is what ships in the app."""
    src = _read(_OAUTH_STORE_SRC)
    assert "def create_user" in src, "create_user is no longer in the shipped store template"
    tail = src.split("def create_user", 1)[1]
    # to the next METHOD, not the next `def` -- the body contains nested helpers
    body = tail.split("\n    def ", 1)[0]
    assert "dict(row)" in body, (
        "create_user no longer returns the row, so the summary now overstates what comes "
        "back -- correct one or the other, never leave them disagreeing")


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
