"""#1203r8 -- a write that does not restate `status` must not demote an audited record.

The registries merge status as `status or existing.get("status") or "defined"`, which reads as
"a caller that says nothing keeps what is there". Every one of the four writers defaulted
`status` to the TRUTHY string `"defined"`, so the `or existing` arm was dead and ANY
re-registration demoted the record. The production trigger is at schema level: the
`registryhub_register_ui_page` tool declared `status` with `default: "defined"`, so every lane
registration explicitly un-audited the page.

Measured over 216 runs carrying a UI-PAGE LIFECYCLE line:

    (run, page) pairs announced `implemented`            3081
    total "newly implemented" announcements             10795
  * pairs announced more than once               2059    67% of pairs
  * announcements that are RE-announcements      7714    71% of all
  * repeats with NO `regressed` line for that page 1326  64% of repeats

`for_you_page` was announced newly-implemented 57 times in one run.

The audit's `implemented` / `regressed` / `pending` are TRANSITION lists, so a demoted page
cannot reach the `regressed` arm (`not ok and status == "implemented"`); it falls to `pending`,
and the lifecycle line reports `regressed=[]` while the state moved backwards.

EVERY TEST HERE DRIVES THE REGISTRY. None of them reads the source text -- the bug was a
default argument that made a correctly-written expression unreachable, which no text assertion
about that expression could ever have seen.
"""
import sys
import tempfile

import pytest

from env_generator.llm_generator.multi_agent.runtime import registryhub as R
from env_generator.llm_generator.multi_agent.runtime import frontend_audit as FA

PAGE = dict(route="/login", component="LoginPage", apis_used=["GET /api/session"],
            components=["LoginForm"], path="src/pages/LoginPage.jsx")


def _hub():
    return R.RegistryHub(tempfile.mkdtemp())


def _audited(hub, name="login_page", **kw):
    """A page the FRAMEWORK AUDIT has marked implemented (mechanism #54: orchestrator only)."""
    kw = {**PAGE, **kw}
    hub.register_ui_page(name, status="implemented", agent="orchestrator", **kw)
    assert hub.get_ui_page(name)["status"] == "implemented", "fixture failed to flip the page"
    return hub


# --------------------------------------------------------------------------- the defect
def test_a_lane_re_registration_that_says_nothing_keeps_the_audited_status():
    hub = _audited(_hub())
    hub.register_ui_page("login_page", agent="frontend", **PAGE)
    assert hub.get_ui_page("login_page")["status"] == "implemented"


def test_an_explicit_defined_from_a_lane_also_keeps_it():
    """The tool's schema used to DEFAULT this field to "defined", so the real-world write
    states it explicitly. Fixing only the Python default would not have held."""
    hub = _audited(_hub())
    hub.register_ui_page("login_page", status="defined", agent="frontend", **PAGE)
    assert hub.get_ui_page("login_page")["status"] == "implemented"


def test_the_orchestrators_own_metadata_write_keeps_it():
    """Attaching a reference image changes nothing about the contract, and it demoted the page."""
    hub = _audited(_hub())
    hub.register_ui_page("login_page", agent="orchestrator", reference_image="shot.png", **PAGE)
    assert hub.get_ui_page("login_page")["status"] == "implemented"


def test_a_changed_contract_still_keeps_it_until_the_audit_looks_again():
    """A lane adding an api makes the verdict STALE, not false. The audit re-runs every
    scaffold pass and downgrades through `regressed` -- which is the channel built to say so,
    and the channel the silent demotion bypassed."""
    hub = _audited(_hub())
    hub.register_ui_page("login_page", agent="frontend",
                         **{**PAGE, "apis_used": ["GET /api/session", "POST /api/login"]})
    rec = hub.get_ui_page("login_page")
    assert rec["status"] == "implemented"
    assert "POST /api/login" in rec["apis_used"], "the contract change itself must still land"


# ------------------------------------------------- what the guard must NOT break
def test_the_audit_can_still_demote_a_page():
    """THE COUNTER-PROOF. A guard that kept `implemented` unconditionally would make the
    `regressed` arm permanently unreachable -- the same blindness from the other side."""
    hub = _audited(_hub())
    hub.register_ui_page("login_page", status="defined", agent="orchestrator", **PAGE)
    assert hub.get_ui_page("login_page")["status"] == "defined"


