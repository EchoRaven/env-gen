r"""#1202z7: the per-phase budget map keeps the 24 costliest labels and must say what it cut.

#1202cr added the split so a finished run can be asked WHERE its budget went. The cap keeps
the 24 costliest LABELS — and cost is spread very unevenly across labels: the five lane roles
have four stages each, while the test-user squad is ELEVEN agents with stages of their own,
so each of its buckets is individually small and every one falls off the end.

MEASURED on r140: the map accounted for 5691 of 6807 calls and $366.22 of $402.92 — 1116
calls and $36.70, 9% of the run, present in NO bucket. `unattributed` held 97 of them, and
it means something different anyway (a call carrying no label at all). Attributing the log's
`[LLM Request]` lines to the agent that issued them puts 937 on the test users — 13.7% of
the run — and the phase map has not one test-user key.

★ THE CAP IS NOT THE DEFECT; THE SILENCE IS. The map's own numbers look complete, so a
reader summing them believes they have the run. I nearly did: today's cost analysis was
computed from the log rather than from this map, and had it been the other way the test-user
squad would have come out at zero.

One `_capped_1202z7` bucket closes the arithmetic and names how many labels it stands for.
"""
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))


def _labels(n, usd_each=1.0, calls_each=10):
    """`n` labels, descending in cost the way the real map arrives."""
    return {
        "role%02d:stage" % i: {
            "calls": calls_each, "prompt": 1000, "cached": 900,
            "uncached": 100, "completion": 50, "usd": usd_each * (n - i),
        }
        for i in range(n)
    }


def _written(monkeypatch, tmp_path, labels):
    import multi_agent.runtime.run_budget as RB
    import utils.llm as LL
    monkeypatch.setattr(LL, "llm_usage_by_label_1202cr", lambda: labels, raising=False)
    monkeypatch.setattr(LL, "llm_usage", lambda: {"calls": 0, "usd": 0.0}, raising=False)
    monkeypatch.setattr(LL, "tool_result_bytes", lambda: {}, raising=False)
    import logging
    assert hasattr(RB, "RunBudget"), "RunBudget is gone"
    b = RB.RunBudget(tmp_path, logging.getLogger("t1202z7"))
    b.write({"max_wall_sec": 1.0, "max_ticks": 1}, 1.0, 1.0, 1, "running")
    import json
    return json.loads((tmp_path / "run_budget.json").read_text(encoding="utf-8"))


def test_nothing_is_added_when_nothing_is_cut(monkeypatch, tmp_path):
    """24 labels or fewer: byte-identical to before, so no reader changes."""
    d = _written(monkeypatch, tmp_path, _labels(24))
    m = d["llm_by_phase_1202cr"]
    assert "_capped_1202z7" not in m, sorted(m)
    assert len(m) == 24


def test_the_cut_labels_are_summed_into_one_bucket(monkeypatch, tmp_path):
    d = _written(monkeypatch, tmp_path, _labels(30))
    m = d["llm_by_phase_1202cr"]
    assert "_capped_1202z7" in m, sorted(m)
    assert m["_capped_1202z7"]["labels"] == 6, m["_capped_1202z7"]


def test_the_arithmetic_closes(monkeypatch, tmp_path):
    """★ The whole point: summing the map must now give the run, not the head of it."""
    labels = _labels(30)
    d = _written(monkeypatch, tmp_path, labels)
    m = d["llm_by_phase_1202cr"]
    for key in ("calls", "usd", "uncached", "prompt", "cached", "completion"):
        want = sum(float(v[key]) for v in labels.values())
        got = sum(float(v[key]) for v in m.values())
        assert abs(got - want) < 1e-6, "%s: %r vs %r" % (key, got, want)


def test_the_kept_head_is_still_the_costliest(monkeypatch, tmp_path):
    """The cap's purpose is unchanged — the head is still what it was."""
    d = _written(monkeypatch, tmp_path, _labels(30))
    m = d["llm_by_phase_1202cr"]
    kept = [k for k in m if k != "_capped_1202z7"]
    assert len(kept) == 24
    assert "role00:stage" in kept, "the costliest label was dropped"
    assert "role29:stage" not in kept, "the cheapest label was kept"


def test_the_bucket_is_named_so_it_cannot_be_read_as_a_role(monkeypatch, tmp_path):
    """`unattributed` already means something else — a call with no label. A reader must not
    confuse 'nobody said who' with 'the cap cut these'."""
    d = _written(monkeypatch, tmp_path, _labels(30))
    assert "_capped_1202z7" in d["llm_by_phase_1202cr"]
    assert "unattributed" not in d["llm_by_phase_1202cr"], "the fixture declares no such label"


def test_a_missing_field_does_not_break_the_sum(monkeypatch, tmp_path):
    """Buckets are built by several writers; one lacking `completion` must not lose the
    whole aggregate."""
    labels = _labels(26)
    labels["role25:stage"].pop("completion")
    d = _written(monkeypatch, tmp_path, labels)
    assert d["llm_by_phase_1202cr"]["_capped_1202z7"]["labels"] == 2


def test_the_total_stays_authoritative():
    """#1202cr's own rule, restated: `payload['llm']` is never derived from this map. The
    aggregate is there so a READER can check the map, not so anything computes from it."""
    import inspect
    import multi_agent.runtime.run_budget as RB
    src = inspect.getsource(RB)
    i = src.index("_capped_1202z7")
    assert 'payload["llm"] = llm_usage()' in src[:i], "the total must be written independently"
