r"""#883: "empty" is safe in one direction and a silent pass in the other.

#879 and #881 each found a decision-driving swallow **inside a file its own class sweep had
already swept**. That is not carelessness twice — it is what a sweep is, so the correction has to
be mechanical. This is the scanner.

**Measured: 189 exception handlers assign an empty default; 167 do it silently; 17 of those are in
a gate or audit file.** Blanket-fixing all 17 would be wrong, because most are fine. The
discriminator is **which direction empty points**:

| site | what empty means | |
|---|---|---|
| `delivery_gate.py:143` `rows = []` | the contract expects **no tables** → every expectation vacuous | ★ dangerous |
| `completeness_audit.py:679` `endpoints = {}` | nothing registered → **nothing can be missing** → the audit passes by having failed | ★ dangerous |
| `flow_coverage.py:336` `results = []` | no flow is marked covered → **fail-closed** | safe |

★ **"Empty ⇒ clean/passing" is a silent pass. "Empty ⇒ nothing covered" is conservative.** Same
construct, opposite consequence, and only reading the consumer tells them apart — which is why
this is a *baseline* scanner rather than a rule that fails on every `except: x = []`.

Both dangerous sites now announce through the existing helpers (`_swallowed_790`,
`_gate_absent_792`). The baseline freezes the remaining count so the class cannot grow unnoticed;
lowering it is always allowed, raising it is not.
"""
import ast
import pathlib

import pytest


_ROOT = (pathlib.Path(__file__).resolve().parents[1]
         / "env_generator/llm_generator/multi_agent")

_GATES = ("delivery_gate.py", "deliverability.py", "frontend_audit.py", "backend_audit.py",
          "completeness_audit.py", "seed_audit.py", "flow_coverage.py",
          "framework_validation.py")

# frozen after #883 reviewed all 17. Lower these freely; never raise one.
_BASELINE = {
    "completeness_audit.py": 1,     # tables — mirrors endpoints, reviewed: same read, guarded now
    "deliverability.py": 2,         # _real / _data — absent file is the normal case, not a failure
    "delivery_gate.py": 2,          # endpoints / tables — #772's re-implementation, non-vacuity checked
    "flow_coverage.py": 5,          # every one fail-closed: empty => nothing covered
    "framework_validation.py": 4,   # signature reads; empty => "changed", the conservative side
    "frontend_audit.py": 1,         # text — unreadable file, already reported by its caller
}


def _is_empty(n):
    if isinstance(n, ast.Constant) and n.value in (None, False, 0, ""):
        return True
    return isinstance(n, (ast.List, ast.Dict, ast.Set, ast.Tuple)) and not (
        getattr(n, "elts", None) or getattr(n, "keys", None))


def _announces(h):
    src = " ".join(ast.unparse(x) for x in h.body)
    return any(k in src for k in ("_gate_absent_792", "_swallowed_790", "logger", "_LOG",
                                  "warn", "error", "raise", "_say", "print"))


def _counts():
    out, total = {}, 0
    for f in sorted(_ROOT.rglob("*.py")):
        if f.name.startswith("test_"):
            continue
        try:
            tree = ast.parse(f.read_text(errors="ignore"))
        except Exception:
            continue
        n = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            for h in node.handlers:
                if not any(isinstance(x, ast.Assign) and _is_empty(x.value) for x in h.body):
                    continue
                total += 1
                if f.name in _GATES and not _announces(h):
                    n += 1
        if n:
            out[f.name] = n
    return out, total


def test_the_scan_sees_the_tree():
    """★ Non-vacuity with a denominator: a matcher that silently stopped working would report an
    empty dict and be indistinguishable from a clean tree."""
    _, total = _counts()
    assert total >= 100, f"only {total} empty-default handlers matched — the AST walk has drifted"


def test_no_gate_file_gains_a_silent_empty_default():
    counts, _ = _counts()
    grew = {f: (n, _BASELINE.get(f, 0)) for f, n in counts.items() if n > _BASELINE.get(f, 0)}
    assert not grew, (
        "a gate/audit handler now swallows into an empty default without saying so: " + repr(grew)
        + " — if empty means 'clean' there, announce it via _swallowed_790 / _gate_absent_792; "
        "if empty means 'nothing covered', it is fail-closed and the baseline may be raised WITH "
        "that reasoning written down.")


def test_a_new_gate_file_starts_at_zero():
    counts, _ = _counts()
    new = sorted(f for f in counts if f not in _BASELINE)
    assert not new, f"new gate/audit files with a silent empty default: {new}"


def test_the_two_dangerous_sites_now_announce():
    """★ The ones #883 actually fixed, asserted by consequence rather than by line number."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import completeness_audit, delivery_gate
    dg = inspect.getsource(delivery_gate)
    assert "contract_tables_from_milestones" in dg
    assert "the contract expects no tables" in dg
    ca = inspect.getsource(completeness_audit)
    assert "completeness_endpoints" in ca
    assert "nothing can be missing" in ca


def test_the_safe_direction_is_left_alone():
    """★ The discriminator, pinned. `flow_coverage`'s empty results mean NO flow is covered — the
    conservative side. Wrapping it would add noise on the one shape that cannot cause a silent
    pass, and a scanner that cannot tell the directions apart is a scanner nobody will keep."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import flow_coverage
    src = inspect.getsource(flow_coverage)
    assert "results = hub_registry.get_validation_results" in src
    assert _BASELINE["flow_coverage.py"] >= 1


def test_the_helpers_it_routes_to_still_exist():
    """Non-vacuity for the fix: both announcements go somewhere real."""
    from env_generator.llm_generator.multi_agent.runtime.delivery_gate import _swallowed_790
    from env_generator.llm_generator.multi_agent.runtime.deliverability import _gate_absent_792
    assert callable(_swallowed_790) and callable(_gate_absent_792)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
