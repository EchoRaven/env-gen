r"""#1202sp: the realism contract has to reach every lane that can write content.

`#1202rg` put the contract into the shared agent-definition macros, and the A/B experiment
behind `#1202rs` is the reason it matters: the group WITHOUT the contract seeded eight
`@example.com` addresses, the group with it seeded zero. That benefit is entirely conditional
on the contract actually reaching the lane that writes the seed — and "a mechanism that is
never called" is the defect class this work keeps finding, including twice in its own output
(`#1202rt`'s judge had no caller; `#1202iy`'s rewrite never reached the lane's own App.jsx).

So this renders EVERY profile's real system prompt through its real macro and asserts the
contract is in the text the model will actually receive. Checked by hand once; a hand check
does not survive the next profile someone adds.

All 14 profiles carry it today: orchestrator, backend, frontend, verifier, debugger,
knowledge, analysis_worker, review_worker, worker, api/mcp/browser_test_user, realism_judge,
design_analyst. The exemption list below is empty and may only shrink.
"""
import jinja2
import pytest
import yaml

from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator" / "multi_agent"

# Empty on purpose. A profile that genuinely cannot carry the contract goes here WITH a reason,
# and the list may never grow silently — same shape as #647's frozen baseline.
_EXEMPT: dict = {}


def _profiles():
    cfg = yaml.safe_load((_ROOT / "agents" / "agents_config.yaml").read_text(encoding="utf-8"))
    out = []
    for name, spec in (cfg.get("profiles") or {}).items():
        prompts = (spec or {}).get("prompts") or {}
        if prompts.get("system_macro") and prompts.get("template"):
            out.append((name, prompts["template"], prompts["system_macro"]))
    return sorted(out)


def _render(template: str, macro_name: str) -> str:
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(_ROOT / "prompts")))
    macro = getattr(env.get_template(template).module, macro_name, None)
    assert macro is not None, "%s::%s does not exist" % (template, macro_name)
    return str(macro(**{a: "" for a in (getattr(macro, "arguments", ()) or ())}))


@pytest.mark.parametrize("name,template,macro", _profiles())
def test_every_profile_receives_the_realism_contract(name, template, macro):
    if name in _EXEMPT:
        pytest.skip("exempt: %s" % _EXEMPT[name])
    text = _render(template, macro)
    assert len(text) > 2000, "%s's system prompt rendered to almost nothing" % name
    assert "realism" in text.lower() or "真实" in text, \
        "%s never sees the realism contract" % name


@pytest.mark.parametrize("name,template,macro", _profiles())
def test_the_contract_names_what_it_forbids(name, template, macro):
    """A rule without an example is a rule the model can agree with and still break. The
    corpus measured these as the recurring tells, and `example.com` as the most frequent of
    all — four domains, six runs, every one of eight SUCCESS deliveries."""
    if name in _EXEMPT:
        pytest.skip("exempt: %s" % _EXEMPT[name])
    text = _render(template, macro).lower()
    for tell in ("example.com", "placeholder", "lorem"):
        assert tell in text, "%s's contract does not name %r" % (name, tell)


def test_the_exemption_list_is_empty():
    """It may shrink, never grow. A profile added without the contract has to fail above
    rather than be quietly listed here."""
    assert _EXEMPT == {}, "profiles were exempted from the realism contract: %s" % _EXEMPT


def test_there_are_profiles_to_check():
    """The parametrisation is the test: if the config stops yielding profiles, every case
    above silently passes by not existing."""
    assert len(_profiles()) >= 10, _profiles()
