"""#1202mv / #1202mw: a resume re-entering a milestone must not pay for, or undo, its kickoff.

#1202mv — tiktok-r124's last resume spent $48.1 of its $80.3 in the 15-minute kickoff window
(585 LLM calls, ~65k prompt tokens each): attendee turns, the facilitator, a synthesis that
failed validation — and the contract it finalized came from the deterministic registry
reconcile anyway. When the milestone already has a closed kickoff that produced a contract, the
meeting is opened without broadcasting, the settled sections are carried in, and it finalizes
through that same reconcile. Replayed on r124's hubs: 49 sections carried -> ready -> finalized.

#1202mw — `finalize_kickoff` registers with status="defined", and both registries store
`status or existing`, so a resumed finalize reset the lanes' progress. Replayed on r124's real
hubs: 41 implemented endpoints -> defined, 2 deprecated -> defined, 18 implemented tables ->
defined. After the fix the same replay leaves 41 / 2 / 18 exactly as they were.
"""
import ast
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR), str(Path(__file__).resolve().parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.kickoff import run_kickoff as RK  # noqa: E402
from test_kickoff_run_kickoff import ATTENDEES, _all_clean_decisions  # noqa: E402

ORCH = LLM_DIR / "multi_agent" / "orchestrator.py"


def _hubs(tmp):
    root = Path(tmp)
    (root / "shared").mkdir()
    return HubRegistry(root)


def _kickoff(hubs, ms=1, decisions=True, broadcast=True):
    h = RK.start_kickoff(hubs=hubs, milestone_index=ms, requirements=[f"M{ms}"],
                         attendees=ATTENDEES, broadcast=broadcast)
    if decisions:
        for d in _all_clean_decisions():
            hubs.workhub.add_meeting_decision(h["meeting_id"], decision=d,
                                              agent=d.get("agent") or d["section"],
                                              milestone_index=ms)
    return h


def _finalize(hubs, h):
    s = RK.try_synthesize(hubs, h)
    assert s["status"] == "ready", s
    return RK.finalize_kickoff(hubs=hubs, kickoff_handle=h, synthesis=s)


def _mark_built(hubs):
    """The lanes' progress between the first finalize and the resume."""
    ep = hubs.registryhub.get_endpoints()["GET /api/posts"]
    hubs.registryhub.register_endpoint(method="GET", path="/api/posts", schema=ep.get("schema"),
                                       provider="backend", agent="backend", status="implemented")
    t = hubs.schema_hub.get_table("posts")
    hubs.schema_hub.register_table(name="posts", schema=t.get("schema"), provider="backend",
                                   agent="backend", status="implemented")


# ── #1202mw ────────────────────────────────────────────────────────────────────────────────

def test_a_resumed_finalize_keeps_what_the_lanes_built():
    with tempfile.TemporaryDirectory() as tmp:
        hubs = _hubs(tmp)
        _finalize(hubs, _kickoff(hubs))
        _mark_built(hubs)
        _finalize(hubs, _kickoff(hubs))            # the resume re-entering M1
        assert hubs.registryhub.get_endpoints()["GET /api/posts"]["status"] == "implemented"
        assert hubs.schema_hub.get_table("posts")["status"] == "implemented"


def test_a_first_finalize_still_registers_defined():
    with tempfile.TemporaryDirectory() as tmp:
        hubs = _hubs(tmp)
        _finalize(hubs, _kickoff(hubs))
        assert hubs.registryhub.get_endpoints()["GET /api/posts"]["status"] == "defined"
        assert hubs.schema_hub.get_table("posts")["status"] == "defined"


def test_a_different_milestone_is_not_a_resume():
    """M2's contract may legitimately change an endpoint M1 built — unchanged behaviour."""
    with tempfile.TemporaryDirectory() as tmp:
        hubs = _hubs(tmp)
        _finalize(hubs, _kickoff(hubs, ms=1))
        _mark_built(hubs)
        _finalize(hubs, _kickoff(hubs, ms=2))
        assert hubs.registryhub.get_endpoints()["GET /api/posts"]["status"] == "defined"


# ── #1202mv: the helpers ───────────────────────────────────────────────────────────────────

def test_the_settled_meeting_is_this_milestones_closed_contract_meeting():
    with tempfile.TemporaryDirectory() as tmp:
        hubs = _hubs(tmp)
        assert RK.settled_kickoff_meeting_1202mv(hubs, 1) is None
        h1 = _kickoff(hubs)
        assert RK.settled_kickoff_meeting_1202mv(hubs, 1) is None   # open, not settled
        _finalize(hubs, h1)
        assert RK.settled_kickoff_meeting_1202mv(hubs, 1) == h1["meeting_id"]
        assert RK.settled_kickoff_meeting_1202mv(hubs, 2) is None
        assert RK.settled_kickoff_meeting_1202mv(
            hubs, 1, exclude_meeting_id=h1["meeting_id"]) is None


def test_a_resume_finalizes_from_carried_sections_without_asking_anyone():
    with tempfile.TemporaryDirectory() as tmp:
        hubs = _hubs(tmp)
        h1 = _kickoff(hubs)
        _finalize(hubs, h1)
        _mark_built(hubs)

        h2 = _kickoff(hubs, decisions=False, broadcast=False)
        carried = RK.carry_settled_sections_1202mv(hubs, h1["meeting_id"], h2)
        assert carried >= len(ATTENDEES)
        r = _finalize(hubs, h2)
        assert r["phase"] == "finalized"
        assert hubs.registryhub.get_endpoints()["GET /api/posts"]["status"] == "implemented"


def test_start_kickoff_without_broadcast_asks_nobody():
    with tempfile.TemporaryDirectory() as tmp:
        hubs = _hubs(tmp)
        sent = []
        real = hubs.eventhub.publish_event

        def _spy(*a, **kw):
            sent.append(kw.get("event_type"))
            return real(*a, **kw)
        hubs.eventhub.publish_event = _spy
        RK.start_kickoff(hubs=hubs, milestone_index=1, requirements=["M1"],
                         attendees=ATTENDEES, broadcast=False)
        assert "kickoff_request" not in sent
        RK.start_kickoff(hubs=hubs, milestone_index=1, requirements=["M1"], attendees=ATTENDEES)
        assert "kickoff_request" in sent


# ── #1202mv: the orchestrator wiring ───────────────────────────────────────────────────────

def _orch_src():
    return ORCH.read_text(encoding="utf-8")


def test_the_orchestrator_opens_a_settled_milestone_without_broadcasting():
    tree = ast.parse(_orch_src())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "attr", None) == "start_kickoff"]
    assert calls, "start_kickoff is no longer called"
    for c in calls:
        kw = {k.arg: k.value for k in c.keywords}
        assert "broadcast" in kw, "a start_kickoff call ignores the settled-meeting check"


