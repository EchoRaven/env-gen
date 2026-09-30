r"""#1202zq: #948 capped each gate field by BYTES, so the answer was the part that got cut.

#948 caps every oversized field because "an artifact nobody can open is the same as no
artifact". The cap was `_enc[:4000]` -- a byte prefix, which keeps whatever the serializer
happened to write first. For `deliverability` that is `last_successful_run`, the largest and
least actionable member.

MEASURED over the 1371 delivery-gate records of r130+: 721 (53%) are truncated, cutting
4007-6854 bytes. A DEPTH-AWARE scan of which top-level keys survived in the retained head:

    last_successful_run 100%   coverage 61%   flow_coverage 50%   blockers 29%   verdict 4%

and 282 of the 721 keep NOTHING but `last_successful_run`. The gate's reasoning about whether
the app can ship was recorded as the probe dump with the answer thrown away.

★ MY FIRST MEASUREMENT SAID `verdict` SURVIVED 100%, and it was wrong: a substring search for
`"verdict"` matches the per-probe verdicts NESTED inside `last_successful_run` (pass/skipped,
721/721 of them). Only a depth-1 scan tells you the gate's own verdict is there 4% of the time.
The same shape as the other locator errors this session -- the container had to be parsed, not
grepped.

★ CHEAPEST-FIRST NEEDS NO FIELD NAMES. `verdict` is ~20 bytes, `blockers` a few hundred,
`last_successful_run` thousands, so a budget filled from the small end keeps the verdicts and
spends the remainder on the dumps -- no allow-list to drift (#1032), and it works the same for
`business_chain` or any field added later. Replayed against the 650 UNTRUNCATED `deliverability`
dicts on disk, at a cap small enough to force the choice:

    cap=800    verdict 0% -> 100%   blockers 0% -> 74%   flow_coverage  8% -> 48%
    cap=1500   verdict 1% -> 100%   blockers 9% -> 88%   flow_coverage 13% -> 86%

Same budget. `_truncated_948` keeps its spelling and meaning, so a reader that only tests for it
is unaffected.
"""
import json
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import multi_agent.orchestrator as O  # noqa: E402

_F = O._capped_value_1202zq


def _real_shape(dump_bytes=3000):
    """The shape r140 actually logs: a huge `last_successful_run` first, the answer last."""
    return {
        "last_successful_run": {"probes": [{"verdict": "pass", "pad": "x" * dump_bytes}]},
        "endpoint_probes": [{"path": "/api/feed", "status": 200}],
        "flow_coverage": {"required": 10, "covered": 10},
        "blockers": ["ui_page `signup` declared but unusable"],
        "verdict": "deliverable",
    }


def _cap(value, cap):
    return _F("deliverability", value, json.dumps(value, default=str), cap, json)


# ── what the reader gets ──────────────────────────────────────────────────────────

def test_the_verdict_survives_the_cap():
    """★ The whole ticket: the answer is the cheapest field, so it is the first one kept."""
    out = _cap(_real_shape(), 400)
    assert out["_kept_1202zq"]["verdict"] == "deliverable", out


def test_the_reason_survives_before_the_dump():
    out = _cap(_real_shape(), 400)
    kept = out["_kept_1202zq"]
    assert "blockers" in kept, sorted(kept)
    assert "last_successful_run" not in kept, "the dump was kept over the reason"


def test_what_was_cut_is_named_with_its_size():
    """#1202z7: a ledger that records only how many bytes it cut cannot be audited."""
    out = _cap(_real_shape(), 400)
    dropped = " ".join(out["_dropped_1202zq"])
    assert "last_successful_run(" in dropped, dropped


def test_the_old_field_is_still_written_with_the_old_meaning():
    """Backward compatible: a reader that only tests `_truncated_948` is unaffected."""
    v = _real_shape()
    enc = json.dumps(v, default=str)
    out = _cap(v, 400)
    assert out["_truncated_948"] == len(enc)


# ── the cases that must NOT change ────────────────────────────────────────────────

def test_a_value_under_the_cap_is_returned_whole():
    """The helper is only ever called past the cap, but the caller's branch must keep the
    untouched path -- that is what makes this additive for every run that never overflows."""
    import ast
    import inspect
    src = inspect.getsource(O._persist_gate_948)
    tree = ast.parse(src.lstrip())
    ifs = [n for n in ast.walk(tree) if isinstance(n, ast.If)
           and "_CAP" in ast.dump(n.test)]
    assert ifs, "the cap comparison is gone"
    assert any(isinstance(b, ast.Assign) and "row" in ast.dump(b) for b in ifs[0].body), \
        "the under-cap branch no longer assigns the value whole"


def test_a_non_dict_keeps_the_byte_prefix():
    """A list or string has no members to choose between, so nothing is gained by changing it."""
    v = ["x" * 100 for _ in range(50)]
    out = _F("business_chain", v, json.dumps(v), 200, json)
    assert out["head"] == json.dumps(v)[:200]
    assert "_kept_1202zq" not in out


def test_a_dict_whose_every_member_overflows_still_says_something():
    """★ Keeping nothing would be worse than the prefix it replaced."""
    v = {"a": "x" * 500, "b": "y" * 500}
    out = _F("deliverability", v, json.dumps(v), 100, json)
    assert out.get("head"), out
    assert out.get("_dropped_1202zq"), out


