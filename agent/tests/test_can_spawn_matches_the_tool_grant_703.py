r"""#703: `can_spawn` is declared, told to agents as enforcement, and read by no code.

Sweep G of the "computed but never consumed" family: keys defined in `agents_config.yaml` that no
code reads. Five hits. Three (`dynamic`, `notifies`, `coordinator`) are common words my key scan
matched loosely and are not dead. Two are real:

    optional_stages   declared as [retrieve_context, knowledge_sync] under the comment
                      "Optional stages may be skipped by the model" — and read nowhere, so the
                      declaration has no effect. Its neighbour `stages:` IS live
                      (step_runner calls `_stage_enabled(...)`).
    can_spawn         read by no code either — but three PROMPTS tell agents it is enforcement:
                      "DO NOT spawn workers (can_spawn=false by YAML flag)".

The second is the interesting one, and the interesting part is that it turns out FINE. The real
mechanism is the tool bundle: an agent without `team_spawn` in its `tool_categories` has no spawn
tool and cannot spawn whatever a prompt says. Cross-checking the two independently-maintained
declarations across every role that sets the flag:

    analysis_worker, review_worker, worker, api_test_user, mcp_test_user,
    browser_test_user, design_analyst      can_spawn=false, team_spawn absent   (7 of 7)

So no role is restricted by prompt alone today. What is missing is anything that KEEPS that true:
the flag and the grant are maintained in different parts of the same file, and if someone adds
`team_spawn` to a `can_spawn: false` role, the prompt will keep telling that agent it is
restricted "by YAML flag" while the tool sits in its hands.

No production change — nothing is broken. This is the guard that makes the redundancy
self-enforcing, in the same spirit as the fixed-width-source-window and tuned-constant guards.
"""
import re
from pathlib import Path

import pytest

CFG = (Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"
       / "multi_agent" / "agents" / "agents_config.yaml")


def _roles() -> dict:
    """{role: {"can_spawn": bool|None, "team_spawn": bool}} straight from the yaml text."""
    out, role = {}, None
    for line in CFG.read_text(encoding="utf-8").split("\n"):
        m = re.match(r"^  ([a-z_]+):\s*$", line)
        if m:
            role = m.group(1)
            out.setdefault(role, {"can_spawn": None, "team_spawn": False})
        if not role:
            continue
        mc = re.search(r"can_spawn:\s*(true|false)", line)
        if mc:
            out[role]["can_spawn"] = (mc.group(1) == "true")
        if "tool_categories:" in line:
            out[role]["team_spawn"] = '"team_spawn"' in line
    return out


# --- the probe works ------------------------------------------------------------------------------

def test_the_config_is_readable():
    assert CFG.is_file(), CFG


def test_some_roles_declare_the_flag():
    flagged = [r for r, d in _roles().items() if d["can_spawn"] is not None]
    assert len(flagged) >= 5, flagged


def test_some_roles_hold_the_bundle():
    """Negative control: if the parser never sees team_spawn, the invariant is vacuous."""
    holders = [r for r, d in _roles().items() if d["team_spawn"]]
    assert holders, "no role parsed as holding team_spawn — the parser is broken"


# --- the invariant --------------------------------------------------------------------------------

def test_can_spawn_false_implies_no_spawn_tool():
    """The one that matters: a prompt saying "by YAML flag" must not be the only restraint."""
    violations = [r for r, d in _roles().items()
                  if d["can_spawn"] is False and d["team_spawn"]]
    assert violations == [], (
        f"{violations} declare can_spawn: false but still hold the team_spawn bundle. The "
        f"prompts tell those agents they are restricted 'by YAML flag'; no code reads that "
        f"flag, so the tool is the only real restraint and they have it.")


def test_can_spawn_true_implies_the_spawn_tool():
    """The converse: a role told it may spawn must actually be able to."""
    violations = [r for r, d in _roles().items()
                  if d["can_spawn"] is True and not d["team_spawn"]]
    assert violations == [], (
        f"{violations} declare can_spawn: true but lack the team_spawn bundle — they cannot "
        f"spawn no matter what the flag or the prompt says.")


def test_every_restricted_role_is_still_restricted():
    """Pins today's measured state so a regression names the role that changed."""
    restricted = sorted(r for r, d in _roles().items() if d["can_spawn"] is False)
    assert restricted == sorted([
        "analysis_worker", "api_test_user", "browser_test_user", "design_analyst",
        # #1202rh: the realism judge is detect-only and cannot spawn, like the test-users
        # it is modelled on.
        "mcp_test_user", "realism_judge", "review_worker", "worker",
    ]), restricted


# --- the flag really is unread, which is why the guard is needed -------------------------------

def test_no_code_reads_can_spawn():
    """If someone wires it up, delete this guard and trust the code instead."""
    root = CFG.resolve().parents[2]
    assert root.name == "llm_generator", root
    hits = []
    for p in root.rglob("*.py"):
        if re.search(r"""can_spawn""", p.read_text(errors="ignore")):
            hits.append(str(p))
    assert hits == [], f"can_spawn is now read by code: {hits}"


def test_the_prompts_still_claim_it_is_enforcement():
    """The claim is what makes the unread flag worth guarding."""
    root = CFG.resolve().parents[2]
    claims = [p for p in root.rglob("*.j2") if "can_spawn" in p.read_text(errors="ignore")]
    assert claims, "no prompt mentions can_spawn — the guard's premise is gone"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