def test_mechanism_54_still_refuses_a_lane_self_claim():
    hub = _hub()
    hub.register_ui_page("p2", route="/p2", component="P2", apis_used=["GET /a"],
                         agent="frontend")
    assert hub.get_ui_page("p2")["status"] == "defined", "a new lane page is not implemented"
    hub.register_ui_page("p2", route="/p2", component="P2", status="implemented",
                         agent="frontend")
    assert hub.get_ui_page("p2")["status"] == "defined", "#54: a lane may not self-claim"


def test_a_brand_new_page_is_still_defined():
    """`status=""` must not leave a record statusless -- the merge's last arm supplies it."""
    hub = _hub()
    hub.register_ui_page("fresh", route="/fresh", component="Fresh", apis_used=["GET /a"],
                         agent="frontend")
    assert hub.get_ui_page("fresh")["status"] == "defined"


# ------------------------------------------------------------------- ui_components
def test_a_lane_write_does_not_un_audit_a_component():
    hub = _hub()
    hub.register_ui_component("LoginForm", component="LoginForm", apis_used=["GET /a"],
                              status="implemented", agent="orchestrator")
    hub.register_ui_component("LoginForm", component="LoginForm", apis_used=["GET /a"],
                              agent="frontend")
    assert hub.list_ui_components()["LoginForm"]["status"] == "implemented"


def test_the_orchestrators_own_silent_write_does_not_un_audit_a_component():
    """The component counterpart of `test_the_orchestrators_own_metadata_write_keeps_it`, and
    the test that was MISSING: mutation R8D (the component default back to "defined") went
    MISSED without it, because the actor guard masks that default for every NON-orchestrator
    write. The orchestrator is exactly the actor the guard lets through, so a silent write from
    it is the only thing that can still see the default -- which makes it the only mutation
    detector for that default. The page side had this test; the component side did not."""
    hub = _hub()
    hub.register_ui_component("LoginForm", component="LoginForm", apis_used=["GET /a"],
                              status="implemented", agent="orchestrator")
    hub.register_ui_component("LoginForm", component="LoginForm", apis_used=["GET /a"],
                              agent="orchestrator")
    assert hub.list_ui_components()["LoginForm"]["status"] == "implemented"


def test_a_silent_write_does_not_clobber_a_deprecated_component():
    """`status=""` must preserve ANY stored status, not only `implemented` -- the guard above
    covers `implemented` alone, so this is what the default itself is responsible for."""
    hub = _hub()
    hub.register_ui_component("Old", component="Old", status="deprecated", agent="frontend")
    hub.register_ui_component("Old", component="Old", agent="frontend")
    assert hub.list_ui_components()["Old"]["status"] == "deprecated"


def test_a_silent_write_does_not_clobber_a_deprecated_page():
    hub = _hub()
    hub.register_ui_page("old_page", status="deprecated", agent="frontend", **PAGE)
    hub.register_ui_page("old_page", agent="frontend", **PAGE)
    assert hub.get_ui_page("old_page")["status"] == "deprecated"


def test_the_audit_can_still_demote_a_component():
    hub = _hub()
    hub.register_ui_component("LoginForm", component="LoginForm", status="implemented",
                              agent="orchestrator")
    hub.register_ui_component("LoginForm", component="LoginForm", status="defined",
                              agent="orchestrator")
    assert hub.list_ui_components()["LoginForm"]["status"] == "defined"


# --------------------------------------------- endpoints and tables: the silence half only
def test_silence_preserves_an_implemented_endpoint():
    hub = _hub()
    hub.register_endpoint("GET", "/api/x", schema={"request": {}}, provider="backend",
                          agent="backend", status="implemented")
    eid = R.RegistryHub.endpoint_id("GET", "/api/x")
    hub.register_endpoint("GET", "/api/x", schema={"request": {}}, provider="backend",
                          agent="backend")
    assert hub._endpoints.value()[eid]["status"] == "implemented"


