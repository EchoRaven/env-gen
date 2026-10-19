r"""#888: the same collapse across a function boundary — and this one permits delivery.

The #881–#887 census looked at `except: x = <empty>` **inline**. It cannot see the identical
collapse across a **function boundary**: a helper that returns an empty value from an except arm,
where the caller has no way to distinguish "nothing found" from "the check failed".

Swept: **186 functions** return an empty value from a silent except arm while also returning real
data. Nearly all are best-effort helpers where empty is the right answer. Three are gate-shaped:

| | direction |
|---|---|
| `_all_business_endpoints_have_route_code` → `False` | the gate stays **shut** — fail-closed, safe |
| `missing_required_args_634` → `[]` | the call proceeds and raises inside; the agent gets the raw error instead of the friendly one — degraded, not dangerous |
| **`_visual_delivery_defer_active` → `False`** | **"not deferring" — which is what PERMITS `deliver_project`** |

★ The last one's own docstring says why it exists: run-32, where *"the LLM called deliver_project
at 1406s into a 3600s window → loop exited → lanes terminated"*. **A fault in the check re-creates
the exact failure the check was written to prevent.**

**The default is not changed.** Returning `True` would be the conservative direction here — and
unlike the general case it could not wedge forever, because the #112 window bounds it — but that
is a behaviour change on a release path, unverifiable without a run, and this session's rule is
not to guess on an unverified root. What changes is that it stops being indistinguishable from an
honest "not deferring".
"""
import inspect
import types

import pytest

from env_generator.llm_generator.multi_agent import orchestrator as orch


def _span():
    src = inspect.getsource(orch)
    start = src.index("#888: a fault here silently PERMITS delivery")
    end = src.index("_coordination_tick_due", start)
    return src[start:end]


def test_the_site_is_findable():
    """Non-vacuity."""
    assert "#888: a fault here silently PERMITS delivery" in inspect.getsource(orch)


def test_it_announces():
    span = _span()
    assert "_logger.error" in span
    assert "VISUAL-DEFER CHECK FAILED" in span


def test_the_message_names_the_consequence_not_just_the_fault():
    """★ "check failed" is not actionable; "this permits deliver_project" is.

    Asserted as FRAGMENTS, not as the joined phrase. The log string is wrapped across two source
    lines (`"...which PERMITS "` + `"deliver_project. ..."`), so `PERMITS deliver_project` exists
    only in the runtime-concatenated value and never in the source text. Matching a message's
    wording against source is a check that breaks on line wrapping rather than on behaviour."""
    span = _span()
    assert "PERMITS" in span and "deliver_project" in span
    assert "unverified" in span


def test_it_names_the_incident_the_check_exists_for():
    span = _span()
    assert "run-32" in span
    assert "1406s" in span


def test_it_says_it_once():
    """This is consulted on every delivery poll."""
    src = inspect.getsource(orch)
    assert src.count("_said_vd_888") >= 2


def test_the_permissive_default_is_deliberate_and_unchanged():
    """★ Pinned so a later change of direction is a decision, not a drift. `True` is arguably
    right here — the #112 window bounds it — but it is a release-path behaviour change and
    unverifiable offline."""
    span = _span()
    assert "return False" in span
    assert "not changed" in span.lower() or "NOT changed" in span


def test_the_two_siblings_keep_their_directions():
    """Non-vacuity for the triage: the other two gate-shaped functions must stay as classified,
    or the table in this docstring is stale."""
    src = inspect.getsource(orch)
    i = src.index("def _all_business_endpoints_have_route_code")
    body = src[i:src.index("def ", i + 10)]
    assert "return False" in body, "the fail-closed sibling changed direction"

    from env_generator.llm_generator.multi_agent.agents.runtime import tooling
    t = inspect.getsource(tooling.missing_required_args_634)
    assert "return []" in t


def test_the_caller_still_reads_it_as_the_defer_signal():
    """Non-vacuity for the premise: if `deliver_project` stops consulting this, the severity claim
    is wrong and the note should be re-read."""
    src = inspect.getsource(orch)
    assert "_visual_defer_check" in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


# --- #1203pg: the announcement, DRIVEN -----------------------------------------------------------
#
# Every assertion above reads the SOURCE. A mutation showed what that misses: inserting
# `return False` above the announcement, or inverting the say-once latch, leaves every asserted
# string in place and makes the fault silent again -- which is the entire state #888 was written
# to end. The permissive default was the only property with a real driver (it is pinned by a
# `return False` that the span contains exactly once), and it was the only one the mutation
# could not get past.


class _ReferenceLookupRaises:
    """A `self` for which the FIRST getattr inside the check raises, so the except arm runs.

    `_reference_images` is the check's first lookup. Only that name raises; everything else
    raises AttributeError so `getattr(self, "_said_vd_888", False)` still falls to its default,
    exactly as it does on a real orchestrator that has never announced.
    """

    def __init__(self):
        self.errors = []
        self._logger = types.SimpleNamespace(
            error=self._record, warning=lambda *a, **k: None,
            info=lambda *a, **k: None, debug=lambda *a, **k: None)

    def _record(self, *a, **k):
        self.errors.append((a[0] % a[1:]) if len(a) > 1 else str(a[0]))

    def __getattr__(self, name):
        if name == "_reference_images":
            raise RuntimeError("the hub hiccuped")
        raise AttributeError(name)


def test_a_fault_really_announces():
    s = _ReferenceLookupRaises()
    assert orch.Orchestrator._visual_delivery_defer_active(s) is False
    assert len(s.errors) == 1, "the fault was silent -- #888's whole subject"
    assert "VISUAL-DEFER CHECK FAILED" in s.errors[0]


def test_the_announcement_names_the_consequence_in_the_FORMATTED_message():
    """The source-text sibling of this test has to assert `PERMITS` and `deliver_project`
    separately, because the format string is wrapped across two lines. The runtime value is
    joined, so the phrase a human actually reads can be asserted whole."""
    s = _ReferenceLookupRaises()
    orch.Orchestrator._visual_delivery_defer_active(s)
    msg = s.errors[0]
    assert "PERMITS deliver_project" in msg
    assert "RuntimeError" in msg, "the message must name the fault it is reporting"
    assert "unverified" in msg


def test_it_really_says_it_once():
    """Consulted on every delivery poll, so a per-poll line would drown the log."""
    s = _ReferenceLookupRaises()
    for _ in range(5):
        assert orch.Orchestrator._visual_delivery_defer_active(s) is False
    assert len(s.errors) == 1, "announced %d times" % len(s.errors)
    assert s._said_vd_888 is True


def test_the_permissive_default_is_what_it_actually_returns():
    """Pinned behaviourally as well as textually: `False` means "not deferring", which is what
    lets `deliver_project` through, and that direction is deliberate (#112 bounds it)."""
    assert orch.Orchestrator._visual_delivery_defer_active(
        _ReferenceLookupRaises()) is False
