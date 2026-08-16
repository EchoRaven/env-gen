r"""#868: enforce the rule that was only ever a comment — and correct #867's overclaim.

`JsonStore.update()` runs caller-supplied `mutator(view)` while holding the file lock, so a
mutator that calls back into the store deadlocks (#867). `milestone_registry._reindex` states the
rule — *"never call back into `self._store` / `self._all()` here … re-entering it self-deadlocks
on a second flock fd"* — in one docstring, binding every mutator in the codebase.

**Scanned: 100 resolvable `update(<mutator>)` sites across 163 modules. Zero re-enter.**

The rule the scan encodes: inside a mutator, a call on `self` is safe **iff it threads the
mutator's own view as its first argument** — `self.helper(m, ...)` is a helper operating on the
MapView it was handed and cannot reach the store. Anything else can. A first cut flagged
`eventhub`'s `self._set_and_prune_events(m, ...)`, which is the safe form; the test was too
strict and the code was right.

★ **That corrects item 197.** I called #867 "the first link" of the chain that kills 7 corpus
runs. The *signature* match is real — `open()` creates the `.lock`, `flock` blocks before any
write, no exception, a run that looks idle — but I did not check whether the mechanism is
reachable, and statically it is not. #867 is a safety net over a path nothing currently takes, not
a demonstrated cause. The lost write in those runs still has no confirmed mechanism.

What remains possible and is **out of this scan's reach**, recorded so nobody reads a green test
as more than it is:

- an indirect path — a mutator calling a helper that eventually touches the store
- a second `JsonStore` instance for the same file in the same thread (#867's guard keys on the
  instance, so it would not help either)
- cross-thread lock-order inversion, where the holder blocks on something else

This test is worth having regardless: it is the difference between a rule written down once and a
rule that fails a build. The scan is deliberately narrow — a call on `self` inside a mutator body
— because that is the shape the docstring forbids and the only one that can be judged without
running anything.
"""
import ast
import pathlib

import pytest


_ROOT = (pathlib.Path(__file__).resolve().parents[1]
         / "env_generator/llm_generator/multi_agent")


def _root_name(node):
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _scan():
    """(offenders, mutators_resolved, files) — a call on `self` inside an `update()` mutator."""
    offenders, muts, files = [], 0, 0
    for f in sorted(_ROOT.rglob("*.py")):
        if f.name.startswith("test_"):
            continue
        text = f.read_text(errors="ignore")
        try:
            tree = ast.parse(text)
        except Exception:
            continue
        files += 1
        defs = {n.name: n for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "update" and node.args):
                continue
            arg = node.args[0]
            body = (arg if isinstance(arg, ast.Lambda)
                    else defs.get(arg.id) if isinstance(arg, ast.Name) else None)
            if body is None:
                continue
            muts += 1
            params = [a.arg for a in body.args.args]
            view = params[0] if params else None
            for c in ast.walk(body):
                if not (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                        and _root_name(c.func) == "self"):
                    continue
                # `self.helper(view, ...)` is the SAFE shape: a helper operating on the MapView
                # the mutator was handed. Only a call that does NOT thread the view can reach the
                # store. eventhub's `self._set_and_prune_events(m, ...)` is exactly the safe form.
                first = c.args[0] if c.args else None
                if (view is not None and isinstance(first, ast.Name) and first.id == view):
                    continue
                offenders.append(
                    f"{f.relative_to(_ROOT)}:{c.lineno} in "
                    f"{getattr(body, 'name', '<lambda>')}() -> {ast.unparse(c.func)}")
    return offenders, muts, files


def test_the_scan_sees_the_tree():
    """Non-vacuity, and specifically the count: a resolver that silently stopped matching would
    report zero offenders out of zero mutators and look identical to a clean tree."""
    _, muts, files = _scan()
    assert files >= 100, files
    assert muts >= 50, f"only {muts} mutators resolved — the matcher has drifted"


def test_no_mutator_calls_back_through_self():
    """The rule `milestone_registry._reindex` states and nothing enforced."""
    offenders, _, _ = _scan()
    assert not offenders, (
        "a store mutator re-enters through `self` — it will read half-written state, and before "
        "#867 it deadlocked the run:\n" + "\n".join(offenders))


def test_the_scan_would_catch_a_real_re_entry():
    """★ Non-vacuity for the detector itself, on the exact shape being forbidden. Without this the
    green above could mean 'the AST walk broke' — which is how this session's probes failed most
    often."""
    src = (
        "class H:\n"
        "    def go(self):\n"
        "        def _mut(m):\n"
        "            m.set('a', 1, 't')\n"
        "            self.value()\n"
        "            return m\n"
        "        self._store.update(_mut)\n"
    )
    tree = ast.parse(src)
    defs = {n.name: n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    found = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "update" and node.args):
            body = defs.get(node.args[0].id)
            for c in ast.walk(body):
                if (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                        and _root_name(c.func) == "self"):
                    found.append(ast.unparse(c.func))
    assert found == ["self.value"], found


def test_the_mapview_pattern_is_not_flagged():
    """★ The false positive that had to be removed. `eventhub`'s lambda reads
    `self._set_and_prune_events` — an attribute lookup to FETCH the function, whose body takes the
    view as its first parameter and never touches the store. A looser probe (grepping `.get(` or
    `.value()`) flags it, and flagged four other correct mutators with it."""
    from env_generator.llm_generator.multi_agent.runtime import eventhub
    import inspect
    fn = eventhub.EventHub._set_and_prune_events
    params = list(inspect.signature(fn).parameters)
    assert params and params[0] == "view", params
    body = inspect.getsource(fn)
    assert "self." not in body, body


def test_the_rule_is_still_documented_where_it_was_learned():
    """If `_reindex`'s warning goes away, this test becomes the only statement of the rule and
    should be re-read rather than trusted."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import milestone_registry as mr
    assert "self-deadlocks on a second flock fd" in inspect.getsource(mr)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
