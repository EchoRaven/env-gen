r"""#1203e4: the gate's primary functional evidence did not say which of two writers produced it.

`RunHub` runs are created by two different things, and `compute_deliverability` reads whichever
was the most recent `completed` run with `fail_count == 0`:

    started_by ""              tools/validation_tools.RunValidationTool — the endpoints
                               API_SMOKE ACTUALLY EXERCISED, with a real token and a real body.
                               3317 runs on disk; every probe record carries `endpoint_id`
                               and no `severity`.
    started_by "orchestrator"  RunHub.run_start's generic battery — every registered endpoint
                               asked ANONYMOUSLY with an empty body. 1434 runs; records carry
                               `severity` and `url`. The two sets never overlap.

`endpoint_probes {total: 19, passed: 19}` could therefore mean "api_smoke exercised 19 endpoints
with credentials" or "an anonymous sweep got 19 2xx", and nothing on disk said which. That field
is what `functionally_validated` judges the app on, and what it downgrades the dead-artifact,
visual and ui_flow blockers over.

★ The motivating case is my own mistake. r152 alternated between the two writers every few
minutes — `started_by ""` runs reporting `pass=19 skip=0` and `started_by "orchestrator"` runs
reporting `pass=14 skip=15` — and reading the gate's field without this, I attributed a
`passed: 19` to #1203d6 and had to retract it: that number belongs to the other writer and was
19 before #1203d6 as well. The retraction took a check of r149's pre-#1203d6 runs; the field
should have answered it.

The raw `started_by` is recorded rather than a friendlier name, because the mapping above is
what the corpus shows TODAY and a third writer would be mislabelled by a guess while merely
unfamiliar here.
"""
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.deliverability import (  # noqa: E402
    DeliverabilityReport, _probe_counts, _probe_source_1203e4, probed_something_1203d6)


# ---------------------------------------------------------------- the helper

def test_api_smokes_run_is_named():
    """`agent=""` is what `validation_tools` passes; 3317 runs on disk carry it."""
    assert _probe_source_1203e4({"started_by": ""}) == "(unset)"


def test_the_generic_batterys_run_is_named():
    assert _probe_source_1203e4({"started_by": "orchestrator"}) == "orchestrator"


def test_an_unknown_third_writer_passes_through_unmapped():
    """★ Not guessed at: a writer the corpus has never seen is reported verbatim, not binned
    into one of the two known names."""
    assert _probe_source_1203e4({"started_by": "verifier"}) == "verifier"


def test_a_missing_or_broken_run_does_not_raise():
    """This runs inside the delivery gate; a formatting slip must not be able to block a run."""
    for r in (None, {}, {"started_by": None}, "not a dict", 7):
        assert isinstance(_probe_source_1203e4(r), str)


# ---------------------------------------------------------------- the wiring

def _stanza():
    """Bounded by two landmarks, never a byte window (#943)."""
    import inspect
    from multi_agent.runtime import deliverability as D
    src = inspect.getsource(D)
    i = src.index('ep_counts = _probe_counts(')
    j = src.index('if ep_counts.get("failed", 0) > 0:', i)
    return src[i:j]


def test_the_source_is_stamped_where_the_counts_are_taken():
    """★ The defect in one assertion: the fact must reach the record, not just be derivable."""
    s = _stanza()
    assert "_probe_source_1203e4(last_run)" in s, s
    assert 'ep_counts["source_1203e4"]' in s, s


def test_the_run_id_is_stamped_too():
    """A source without an id cannot be looked up in `runhub_runs.json` afterwards."""
    assert 'ep_counts["run_id_1203e4"]' in _stanza()


def test_nothing_is_stamped_when_there_is_no_run():
    """`last_run` is None when no qualifying run exists; the stamp must not invent one."""
    s = _stanza()
    assert "if last_run:" in s, s


# ---------------------------------------------------------------- it does not disturb the readers

def test_the_count_readers_are_unaffected_by_the_new_keys():
    """★ The invariant: three named count keys drive the gate, and adding strings beside them
    must not change a single verdict."""
    counts = _probe_counts([{"verdict": "pass"}, {"verdict": "pass"}, {"verdict": "skipped"}])
    plain = dict(counts)
    counts["source_1203e4"] = "orchestrator"
    counts["run_id_1203e4"] = "run_abc"
    assert counts.get("failed", 0) == plain.get("failed", 0) == 0
    assert probed_something_1203d6(counts) is probed_something_1203d6(plain) is True


def test_a_zero_probe_run_still_reads_as_unvalidated_with_a_source():
    """r152's `orchestrator` runs reported 14 passes; a hypothetical all-skipped one must still
    fail #1203d6's evidence test even though it now carries a source."""
    counts = _probe_counts([{"verdict": "skipped"} for _ in range(29)])
    counts["source_1203e4"] = "orchestrator"
    assert probed_something_1203d6(counts) is False


def test_the_report_annotation_admits_the_strings():
    """The dataclass used to declare `Dict[str, int]`; a string value there would be a lie about
    the shape that reaches `delivery_gate.jsonl`."""
    ann = DeliverabilityReport.__annotations__["endpoint_probes"]
    assert "int]" not in str(ann), ann


def test_the_report_carries_the_dict_through_to_its_payload():
    """#1202zq caps and serialises this; the keys must survive into what the ledger gets."""
    rep = DeliverabilityReport()
    rep.endpoint_probes = {"total": 19, "passed": 19, "failed": 0, "skipped": 0,
                           "source_1203e4": "(unset)", "run_id_1203e4": "run_x"}
    out = rep.to_dict() if hasattr(rep, "to_dict") else None
    assert out is not None, "DeliverabilityReport lost its payload builder"
    assert out["endpoint_probes"]["source_1203e4"] == "(unset)", out["endpoint_probes"]
