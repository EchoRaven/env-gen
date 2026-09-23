r"""#1202sa: the generator's company does not belong in the app it generates.

Four places in the framework hard-coded `dev@virtueai.com` (password "virtue"), and all four
reach the delivered environment:

  * `mcp_scaffold._SKELETON_HEADER` -- emitted verbatim into `mcp_server/<env>/main.py`, where
    `_dev_token()` REGISTERS that address as a real user of the app in DISABLE_OAUTH mode. The
    account then appears in the app's own user listings.
  * three `bundled_skills/*/SKILL.md`, which are copied into every run's `.agents/skills/`.

112 files across the generated corpus carry the string. `smoke@virtueai.com` in
validation_runner creates one more such row per run.

The realism taxonomy calls this a source-company leak, and my own notes recorded it as "0
across the corpus" -- which was wrong, and wrong in the way that keeps recurring: I had
scanned seed data and app source, not `mcp_server/` or `.agents/skills/`. A count of zero
means the scan found nothing where it looked.

The defaults are now derived from the ENV NAME, which is the only identity that belongs in a
generated app. These tests pin the derivation rather than the one string, because a fixed
neutral constant would go stale the moment someone picks a different one.
"""
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime.mcp_scaffold import render_mcp_server


# The operator identities this repo has actually carried. Not a general blocklist -- a
# regression pin, so that removing them once cannot be quietly undone.
_OPERATOR_TOKENS = ("virtueai", "virtue-ai", "@virtue")


def _framework_root() -> Path:
    return Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator" / "multi_agent"


# --- the emitted MCP server -----------------------------------------------------------

@pytest.mark.parametrize("env", ["tiktok", "googlemaps", "netflix"])
def test_the_dev_identity_is_derived_from_the_env(env):
    out = render_mcp_server({}, env)
    assert 'DEV_USER_EMAIL", "dev@%s.local"' % env in out, \
        "the emitted dev account is not named after the env"


def test_two_envs_do_not_share_one_dev_account():
    a, b = render_mcp_server({}, "tiktok"), render_mcp_server({}, "netflix")
    assert a != b
    assert "dev@tiktok.local" in a and "dev@tiktok.local" not in b


@pytest.mark.parametrize("env", ["tiktok", "googlemaps"])
def test_nothing_the_server_ships_names_the_generator(env):
    """Including the comments. The first version of this fix put the old address back into
    the explanatory comment beside the line it was fixing -- and that comment sits INSIDE
    the skeleton template, so it would have shipped in every main.py.
    """
    out = render_mcp_server({}, env).lower()
    for token in _OPERATOR_TOKENS:
        assert token not in out, "the emitted mcp_server still carries %r" % token


# --- the skills that ship with every run ----------------------------------------------

def test_no_bundled_skill_names_the_generator():
    """`.agents/skills/` is copied into every generated run, so these are delivered docs."""
    hits = []
    for f in (_framework_root() / "bundled_skills").rglob("*"):
        if not f.is_file() or f.suffix.lower() not in (".md", ".py", ".json", ".yaml", ".yml"):
            continue
        text = f.read_text(encoding="utf-8", errors="ignore").lower()
        for token in _OPERATOR_TOKENS:
            if token in text:
                hits.append("%s:%s" % (f.name, token))
    assert not hits, "bundled skills carry operator identity: %s" % sorted(set(hits))


# --- and the framework's own smoke account --------------------------------------------

def test_the_smoke_account_does_not_name_the_generator():
    """It is infrastructure, but the row it registers is listed by the app like any other."""
    import inspect

    from env_generator.llm_generator.multi_agent.runtime import validation_runner

    src = inspect.getsource(validation_runner).lower()
    for token in _OPERATOR_TOKENS:
        assert token not in src, "the smoke account still carries %r" % token


def test_the_smoke_credential_is_consistent_between_register_and_login():
    """Two call sites share this address; if they drift, register succeeds and login never
    finds the account it just made."""
    import inspect
    import re

    from env_generator.llm_generator.multi_agent.runtime import validation_runner

    src = inspect.getsource(validation_runner)
    found = set(re.findall(r'"(smoke@[^"]+)"', src))
    assert len(found) == 1, "the smoke address disagrees between call sites: %s" % sorted(found)
