"""#1202xq: a preflight verdict that read False in 92 of 92 runs, 18 of which delivered.

`_preflight_check` probed the run's own api/ui/db ports TOGETHER WITH the fixed set
{3000, 5432, 8080, 8083} and set `available = False` if any were taken. No run binds the fixed
four -- each gets its own allocation -- so on any box where something already listens on
3000/5432/8080 the verdict is False forever.

MEASURED over the 92 runs carrying preflight.json:

  * `available` is False in 92 of 92, including the 18 that DELIVERED
  * the blocked set is a subset of {3000, 5432, 8080} in every one -- 81 report exactly
    (3000, 5432, 8080), 10 report (5432,), 1 reports (3000, 5432)
  * a run's OWN port has been blocked ZERO times: the allocator works
  * `netflix-local-r43-portclash-forensics` -- a run named for the port clash it was
    investigating -- reports the identical three. The signal could not distinguish it.

And nothing reads the verdict: only `docker.available` is acted on, at #945's fail-fast.

The verdict now answers the one actionable question that was drowned out -- is a port THIS RUN
will bind already taken -- and the environment probe is kept beside it as context, because
"something else holds 5432" is useful to a human reading the file and is simply not a statement
about whether this run can start.
"""
import ast
import os
from pathlib import Path
import socket
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

_ORCH = os.path.join(_AGENT, "env_generator", "llm_generator", "multi_agent", "orchestrator.py")


def _preflight_src():
    """`ast.unparse` normalises quoting, so callers below match on single quotes."""
    with open(_ORCH, encoding="utf-8") as fh:      # #1202eu
        tree = ast.parse(fh.read())
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == "_preflight_check"), None)
    assert fn is not None, "_preflight_check is gone"
    return ast.unparse(fn)


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("0.0.0.0", 0))
        return s.getsockname()[1]


def _blocked_loop():
    """The `for` statement whose body appends to `ports.blocked`, as an AST node.

    A text window around the append caught the wrong thing on its first draft -- 400 chars
    back reached the `_ctx_ports_1202xq = [3000, ...]` line and the assertion fired on the
    test's own window width. The loop is the structure that matters, so read it as one.
    """
    with open(_ORCH, encoding="utf-8") as fh:      # #1202eu
        tree = ast.parse(fh.read())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "_preflight_check")
    for node in ast.walk(fn):
        if not isinstance(node, ast.For):
            continue
        body = ast.unparse(node)
        if "['blocked'].append" in body or '["blocked"].append' in body:
            return node
    raise AssertionError("no loop fills ports.blocked any more")


def test_the_verdict_is_computed_from_the_runs_own_ports():
    """★ The defect, and the mutation that first slipped past this test.

    Asserting `"_own_ports_1202xq" in <iterable text>` passed a mutation that iterated
    `set(_own_ports_1202xq) | set(_ctx_ports_1202xq)` -- the name is still in there. The
    property is that the iterable mentions NOTHING ELSE, so read every Name in it.
    """
    import builtins
    names = {n.id for n in ast.walk(_blocked_loop().iter) if isinstance(n, ast.Name)}
    names -= set(dir(builtins))          # `sorted(set(...))` is the shape, not a source
    assert names == {"_own_ports_1202xq"}, (
        "`blocked` is filled by iterating over %r; only this run's own ports belong there"
        % sorted(names))


def test_no_well_known_port_reaches_the_verdict_loop():
    """★ The same property from the literal side: the mutation could also inline them."""
    loop = _blocked_loop()
    consts = {n.value for n in ast.walk(loop) if isinstance(n, ast.Constant)}
    for p in (3000, 5432, 8080, 8083):
        assert p not in consts, "the fixed port %d is back in the verdict loop" % p


def test_the_fixed_set_is_still_reported_as_context():
    """Context, not a verdict -- a human reading the file still learns 5432 is held.

    Asserted on the ASSIGNMENT, not on the name appearing somewhere: the first draft searched
    the whole function and passed a mutation that renamed the key, because the old name still
    appeared inside the note's prose.
    """
    src = _preflight_src()
    keys = set()
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            if (isinstance(tgt, ast.Subscript) and isinstance(tgt.slice, ast.Constant)
                    and isinstance(tgt.slice.value, str)):
                keys.add(tgt.slice.value)
    assert "environment_busy_1202xq" in keys, (
        "the environment probe is no longer ASSIGNED; keys present: %r" % sorted(keys))