# ── the cap on the cap ────────────────────────────────────────────────────────────

def test_the_dropped_list_is_bounded_and_says_so():
    v = {("k%02d" % i): ("x" * 300) for i in range(30)}
    out = _F("business_chain", v, json.dumps(v), 400, json)
    d = out["_dropped_1202zq"]
    assert len(d) == O._DROPPED_NAME_CAP_1202ZQ + 1, len(d)
    assert d[-1].startswith("... and "), d[-1]


def test_a_short_dropped_list_carries_no_more_line():
    out = _cap(_real_shape(), 400)
    assert not any(str(x).startswith("... and ") for x in out["_dropped_1202zq"])


def test_the_payload_stays_near_the_budget():
    """The point of #948's cap is an openable artifact; the wrapper must not undo it."""
    v = {("k%02d" % i): ("x" * 300) for i in range(30)}
    out = _F("business_chain", v, json.dumps(v), 400, json)
    assert len(json.dumps(out)) < 400 * 3, len(json.dumps(out))


# ── the caller, not just the helper ───────────────────────────────────────────────

def test_the_gate_writer_uses_it(tmp_path):
    """★ I have tested a helper and not its caller repeatedly. This drives `_persist_gate_948`
    end to end and reads the line back off disk."""
    import logging
    gate = {"ok": False, "failed_checks": ["validation_ui_evidence_failed"],
            "deliverability": _real_shape(dump_bytes=9000)}
    O._persist_gate_948(tmp_path, gate, logging.getLogger("t1202zq"))
    line = (tmp_path / "logs" / "delivery_gate.jsonl").read_text(encoding="utf-8").strip()
    rec = json.loads(line)
    assert rec["failed_checks"] == ["validation_ui_evidence_failed"]
    dv = rec["deliverability"]
    assert dv["_kept_1202zq"]["verdict"] == "deliverable", dv
    assert "last_successful_run(" in " ".join(dv["_dropped_1202zq"])


def test_a_small_gate_row_is_written_unchanged(tmp_path):
    import logging
    gate = {"ok": True, "failed_checks": [], "deliverability": {"verdict": "deliverable"}}
    O._persist_gate_948(tmp_path, gate, logging.getLogger("t1202zq"))
    rec = json.loads((tmp_path / "logs" / "delivery_gate.jsonl").read_text(encoding="utf-8"))
    assert rec["deliverability"] == {"verdict": "deliverable"}


# ── the ordering itself, which the tests above did NOT reach ──────────────────────
#
# ★ Mutating `sized.sort(key=lambda t: t[0])` to `-t[0]`, and deleting the sort outright, left
# every test above green. The fixtures could not tell: with a 3000-byte dump against a cap of
# 400 the dump never fits in ANY order, and the budget test is PER ITEM, so a 25-byte `verdict`
# still lands however late it is tried. Order only decides when the big member FITS and eats
# the budget the answer needed -- so the fixture has to make that true.
#
# Sizes below are chosen for exactly that: `dump` alone consumes 490 of a 500 budget, leaving
# less than `verdict` costs. Cheapest-first spends the budget on verdict+blockers and rejects
# the dump; anything else keeps the dump and evicts the answer.


def _tight():
    return {
        "dump": "x" * 495,          # 497 encoded: fits alone, leaves 3 bytes
        "blockers": ["y" * 180],    # ~187 encoded
        "verdict": "deliverable",   # 13 encoded
    }


_TIGHT_CAP = 500


def test_cheapest_first_is_what_keeps_the_answer():
    """★ The property the whole helper exists for, on a budget where order decides it."""
    out = _F("deliverability", _tight(), json.dumps(_tight()), _TIGHT_CAP, json)
    kept = out["_kept_1202zq"]
    assert kept.get("verdict") == "deliverable", kept
    assert "blockers" in kept, kept
    assert "dump" not in kept, "the dump ate the budget the answer needed"


def test_the_fixture_actually_forces_the_choice():
    """★ Pins the premise, because the first version of this file did NOT force it: with a
    3000-byte dump against a 400 cap the dump never fits in any order, and both the
    reverse-sort and the no-sort mutation stayed green. The sizes below have to satisfy two
    things at once or the test above proves nothing --

      1. `dump` FITS on its own, so evicting it is a choice and not arithmetic;
      2. once `dump` is in, even the 13-byte `verdict` no longer fits, so an expensive-first
         budget really does lose the answer.
    """
    d = json.dumps(_tight()["dump"])
    v = json.dumps(_tight()["verdict"])
    assert len(d) <= _TIGHT_CAP, (len(d), _TIGHT_CAP)
    assert len(d) + len(v) > _TIGHT_CAP, (len(d), len(v), _TIGHT_CAP)


def test_expensive_first_would_lose_the_answer():
    """The counterfactual stated as a test rather than only in prose: on THIS payload, a budget
    filled from the large end keeps the dump and records no verdict at all."""
    v = _tight()
    sized = sorted(((len(json.dumps(x)), k) for k, x in v.items()), reverse=True)
    used = 0
    kept = []
    for n, k in sized:
        if used + n <= _TIGHT_CAP:
            kept.append(k)
            used += n
    assert kept == ["dump"], kept