def test_the_normal_meeting_is_the_fallback_when_the_carry_does_not_finalize():
    """Order at the call site: the carry and reconcile come first; the driver runs only when
    they produced no finalized receipt; a failed carry re-broadcasts before driving."""
    src = _orch_src()
    carry = src.index("carry_settled_sections_1202mv(")
    finalize = src.index('"resume_settled")')
    rebroadcast = src.index("rebroadcast_kickoff_request(", carry)
    guard = src.index("if kickoff_receipt is None:", carry)
    drive = src.index("self._drive_kickoff_to_completion(", guard)
    assert carry < finalize < rebroadcast < guard < drive


def test_a_meeting_closed_without_a_contract_is_not_settled():
    """A kickoff that closed without producing a contract (a failed or abandoned meeting) is
    not something a resume may finalize from."""
    with tempfile.TemporaryDirectory() as tmp:
        hubs = _hubs(tmp)
        h = _kickoff(hubs)
        hubs.workhub.close_meeting(h["meeting_id"], produced_artifacts=["task_tree"],
                                   agent="orchestrator")
        assert hubs.workhub.stores.documents.value()[h["meeting_id"]]["status"] == "closed"
        assert RK.settled_kickoff_meeting_1202mv(hubs, 1) is None


# ── #1202na: the schema the lanes corrected survives a resumed finalize ────────────────────

def test_a_resumed_finalize_keeps_the_lanes_corrected_table_schema():
    """tiktok-r125: the resumed M2 finalize wrote the kickoff draft's `user.id` reference back
    over the lane's `users(id)`; the schema SQL then broke Postgres."""
    with tempfile.TemporaryDirectory() as tmp:
        hubs = _hubs(tmp)
        _finalize(hubs, _kickoff(hubs))
        corrected = {"columns": [{"name": "id", "type": "integer primary key"},
                                 {"name": "lane_fixed_column", "type": "text"}]}
        hubs.schema_hub.register_table(name="posts", schema=corrected, provider="backend",
                                       agent="backend", status="implemented")
        before = hubs.schema_hub.get_table("posts")["schema"]
        _finalize(hubs, _kickoff(hubs))
        after = hubs.schema_hub.get_table("posts")
        assert after["schema"] == before, (before, after["schema"])
        assert after["status"] == "implemented"


def test_a_resumed_finalize_keeps_the_lanes_corrected_endpoint_schema():
    with tempfile.TemporaryDirectory() as tmp:
        hubs = _hubs(tmp)
        _finalize(hubs, _kickoff(hubs))
        hubs.registryhub.register_endpoint(method="GET", path="/api/posts",
                                           schema={"response_key": "items", "lane": "fixed"},
                                           provider="backend", agent="backend",
                                           status="implemented")
        before = hubs.registryhub.get_endpoints()["GET /api/posts"]["schema"]
        _finalize(hubs, _kickoff(hubs))
        assert hubs.registryhub.get_endpoints()["GET /api/posts"]["schema"] == before


def test_a_resumed_finalize_still_registers_what_is_missing():
    with tempfile.TemporaryDirectory() as tmp:
        hubs = _hubs(tmp)
        _finalize(hubs, _kickoff(hubs))
        hubs.registryhub._endpoints.delete("GET /api/posts")   # lost from the registry
        assert "GET /api/posts" not in hubs.registryhub.get_endpoints()
        _finalize(hubs, _kickoff(hubs))
        assert "GET /api/posts" in hubs.registryhub.get_endpoints()
