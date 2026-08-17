r"""#804: the prompt edits were the last source-asserted change in the batch. Now they execute.

#803's lesson — *a testing gap described as a validation gap* — run against everything shipped
this session. Almost all of it already had an executable proof: #782/#783 under node, #803 against
SQLite, #784/#789-#793/#796-#799 against real fixtures. **The prompt edits did not.** They were
asserted with `"<marker>" in file.read_text()`, and every one of them was applied by raw Python
string surgery on a Jinja2 template — five times across `v3` and `v4`, without ever rendering the
result.

A `.j2` file that has been string-patched can:
  * fail to parse (an unbalanced `{{`, a stray `{%`);
  * parse but land the new text inside a block that never executes;
  * parse and render while a *sibling* macro breaks.

None of that is caught by a substring check on the source.

**Two instrument errors on the way to this test, both recorded because the numbers looked like
findings.** A plain `Environment().render()` first raised *"no loader for this environment"* (the
templates `include`), and with a loader it returned **31 characters** — which looks like a
catastrophic regression and is not: `frontend_agent.j2` puts its body in `{% macro %}` blocks, so
a bare render emits almost nothing. The framework calls `render_macro`. Rendering the macros gives
**115,980 chars (v3)** and **108,553 (v4)**. Both zeros were the instrument, the eighth and ninth
of this session.
"""
import pathlib

import pytest

jinja2 = pytest.importorskip("jinja2")
from jinja2 import Environment, FileSystemLoader, TemplateSyntaxError  # noqa: E402


_PROMPTS = (pathlib.Path(__file__).resolve().parents[1]
            / "env_generator/llm_generator/multi_agent/prompts")
_TEMPLATES = sorted(p.relative_to(_PROMPTS).as_posix() for p in _PROMPTS.rglob("*.j2"))


def _env():
    return Environment(loader=FileSystemLoader(str(_PROMPTS)))


def test_the_scan_finds_the_templates():
    """Non-vacuity: a moved prompts dir would otherwise turn this whole file into silent passes."""
    assert len(_TEMPLATES) >= 10, _TEMPLATES


@pytest.mark.parametrize("rel", _TEMPLATES, ids=_TEMPLATES)
def test_every_template_parses(rel):
    try:
        _env().parse((_PROMPTS / rel).read_text(encoding="utf-8"))
    except TemplateSyntaxError as e:                  # pragma: no cover - the failure IS the report
        pytest.fail(f"{rel}:{e.lineno}: {e.message}")


# Macros declare their own required parameters and raise `UndefinedError` when one is missing —
# CORRECT behaviour, not a defect. Two wrong turns before this:
#   1. catching only `TypeError`, so `kickoff_response_prompt` (needs `milestone_index`) took the
#      whole render down and every clause assertion failed against working templates;
#   2. hand-listing candidate kwarg sets — item 110's trap, a curated list standing in for a
#      semantic question, and it left five templates "failing" for want of a parameter name.
# Jinja exposes each macro's declared parameters. Ask the macro.


def _render_all_macros(rel):
    """Every macro in a template, rendered with placeholders for whatever IT declares. Returns
    ``(output, failed)`` — a macro that still raises is reported rather than silently skipped, so
    this cannot decay into a vacuous pass."""
    mod = _env().get_template(rel).module
    out, failed = "", []
    for name in dir(mod):
        # Skip Jinja internals only. Skipping every underscore name — the first version —
        # silently excluded real content macros: `backend_agent.j2` keeps its ownership rules in
        # `_ownership_block`, so #809's clause was in the file, rendered fine, and this helper
        # could not see it. #804's own coverage gap, found the first time #804 was used in anger.
        if name.startswith("__") or name in ("environment", "eval_ctx", "exported_vars"):
            continue
        macro = getattr(mod, name)
        if not callable(macro):
            continue
        args = {a: (0 if "index" in a or "round" in a or "count" in a else f"<{a}>")
                for a in (getattr(macro, "arguments", ()) or ())}
        try:
            out += str(macro(**args))
        except Exception as exc:                      # pragma: no cover - the failure IS the report
            failed.append(f"{name}: {type(exc).__name__}: {exc}")
    return out, failed