def test_silence_preserves_an_implemented_table():
    hub = _hub()
    hub.register_table("users", schema={"columns": {"id": "int"}}, provider="backend",
                       agent="backend", status="implemented")
    key = list(hub._tables.value())[0]
    hub.register_table("users", schema={"columns": {"id": "int"}}, provider="backend",
                       agent="backend")
    assert hub._tables.value()[key]["status"] == "implemented"


def test_an_explicit_defined_on_an_endpoint_STILL_demotes_on_purpose():
    """THE DOCUMENTED SCOPE BOUNDARY, pinned so narrowing it later is a decision.

    For endpoints the backend lane IS the lifecycle authority -- hub_pulse tells it to call
    `register_endpoint(status='implemented')` for what it owns -- so "only the orchestrator may
    demote" would be wrong here. An explicit `defined` is a caller stating intent."""
    hub = _hub()
    hub.register_endpoint("GET", "/api/x", schema={"request": {}}, provider="backend",
                          agent="backend", status="implemented")
    eid = R.RegistryHub.endpoint_id("GET", "/api/x")
    hub.register_endpoint("GET", "/api/x", schema={"request": {}}, provider="backend",
                          agent="backend", status="defined")
    assert hub._endpoints.value()[eid]["status"] == "defined"


# ------------------------------------------------------- the consequence, end to end
class _Hub:
    """The minimal workhub surface `sync_ui_page_statuses` uses, over a real RegistryHub."""

    def __init__(self, reg):
        self.reg = reg

    def get_ui_pages(self):
        return self.reg.list_ui_pages()

    def get_ui_components(self):
        return self.reg.list_ui_components()

    def update_ui_page(self, name, data, agent=""):
        data = dict(data or {})
        return self.reg.register_ui_page(
            name, route=data.pop("route", ""), component=data.pop("component", ""),
            apis_used=data.pop("apis_used", None), components=data.pop("components", None),
            path=data.pop("path", ""), status=data.pop("status", ""), agent=agent, **data)

    def update_ui_component(self, name, data, agent=""):
        data = dict(data or {})
        return self.reg.register_ui_component(
            name, component=data.pop("component", ""), apis_used=data.pop("apis_used", None),
            status=data.pop("status", ""), agent=agent, **data)


@pytest.fixture
def failing_audit(monkeypatch):
    """Make the page audit fail, so the only question is WHICH list the page lands in."""
    monkeypatch.setattr(FA, "audit_ui_page",
                        lambda *a, **k: (False, ["dead controls: 2 of 2 <button> tags"]))
    monkeypatch.setattr(FA, "audit_ui_component", lambda *a, **k: (True, []))


def _project(tmp_path):
    src = tmp_path / "app" / "frontend" / "src"
    src.mkdir(parents=True)
    (src / "App.jsx").write_text("export default function App(){return null}", encoding="utf-8")
    return tmp_path


def test_a_failing_audit_on_an_implemented_page_reports_REGRESSED(tmp_path, failing_audit):
    """★ THE PAYOFF. With the silent demotion, the page was already `defined` by the time the
    audit looked, so `not ok and status == "implemented"` could not fire and the page fell to
    `pending` -- the lifecycle line then said `regressed=[]`. netflix-local-r46 is the shape:
    `landing_page` implemented in pass 1, `pending` in passes 2-5, `regressed=[]` in all five.
    """
    reg = _hub()
    _audited(reg)
    hub = _Hub(reg)
    # a lane touches the page between passes -- exactly what used to erase the verdict
    reg.register_ui_page("login_page", agent="frontend", **PAGE)

    out = FA.sync_ui_page_statuses(_project(tmp_path), hub, reg)

    assert "login_page" in (out.get("regressed") or []), (
        "a page that LOST a passing audit must be reported as regressed, not pending; got "
        "regressed=%r pending=%r" % (out.get("regressed"), sorted(out.get("pending") or {})))
    assert "login_page" not in (out.get("pending") or {})
    assert reg.get_ui_page("login_page")["status"] == "defined", "and it must actually demote"


def test_a_page_that_never_passed_is_pending_not_regressed(tmp_path, failing_audit):
    """The other arm, so the test above cannot pass by reporting everything as regressed."""
    reg = _hub()
    reg.register_ui_page("never", route="/never", component="Never", apis_used=["GET /a"],
                         agent="frontend")
    out = FA.sync_ui_page_statuses(_project(tmp_path), _Hub(reg), reg)
    assert "never" in (out.get("pending") or {})
    assert "never" not in (out.get("regressed") or [])


