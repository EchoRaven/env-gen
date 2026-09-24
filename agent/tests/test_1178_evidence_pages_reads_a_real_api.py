"""#1178 — the named-pages remediation read two attributes the orchestrator does not have.

`_ui_evidence_failed_pages` fetched `orch._last_validation_results` / `orch._validation_results`.
Neither exists: the orchestrator exposes the METHOD `_get_validation_results(limit=...)`, which
is what the gate's own consumer calls and whose docstring says "the two readers must agree".
Both getattr calls returned None, so the function returned [] on every call since #982 landed,
and the dispatcher fell through to the generic body every time — taking #982's page list,
#1043's auth-root hint and #1176/#1177 down with it.

r17 shows it on both sides of a resume: task_fa4adc4f11 (original) and task_f2496728f6 (resume)
are both exactly 789 characters — the base body alone — while the gate one line above printed
"#1017 validation_ui_evidence_failed on 1 record(s), 1 named page(s): landing_page".

The last test is the one that would have caught it: assert the producer's dependency is a real
name on the real class, not a plausible-looking one.
"""
import inspect

from env_generator.llm_generator.multi_agent.orchestrator import Orchestrator
from env_generator.llm_generator.multi_agent.runtime import remediation_dispatcher as rd


class _OrchWithMethodOnly:
    """Exactly the surface the real orchestrator offers — the method, and no attributes."""

    def __init__(self, records):
        self._records = records

    def _get_validation_results(self, limit=200):
        return list(self._records)[:limit]


_FAILING = [
    {"name": "validation:ui_smoke:landing_page", "status": "failed", "metadata": {}},
    {"name": "validation:ui_flow:browse_home_page", "status": "passed", "metadata": {}},
]


def test_pages_are_named_from_the_method_the_orchestrator_actually_has():
    pages = rd._ui_evidence_failed_pages(_OrchWithMethodOnly(_FAILING))
    assert "landing_page" in pages, (
        "the producer must read _get_validation_results — this returned [] for the whole "
        "life of #982 because it read two attributes that do not exist")


def test_an_orchestrator_with_neither_source_is_quiet():
    class _Bare:
        pass

    assert rd._ui_evidence_failed_pages(_Bare()) == []


def test_the_legacy_attributes_still_work_when_present():
    """Kept as a fallback: a caller that sets the attribute is not broken by the fix."""
    class _AttrOnly:
        _last_validation_results = _FAILING

    assert "landing_page" in rd._ui_evidence_failed_pages(_AttrOnly())


def test_the_orchestrator_really_exposes_what_the_producer_reads():
    """★ The guard that was missing. A name the producer depends on must exist on the class
    it is handed — otherwise the read fails open to [] and the remediation silently degrades
    to generic text with nothing in any log to say so."""
    src = inspect.getsource(rd._ui_evidence_failed_pages)
    assert "_get_validation_results" in src
    assert hasattr(Orchestrator, "_get_validation_results"), (
        "the producer's primary source must be a real attribute of the real Orchestrator")
    assert callable(getattr(Orchestrator, "_get_validation_results"))