@pytest.mark.parametrize("rel", _TEMPLATES, ids=_TEMPLATES)
def test_every_template_executes(rel):
    """At least one macro must render. That is the property this test can honestly assert.

    ★ The over-reaching version — *every* macro renders — was tried and withdrawn. Placeholders are
    synthesized from each macro's declared parameter NAMES, and a name does not give a TYPE: a
    macro expecting a dict got `"<prior_decisions>"` and raised `'str object' has no attribute
    'get'`. That is my placeholder being wrong, not the template. Faking type knowledge to make the
    assertion pass would have produced a test that fails for reasons that are not defects — the
    thing this session has spent most of its time removing."""
    out, _failed = _render_all_macros(rel)
    if not out.strip():
        # Not every prompt is macro-shaped: the `vision/` templates are plain bodies the
        # framework renders directly. Asserting "at least one macro" against those was the
        # curated-shape assumption one more time.
        out = _env().get_template(rel).render()
    assert out.strip(), f"{rel}: produced no output as either a macro set or a plain body"


# --- the session's clauses survive rendering, in BOTH versions ------------------------------------

_CLAUSES = [
    ("#779 measured depth", "shadow_scale"),
    ("#786 verbatim copy", "VERBATIM text transcribed"),
    ("#787 layout metrics", "LAYOUT IS MEASURED FOR YOU TOO"),
    ("#787 full-bleed case", "FULL-BLEED"),
    ("#788 honest binding spec", "is NOT machine-checked anywhere"),
]

_BACKEND_CLAUSES = [
    ("#809 the dataset exists", "seed_dataset.json"),
    ("#809 it replaces wholesale", "REPLACES your rows WHOLESALE"),
    ("#809 the actionable rule", "INTEGER surrogate primary key"),
]


@pytest.mark.parametrize("label,marker", _CLAUSES, ids=[c[0] for c in _CLAUSES])
@pytest.mark.parametrize("v", ["v3", "v4"])
def test_the_clause_reaches_the_rendered_prompt(v, label, marker):
    """Source presence is not delivery. v3 is default and v4 is opt-in per file (#269), so a
    clause that renders in one and not the other makes runs silently non-comparable."""
    out, _ = _render_all_macros(f"{v}/frontend_agent.j2")
    assert marker in out, label


@pytest.mark.parametrize("label,marker", _BACKEND_CLAUSES, ids=[c[0] for c in _BACKEND_CLAUSES])
@pytest.mark.parametrize("v", ["v3", "v4"])
def test_the_backend_clause_reaches_the_rendered_prompt(v, label, marker):
    """#809: the prompt told the lane *"the framework cannot invent good values for you"* while
    the framework was staging 60 real titles and replacing the lane's table with them. The lane
    therefore authored slug-keyed titles as if it were the source of truth, and 93 dependent rows
    across 5 tables were orphaned — the root cause of #807/#807b/#808. Same class as #788: a
    prompt sentence is a claim about the code, and this one had stopped being true."""
    # `_render_all_macros` returns (output, failed) — `marker in <tuple>` is a membership test
    # against the two elements and is silently False. Seam again: a new caller for a signature I
    # had changed myself two items earlier.
    out, _ = _render_all_macros(f"{v}/backend_agent.j2")
    assert marker in out, label


@pytest.mark.parametrize("v", ["v3", "v4"])
def test_the_old_false_claim_is_gone(v):
    out, _ = _render_all_macros(f"{v}/backend_agent.j2")
    assert "the framework cannot invent good values for you" not in out


@pytest.mark.parametrize("v", ["v3", "v4"])
def test_the_rendered_prompt_is_substantial(v):
    """Guards the exact artifact that made this test look like a finding: a bare `render()` on
    this template yields 31 chars because the body lives in macros. If a future refactor collapses
    the real output, this fails instead of the clause checks passing on an empty string."""
    out, _ = _render_all_macros(f"{v}/frontend_agent.j2")
    assert len(out) > 50_000


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
