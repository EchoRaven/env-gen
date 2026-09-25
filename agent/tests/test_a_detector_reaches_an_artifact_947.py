r"""#947: a ratchet on detectors whose finding reaches no artifact.

Seven repairs this session were the same defect — #932, #933, #935, #939, #941, #944, #946 — a
detector that found something real and wrote it only to a logger no run persists. #946 is the one
that made it a rule: it silently voided an APPROVED PLAN ("take #914's free exposure measurement
over the next runs"), because the exposure was a log line and `LANE PAGE WITH OWN COMPONENTS`
appears in zero of r154's artifacts.

    A measurement that exists only in a log line is not a measurement.

Scanned: functions whose `_LOG.warning/error` names a ticket, that hand their finding to no disk
write, no persisted dict, and no out-parameter. **8 functions, 15 tickets.**

★ Two of them survive PARTIALLY and the number must not be read as "15 findings are lost":
  * `validate_delivery_gate` (#287 #566 #671 #739 #743 #755 #774) — the check NAMES do reach
    `progress_events.jsonl` (r154's has them); the seven tickets' EXPLANATIONS do not.
  * `maybe_run` (#711 #712) — the aggregate NUMBER reaches `verdict.json` as
    `record_exceeds_live_by`, written by a different function; the text does not.

So the honest claim is narrower than the count: eight detectors whose REASONING is unavailable to
anyone holding only the run's artifacts.

★★ The scanner took three corrections before it could be trusted, which is the session's other
lesson repeated: `dumps` in the persist-set marked every JSON-encoding function safe (it hid
#769's `capture_route_screenshots`, the canonical case), and out-parameters — this module's own
idiom, four times over, and #935's own fix — read as no persistence at all. A guard nobody has
watched fail is a guess.
"""
import ast
import pathlib

import pytest


# 8 -> 10 for #1202an's two json_store frames. They are in _FIXED_UPSTREAM below with their
# reason: the finding reaches a real artifact — the corrupt store's own bytes, copied beside it
# — but via `shutil.copy2`, which this intra-procedural scan does not count as persistence, and
# json_store is the layer the hubs are built ON so "write it to a hub" is not available to it.
# 10 -> 11 for #1202cn's `_compose` frame. Its audience is the OPERATOR, not a lane: it
# names a failure the host owns ("docker has run out of network address pools ... stop the
# finished runs' stacks"), and there is no artifact a lane would read because no lane can
# act on it. r37 is why it exists — 168 minutes and $371.74 with every `docker up` failing
# the same way forty times, the orchestrator escalating stalls and nudging lanes the whole
# time. Filing that as a task would send a lane after the host; the log line, read by
# whoever clears it, IS the right destination.
# Raised deliberately and once; a ceiling moved without a reason stops being a ratchet.
_CEILING = 11

#: Detectors the scan flags but whose finding DOES reach an artifact via the caller. The scan is
#: intra-procedural — it cannot follow a returned structure — so a fix applied one frame up is
#: invisible to it. #948 is exactly that: `validate_delivery_gate` still only logs, and the
#: orchestrator wrapper now appends its whole 21-field return to `logs/delivery_gate.jsonl`.
#: Recorded here rather than papered over, because a ceiling that silently counts a FIXED entry
#: stops meaning anything.
_FIXED_UPSTREAM = {
    "validate_delivery_gate": "#948 — persisted by _validate_delivery_gate wrapper",
    # #1202an: these two DO reach an artifact — the corrupt store's own bytes, copied to
    # `<name>.corrupt.<pid>.<ts>` beside it before anything can overwrite them. The copy is
    # `shutil.copy2`, which is not in _PERSIST_CALLS, so the intra-procedural scan cannot see
    # it. json_store is also the layer the hubs are built ON, so "write it to a hub" is not
    # available to it: the artifact has to be a plain file, and it is.
    "_load_raw": "#1202an — quarantines the unparsable bytes to <name>.corrupt.<pid>.<ts>",
    "update": "#1202an — the same quarantine; this frame announces that the loss is permanent",
}

_ROOT = pathlib.Path(__file__).resolve().parents[1] / "env_generator"

#: serialising is NOT persisting — `dumps` here hid the canonical case behind `json.dumps(token)`.
_PERSIST_CALLS = {"write_text", "writelines", "dump"}
# #1202cw routed every projector write through a choke point, so the `.write_text` these
# functions used to call is now one frame away. It is the SAME file write — a plain call,
# not an attribute, hence the separate set below.
# #1202mg is the same shape: `clear_stale_git_locks_1202mg` routes its row through one
# recorder so the clear and the refusal cannot write two different shapes. The recorder
# calls `.write_text` — the entry below is backed by a behavioural test that plants a
# stale lock, runs the real wrapper and reads the jsonl back
# (test_1202mg_both_git_wrappers_clear_a_stale_lock.py), not by this list asserting it.
# #1202ub: a hub WRITER is a persist call too. `register_ui_page` lands the finding in
# registryhub_ui_pages.json -- verified by calling it against a temp hub and reading the file
# back -- so a detector that hands its finding to the hub is not log-only. The scan is
# intra-procedural and cannot follow into the method, which is why the name is listed here
# rather than the claim being waived.
_PERSIST_FUNCS_1202CW = {"framework_write_1202cw", "_fw_write_1202cw", "register_ui_page",
                         "_record_lock_event_1202mg"}
