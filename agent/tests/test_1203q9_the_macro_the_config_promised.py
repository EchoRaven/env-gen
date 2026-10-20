r"""#1203q9: the config names a macro, the template defines it, and only half of that was checked.

`agents_config.yaml` declares, per profile, a `template` plus a `system_macro` and/or a
`task_macro` / `task_macros.*`. Nothing in Python ever spells those macro names -- they are
config strings handed to `BaseAgent.render_macro(template, macro_name)`, which resolves them
with `getattr(template.module, macro_name, None)`. So the contract between the two files is
load-bearing and invisible to any grep.

What happens when it breaks is NOT symmetrical:

  * `_get_system_prompt` renders and then `raise RuntimeError(f"Failed to render system
    prompt: {template}::{macro}")` -- loud, correct.
  * `_build_task_prompt` renders and then `if prompt: return prompt`, three times over, and
    falls through to `_build_generic_task_prompt(...)`. A declared-but-missing task macro
    therefore costs the lane its entire role-specific task prompt and produces a generic one
    instead, with only a `self._logger.warning` to show for it.

MEASURED before writing this file:
  * 29 (template, macro) pairs are declared in `agents_config.yaml`; 0 are broken today, and
    0 would break under `ENVGEN_PROMPT_VERSION=v4` (only v4/backend_agent.j2 and
    v4/frontend_agent.j2 exist, and both define the macros their profiles name).
  * all 15 task-side pairs render, the smallest at 333 characters -- so an empty render is
    never legitimate here and `""` always means a real break.
  * `Macro ... not found`, `Macro error ...` and `Template error ...` appear in ZERO run
    logs across the corpus, so the fall-through above has never actually fired. Under #647
    that is a reason NOT to change the behaviour on this evidence -- and a behaviour change
    there would need a live run anyway (#1202w6). What it does justify is pinning the
    contract, which makes a missing macro impossible to land in the first place.

`#1202sp` already renders every profile's SYSTEM macro (its `_render` asserts the macro
exists) -- but that file owns a different rule, "the realism contract reaches every lane",
and it never looks at a task macro. This file owns the existence-and-renders rule for ALL 29
pairs, system and task, so there is one owner for it (#1032).
"""
from __future__ import annotations

import jinja2
import pytest
import yaml

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator" / "multi_agent"
_PROMPTS = _ROOT / "prompts"

# The smallest real task prompt renders at 333 chars (mcp_test_user). This floor only has to
# separate "rendered" from "", so it is deliberately far below that and is not a measurement
# anyone needs to keep fresh (#1203oa: a parked number rots -- this one is a floor, not a fit).
_MIN_CHARS = 200


def _pairs():
    """Every (profile, template, key, macro) the config declares -- system AND task."""
    cfg = yaml.safe_load((_ROOT / "agents" / "agents_config.yaml").read_text(encoding="utf-8"))
    out = []
    for name, spec in (cfg.get("profiles") or {}).items():
        prompts = (spec or {}).get("prompts") or {}
        template = prompts.get("template")
        if not template:
            continue
        for key in ("system_macro", "task_macro"):
            if isinstance(prompts.get(key), str):
                out.append((name, template, key, prompts[key]))
        for sub, macro in (prompts.get("task_macros") or {}).items():
            if isinstance(macro, str):
                out.append((name, template, "task_macros.%s" % sub, macro))
    return sorted(out)


def _macro(template: str, macro_name: str):
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(_PROMPTS)))
    return getattr(env.get_template(template).module, macro_name, None)


def _render(macro) -> str:
    """Jinja macro args with a `{}` filler: every one of the 29 renders under it, and a dict
    answers both `.get(...)` and plain interpolation."""
    return str(macro(**{a: {} for a in (getattr(macro, "arguments", ()) or ())}))


@pytest.mark.parametrize("name,template,key,macro_name", _pairs())
def test_the_template_the_config_names_exists(name, template, key, macro_name):
    assert (_PROMPTS / template).exists(), (
        "%s.%s points at %s, which is not a prompt template" % (name, key, template))


@pytest.mark.parametrize("name,template,key,macro_name", _pairs())
def test_every_declared_macro_exists_in_its_template(name, template, key, macro_name):
    """`render_macro` resolves this with getattr(..., None); a typo here is a warning and an
    empty string, and on the task side an empty string is silently a generic prompt."""
    assert _macro(template, macro_name) is not None, (
        "%s.%s names %r, which %s does not define -- render_macro would log a warning and "
        "return ''" % (name, key, macro_name, template))


@pytest.mark.parametrize("name,template,key,macro_name", _pairs())
def test_every_declared_macro_renders_something(name, template, key, macro_name):
    macro = _macro(template, macro_name)
    assert macro is not None, "%s.%s: %r missing" % (name, key, macro_name)
    text = _render(macro)
    assert len(text) >= _MIN_CHARS, (
        "%s.%s rendered %d chars; the lane would receive essentially nothing"
        % (name, key, len(text)))


def test_both_halves_of_the_contract_are_actually_covered():
    """#983/#1026b: a parametrised suite that yields nothing passes by not existing. And the
    reason this file exists is the TASK half, so count it separately -- if a refactor moved
    task macros somewhere else, the cases above would quietly stop checking them.
    """
    pairs = _pairs()
    system = [p for p in pairs if p[2] == "system_macro"]
    task = [p for p in pairs if p[2] != "system_macro"]
    assert len(system) >= 10, system
    assert len(task) >= 10, task


def test_the_version_switch_cannot_strand_a_macro():
    """`resolve_prompt_version` swaps the `vN/` head when ENVGEN_PROMPT_VERSION is set and the
    candidate file exists -- so a vN template that exists but lacks the macro would resolve and
    then render ''. Only v4/backend_agent.j2 and v4/frontend_agent.j2 exist today; both must
    keep defining the macros their profiles name.
    """
    checked = 0
    for name, template, key, macro_name in _pairs():
        head, _, tail = template.partition("/")
        if not head.startswith("v"):
            continue
        for other in sorted(p.name for p in _PROMPTS.iterdir() if p.is_dir()):
            if other == head or not (_PROMPTS / other / tail).exists():
                continue
            checked += 1
            assert _macro("%s/%s" % (other, tail), macro_name) is not None, (
                "ENVGEN_PROMPT_VERSION=%s would resolve %s.%s to %s/%s, which does not define "
                "%r" % (other, name, key, other, tail, macro_name))
    assert checked > 0, (
        "no alternate-version template was found to check -- if the vN directories were "
        "flattened this test stopped testing anything")
