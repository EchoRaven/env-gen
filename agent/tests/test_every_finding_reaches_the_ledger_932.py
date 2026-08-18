r"""#932: #900's remedy carried one finding of eight into the append-only record.

#900 saw the shape exactly and wrote it down:

    "#893 wrote `judge_unstable_893` only into verdict.json, which `_persist_verdict` OVERWRITES
     every round — so a detection could be erased by the very next round. That is #500's
     evidence-erasure shape, committed by the detector built to expose the judge's inconsistency."

Then it carried `judge_unstable_893` and stopped. Seven other findings live on the same overwritten
file: `identical_captures_713`, `screens_below_record_928`, `record_exceeds_live_by` (+note),
`better_state_available` (+note), `scope_excluded_screens`.

★ r154 proved the erasure while this was being written. Round 2 recorded

    identical_captures_713: [{"md5": "41a9d24b...", "screens": ["login", "movies"]}]

— `movies` had photographed the login page and scored 0.05 for it. Round 3 saw `movies` recover to
0.62, the key was not re-added, and the only surviving verdict has no trace of it. The run's
history now says it never happened. I know it happened because I dumped the file an hour earlier.

The guard matters more than the list: a finding added later is exactly the thing that quietly
would not be carried, so `test_every_verdict_finding_is_carried_932` walks `_persist_verdict`'s
AST for every key the verdict can grow and demands it be declared one way or the other.
"""
import ast
import inspect
import json
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


# --------------------------------------------------------------------------- the completeness guard

#: keys the verdict grows that are NOT findings. A future non-finding key goes here with a reason,
#: which is the point — the decision gets made rather than defaulted.
#:
#: ★ This guard caught its first real case within hours of being written: #941 added `milestone`
#: to the verdict and the suite went red. That key is an IDENTITY LABEL, not a detection, and it
#: reaches the ledger by its own line in the row builder rather than through the findings loop —
#: carrying it twice would be the duplication #926 is about.
_NOT_A_FINDING = frozenset({"milestone"})


def _verdict_conditional_keys():
    """Every literal key `_persist_verdict` can ADD after building the base dict.

    AST, not a regex: the keys appear as `_verdict["x"] = ...` and `_verdict.setdefault("x", ...)`,
    and a regex over the source would also match them inside the docstrings and comments that
    discuss them by name — which is how three source-scanning instruments went wrong this session.
    """
    keys = set()
    fn = [n for n in ast.walk(ast.parse(inspect.getsource(vf)))
          if isinstance(n, ast.FunctionDef) and n.name == "_persist_verdict"][0]
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)
                        and t.value.id == "_verdict" and isinstance(t.slice, ast.Constant)):
                    keys.add(t.slice.value)
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "setdefault" and isinstance(n.func.value, ast.Name)
                and n.func.value.id == "_verdict" and n.args
                and isinstance(n.args[0], ast.Constant)):
            keys.add(n.args[0].value)
    return keys


def test_the_locator_finds_the_keys_it_is_supposed_to():
    """★ Prove the instrument before trusting it — a scan that finds nothing would pass the next
    test vacuously."""
    keys = _verdict_conditional_keys()
    assert "judge_unstable_893" in keys and "identical_captures_713" in keys
    assert len(keys) >= 8, sorted(keys)


def test_every_verdict_finding_is_carried_932():
    """★ THE guard. A finding added to the verdict later must be carried or explicitly excused."""
    undeclared = _verdict_conditional_keys() - set(vf._ROUND_FINDINGS_932) - _NOT_A_FINDING
    assert not undeclared, (
        f"these verdict keys reach no append-only record and will be erased by the next round: "
        f"{sorted(undeclared)} — add them to _ROUND_FINDINGS_932 or to _NOT_A_FINDING")


def test_the_carried_set_has_no_dead_entries():
    """The other direction: a name that no longer exists is a comment pretending to be a guard."""
    stale = set(vf._ROUND_FINDINGS_932) - _verdict_conditional_keys()
    assert not stale, sorted(stale)


# --------------------------------------------------------------------------- behaviour

def _write(tmp_path, verdict, results):
    vdir = tmp_path / "design" / "visual_gate"
    vdir.mkdir(parents=True, exist_ok=True)
    vf._append_round_record_640(vdir, verdict, results)
    return [json.loads(l) for l in (vdir / "rounds.jsonl").read_text().splitlines() if l.strip()]


def test_a_duplicate_capture_finding_reaches_the_ledger(tmp_path):
    """★ r154's erased finding."""
    dup = [{"md5": "41a9d24b", "screens": ["login", "movies"]}]
    rows = _write(tmp_path, {"code_state": "abc", "identical_captures_713": dup}, [])
    assert rows[-1]["identical_captures_713"] == dup


def test_a_later_clean_round_does_not_erase_the_earlier_one(tmp_path):
    """The whole point: round 3 recovering must not delete round 2's evidence."""
    dup = [{"md5": "41a9d24b", "screens": ["login", "movies"]}]
    _write(tmp_path, {"code_state": "a", "identical_captures_713": dup}, [])
    rows = _write(tmp_path, {"code_state": "b"}, [])
    assert len(rows) == 2
    assert rows[0]["identical_captures_713"] == dup
    assert "identical_captures_713" not in rows[1]


def test_the_divergence_and_collapsed_list_are_carried(tmp_path):
    rows = _write(tmp_path, {"code_state": "a", "record_exceeds_live_by": 0.2,
                             "screens_below_record_928": ["movies", "title_detail"]}, [])
    assert rows[-1]["record_exceeds_live_by"] == 0.2
    assert rows[-1]["screens_below_record_928"] == ["movies", "title_detail"]


def test_absent_findings_add_no_keys(tmp_path):
    """A row for a clean round must stay clean — an always-present empty key is noise (#845)."""
    rows = _write(tmp_path, {"code_state": "a"}, [])
    assert not (set(vf._ROUND_FINDINGS_932) & set(rows[-1]))


def test_the_existing_columns_are_unchanged(tmp_path):
    rows = _write(tmp_path, {"code_state": "a", "blocking_average": 0.55,
                             "blocking_average_live": 0.35, "passed": False,
                             "min_similarity": 0.65},
                  [{"name": "login", "similarity": 0.5}])
    r = rows[-1]
    assert r["blocking_average"] == 0.55 and r["blocking_average_live"] == 0.35
    assert r["live"] == {"login": 0.5} and r["passed"] is False and r["at"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