def test_the_note_says_what_changed_and_why():
    """#983's rule applied to an artifact: a reader must be able to tell the two apart."""
    src = _preflight_src()
    assert "note_1202xq" in src
    assert "92 of 92" in src, "the measurement that justifies the split is gone"


def _taken_probe():
    """The real `_taken_1202xq`, compiled from the orchestrator and callable.

    #1203gb: this test's docstring says "the probe itself, EXERCISED rather than read" and its
    body ended in `assert True` — it bound a socket and then asserted nothing, so it could not
    fail however the probe behaved. The predicate is nested inside `_preflight_check`, which is
    why the siblings read it via AST; it closes over only `socket` and `_probe_faults_1202xq`,
    so it can be compiled and CALLED with those supplied."""
    tree = ast.parse(Path(_ORCH).read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "_taken_1202xq")
    ns = {"socket": socket, "_probe_faults_1202xq": {}}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "<_taken_1202xq>", "exec"), ns)
    return ns["_taken_1202xq"], ns["_probe_faults_1202xq"]


def test_a_free_port_is_not_reported_blocked():
    """The probe itself, exercised rather than read."""
    taken, faults = _taken_probe()
    port = _free_port()
    assert taken(port) is False, "a free port was reported as taken"
    assert faults == {}, faults


def test_a_held_port_is_reported_blocked():
    """The other half: the probe must say True for a port something else is holding, or the
    whole verdict is vacuous in the direction that matters."""
    taken, faults = _taken_probe()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
        held.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        held.bind(("0.0.0.0", 0))
        held.listen(1)
        port = held.getsockname()[1]
        assert taken(port) is True, "a port held by a live listener read as free"
    assert faults == {}, faults


def test_a_held_port_is_detected():
    """★ The capability the verdict now rests on: a held port must read as held."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
        held.bind(("0.0.0.0", 0))
        held.listen(1)
        port = held.getsockname()[1]
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.settimeout(1)
            raised = False
            try:
                probe.bind(("0.0.0.0", port))
            except OSError:
                raised = True
            assert raised, "a port held by a listener was not detected as taken"
        finally:
            probe.close()


def test_only_docker_still_fails_the_run_fast():
    """★ The ports verdict must not start aborting runs: 92 of 92 would have been stopped.

    Read as an AST node, not a window behind the string. #943's ratchet caught the first
    draft's `src[i - 600:i]` and was right to: a backwards window breaks when a comment above
    it grows, exactly as a forward one does.
    """
    with open(_ORCH, encoding="utf-8") as fh:      # #1202eu
        tree = ast.parse(fh.read())
    guard = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        if "PREFLIGHT ABORT" in ast.unparse(node):
            guard = node
            break
    assert guard is not None, "the preflight fail-fast is gone"
    test_src = ast.unparse(guard.test)
    assert "docker" in test_src, test_src
    assert "ports" not in test_src, (
        "the ports verdict now gates the abort; 92 of 92 corpus runs would have been "
        "stopped, 18 of them deliveries: %s" % test_src)


def test_a_failed_probe_is_not_reported_as_taken():
    """★ #1202be's ratchet caught the first draft: `except OSError: return True` reads a
    CRASH as "the port is taken". Only EADDRINUSE/EACCES mean that; anything else is a probe
    fault and is recorded, because a silent "free" would be the same lie the other way."""
    src = _preflight_src()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "_taken_1202xq")
    body = ast.unparse(fn)
    assert "EADDRINUSE" in body and "EACCES" in body, (
        "the handler no longer distinguishes 'someone has it' from 'the probe broke': %s"
        % body)
    handler = next(h for h in ast.walk(fn) if isinstance(h, ast.ExceptHandler))
    returns = {ast.unparse(n.value) for n in ast.walk(handler)
               if isinstance(n, ast.Return) and n.value is not None}
    assert "False" in returns, (
        "the except branch never returns False, so a broken probe still reads as taken: %r"
        % sorted(returns))


def test_a_probe_fault_reaches_the_artifact():
    """A fault nobody can see is the #947 shape."""
    keys = set()
    for node in ast.walk(ast.parse(_preflight_src())):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if (isinstance(tgt, ast.Subscript) and isinstance(tgt.slice, ast.Constant)
                        and isinstance(tgt.slice.value, str)):
                    keys.add(tgt.slice.value)
    assert "probe_failed_1202xq" in keys, sorted(keys)
