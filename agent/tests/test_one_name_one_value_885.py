r"""#885: two modules may not define the same NAME with different values.

Third of the four generalisable fixes named when the user asked why this pipeline has so many
problems. Item 177 already showed that scanning by **value** is the wrong axis — 41 candidates,
1 real finding — and that the single real one was the pair sharing a **name**. So the enforceable
rule is the precise one:

> a value duplicated under two NAMES is usually two concepts; a value duplicated under ONE name is
> a promise that they are the same thing.

**Measured: 440 module/class-level constants, 8 names defined in 2+ places, 4 with different
values.** Three are legitimately different concepts wearing one name and are baselined with the
reason; the fourth was a real subset bug.

| name | verdict |
|---|---|
| `_PYPROJECT` | two templates (backend vs mcp) — different artifacts |
| `_VALID_STATUSES` | runhub run states vs milestone states — different domains |
| `_FONT_EXTS` | a dict (ext → CSS `format()`) vs a list (file filter) — different types |
| **`_WRITE_METHODS`** | ★ **same concept, one a strict subset — DELETE was missing** |

`completeness_audit._WRITE_METHODS` omitted `DELETE`, which changed three decisions: a GET+DELETE
resource read as read-only, and a flow backed only by DELETE was not "write-backed" — so the audit
reported a **false gap** and filed a remediation task for it.

**Zero live exposure**, measured with the module's own loader rather than a reimplementation
(#880's rule, after three of my probes failed at three different extraction steps): 151 runs, 128
with a feature inventory, 1811 flows, 232 mutation flows, **0** backed only by DELETE.
"""
import ast
import pathlib

import pytest


_ROOT = (pathlib.Path(__file__).resolve().parents[1]
         / "env_generator/llm_generator/multi_agent")

# frozen at #885 — each reviewed and genuinely a different concept under a shared name.
# Removing an entry is always allowed; adding one requires the reason beside it.
_ALLOWED_DIVERGENT = {
    "_PYPROJECT":       "backend vs mcp pyproject templates — different artifacts",
    "_VALID_STATUSES":  "runhub run states vs milestone states — different domains",
    "_FONT_EXTS":       "dict(ext -> CSS format()) vs list(file filter) — different types",
}


def _literal(node):
    try:
        return ast.literal_eval(node)
    except Exception:
        if (isinstance(node, ast.Call) and getattr(node.func, "id", None)
                in ("frozenset", "set", "tuple", "list") and node.args):
            try:
                return frozenset(ast.literal_eval(node.args[0]))
            except Exception:
                return None
    return None


def _key(v):
    if isinstance(v, (set, frozenset, list, tuple)) and all(isinstance(x, str) for x in v):
        return frozenset(v)
    return repr(v)


def _defs():
    out, files = {}, 0
    for f in sorted(_ROOT.rglob("*.py")):
        if f.name.startswith("test_"):
            continue
        try:
            tree = ast.parse(f.read_text(errors="ignore"))
        except Exception:
            continue
        files += 1
        scopes = [(tree.body, f.name)] + [
            (c.body, f"{f.name}::{c.name}") for c in ast.walk(tree)
            if isinstance(c, ast.ClassDef)]
        for body, where in scopes:
            for n in body:
                if not (isinstance(n, ast.Assign) and len(n.targets) == 1
                        and isinstance(n.targets[0], ast.Name)):
                    continue
                nm = n.targets[0].id
                if nm.lstrip("_") != nm.lstrip("_").upper() or not nm.lstrip("_"):
                    continue
                v = _literal(n.value)
                if v is None:
                    continue
                out.setdefault(nm, []).append((where, _key(v)))
    return out, files


def test_the_scan_sees_the_tree():
    """★ Non-vacuity with a denominator — a matcher that stopped resolving literals would report
    no divergence and look identical to a clean tree."""
    defs, files = _defs()
    assert files >= 100, files
    assert len(defs) >= 300, f"only {len(defs)} constants resolved — the matcher has drifted"


def test_a_name_defined_twice_has_one_value():
    defs, _ = _defs()
    bad = {k: sorted({w for w, _ in v}) for k, v in defs.items()
           if len({val for _, val in v}) > 1 and k not in _ALLOWED_DIVERGENT}
    assert not bad, (
        "the same NAME carries different values in different modules — one of them is stale:\n"
        + "\n".join(f"  {k}: {w}" for k, w in bad.items())
        + "\nIf they are genuinely different concepts, rename one or add it to "
          "_ALLOWED_DIVERGENT with the reason.")


def test_the_baseline_still_describes_real_divergence():
    """★ A baseline that outlives its entries becomes a licence. Each allowed name must still
    actually diverge, or it should be removed."""
    defs, _ = _defs()
    stale = [k for k in _ALLOWED_DIVERGENT
             if k in defs and len({val for _, val in defs[k]}) <= 1]
    assert not stale, f"no longer divergent — drop from _ALLOWED_DIVERGENT: {stale}"


def test_every_allowed_entry_carries_a_reason():
    assert all(len(v) > 20 for v in _ALLOWED_DIVERGENT.values()), _ALLOWED_DIVERGENT


def test_write_methods_agree_and_include_delete():
    """★ The one real finding. DELETE is a write; the projector's copy always said so."""
    from env_generator.llm_generator.multi_agent.runtime import completeness_audit, route_projector
    assert set(completeness_audit._WRITE_METHODS) == set(route_projector._WRITE_METHODS)
    assert "DELETE" in completeness_audit._WRITE_METHODS


def test_the_three_decisions_it_changes_are_still_there():
    """Non-vacuity for the severity claim: if these sites move, re-read why DELETE mattered."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import completeness_audit as ca
    src = inspect.getsource(ca)
    assert src.count("_WRITE_METHODS") >= 4          # the definition plus three uses
    assert '"GET" in methods and not (methods & _WRITE_METHODS)' in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
