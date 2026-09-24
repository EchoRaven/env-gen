r"""#1202eb: every run ends "finished", including the ones that never started.

googlemaps-r15 launched at 03:24:27 and hit `429 ... 'You have no credits remaining'`
nine seconds later. #1159/#1174 did their job: the provider error latched terminal, the
retry ladder stopped, and the run aborted at 03:38 instead of spinning for hours. What it
left behind was:

    "usage": {"elapsed_sec": 851.8, "ticks": 0, "status": "finished"}
    "llm":   {"calls": 0, "usd": 0.0}

`finished` is the word a clean three-milestone delivery gets. The status argument at the
final write was the string literal `"finished"` for every outcome, four lines above
`GenerationResult(success=success, ...)` — the answer was in scope and discarded. The
reason existed too, latched in `terminal_llm_error()`, and reached only the log.

Same shape as #973/#978/#1202df/#1202ea: the framework holds the actionable fact and
reports the outcome without it.
"""
import sys
from pathlib import Path

import pytest

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

SRC = (THIS_DIR.parent / "env_generator" / "llm_generator" / "multi_agent"
       / "orchestrator.py").read_text(encoding="utf-8")


def _final_write_segment():
    i = SRC.index("#1175: stop the refresher")
    return SRC[i:SRC.index("return GenerationResult(", i)]


def test_a_provider_abort_is_not_called_finished():
    seg = _final_write_segment()
    assert "aborted_provider" in seg, (
        "a run the provider killed still records the word a delivered run gets")


def test_a_failed_run_is_not_called_finished():
    seg = _final_write_segment()
    assert '"failed"' in seg
    assert "success" in seg, "`success` is in scope at this write and must decide the word"


def test_the_reason_travels_with_the_status():
    """A category without its instance starts the post-mortem at `grep`."""
    seg = _final_write_segment()
    assert "_abort_1202eb" in seg


def test_the_ledger_persists_the_reason():
    rb = (THIS_DIR.parent / "env_generator" / "llm_generator" / "multi_agent"
          / "runtime" / "run_budget.py").read_text(encoding="utf-8")
    assert "terminal_reason" in rb


def _write_ledger(tmp_path, status, reason=""):
    """Drive the real RunBudget against a real file and read the JSON back."""
    import json
    from multi_agent.runtime.run_budget import RunBudget  # noqa: E402
    import logging
    b = RunBudget(tmp_path, logging.getLogger("test1202eb"))
    caps = {"max_wall_sec": 10800.0, "max_ticks": 200, "unlimited": False}
    b.write(caps, 1788683069.6, 851.8, 0, status, reason)
    return json.loads(b.path().read_text(encoding="utf-8"))["usage"]


def test_r15s_ledger_now_names_its_killer(tmp_path):
    """The record googlemaps-r15 should have left behind."""
    u = _write_ledger(tmp_path, "aborted_provider",
                      "[RateLimitError] Error code: 429 - You have no credits remaining.")
    assert u["status"] == "aborted_provider"
    assert "no credits remaining" in u["terminal_reason"]


def test_a_clean_run_carries_no_reason_field(tmp_path):
    """The field appears exactly when there is something to read."""
    u = _write_ledger(tmp_path, "finished")
    assert u["status"] == "finished"
    assert "terminal_reason" not in u


def test_a_pathological_reason_cannot_bloat_the_record(tmp_path):
    from multi_agent.runtime.run_budget import _REASON_CAP_1202EB as CAP  # noqa: E402
    u = _write_ledger(tmp_path, "aborted_provider", "x" * 9000)
    assert len(u["terminal_reason"]) <= CAP


def test_the_only_reason_we_have_measured_survives_whole(tmp_path):
    """217 chars, the one distinct terminal reason in the corpus (257 occurrences)."""
    from multi_agent.runtime.run_budget import _REASON_CAP_1202EB as CAP  # noqa: E402
    assert CAP >= 217, "the one terminal reason we have ever observed no longer fits"


def test_the_accessor_never_raises():
    """Accounting must never be the reason a run record fails to write (#1163)."""
    i = SRC.index("def _provider_abort_reason_1202eb")
    seg = SRC[i:SRC.index("def _load_run_budget_caps", i)]
    assert "except Exception" in seg
    assert "warn_once_1201" in seg, "a silent guard here hides a broken ledger (#1201)"


def test_the_accessor_reads_the_latched_error():
    i = SRC.index("def _provider_abort_reason_1202eb")
    seg = SRC[i:SRC.index("def _load_run_budget_caps", i)]
    assert "terminal_llm_error" in seg