def test_the_audit_announces_an_implemented_page_only_once(tmp_path, monkeypatch):
    """71% of all `implemented` announcements in the corpus were re-announcements of a flip
    that had already happened, because the page kept being demoted behind the audit's back."""
    monkeypatch.setattr(FA, "audit_ui_page", lambda *a, **k: (True, []))
    monkeypatch.setattr(FA, "audit_ui_component", lambda *a, **k: (True, []))
    reg = _hub()
    # the page's declared api must be IN the contract, or `_contract_misses` fails the page
    # on its own and the audit never gets to the flip (it did, the first time this was run).
    reg.register_endpoint("GET", "/api/session", schema={"request": {}}, provider="backend",
                          agent="backend", status="implemented")
    reg.register_ui_page("login_page", agent="frontend", **PAGE)
    hub, proj = _Hub(reg), _project(tmp_path)

    first = FA.sync_ui_page_statuses(proj, hub, reg)
    assert "login_page" in (first.get("implemented") or []), "pass 1 must flip it"
    # a lane re-registers it, as lanes do every pass
    reg.register_ui_page("login_page", agent="frontend", **PAGE)
    second = FA.sync_ui_page_statuses(proj, hub, reg)
    assert "login_page" not in (second.get("implemented") or []), (
        "pass 2 re-announced a flip that already happened: %r" % (second.get("implemented"),))


# ------------------------------------------------- the two layers in front of the registry
def test_the_real_workhub_delegate_does_not_demote():
    """`WorkHub.update_ui_page` unpacks a FLAT dict into `register_ui_page`'s kwargs, and it
    supplied its own `"defined"` default -- so even with the registry fixed, a write through
    the delegate would have demoted. The audit itself goes through this delegate."""
    from multi_agent.runtime.hubs.workhub.service import WorkHub
    from pathlib import Path
    reg = _hub()
    wh = WorkHub(Path(tempfile.mkdtemp()))
    wh._registryhub = reg
    wh.update_ui_page("login_page", {**PAGE, "status": "implemented"}, agent="orchestrator")
    assert reg.get_ui_page("login_page")["status"] == "implemented"
    # the lane's write: route/component restated, status not mentioned
    wh.update_ui_page("login_page", dict(PAGE), agent="frontend")
    assert reg.get_ui_page("login_page")["status"] == "implemented"
    # ★ AND THE ORCHESTRATOR'S OWN SILENT WRITE. This assertion is the only detector for the
    # delegate's default: mutation R8H (the delegate supplying "defined" again) went MISSED
    # without it, because the registry guard rescues every NON-orchestrator write, and the
    # orchestrator is precisely the actor the guard exempts. Second time that shape bit in one
    # session -- see the component twin above.
    wh.update_ui_page("login_page", dict(PAGE), agent="orchestrator")
    assert reg.get_ui_page("login_page")["status"] == "implemented"
    # and the audit can still demote through the same delegate
    wh.update_ui_page("login_page", {"status": "defined"}, agent="orchestrator")
    assert reg.get_ui_page("login_page")["status"] == "defined"


def test_the_tool_does_not_advertise_a_default_status():
    """★ THE PRODUCTION TRIGGER, asserted on the DECLARED CONTRACT rather than the source.

    `registryhub_register_ui_page` declared `status` with `default: "defined"`. A model filling
    a tool call from that schema states `defined` explicitly, which is why fixing the Python
    default alone would not have held -- and why the registry guards the value too. `enum` must
    keep excluding `implemented` (mechanism #54: a lane may not self-claim)."""
    from tools.hub_tools import WorkHubUpdatePageTool
    props = (WorkHubUpdatePageTool.PARAMETERS or {}).get("properties") or {}
    status = props.get("status")
    assert isinstance(status, dict), "the tool must still expose `status`"
    assert "default" not in status, (
        "a default here un-audits the page on every lane registration: %r" % (status,))
    assert "implemented" not in (status.get("enum") or []), "mechanism #54 must still hold"
