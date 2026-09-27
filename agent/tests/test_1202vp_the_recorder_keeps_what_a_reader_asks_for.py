"""#1202vp — every key a reader takes OUT of `last_result` must survive going IN.

`record_chain_result` did not merge into `last_result`; it REBUILT it from two keys::

    "last_result": {"broken": ..., "steps": ...}

so any other field its caller handed it was dropped on the floor without a word. Three
readers in `delivery_gate` ask `last_result` for a key that is not one of those two, and
`validation_tools._record_chain_results` is the only writer that can supply them — the
wire was cut at the one point where both ends are framework code.

Measured before the fix: 150 runs, 4353 chain records carrying a `last_result`, and those
keys are non-empty in exactly ZERO of them. On r137 `run_chains` read the build currency as
`changed` 4 times (r136: 47) — each time it computed the verdict, logged it, handed it to
the recorder, and the recorder discarded it, so the `business_chain_failing` detail the lane
acts on never said the container may predate the fix. That is precisely what #1202vn was
written to say, and it could not have worked.

The last test is the one that lasts: it names no keys. It reads them out of the readers by
AST and pushes them through the REAL recorder, so a fourth reader added tomorrow fails here
on the day it is added instead of quietly reading None forever.
"""
import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import registryhub as _rh_mod          # noqa: E402
from multi_agent.runtime.hub_registry import HubRegistry        # noqa: E402


def _hub(tmp_path):
    rh = HubRegistry(tmp_path).registryhub
    # Both endpoints: the framework prepends an auth step to an authored chain, and an
    # unregistered endpoint makes `register_verification_chain` reject the whole chain.
    for _m, _p in (("POST", "/auth/register"), ("GET", "/api/items")):
        rh.register_endpoint(_m, _p, agent="backend", status="implemented")
    rh.register_verification_chain(
        "flow", steps=[{"method": "GET", "path": "/api/items", "expect": [200]}],
        agent="verifier")
    return rh


def test_a_carried_field_survives_the_recorder(tmp_path):
    rh = _hub(tmp_path)
    currency = {"verdict": "changed", "detail": "image built 41 min before HEAD"}
    rh.record_chain_result("flow", {
        "broken": ["GET /api/items -> 500"],
        "steps": [{"kind": "broken", "ok": False}],
        "build_currency_1202ex": currency,
    }, agent="")
    last = rh.get_verification_chains()["flow"]["last_result"]
    assert last.get("build_currency_1202ex") == currency, (
        "the recorder rebuilt last_result and dropped what it was handed")
    assert last.get("broken") and last.get("steps"), "the original two keys still land"


def test_an_absent_field_is_not_invented(tmp_path):
    """Carrying must not manufacture empty keys — an absent verdict stays absent, so a
    reader can still tell 'never computed' from 'computed and clean' (#883)."""
    rh = _hub(tmp_path)
    rh.record_chain_result("flow", {"broken": [], "steps": []}, agent="")
    last = rh.get_verification_chains()["flow"]["last_result"]
    assert "build_currency_1202ex" not in last
    assert sorted(last) == ["broken", "steps"]


def test_a_caller_cannot_stuff_arbitrary_payload_into_the_record(tmp_path):
    """The recorder carries what a reader asks for, not whatever it is handed — this store
    is written on every chain run and whole-file rewritten each time (#1202sg)."""
    rh = _hub(tmp_path)
    rh.record_chain_result("flow", {
        "broken": ["GET /api/items -> 500"], "steps": [],
        "a_field_no_reader_asks_for": "x" * 10000,
    }, agent="")
    last = rh.get_verification_chains()["flow"]["last_result"]
    assert "a_field_no_reader_asks_for" not in last


def _is_last_result_expr(node) -> bool:
    """True for `X.get("last_result")`, optionally wrapped in `... or {}`.

    Deliberately NOT "mentions last_result anywhere inside": that looser rule also
    collected `cur.get("verdict")` where `cur` is the build-currency dict NESTED in
    last_result, and would have demanded the recorder store `verdict`, `detail`, `kind`
    and `name` as top-level fields. Checked against the five keys found by hand before
    being trusted (#1202rr's rule: validate the detector on a known answer first).
    """
    if isinstance(node, ast.BoolOp):
        return bool(node.values) and _is_last_result_expr(node.values[0])
    return (isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "last_result")


def _keys_read_from_last_result(path: pathlib.Path):
    """Every literal key some reader asks a `last_result` mapping for, directly.

    AST only — no source slicing (#943). Covers `(rec.get("last_result") or {}).get("k")`
    and the two-line form where `last = rec.get("last_result") or {}` is asked right after.
    """
    tree = ast.parse(path.read_text())
    aliases = {tgt.id
               for node in ast.walk(tree) if isinstance(node, ast.Assign)
               and _is_last_result_expr(node.value)
               for tgt in node.targets if isinstance(tgt, ast.Name)}
    found = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and len(node.args) == 1
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            continue
        recv = node.func.value
        if _is_last_result_expr(recv) or (isinstance(recv, ast.Name) and recv.id in aliases):
            found.add(node.args[0].value)
    return found


_READERS = ("delivery_gate.py", "remediation_dispatcher.py", "framework_validation.py")


def test_every_key_a_reader_asks_for_can_be_written(tmp_path):
    runtime = pathlib.Path(_rh_mod.__file__).parent
    wanted = set()
    for name in _READERS:
        p = runtime / name
        assert p.exists(), f"{name} moved — this guard is scanning nothing"
        wanted |= _keys_read_from_last_result(p)
    assert "broken" in wanted and "steps" in wanted, (
        "the AST scan lost the two keys every reader uses — the detector is broken, "
        f"not the code (found: {sorted(wanted)})")

    rh = _hub(tmp_path)
    # One truthy value per key a reader asks for, then see which come back. Nothing here
    # is hardcoded: the keys come from the readers themselves.
    sent = {k: [f"probe {k}"] for k in sorted(wanted)}
    sent["broken"] = ["GET /api/items -> 500"]    # keep the record `failing`
    rh.record_chain_result("flow", dict(sent), agent="")
    got = rh.get_verification_chains()["flow"]["last_result"]

    dropped = sorted(k for k in wanted if k not in got)
    assert not dropped, (
        "these keys are read out of `last_result` but the recorder refuses to store them, "
        "so the reader can only ever see None: " + ", ".join(dropped))


def test_the_writer_supplies_every_field_the_recorder_carries():
    """The other end of the same wire.

    Carrying a field the sole caller never passes changes nothing — `framework_defects`
    was exactly that: read by the gate, carried by nobody, supplied by nobody. This reads
    the keys out of the `result={...}` literal at the real call site, so dropping one there
    fails here rather than going quiet for another 150 runs.
    """
    import env_generator.llm_generator.tools.validation_tools as _vt
    tree = ast.parse(pathlib.Path(_vt.__file__).read_text())
    supplied = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "record_chain_result"):
            continue
        for kw in node.keywords:
            if kw.arg == "result" and isinstance(kw.value, ast.Dict):
                supplied |= {k.value for k in kw.value.keys
                             if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    assert "broken" in supplied and "steps" in supplied, (
        f"no `result={{...}}` literal found at the call site (found: {sorted(supplied)})")

    missing = sorted(set(_rh_mod.LAST_RESULT_CARRIED_1202vp) - supplied)
    assert not missing, (
        "the recorder carries these into the durable record but the only caller never "
        "passes them, so they stay empty forever: " + ", ".join(missing))