_PERSIST_TARGETS = {"_verdict", "row", "rec", "results", "payload", "report", "out",
                    "findings", "data"}
_LOGGERS = {"_LOG", "logger", "_LOGGER", "_log939"}


def _persists(fn):
    params = {a.arg for a in list(getattr(fn.args, "posonlyargs", []))
              + list(fn.args.args) + list(fn.args.kwonlyargs)}

    def durable(name):
        return name in _PERSIST_TARGETS or name in params

    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            attr = getattr(n.func, "attr", None)
            if attr in _PERSIST_CALLS:
                return True
            if getattr(n.func, "id", None) in _PERSIST_FUNCS_1202CW:
                return True
            # #1202ub: the same name reached as a METHOD is the same write. `_fw_write_1202cw`
            # is called bare, but a hub writer is `registryhub.register_ui_page(...)`, and
            # matching only `n.func.id` called that log-only while it was landing the finding
            # in registryhub_ui_pages.json.
            if attr in _PERSIST_FUNCS_1202CW:
                return True
            owner = getattr(getattr(n.func, "value", None), "id", None)
            if attr in ("setdefault", "append", "update") and owner and durable(owner):
                return True
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)
                        and durable(t.value.id)):
                    return True
    return False


def _log_only_detectors():
    import re
    out = []
    for p in sorted(_ROOT.rglob("*.py")):
        if "test" in p.name:
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        for fn in [n for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            tickets = set()
            for n in ast.walk(fn):
                if (isinstance(n, ast.Call) and getattr(n.func, "attr", None) in ("warning", "error")
                        and getattr(getattr(n.func, "value", None), "id", "") in _LOGGERS
                        and n.args and isinstance(n.args[0], ast.Constant)
                        and isinstance(n.args[0].value, str)):
                    tickets |= set(re.findall(r"#(\d{3})", n.args[0].value))
            if tickets and not _persists(fn):
                out.append(f"{p.relative_to(_ROOT)}:{fn.name}()  "
                           + " ".join("#" + t for t in sorted(tickets)))
    return out


def test_the_scanner_recognises_a_real_persister():
    """★ Validation before trust, half one: the two functions that DO persist must not be flagged."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf
    tree = ast.parse(inspect.getsource(vf))
    for name in ("_persist_verdict", "_append_round_record_640"):
        fn = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name][0]
        assert _persists(fn), name


def test_the_scanner_recognises_an_out_parameter():
    """★ Half two: #935's fix hands the reason out through `capture_errors`, which IS persistence.
    Before this the scanner flagged a detector repaired hours earlier."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf
    tree = ast.parse(inspect.getsource(vf))
    fn = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
          and n.name == "capture_route_screenshots"][0]
    assert _persists(fn), "an out-parameter is how this module has always handed findings out"


def test_the_scanner_still_finds_the_known_ones():
    """Non-vacuity."""
    found = " ".join(_log_only_detectors())
    assert "maybe_run" in found and "validate_delivery_gate" in found


def test_log_only_detectors_do_not_grow():
    """★ THE ratchet. A new detector must write an artifact, not just a log line."""
    found = _log_only_detectors()
    assert len(found) <= _CEILING, (
        f"{len(found)} detectors report only to a logger no run persists (ceiling {_CEILING}). "
        f"A measurement that exists only in a log line is not a measurement:\n  "
        + "\n  ".join(found))


def test_the_ceiling_is_not_stale():
    n = len(_log_only_detectors())
    assert n >= _CEILING - 2, f"only {n} remain; lower _CEILING to {n}"


def test_the_upstream_fixes_are_still_upstream():
    """★ The scan is intra-procedural, so #948's fix (one frame up) does not reduce the count.
    Assert the fix is really there rather than letting the exemption rot into a lie."""
    import ast
    import inspect
    from env_generator.llm_generator.multi_agent import orchestrator as orc
    tree = ast.parse(inspect.getsource(orc))
    fn = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
          and n.name == "_validate_delivery_gate"][0]
    assert any(isinstance(n, ast.Call) and getattr(n.func, "id", None) == "_persist_gate_948"
               for n in ast.walk(fn)), _FIXED_UPSTREAM["validate_delivery_gate"]


def test_the_real_remaining_count_is_reported():
    """What the ceiling counts vs what is actually unrecorded — stated, not conflated."""
    found = _log_only_detectors()
    truly = [f for f in found if not any(k in f for k in _FIXED_UPSTREAM)]
    assert len(truly) == len(found) - len(_FIXED_UPSTREAM), (found, truly)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
