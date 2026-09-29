r"""#1202ze: the gate returns ok while the run's own validation matrix says the smoke failed.

The gate computes `api_smoke_pass` / `ui_smoke_pass` on EVERY evaluation and publishes them in
`validation_runtime`. Whether they are ENFORCED — appended to `failed_checks` — sits behind
`task_suite_exists = (output_dir/"tasks"/"tasks.yaml").exists()`, FALSE in 172 of 172 corpus
runs, because nothing calls `save_task_suite`. So both signals are computed, written down, and
read by nobody: `_maybe_framework_deliver` gates on `failed_checks`, which stays empty.

MEASURED over the corpus gate ledgers: of 987 evaluations with `ok: true`, **86 in 27 runs**
carried `api_smoke_pass` or `ui_smoke_pass` FALSE at the same time. An r119 record reads
`ok: True`, `failed_checks: []`, `verification.all_required_passing: True` beside
`api_smoke_pass: False` and `failed_top: api_smoke | FAILED: business_chain`.

★ IT IS NOT AN EARLY-RUN ARTIFACT AND NOT STALE DATA, and both had to be checked before this
was worth building:
  * position in each run's ledger — median 0.73, and 22 of the 86 in the LAST 10%, i.e. at the
    release cut;
  * `total_results` 6..27 at the time, so validation had run;
  * `api_smoke_pass` is `any(status == "passed" for the last 200 results)` — a rolling window,
    so False means no passing smoke in that whole window, which one stale record cannot make.

★ REPORTS, NEVER BLOCKS. Enforcing the signals would turn 86 of 987 passing evaluations into
blocks — 8.7% blast radius on the delivery gate — and a gate change is verified on a live run
before it ships (#1202w6); the provider account is at zero credits. What is missing is not the
judgement but the AUDIENCE, the same defect as #1202z0 and #1202z4.
"""
import ast
import inspect
import json
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import multi_agent.orchestrator as O  # noqa: E402


class _WH:
    def __init__(self, existing=None):
        self.tasks = list(existing or [])
        self.created = []

    def list_tasks(self):
        return self.tasks

    def create_task(self, **kw):
        # ★ A faithful stand-in: a real WorkHub's `list_tasks` returns what `create_task` just
        # stored, so the dedupe can see its own task. The first version of this kept the two
        # lists apart and the storm-control test failed against CORRECT code — a stand-in that
        # cannot do what the real object does proves nothing about the real object.
        self.created.append(kw)
        rec = {"id": "t%d" % len(self.created), "status": "pending", **kw}
        self.tasks.append(rec)
        return rec


class _Orch:
    def __init__(self, tmp, wh=None):
        self.output_dir = str(tmp)

        class _H:
            workhub = wh
        self.hubs = _H() if wh is not None else None


def _gate(ok=True, api=False, ui=True, total=16, tops=None, with_vr=True):
    g = {"ok": ok, "failed_checks": []}
    if with_vr:
        g["validation_runtime"] = {
            "task_suite_exists": False, "api_smoke_pass": api, "ui_smoke_pass": ui,
            "total_results": total,
            "failed_top": tops if tops is not None else
            [{"task_id": "api_smoke", "status": "failed",
              "summary": "FAILED: business_chain"}]}
    return g


def _run(tmp, gate, wh=None):
    wh = _WH() if wh is None else wh
    O._gate_cleared_while_smoke_failed_1202ze(_Orch(tmp, wh), gate)
    return wh


def _artifact(tmp):
    p = tmp / "logs" / "gate_passed_while_smoke_failed_1202ze.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


# ── when it fires ─────────────────────────────────────────────────────────────────

def test_a_clearing_gate_with_a_failed_api_smoke_is_reported(tmp_path):
    """★ The r119 record, as a fixture."""
    wh = _run(tmp_path, _gate(ok=True, api=False, ui=True))
    assert len(wh.created) == 1, wh.created
    assert wh.created[0]["assignee"] == "verifier"
    assert wh.created[0]["priority"] == "P1", "a task, not a blocker"
    assert _artifact(tmp_path)[0]["false_signals"] == ["api_smoke_pass"]


def test_a_failed_ui_smoke_counts_too(tmp_path):
    wh = _run(tmp_path, _gate(ok=True, api=True, ui=False))
    assert len(wh.created) == 1
    assert _artifact(tmp_path)[0]["false_signals"] == ["ui_smoke_pass"]


def test_both_signals_are_named_when_both_are_false(tmp_path):
    wh = _run(tmp_path, _gate(ok=True, api=False, ui=False))
    assert _artifact(tmp_path)[0]["false_signals"] == ["api_smoke_pass", "ui_smoke_pass"]
    assert "api_smoke_pass" in wh.created[0]["title"] and "ui_smoke_pass" in wh.created[0]["title"]


# ── when it must stay quiet ───────────────────────────────────────────────────────

def test_a_failing_gate_is_not_reported(tmp_path):
    """The gate already blocks; adding a second voice there is noise, and the whole point is
    the case where NOTHING speaks."""
    wh = _run(tmp_path, _gate(ok=False, api=False))
    assert wh.created == []
    assert _artifact(tmp_path) == []


def test_a_passing_smoke_is_not_reported(tmp_path):
    wh = _run(tmp_path, _gate(ok=True, api=True, ui=True))
    assert wh.created == [] and _artifact(tmp_path) == []


