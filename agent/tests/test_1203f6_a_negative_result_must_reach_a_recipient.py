r"""#1203f6: every "it did NOT happen" key a repair returns must reach a recipient.

The f-series fixed repairs that CLAIMED writes #1202cw had refused, by recording the refusal
under a key of its own instead of omitting the claim. Then three of those keys were read by
nobody -- the fact reached a return value, not a recipient, which is the shape the series
spent the day removing, re-created by the fix for it.

It is not a new mistake either. #1202iy stopped
`repair_frontend_unmatchable_routes_1202sd` claiming a rewrite it had not made and put the
refusal in `result["refused"]`; its consumer logs `repaired` and `routes` and has never read
`refused`. The precedent being followed had the hole.

Why it matters per key, since "a log line nobody reads" is a fair objection:
  * an unmounted shared nav is a chrome-less page, which the visual judge charges on every
    dimension at once (r138: four such pages, all four in visual_screens_below);
  * an unwritten token key means login appears to succeed and every request after it 401s --
    the exact failure #1108 exists for;
  * an unreconciled api path means the page keeps 404ing;
  * an unrewritten `<Route path>` means the page stays unreachable, which is what #1202sd
    was built to prevent.

In each case the repair is the only thing that knows, the lane cannot see it, and the next
tick meets the same condition. The recipient is whoever reads the run log, so that is where
it goes.

This is the RULE, not a list of the four (#1202tb): it enumerates what the repair modules
actually return and requires a reader for each, so the next negative-result key has to be
wired by whoever adds it.
"""
import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
for _p in (str(ROOT), str(ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# A key whose whole content is "this did not happen". `conflicts` is deliberately out: it
# predates the series and already has readers, and its name does not promise a write.
_NEGATIVE_KEYS = ("unwritten", "unmounted", "unrepairable", "refused")

# #1203f7: `skipped` is BOTH, and the shape of its value says which. A formatted or literal
# SENTENCE is a negative result -- `{comp}: no default export` means pages stay chrome-less
# and the reason is known. `True` beside a separate `reason` is an informational "nothing to
# do" (enforce_measured_dark_theme: "measured theme is not dark"), and an int is a counter
# whose dict is published whole (deliverability._probe_counts). Measured over runtime/: 4
# string producers, 4 True ones, 2 counters -- so adding the name alone to _NEGATIVE_KEYS
# would have demanded readers for six states that are not failures.
_CONDITIONAL_KEYS = ("skipped",)

# The whole tree, not one file (#1202tb): the rule has to hold for the module someone adds
# tomorrow. Measured when it was widened: every unwritten/unmounted/unrepairable/refused key
# outside frontend_scaffold.py already had a reader, so widening cost nothing and the sweep
# now covers backend_scaffold, route_projector, heal_pipeline and the rest.
RUNTIME_MODULES = tuple(sorted(p.name for p in (RUNTIME).rglob("*.py")))
SOURCES = RUNTIME_MODULES
CONSUMERS = RUNTIME_MODULES


def _is_sentence(node):
    """A dict value that is a string -- an f-string or a literal. Not True, not an int."""
    return (isinstance(node, ast.JoinedStr)
            or (isinstance(node, ast.Constant) and isinstance(node.value, str)))


def _producers():
    """{function name: {negative keys it writes into its result}}"""
    out = {}
    for name in SOURCES:
        p = RUNTIME / name
        if not p.is_file():
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        spans = [(f.lineno, f.end_lineno, f.name) for f in ast.walk(tree)
                 if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            keys = set()
            for node in ast.walk(fn):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Constant) and sub.value in _NEGATIVE_KEYS:
                        keys.add(sub.value)
            if keys:
                out.setdefault(fn.name, set()).update(keys)
        # the conditional ones are classified by the VALUE, so they need the dict literal
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for k, v in zip(node.keys, node.values):
                if not (isinstance(k, ast.Constant) and k.value in _CONDITIONAL_KEYS):
                    continue
                if not _is_sentence(v):
                    continue
                owner = [f for f in spans if f[0] <= k.lineno <= f[1]]
                if owner:
                    out.setdefault(owner[-1][2], set()).add(k.value)
    return out


def _bindings_of(func_name):
    """[(module, src, tree, var)] for each `var = func_name(...)` in a consumer module.

    Per CALL SITE, not per module: a first version asked only whether the key's NAME appeared
    anywhere in the caller's source, and `heal_pipeline.py` already reads `unwritten` for a
    DIFFERENT repair -- so deleting the token-key announcement left the sweep green. One key
    read once must not vouch for every function that happens to use the same key name.
    """
    out = []
    for name in CONSUMERS:
        p = RUNTIME / name
        if not p.is_file():
            continue
        src = p.read_text(encoding="utf-8")
        if "%s(" % func_name not in src:
            continue
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
                continue
            f = node.value.func
            if (getattr(f, "id", None) or getattr(f, "attr", None)) != func_name:
                continue
            tg = node.targets[0]
            if isinstance(tg, ast.Name):
                out.append((name, src, tree, tg.id))
    return out


def _reads_key(tree, var, key):
    """does any `var.get("key")` / `var["key"]` appear in this module?"""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
           and node.func.attr == "get" and isinstance(node.func.value, ast.Name) \
           and node.func.value.id == var and node.args \
           and isinstance(node.args[0], ast.Constant) and node.args[0].value == key:
            return node
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) \
           and node.value.id == var and isinstance(node.slice, ast.Constant) \
           and node.slice.value == key:
            return node
    return None


class EveryNegativeKeyHasAReader(unittest.TestCase):
    def test_each_producer_key_is_read_at_the_call_site(self):
        unread = []
        for fn, keys in sorted(_producers().items()):
            binds = _bindings_of(fn)
            if not binds:
                continue                      # nobody binds its result; nothing to report to
            for key in sorted(keys):
                if not any(_reads_key(tree, var, key) for _n, _s, tree, var in binds):
                    unread.append("%s -> %r (bound as %s)"
                                  % (fn, key, [v for _n, _s, _t, v in binds]))
        self.assertEqual(unread, [],
                         "these repairs record a negative result nothing reads, so an "
                         "unlanded repair is silent again: %s" % unread)

    def test_the_reader_hands_it_to_a_logger(self):
        """Reading the key and dropping it is the same silence one step later. The logging
        call must sit in the same statement that reads the key, so a logger elsewhere in a
        3000-line module cannot vouch for it."""
        silent = []
        for fn, keys in sorted(_producers().items()):
            for name, _src, tree, var in _bindings_of(fn):
                for key in sorted(keys):
                    if _reads_key(tree, var, key) is None:
                        continue
                    ok = False
                    for node in ast.walk(tree):
                        if not isinstance(node, (ast.For, ast.If, ast.Expr)):
                            continue
                        if _reads_key(node, var, key) is None:
                            continue
                        d = ast.dump(node)
                        if "warning" in d or "error" in d or "info" in d:
                            ok = True
                            break
                    if not ok:
                        silent.append("%s reads %s[%r] from %s and never says it"
                                      % (name, var, key, fn))
        self.assertEqual(silent, [], "; ".join(silent))

    def test_the_rule_found_the_four_it_was_written_for(self):
        """A sweep that matches nothing proves nothing (#1202tb): the producers it
        enumerates must actually include the ones this ticket wired."""
        prod = _producers()
        for fn, key in (("mount_shared_nav_on_projected_pages", "unmounted"),
                        ("repair_token_key_mismatch_1108", "unwritten"),
                        ("reconcile_frontend_api_paths", "unwritten"),
                        ("repair_frontend_unmatchable_routes_1202sd", "refused"),
                        ("repair_frontend_missing_local_exports", "unwritten"),
                        ("repair_frontend_named_default_imports", "unrepairable"),
                        # #1203f7's three, classified by the VALUE being a sentence
                        ("mount_shared_nav_on_projected_pages", "skipped"),
                        ("recover_agent_nav", "skipped"),
                        ("scaffold_pages_from_contract", "skipped")):
            self.assertIn(fn, prod, "the scan stopped seeing %s" % fn)
            self.assertIn(key, prod[fn], "the scan stopped seeing %s's %r" % (fn, key))


class TheDiscriminatorExcludesInformationalStates(unittest.TestCase):
    """#1203f7: `skipped` alone is not a negative result. Pinning the exclusions matters as
    much as the inclusions -- demanding a reader for "measured theme is not dark" would be
    noise presented as rigor, and the sweep would have to be weakened to shut it up."""

    def test_a_true_valued_skip_is_not_required_to_be_read(self):
        prod = _producers()
        self.assertNotIn("skipped", prod.get("enforce_measured_dark_theme", set()),
                         "a `skipped: True` beside a separate `reason` is an informational "
                         "state, not an unlanded repair")

    def test_a_counter_named_skipped_is_not_required_to_be_read(self):
        prod = _producers()
        self.assertNotIn("skipped", prod.get("_probe_counts", set()),
                         "an int counter whose dict is published whole is not a negative "
                         "result key")


if __name__ == "__main__":
    unittest.main()