def test_an_absent_signal_is_not_a_failed_one(tmp_path):
    """★ `None` means the matrix never reported, which is a different fact from `False`. A
    truthiness test here would fire on every run that has no validation matrix at all."""
    g = _gate(ok=True)
    g["validation_runtime"].pop("api_smoke_pass")
    g["validation_runtime"]["ui_smoke_pass"] = True
    wh = _run(tmp_path, g)
    assert wh.created == [], wh.created


def test_a_gate_without_a_validation_block_is_not_reported(tmp_path):
    wh = _run(tmp_path, _gate(ok=True, with_vr=False))
    assert wh.created == [] and _artifact(tmp_path) == []


# ── what the report says ──────────────────────────────────────────────────────────

def test_the_task_names_the_instance(tmp_path):
    """#983: a finding that reports only a check name cannot be acted on."""
    d = _run(tmp_path, _gate(ok=True, api=False, total=16))[0].created[0]["description"] \
        if False else _run(tmp_path, _gate(ok=True, api=False, total=16)).created[0]["description"]
    assert "api_smoke_pass" in d
    assert "16" in d, "the number of results behind the signal is not named"
    assert "FAILED: business_chain" in d, "the matrix's own failure text is not carried"


def test_the_task_says_the_gate_was_right(tmp_path):
    """The gate cleared BY ITS OWN RULES — enforcement is switched off upstream. A task that
    reads as 'the gate is broken' sends the verifier to edit the gate, which is the one thing
    it must not do."""
    d = _run(tmp_path, _gate(ok=True, api=False)).created[0]["description"]
    assert "tasks/tasks.yaml" in d and "save_task_suite" in d, d
    assert "Do NOT edit the gate" in d, d


def test_the_task_asks_for_one_of_two_concrete_things(tmp_path):
    d = _run(tmp_path, _gate(ok=True, api=False)).created[0]["description"]
    assert "run validation" in d.lower() and "why it cannot pass" in d.lower(), d


def test_a_matrix_with_no_failure_detail_still_files(tmp_path):
    """`failed_top` can be empty — the signal is the finding, the detail is a bonus."""
    wh = _run(tmp_path, _gate(ok=True, api=False, tops=[]))
    assert len(wh.created) == 1
    assert "no failure detail" in wh.created[0]["description"]


# ── storm control and robustness ──────────────────────────────────────────────────

def test_an_open_task_is_not_cloned(tmp_path):
    """#794: r119 hit this on 9 separate evaluations."""
    wh = _WH([{"title": "Delivery gate cleared while the validation matrix reports a failed "
                        "smoke (api_smoke_pass)", "status": "in_progress"}])
    _run(tmp_path, _gate(ok=True, api=False), wh=wh)
    assert wh.created == [], wh.created


def test_a_completed_task_does_not_suppress_a_new_one(tmp_path):
    wh = _WH([{"title": "Delivery gate cleared while the validation matrix reports a failed "
                        "smoke (api_smoke_pass)", "status": "completed"}])
    _run(tmp_path, _gate(ok=True, api=False), wh=wh)
    assert len(wh.created) == 1


def test_the_artifact_lands_even_with_no_hub(tmp_path):
    """#947: the evidence must not depend on a hub being present."""
    O._gate_cleared_while_smoke_failed_1202ze(_Orch(tmp_path, None), _gate(ok=True, api=False))
    assert len(_artifact(tmp_path)) == 1


def test_a_listing_fault_still_files(tmp_path):
    class _Bad(_WH):
        def list_tasks(self):
            raise RuntimeError("hub down")
    wh = _Bad()
    _run(tmp_path, _gate(ok=True, api=False), wh=wh)
    assert len(wh.created) == 1, "a dedupe fault must not swallow the finding"


def test_every_evaluation_appends_to_the_artifact(tmp_path):
    """The task is deduped; the evidence is not, because the COUNT is what says whether this
    happened once or at every cut."""
    wh = _WH()
    for _ in range(3):
        _run(tmp_path, _gate(ok=True, api=False), wh=wh)
    assert len(_artifact(tmp_path)) == 3
    assert len(wh.created) == 1


# ── the verdict must not move ─────────────────────────────────────────────────────

def test_the_helper_cannot_change_the_verdict():
    """★ The whole bargain. Enforcing these signals is an 8.7% blast radius on the delivery
    gate and needs a live run; this ticket only adds an audience."""
    tree = ast.parse(inspect.getsource(O._gate_cleared_while_smoke_failed_1202ze).lstrip())
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript):
            sl = ast.dump(node.slice)
            assert not any(k in sl for k in ("'ok'", '"ok"', "failed_checks")) or not isinstance(
                getattr(node, "ctx", None), ast.Store), "the helper writes to the verdict"
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", "") or getattr(node.func, "id", "")
            assert name not in ("update", "setdefault") or "gate" not in ast.dump(node), \
                "the helper mutates the gate dict"


def test_the_caller_is_wired_after_the_ledger_and_not_behind_a_branch():
    """★ Three properties, because I have repeatedly tested a helper and not its caller: the
    call exists once, it is fed the gate the ledger just persisted, and it is not guarded."""
    src = inspect.getsource(O)
    i = src.index("_gate_cleared_while_smoke_failed_1202ze(self,")
    assert src.count("_gate_cleared_while_smoke_failed_1202ze(self,") == 1
    before = src[:i]
    assert "_persist_gate_948(self.output_dir, _gate793," in before[-400:], \
        "the call no longer sits beside the ledger write it shares a subject with"
    line = src[i:src.index("\n", i)]
    assert "_gate793" in line, line
