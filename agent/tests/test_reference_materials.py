"""Reference materials beyond screenshots: classification, text extraction
(md/html/pdf), spec compilation parsing, gate generation (validated against the
real user_gates schema), and the workspace gate-store merge."""

import asyncio
import json
import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent))
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.reference_materials import (  # noqa: E402
    _parse_spec,
    classify_references,
    compile_reference_spec,
    extract_text,
    gates_from_spec,
    merge_user_gates,
    spec_summary_for_requirements,
    stage_reference_docs,
)
from multi_agent.runtime.user_gates import validate_gate  # noqa: E402


class ClassifyAndExtractTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="refmat_"))

    def test_classify_mixed(self):
        files = {}
        for name in ("home.png", "spec.md", "tools.pdf", "intro.html", "notes.txt", "junk.xyz"):
            f = self.tmp / name
            f.write_bytes(b"x")
            files[name] = str(f)
        split = classify_references(list(files.values()) + [str(self.tmp / "ghost.md")])
        self.assertEqual(split["images"], [files["home.png"]])
        self.assertEqual(set(map(Path, split["docs"])),
                         {Path(files["spec.md"]), Path(files["tools.pdf"]),
                          Path(files["intro.html"]), Path(files["notes.txt"])})

    def test_extract_markdown_and_html(self):
        md = self.tmp / "a.md"
        md.write_text("# Feed\nshows posts", encoding="utf-8")
        self.assertIn("shows posts", extract_text(md))
        html = self.tmp / "a.html"
        html.write_text("<html><script>x()</script><body><h1>Boards</h1>"
                        "<p>kanban&nbsp;view</p></body></html>", encoding="utf-8")
        text = extract_text(html)
        self.assertIn("Boards", text)
        self.assertIn("kanban view", text)
        self.assertNotIn("x()", text)

    def test_extract_pdf(self):
        from pypdf import PdfWriter
        pdf = self.tmp / "doc.pdf"
        w = PdfWriter()
        w.add_blank_page(width=200, height=200)
        with open(pdf, "wb") as fh:
            w.write(fh)
        # blank page → empty text, but must not raise
        self.assertIsInstance(extract_text(pdf), str)

    def test_unreadable_is_marker_not_raise(self):
        self.assertIn("unreadable", extract_text(self.tmp / "nope.pdf"))

    def test_stage_docs(self):
        d = self.tmp / "mcp.md"
        d.write_text("tools", encoding="utf-8")
        out = self.tmp / "ws"
        staged = stage_reference_docs([str(d)], out)
        self.assertEqual(staged, ["design/references/mcp.md"])
        self.assertEqual((out / "design" / "references" / "mcp.md").read_text(), "tools")


class SpecAndGateTests(unittest.TestCase):
    SPEC = {
        "screens": [{"name": "boards", "route_hint": "/boards", "must_have": ["kanban columns"]}],
        "endpoints": [
            {"method": "GET", "path": "/api/boards", "purpose": "list"},
            {"method": "get", "path": "/api/boards", "purpose": "dup, case"},
            {"method": "POST", "path": "/api/boards", "purpose": "create"},
            {"method": "FETCH", "path": "/api/bad", "purpose": "bad method dropped"},
        ],
        "entities": [{"name": "boards", "fields": ["id", "name"]}],
        "mcp_tools": [{"name": "create_board", "purpose": "mcp"}],
        "acceptance": ["boards persist"],
    }

    def test_parse_spec_defensive(self):
        self.assertEqual(_parse_spec("no json"), {})
        spec = _parse_spec(json.dumps(self.SPEC))
        self.assertEqual(len(spec["endpoints"]), 4)

    def test_gates_validate_against_user_gates_schema(self):
        gates = gates_from_spec(self.SPEC)
        names = [g["name"] for g in gates]
        self.assertIn("ref_spec: GET /api/boards", names)
        self.assertIn("ref_spec: POST /api/boards", names)
        self.assertIn("ref_spec: mcp tool create_board", names)
        self.assertEqual(len([n for n in names if "GET /api/boards" in n]), 1)  # deduped
        self.assertNotIn("ref_spec: FETCH /api/bad", names)
        for g in gates:
            self.assertIsNone(validate_gate(g), f"gate failed schema: {g}")

    def test_merge_replaces_prior_spec_gates_keeps_user_gates(self):
        import tempfile
        ws = Path(tempfile.mkdtemp(prefix="refmat_ws_"))
        (ws / ".user_gates.json").write_text(json.dumps([
            {"type": "file_exists", "name": "user manual gate", "params": {"path": "x"}},
            {"type": "endpoint_exists", "name": "ref_spec: GET /api/old",
             "params": {"method": "GET", "path": "/api/old"}, "source": "reference_spec"},
        ]))
        n = merge_user_gates(ws, gates_from_spec(self.SPEC))
        self.assertEqual(n, 3)
        data = json.loads((ws / ".user_gates.json").read_text())
        names = [g["name"] for g in data]
        self.assertIn("user manual gate", names)
        self.assertNotIn("ref_spec: GET /api/old", names)  # stale spec gate replaced

    def test_summary_block(self):
        text = spec_summary_for_requirements(self.SPEC)
        self.assertIn("REFERENCE SPEC", text)
        self.assertIn("GET /api/boards", text)
        self.assertIn("create_board", text)
        self.assertEqual(spec_summary_for_requirements({}), "")

    def test_compile_with_fake_llm(self):
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="refmat_c_"))
        doc = tmp / "feature.md"
        doc.write_text("# Boards\nGET /api/boards lists kanban boards", encoding="utf-8")

        class FakeResp:
            content = json.dumps(SpecAndGateTests.SPEC)

        class FakeClient:
            async def chat(self, messages, **kw):
                # the doc text must actually reach the model
                blob = json.dumps([getattr(m, "content", "") for m in messages], default=str)
                assert "kanban boards" in blob
                return FakeResp()

        class FakeLLM:
            _client = FakeClient()

        spec = asyncio.run(compile_reference_spec(FakeLLM(), [], [str(doc)], "build boards app"))
        self.assertEqual(spec["screens"][0]["name"], "boards")

    def test_compile_nothing_returns_empty(self):
        spec = asyncio.run(compile_reference_spec(object(), [], [], ""))
        self.assertEqual(spec, {})


if __name__ == "__main__":
    unittest.main()


class MilestoneSliceCarriesSpecTests(unittest.TestCase):
    def test_orchestrator_appends_spec_summary_to_milestone_slice(self):
        """Explicit-milestone slices replace raw_req — they must re-append the
        compiled spec block (found live 2026-06-10: M1 kickoff lost the
        binding endpoint/MCP lists)."""
        src = Path(THIS_DIR.parent / "env_generator" / "llm_generator" /
                   "multi_agent" / "orchestrator.py").read_text()
        self.assertIn("_reference_spec_summary", src)
        i = src.index('_milestone.get("description_slice")')
        window = src[i:i + 700]
        self.assertIn("_spec_block", window)
        self.assertIn("_milestone_req = _milestone_req + _spec_block", window)


class SectionSubstanceTests(unittest.TestCase):
    def test_empty_shell_is_not_authored(self):
        from multi_agent.agents.runtime.messaging import _section_has_substance
        empty_shell = {"feature_inventory": None, "reference_image_manifest": None,
                       "user_flows": [], "auth": None, "ui_pages": [], "done_def": [],
                       "screens": []}
        self.assertFalse(_section_has_substance(empty_shell, "frontend"))
        self.assertFalse(_section_has_substance({"deferred": True, "ui_pages": [{"id": "x"}]}, "frontend"))
        self.assertTrue(_section_has_substance({"ui_pages": [{"id": "feed"}]}, "frontend"))
        self.assertFalse(_section_has_substance({"endpoints": []}, "backend"))
        self.assertTrue(_section_has_substance({"endpoints": [{"method": "GET", "path": "/api/x"}]}, "backend"))
        self.assertTrue(_section_has_substance({"data_model": {"tables": [{"name": "t"}]}}, "backend"))
        self.assertFalse(_section_has_substance({"predicates": []}, "verifier"))
        self.assertFalse(_section_has_substance(None, "frontend"))


class DecisionFileAuthoringTests(unittest.TestCase):
    """File-first kickoff authoring: write the big section JSON with the write
    tool, then a SMALL add_meeting_decision(decision_file=...) call — sidesteps
    gemini's malformed-long-nested-args failure while keeping authorship with
    the agent."""

    def _setup(self):
        import tempfile
        from multi_agent.runtime.hub_registry import HubRegistry
        tmp = Path(tempfile.mkdtemp(prefix="dfa_"))
        reg = HubRegistry(tmp)
        meeting = reg.workhub.create_meeting(
            agenda="M1 kickoff sections", attendees=["frontend"],
            milestone_index=1, agent="orchestrator")
        meeting_id = meeting.get("id") or meeting.get("page_id")
        from tools.hub_tools import WorkhubAddMeetingDecisionTool
        tool = WorkhubAddMeetingDecisionTool(agent_id="frontend", hub_workspace=reg)
        return tmp, reg, meeting_id, tool

    def test_decision_file_from_worktree(self):
        tmp, reg, meeting_id, tool = self._setup()
        wt = tmp / "worktrees" / "frontend" / "design"
        wt.mkdir(parents=True)
        payload = {"section": "frontend",
                   "content": {"ui_pages": [{"id": "feed", "route": "/feed"}]}}
        (wt / "kickoff_frontend_section.json").write_text(json.dumps(payload))
        res = asyncio.run(tool._run(
            meeting_id=meeting_id,
            decision_file="design/kickoff_frontend_section.json"))
        self.assertTrue(res.success, getattr(res, "error_message", ""))
        page = reg.workhub.get_page(meeting_id)
        decs = (page.get("metadata") or {}).get("decisions") or []
        self.assertTrue(any(
            (d.get("content") or {}).get("content", {}).get("ui_pages")
            or (d.get("content") or {}).get("ui_pages")
            or (d.get("decision") or {}).get("content", {}).get("ui_pages")
            for d in decs) or decs, f"no decision landed: {decs}")

    def test_missing_file_fails_helpfully(self):
        tmp, reg, meeting_id, tool = self._setup()
        res = asyncio.run(tool._run(meeting_id=meeting_id, decision_file="design/nope.json"))
        self.assertFalse(res.success)
        self.assertIn("not found", res.error_message)

    def test_neither_param_fails(self):
        tmp, reg, meeting_id, tool = self._setup()
        res = asyncio.run(tool._run(meeting_id=meeting_id))
        self.assertFalse(res.success)
        self.assertIn("decision_file", res.error_message)


class KickoffCorrectionTests(unittest.TestCase):
    def test_correction_prompt_teaches_author_in_parts(self):
        from multi_agent.agents.runtime.messaging import _kickoff_correction_prompt
        text = _kickoff_correction_prompt("frontend", "page_abc", 2)
        self.assertIn("TOO LONG", text)
        self.assertIn("MERGES", text)
        self.assertIn("SMALL pieces", text)
        self.assertIn("meeting_id='page_abc'", text)
        self.assertIn("milestone_index=2", text)


class FlatDecisionShapeTests(unittest.TestCase):
    """File-first authoring lands FLAT decisions ({"section": ..., fields...});
    both the substance check and the synthesis drafts must accept them
    (live 2026-06-10: a real, good frontend section was read as empty)."""

    FLAT = {"section": "frontend", "recorded_by": "frontend",
            "ui_pages": [{"id": "page_login", "route": "/login"}],
            "user_flows": [{"id": "flow_auth"}]}
    WRAPPED = {"section": "frontend", "recorded_by": "frontend",
               "content": {"ui_pages": [{"id": "feed"}]}}

    def test_decision_substance_both_shapes(self):
        from multi_agent.agents.runtime.messaging import _decision_has_substance
        self.assertTrue(_decision_has_substance(self.FLAT, "frontend"))
        self.assertTrue(_decision_has_substance(self.WRAPPED, "frontend"))
        self.assertFalse(_decision_has_substance(
            {"section": "frontend", "ui_pages": []}, "frontend"))

    def test_collect_drafts_both_shapes(self):
        from multi_agent.runtime.kickoff.run_kickoff import _collect_drafts
        drafts = _collect_drafts([self.FLAT])
        self.assertEqual(drafts["frontend"]["ui_pages"][0]["id"], "page_login")
        self.assertNotIn("recorded_by", drafts["frontend"])
        drafts = _collect_drafts([self.WRAPPED])
        self.assertEqual(drafts["frontend"]["ui_pages"][0]["id"], "feed")


class NullSkeletonTests(unittest.TestCase):
    def test_null_placeholder_pages_are_not_substance(self):
        """gemini round-8 live: ui_pages=[null]*6 passed a len() check."""
        from multi_agent.agents.runtime.messaging import _section_has_substance
        self.assertFalse(_section_has_substance({"ui_pages": [None] * 6}, "frontend"))
        self.assertFalse(_section_has_substance({"ui_pages": [{}, None]}, "frontend"))
        self.assertTrue(_section_has_substance({"ui_pages": [None, {"id": "feed"}]}, "frontend"))
        self.assertFalse(_section_has_substance({"endpoints": [None, None]}, "backend"))
        self.assertFalse(_section_has_substance({"predicates": [None]}, "verifier"))


class PredicateGateTests(unittest.TestCase):
    """Verifier predicates become deliverability gates (user direction:
    verifier's tests matter — stop quietly downgrading them)."""

    def test_predicate_gate_validates(self):
        from multi_agent.runtime.user_gates import validate_gate
        g = {"type": "predicate", "name": "verifier: flow_auth",
             "params": {"description": "User can register and log in"}}
        self.assertIsNone(validate_gate(g))

    def test_predicate_eval_requires_passing_run(self):
        import tempfile
        from multi_agent.runtime.user_gates import evaluate_gate
        from multi_agent.runtime.hub_registry import HubRegistry
        tmp = Path(tempfile.mkdtemp(prefix="pg_"))
        reg = HubRegistry(tmp)
        g = {"type": "predicate", "name": "verifier: p1",
             "params": {"description": "feed renders posts from GET /api/feed"}}
        res = evaluate_gate(g, reg, tmp)
        self.assertFalse(res["passed"])
        self.assertIn("no successful validation run", res["message"])

    def test_finalize_merge_helper_replaces_source(self):
        import tempfile
        from multi_agent.runtime.kickoff.run_kickoff import _merge_predicate_gates
        tmp = Path(tempfile.mkdtemp(prefix="pg_"))
        (tmp / ".user_gates.json").write_text(json.dumps([
            {"type": "endpoint_exists", "name": "ref_spec: GET /api/x",
             "params": {"method": "GET", "path": "/api/x"}, "source": "reference_spec"},
            {"type": "predicate", "name": "verifier: stale",
             "params": {"description": "old"}, "source": "verifier_predicates"},
        ]))
        n = _merge_predicate_gates(tmp, [
            {"type": "predicate", "name": "verifier: fresh",
             "params": {"description": "new"}, "source": "verifier_predicates"}])
        self.assertEqual(n, 1)
        names = [g["name"] for g in json.loads((tmp / ".user_gates.json").read_text())]
        self.assertIn("ref_spec: GET /api/x", names)
        self.assertIn("verifier: fresh", names)
        self.assertNotIn("verifier: stale", names)


class DeadEndpointDefaultTests(unittest.TestCase):
    def test_mcp_only_endpoint_does_not_fail_kickoff(self):
        """An endpoint with no UI consumer (MCP tool surface) must not be an
        error-level kickoff finding by default."""
        from multi_agent.runtime.kickoff.cross_check_suite import api_vs_frontend
        res = api_vs_frontend(
            [{"method": "GET", "path": "/api/users/{username}/insights"}],
            [],
        )
        self.assertEqual(res.get("status"), "pass")


class CancelAuthorizationTests(unittest.TestCase):
    """Only a task's creator or the orchestrator may cancel it — a lane that
    can't do a task uses fail_task. (Live: backend bulk-cancelled the entire
    orchestrator-dispatched impl.* plan as 'kickoff phase only'.)"""

    def _reg(self):
        import tempfile
        from multi_agent.runtime.hub_registry import HubRegistry
        return HubRegistry(Path(tempfile.mkdtemp(prefix="ca_")))

    def test_assignee_cannot_cancel_orchestrator_plan_task(self):
        reg = self._reg()
        t = reg.workhub.create_task(title="impl.endpoint.get._api_users",
                                    description="", assignee="backend",
                                    agent="orchestrator")
        res = reg.workhub.cancel_task(t["id"], agent="backend", reason="kickoff only")
        self.assertIn("error", res)
        self.assertIn("send_message", res["error"])
        self.assertEqual(reg.workhub.get_task(t["id"])["status"], "pending")

    def test_creator_and_orchestrator_can_cancel(self):
        reg = self._reg()
        t1 = reg.workhub.create_task(title="x", description="", assignee="backend",
                                     agent="backend")
        self.assertEqual(reg.workhub.cancel_task(t1["id"], agent="backend", reason="plan changed")["status"], "cancelled")
        t2 = reg.workhub.create_task(title="y", description="", assignee="backend",
                                     agent="orchestrator")
        self.assertEqual(reg.workhub.cancel_task(t2["id"], agent="orchestrator")["status"], "cancelled")


class TaskCompletionDisciplineTests(unittest.TestCase):
    """User policy: agents MUST complete their tasks; blocked → contact the
    creator, who is the only one (plus orchestrator/framework) that terminates."""

    def _reg(self):
        import tempfile
        from multi_agent.runtime.hub_registry import HubRegistry
        return HubRegistry(Path(tempfile.mkdtemp(prefix="tcd_")))

    def test_claimer_cannot_unilaterally_fail(self):
        reg = self._reg()
        t = reg.workhub.create_task(title="impl.x", description="", assignee="backend",
                                    agent="orchestrator")
        reg.workhub.claim_task(t["id"], "backend")
        res = reg.workhub.fail_task(t["id"], agent="backend", reason="too hard")
        self.assertIn("error", res)
        self.assertIn("send_message", res["error"])
        self.assertNotEqual(reg.workhub.get_task(t["id"])["status"], "failed")

    def test_creator_orchestrator_and_framework_can_fail(self):
        reg = self._reg()
        t = reg.workhub.create_task(title="x", description="", assignee="backend",
                                    agent="orchestrator")
        self.assertEqual(reg.workhub.fail_task(t["id"], agent="orchestrator",
                                               reason="obsolete")["status"], "failed")
        t2 = reg.workhub.create_task(title="y", description="", assignee="backend",
                                     agent="frontend")
        self.assertEqual(reg.workhub.fail_task(t2["id"], agent="frontend",
                                               reason="dup")["status"], "failed")
        t3 = reg.workhub.create_task(title="z", description="", assignee="backend",
                                     agent="orchestrator")
        reg.workhub.claim_task(t3["id"], "backend")
        self.assertEqual(reg.workhub.fail_task(t3["id"], agent="backend", reason="idle",
                                               force=True)["status"], "failed")


class AgentNotesTests(unittest.TestCase):
    def test_agent_notes_written_with_conventions(self):
        import tempfile
        from multi_agent.runtime.reference_materials import write_agent_notes
        tmp = Path(tempfile.mkdtemp(prefix="an_"))
        path = write_agent_notes(tmp)
        text = Path(path).read_text()
        for token in ('{"items": [...], "total": N}', "Bearer", "decision_file",
                      "reference_spec.json", "send_message"):
            self.assertIn(token, text)


class ObservationMaskingTests(unittest.TestCase):
    def _msgs(self, n_tools, size=5000):
        from utils.llm import Message
        msgs = [Message.system("sys")]
        for i in range(n_tools):
            msgs.append(Message.assistant(f"call {i}"))
            msgs.append(Message.tool("X" * size, f"call_{i}"))
        return msgs

    def test_old_tool_outputs_masked_recent_kept(self):
        from multi_agent.agents.runtime.step_runner import _mask_old_observations
        msgs = self._msgs(12)
        out = _mask_old_observations(msgs, keep_last=8)
        tool_msgs = [m for m in out if m.role == "tool"]
        masked = [m for m in tool_msgs if m.content.endswith("[masked]")]
        self.assertEqual(len(masked), 4)
        self.assertTrue(all(len(m.content) < 600 for m in masked))
        # 最近 8 条保持全文
        self.assertTrue(all(len(m.content) == 5000 for m in tool_msgs[-8:]))
        # 幂等
        out2 = _mask_old_observations(out, keep_last=8)
        self.assertEqual(sum(1 for m in out2 if m.role == "tool" and m.content.endswith("[masked]")), 4)

    def test_small_outputs_untouched_and_flag_off(self):
        import os
        from multi_agent.agents.runtime.step_runner import _mask_old_observations
        msgs = self._msgs(12, size=100)
        out = _mask_old_observations(msgs, keep_last=8)
        self.assertTrue(all(len(m.content) == 100 for m in out if m.role == "tool"))
        os.environ["ENVGEN_OBS_MASK"] = "0"
        try:
            msgs2 = self._msgs(12)
            out2 = _mask_old_observations(msgs2, keep_last=8)
            self.assertTrue(all(len(m.content) == 5000 for m in out2 if m.role == "tool"))
        finally:
            os.environ.pop("ENVGEN_OBS_MASK")


class FrontendDockerfileTests(unittest.TestCase):
    def test_npm_install_tolerates_peer_conflicts(self):
        from multi_agent.runtime.frontend_scaffold import _BASELINE_DOCKERFILE
        self.assertIn("npm install --legacy-peer-deps", _BASELINE_DOCKERFILE)


class ApiHelperOwnershipTests(unittest.TestCase):
    """apiGet/apiPost belong to the page projector — the export-drift repairer
    must never stub them (live 1.2.0: every projected page threw
    'apiGet not implemented (auto-stub)')."""

    def _tree(self, tmp):
        fe = tmp / "frontend"
        (fe / "src" / "services").mkdir(parents=True)
        (fe / "src" / "pages").mkdir(parents=True)
        (fe / "src" / "services" / "api.js").write_text(
            "async function request(p, o) { return fetch(p, o); }\n"
            "export { request };\n", encoding="utf-8")
        (fe / "src" / "pages" / "FeedPage.jsx").write_text(
            "import { apiGet } from '../services/api';\n"
            "export default function FeedPage() { return null; }\n", encoding="utf-8")
        return fe

    def test_repairer_installs_real_helpers_not_stubs(self):
        import tempfile
        from multi_agent.runtime.frontend_scaffold import repair_frontend_api_exports
        fe = self._tree(Path(tempfile.mkdtemp(prefix="aho_")))
        repair_frontend_api_exports(fe)
        api = (fe / "src" / "services" / "api.js").read_text()
        self.assertNotIn("auto-stub", api)
        self.assertIn("export async function apiGet", api)

    def test_ensure_helpers_heals_existing_stub(self):
        import tempfile
        from multi_agent.runtime.frontend_page_projector import _ensure_api_helpers
        fe = self._tree(Path(tempfile.mkdtemp(prefix="aho_")))
        api = fe / "src" / "services" / "api.js"
        api.write_text(api.read_text() +
            "\n// FIX #37: auto-reconciled api.js exports (component import/export drift).\n"
            "export const apiGet = async (...args) => { throw new Error('apiGet not implemented (auto-stub)'); };\n"
            "export const apiPost = async (...args) => { throw new Error('apiPost not implemented (auto-stub)'); };\n",
            encoding="utf-8")
        self.assertTrue(_ensure_api_helpers(api))
        text = api.read_text()
        self.assertNotIn("auto-stub", text)
        self.assertIn("export async function apiGet", text)


class EmptyDecisionRejectionTests(unittest.TestCase):
    """Empty section drafts are rejected AT THE TOOL — the model gets the
    file-first guidance in the same turn instead of wasting it."""

    def _tool(self):
        import tempfile
        from multi_agent.runtime.hub_registry import HubRegistry
        from tools.hub_tools import WorkhubAddMeetingDecisionTool
        tmp = Path(tempfile.mkdtemp(prefix="edr_"))
        reg = HubRegistry(tmp)
        m = reg.workhub.create_meeting(agenda="k", attendees=["backend"],
                                       milestone_index=1, agent="orchestrator")
        return WorkhubAddMeetingDecisionTool(agent_id="backend", hub_workspace=reg), m["id"]

    def test_empty_backend_shell_rejected_with_guidance(self):
        tool, mid = self._tool()
        res = asyncio.run(tool._run(meeting_id=mid, decision={
            "section": "backend", "content": {"endpoints": [], "data_model": None}}))
        self.assertFalse(res.success)
        self.assertIn("decision_file", res.error_message)
        self.assertIn("kickoff_backend_section.json", res.error_message)

    def test_null_skeleton_rejected(self):
        tool, mid = self._tool()
        res = asyncio.run(tool._run(meeting_id=mid, decision={
            "section": "frontend", "ui_pages": [None, None, None]}))
        self.assertFalse(res.success)

    def test_substantive_and_nonsection_pass(self):
        tool, mid = self._tool()
        ok = asyncio.run(tool._run(meeting_id=mid, decision={
            "section": "backend",
            "content": {"endpoints": [{"method": "GET", "path": "/api/x"}]}}))
        self.assertTrue(ok.success, getattr(ok, "error_message", ""))
        note = asyncio.run(tool._run(meeting_id=mid, decision={
            "section": "facilitator_note", "content": {"action": "synthesize"}}))
        self.assertTrue(note.success)
        stub = asyncio.run(tool._run(meeting_id=mid, decision={
            "section": "verifier", "content": {"deferred": True, "source": "auto_backup"}}))
        self.assertTrue(stub.success)


class ChunkedSectionMergeTests(unittest.TestCase):
    """A section may arrive in several SMALL decisions; the drafts collector
    MERGES them (round-16 post-mortem: gemini cannot reliably emit one giant
    payload — small calls succeed)."""

    def test_lists_concatenate_and_dedupe(self):
        from multi_agent.runtime.kickoff.run_kickoff import _collect_drafts
        decisions = [
            {"section": "frontend", "content": {"ui_pages": [{"id": "feed", "route": "/feed"}]}},
            {"section": "frontend", "content": {"ui_pages": [{"id": "profile"}], "auth": {"model": "jwt"}}},
            {"section": "frontend", "content": {"ui_pages": [{"id": "feed", "route": "/feed"}],
                                                "user_flows": [{"id": "f1"}]}},
        ]
        d = _collect_drafts(decisions)["frontend"]
        self.assertEqual([p["id"] for p in d["ui_pages"]], ["feed", "profile"])
        self.assertEqual(d["auth"], {"model": "jwt"})
        self.assertEqual(d["user_flows"], [{"id": "f1"}])

    def test_later_nonempty_scalar_wins_empty_does_not_clobber(self):
        from multi_agent.runtime.kickoff.run_kickoff import _collect_drafts
        decisions = [
            {"section": "backend", "content": {"endpoints": [{"method": "GET", "path": "/api/a"}],
                                               "auth": {"model": "jwt"}}},
            {"section": "backend", "content": {"endpoints": [{"method": "POST", "path": "/api/a"}],
                                               "auth": None}},
        ]
        d = _collect_drafts(decisions)["backend"]
        self.assertEqual(len(d["endpoints"]), 2)
        self.assertEqual(d["auth"], {"model": "jwt"})


class DeclareToolsTests(unittest.TestCase):
    """Per-item kickoff declaration tools: flat typed params per call, the
    meeting merges items into the section (chunked authoring as a CAPABILITY)."""

    def _setup(self):
        import tempfile
        from multi_agent.runtime.hub_registry import HubRegistry
        tmp = Path(tempfile.mkdtemp(prefix="dt_"))
        reg = HubRegistry(tmp)
        m = reg.workhub.create_meeting(agenda="k", attendees=["frontend", "backend", "verifier"],
                                       milestone_index=1, agent="orchestrator")
        return reg, m["id"]

    def test_pages_flows_predicates_endpoints_tables_merge(self):
        from tools.hub_tools import (
            KickoffDeclareUiPageTool, KickoffDeclareUserFlowTool,
            KickoffDeclarePredicateTool, KickoffDeclareEndpointTool,
            KickoffDeclareTableTool)
        from multi_agent.runtime.kickoff.run_kickoff import _collect_drafts
        reg, mid = self._setup()
        fe_page = KickoffDeclareUiPageTool(agent_id="frontend", hub_workspace=reg)
        fe_flow = KickoffDeclareUserFlowTool(agent_id="frontend", hub_workspace=reg)
        ve_pred = KickoffDeclarePredicateTool(agent_id="verifier", hub_workspace=reg)
        be_ep = KickoffDeclareEndpointTool(agent_id="backend", hub_workspace=reg)
        be_tb = KickoffDeclareTableTool(agent_id="backend", hub_workspace=reg)

        for pid, route in (("home_feed", "/feed"), ("profile", "/profile")):
            r = asyncio.run(fe_page._run(meeting_id=mid, id=pid, route=route,
                                         purpose="p", components=["A", "B"]))
            self.assertTrue(r.success, r.error_message)
        asyncio.run(fe_flow._run(meeting_id=mid, id="flow_auth", description="login",
                                 steps=["a", "b"]))
        asyncio.run(ve_pred._run(meeting_id=mid, id="p1", description="feed works",
                                 kind="api_smoke"))
        asyncio.run(be_ep._run(meeting_id=mid, method="get", path="/api/feed",
                               response_key="items"))
        asyncio.run(be_ep._run(meeting_id=mid, method="POST", path="/api/posts"))
        asyncio.run(be_tb._run(meeting_id=mid, name="posts",
                               columns=["id:text:pk", "caption:text",
                                        "author_id:text:fk=users.id"]))
        asyncio.run(be_tb._run(meeting_id=mid, name="users",
                               columns=["id:text:pk", "email:text:unique"]))

        page = reg.workhub.get_page(mid)
        drafts = _collect_drafts((page.get("metadata") or {}).get("decisions") or [])
        fe = drafts["frontend"]
        self.assertEqual([p["id"] for p in fe["ui_pages"]], ["home_feed", "profile"])
        self.assertEqual(fe["user_flows"][0]["id"], "flow_auth")
        self.assertEqual(drafts["verifier"]["predicates"][0]["id"], "p1")
        be = drafts["backend"]
        self.assertEqual([e["method"] for e in be["endpoints"]], ["GET", "POST"])
        tables = be["data_model"]["tables"]
        self.assertEqual([t["name"] for t in tables], ["posts", "users"])
        self.assertEqual(tables[0]["columns"][0], {"name": "id", "type": "text", "primary_key": True})
        self.assertEqual(tables[0]["columns"][2]["references"], "users.id")
        # substance check passes on the merged result
        from multi_agent.runtime.kickoff.section_substance import section_has_substance
        self.assertTrue(section_has_substance(fe, "frontend"))
        self.assertTrue(section_has_substance(be, "backend"))


class PredicateFloorTests(unittest.TestCase):
    def test_empty_predicates_get_default_floor(self):
        """A milestone with no verifier predicates AND no user_flows must not
        deadlock synthesis (round 24 M4: validator hard-requires non-empty)."""
        from multi_agent.runtime.kickoff.run_kickoff import _build_roadmap
        roadmap = _build_roadmap(
            {"backend": {"endpoints": [{"method": "GET", "path": "/api/x"}],
                         "data_model": {"tables": [{"name": "t", "columns": [
                             {"name": "id", "type": "text"}]}]}},
             "frontend": {"ui_pages": [{"id": "p", "route": "/p"}]},
             "verifier": {}},
            milestone_index=4, description="slice")
        preds = roadmap.get("acceptance_predicates") or roadmap.get("predicates")
        self.assertTrue(preds, f"roadmap keys: {list(roadmap)}")
        self.assertEqual(preds[0]["source"], "auto_default")


class PredicateNormalizationTests(unittest.TestCase):
    def test_all_authoring_shapes_coerced_to_validator_canon(self):
        from multi_agent.runtime.kickoff.run_kickoff import _build_roadmap
        roadmap = _build_roadmap(
            {"backend": {"endpoints": [{"method": "GET", "path": "/api/x"}],
                         "data_model": {"tables": [{"name": "t", "columns": [
                             {"name": "id", "type": "text"}]}]}},
             "frontend": {"ui_pages": [{"id": "p", "route": "/p"}],
                          "user_flows": [{"id": "flow_main"}]},
             "verifier": {"predicates": [
                 {"id": "p1", "kind": "api_smoke", "flow_id": "flow_main"},
                 {"description": "no id no kind"},
                 {"id": "p3", "kind": "weird_kind"}]}},
            milestone_index=2, description="slice")
        preds = roadmap.get("acceptance_predicates") or roadmap.get("predicates")
        self.assertEqual(len(preds), 3)
        for q in preds:
            self.assertTrue(q["id"])
            self.assertTrue(isinstance(q["flow"], str) and q["flow"])
            self.assertIn(q["form"]["kind"],
                          {"api_smoke", "ui_flow", "sql_check", "predicate_dsl"})
        self.assertEqual(preds[0]["flow"], "flow_main")
        self.assertEqual(preds[2]["form"]["kind"], "api_smoke")


class GateParamStyleTests(unittest.TestCase):
    def test_colon_and_brace_param_styles_match(self):
        import tempfile
        from multi_agent.runtime.user_gates import evaluate_gate
        from multi_agent.runtime.hub_registry import HubRegistry
        tmp = Path(tempfile.mkdtemp(prefix="gps_"))
        reg = HubRegistry(tmp)
        reg.registryhub.register_endpoint(
            "GET", "/api/users/{username}", schema={},
            provider="backend", agent="backend", status="implemented")
        g = {"type": "endpoint_exists", "name": "x",
             "params": {"method": "GET", "path": "/api/users/:username"}}
        res = evaluate_gate(g, reg, tmp)
        self.assertTrue(res["passed"], res)


class MilestonePlanningTests(unittest.TestCase):
    """User-provided milestones win; absent → the run's model plans (small app
    = 1 milestone, large splits, ≤6); planner failure → single fallback."""

    def _fake_llm(self, payload):
        class R: content = payload
        class C:
            async def chat(self, msgs, **kw): return R()
        class L: _client = C()
        return L()

    def test_planner_parses_and_caps(self):
        from multi_agent.runtime.reference_materials import plan_milestones
        plan = [{"name": f"M{i+1}-x", "version": f"1.{i}.0",
                 "description_slice": f"slice {i}"} for i in range(8)]
        out = asyncio.run(plan_milestones(
            self._fake_llm(json.dumps(plan)), "req", {"endpoints": []}))
        self.assertEqual(len(out), 6)  # capped
        self.assertEqual(out[0]["version"], "1.0.0")

    def test_single_milestone_plan_ok(self):
        from multi_agent.runtime.reference_materials import plan_milestones
        out = asyncio.run(plan_milestones(self._fake_llm(json.dumps(
            [{"name": "M1-all", "version": "1.0.0", "description_slice": "everything"}])),
            "tiny app", {}))
        self.assertEqual(len(out), 1)

    def test_garbage_returns_none(self):
        from multi_agent.runtime.reference_materials import plan_milestones
        self.assertIsNone(asyncio.run(plan_milestones(
            self._fake_llm("not json"), "req", {})))
        self.assertIsNone(asyncio.run(plan_milestones(
            self._fake_llm(json.dumps([{"name": "x", "version": "1.0.0",
                                        "description_slice": ""}])), "req", {})))

    def test_orchestrator_honors_explicit_and_plans_otherwise(self):
        src = Path(THIS_DIR.parent / "env_generator" / "llm_generator" /
                   "multi_agent" / "orchestrator.py").read_text()
        self.assertIn("if not _milestones_explicit:", src)
        self.assertIn("plan_milestones", src)
        self.assertIn("MILESTONE PLAN (agent-decided)", src)


class RoadmapMeetingArtifactTests(unittest.TestCase):
    def test_orchestrator_records_roadmap_on_first_meeting(self):
        src = Path(THIS_DIR.parent / "env_generator" / "llm_generator" /
                   "multi_agent" / "orchestrator.py").read_text()
        i = src.index('"section": "roadmap"')
        window = src[i - 2000:i + 1200]
        self.assertIn('"kind": "milestone_plan"', window)
        self.assertIn('"user_provided"', window)
        self.assertIn('"agent_planned"', window)
        self.assertIn("if _m_idx == 1:", window)


class McpSpecAliasTests(unittest.TestCase):
    """MCP tools emit the SPEC'S semantic names when the compiled spec binds
    them to endpoints — the mcp_tool_exists gates then pass by construction."""

    SPEC = {"mcp_tools": [
        {"name": "get_profile_info", "endpoint": "GET /api/users/me"},
        {"name": "publish_media", "endpoint": "POST /api/posts"},
        {"name": "colon_style", "endpoint": "GET /api/users/:username"},
        {"name": "no_endpoint"}]}

    def test_alias_table(self):
        from multi_agent.runtime.mcp_scaffold import spec_tool_aliases
        a = spec_tool_aliases(self.SPEC)
        self.assertEqual(a["GET /api/users/me"], "get_profile_info")
        self.assertEqual(a["GET /api/users/{username}"], "colon_style")
        self.assertEqual(len(a), 3)

    def test_records_and_server_use_alias(self):
        from multi_agent.runtime.mcp_scaffold import (
            mcp_tool_records, render_mcp_server, spec_tool_aliases)
        eps = {"GET /api/users/me": {"method": "GET", "path": "/api/users/me",
                                     "kind": "business", "schema": {}},
               "POST /api/posts": {"method": "POST", "path": "/api/posts",
                                   "kind": "business", "schema": {}}}
        aliases = spec_tool_aliases(self.SPEC)
        recs = mcp_tool_records(eps, tool_aliases=aliases)
        names = {r["tool_name"] for r in recs}
        self.assertIn("get_profile_info", names)
        self.assertIn("publish_media", names)
        server = render_mcp_server(eps, tool_aliases=aliases)
        self.assertIn("def get_profile_info", server)
        self.assertIn("def publish_media", server)


class ClaimerCancelClosedTests(unittest.TestCase):
    def test_claimer_cannot_cancel_others_task(self):
        import tempfile
        from multi_agent.runtime.hub_registry import HubRegistry
        reg = HubRegistry(Path(tempfile.mkdtemp(prefix="ccc_")))
        t = reg.workhub.create_task(title="impl.x", description="",
                                    assignee="frontend", agent="orchestrator")
        reg.workhub.claim_task(t["id"], "frontend")
        res = reg.workhub.cancel_task(t["id"], agent="frontend", reason="missing tools")
        self.assertIn("error", res)
        self.assertNotEqual(reg.workhub.get_task(t["id"])["status"], "cancelled")


class CancelVisibilityTests(unittest.TestCase):
    """User policy 2026-06-11: cancellation requires creator authority AND
    the orchestrator must be informed (subscription + mandatory reason)."""

    def test_orchestrator_subscribed_to_task_cancelled(self):
        from multi_agent.runtime.agent_subscriptions import DEFAULT_SUBSCRIPTIONS
        self.assertIn(("workhub", "task_cancelled", "high"),
                      DEFAULT_SUBSCRIPTIONS["orchestrator"])

    def test_creator_cancel_requires_reason(self):
        import tempfile
        from multi_agent.runtime.hub_registry import HubRegistry
        reg = HubRegistry(Path(tempfile.mkdtemp(prefix="cvr_")))
        t = reg.workhub.create_task(title="impl.x", description="",
                                    assignee="frontend", agent="backend")
        res = reg.workhub.cancel_task(t["id"], agent="backend", reason="")
        self.assertIn("error", res)
        self.assertIn("reason", res["error"])
        res = reg.workhub.cancel_task(t["id"], agent="backend",
                                      reason="superseded by impl.y")
        self.assertEqual(res["status"], "cancelled")


class SkeletonMarksTablesImplementedTests(unittest.TestCase):
    """Mechanism #43 (round 32: 17-task cancel cascade): once the skeleton
    materializes the contract tables, their RegistryHub status flips to
    implemented, which auto-completes impl.table.* tasks and unblocks every
    depends_on-chained impl.endpoint.* task."""

    def test_orchestrator_flips_generated_tables(self):
        src = Path(__file__).resolve().parent.parent / (
            "env_generator/llm_generator/multi_agent/orchestrator.py")
        body = src.read_text()
        self.assertIn('registryhub.register_table(', body)
        self.assertIn('_tname, agent="orchestrator", status="implemented")', body)

    def test_register_table_implemented_completes_task(self):
        import tempfile
        from multi_agent.runtime.hub_registry import HubRegistry
        reg = HubRegistry(Path(tempfile.mkdtemp(prefix="smt_")))
        t = reg.workhub.create_task(title="impl.table.users", task_id="impl.table.users",
                                    description="", assignee="backend", agent="orchestrator",
                                    kind="implement_table")
        reg.workhub.claim_task(t["id"], "backend")
        reg.registryhub.register_table("users", schema={"columns": [{"name": "id"}]},
                                  agent="backend", status="defined")
        reg.registryhub.register_table("users", agent="orchestrator", status="implemented")
        self.assertEqual(reg.workhub.get_task("impl.table.users")["status"], "completed")


class UiPageLifecycleTests(unittest.TestCase):
    """Mechanism #50 (user design): the frontend mirrors the backend's
    by-construction lifecycle — declare → defined → audited implemented →
    impl.page task completes via cross-hub sync."""

    def _hubs(self):
        import tempfile
        from multi_agent.runtime.hub_registry import HubRegistry
        return HubRegistry(Path(tempfile.mkdtemp(prefix="upl_"))), Path(tempfile.mkdtemp(prefix="uplp_"))

    def test_schema_tolerance_emits_impl_page_tasks(self):
        from multi_agent.runtime.kickoff.schema_tolerance import synthesize_task_tree
        contract = {"endpoints": [], "data_model": {"tables": []},
                    "ui_pages": [{"id": "board_list", "route": "/boards",
                                  "component": "BoardListPage",
                                  "apis_used": ["GET /api/boards"]}],
                    "user_flows": []}
        tasks = synthesize_task_tree(contract)
        page_tasks = [t for t in tasks if t.get("kind") == "implement_page"]
        self.assertEqual(len(page_tasks), 1)
        self.assertEqual(page_tasks[0]["id"], "impl.page.board_list")
        self.assertEqual(page_tasks[0]["metadata"]["apis_used"], ["GET /api/boards"])

    def test_implemented_flip_completes_task(self):
        reg, _ = self._hubs()
        reg.workhub.create_task(title="impl.page.board_list", task_id="impl.page.board_list",
                                description="", assignee="frontend", agent="orchestrator",
                                kind="implement_page")
        reg.workhub.update_ui_page("board_list", {"status": "defined"}, agent="orchestrator")
        self.assertEqual(reg.workhub.get_task("impl.page.board_list")["status"], "pending")
        reg.workhub.update_ui_page("board_list", {"status": "implemented"}, agent="orchestrator")
        self.assertEqual(reg.workhub.get_task("impl.page.board_list")["status"], "completed")

    def test_audit_detects_implemented_page(self):
        import tempfile
        from multi_agent.runtime.frontend_audit import audit_ui_page, sync_ui_page_statuses
        proj = Path(tempfile.mkdtemp(prefix="upla_"))
        src = proj / "app" / "frontend" / "src"; (src / "pages").mkdir(parents=True)
        page = {"component": "BoardListPage", "route": "/boards",
                "apis_used": ["GET /api/boards"]}
        # not implemented yet
        (src / "App.jsx").write_text("<Routes></Routes>")
        ok, missing = audit_ui_page(src, page)
        self.assertFalse(ok)
        self.assertEqual(len(missing), 3)  # component + route + api all missing
        # now implement it
        (src / "pages" / "BoardListPage.jsx").write_text(
            "import { apiGet } from '../services/api';\n"
            "export default function BoardListPage() {\n"
            "  const load = () => apiGet('/api/boards');\n"
            "  return <button onClick={load}>load</button>; }\n")
        (src / "App.jsx").write_text(
            'import BoardListPage from "./pages/BoardListPage";\n'
            '<Routes><Route path="/boards" element={<BoardListPage />} /></Routes>')
        ok, missing = audit_ui_page(src, page)
        self.assertTrue(ok, missing)

    def test_sync_flips_status_and_completes(self):
        import tempfile
        from multi_agent.runtime.frontend_audit import sync_ui_page_statuses
        reg, proj = self._hubs()
        src = proj / "app" / "frontend" / "src"; (src / "pages").mkdir(parents=True)
        (src / "pages" / "CartPage.jsx").write_text(
            "import { apiGet } from '../services/api';\n"
            "export default function CartPage() { return null; }\n"
            "// calls /api/cart\n")
        (src / "App.jsx").write_text(
            '<Routes><Route path="/cart" element={<CartPage />} /></Routes>')
        reg.workhub.create_task(title="impl.page.cart", task_id="impl.page.cart",
                                description="", assignee="frontend", agent="orchestrator",
                                kind="implement_page")
        reg.workhub.update_ui_page("cart", {"status": "defined", "route": "/cart",
                                            "component": "CartPage",
                                            "apis_used": ["GET /api/cart"]},
                                   agent="orchestrator")
        res = sync_ui_page_statuses(proj, reg.workhub)
        self.assertIn("cart", res["implemented"])
        self.assertEqual(reg.workhub.get_task("impl.page.cart")["status"], "completed")


class UiComponentModelTests(unittest.TestCase):
    """Mechanism #52 (user design): pages USE components, components CALL
    APIs — component registry + page rollup."""

    def test_component_registry_roundtrip(self):
        import tempfile
        from multi_agent.runtime.hub_registry import HubRegistry
        reg = HubRegistry(Path(tempfile.mkdtemp(prefix="ucm_")))
        reg.workhub.update_ui_component("card_grid", {
            "status": "defined", "component": "CardGrid",
            "apis_used": ["GET /api/products"]}, agent="orchestrator")
        comps = reg.workhub.get_ui_components()
        self.assertIn("card_grid", comps)
        self.assertEqual(comps["card_grid"]["status"], "defined")

    def test_page_rollup_blocks_on_unimplemented_component(self):
        import tempfile
        from multi_agent.runtime.hub_registry import HubRegistry
        from multi_agent.runtime.frontend_audit import sync_ui_page_statuses
        reg = HubRegistry(Path(tempfile.mkdtemp(prefix="ucr_")))
        proj = Path(tempfile.mkdtemp(prefix="ucrp_"))
        src = proj / "app" / "frontend" / "src"; (src / "pages").mkdir(parents=True)
        # 页面自身条件全满足
        (src / "pages" / "CatalogPage.jsx").write_text(
            "import { apiGet } from '../services/api';\n"
            "export default function CatalogPage() { apiGet('/api/products'); return null; }\n")
        (src / "App.jsx").write_text(
            '<Routes><Route path="/catalog" element={<CatalogPage />} /></Routes>')
        # 组件申明了一个未实现的 API 调用
        reg.workhub.update_ui_component("filter_rail", {
            "status": "defined", "component": "FilterRail",
            "apis_used": ["GET /api/filters"]}, agent="orchestrator")
        reg.workhub.update_ui_page("catalog", {
            "status": "defined", "route": "/catalog", "component": "CatalogPage",
            "components": ["filter_rail"], "apis_used": ["GET /api/products"]},
            agent="orchestrator")
        res = sync_ui_page_statuses(proj, reg.workhub)
        self.assertNotIn("catalog", res["implemented"])
        self.assertIn("filter_rail", res.get("components_pending", {}))
        self.assertTrue(any("filter_rail" in m for m in res["pending"]["catalog"]))
        # 实现组件 → 全绿
        (src / "components").mkdir(exist_ok=True)
        (src / "components" / "FilterRail.jsx").write_text(
            "import { apiGet } from '../services/api';\n"
            "export default function FilterRail() { apiGet('/api/filters'); return null; }\n")
        res2 = sync_ui_page_statuses(proj, reg.workhub)
        self.assertIn("filter_rail", res2.get("components_implemented", []))
        self.assertIn("catalog", res2["implemented"])


class ComponentTaskTests(unittest.TestCase):
    """Mechanism #52 v2 (user decision): components DO get tasks; pages
    depend on their components' tasks — build order is structural."""

    def test_component_tasks_and_page_deps(self):
        from multi_agent.runtime.kickoff.schema_tolerance import synthesize_task_tree
        contract = {"endpoints": [], "data_model": {"tables": []},
                    "ui_components": [
                        {"id": "filter_rail", "component": "FilterRail",
                         "apis_used": ["GET /api/filters"]},
                        {"id": "result_grid", "component": "ResultGrid",
                         "apis_used": ["GET /api/items"]}],
                    "ui_pages": [{"id": "catalog", "route": "/catalog",
                                  "component": "CatalogPage",
                                  "components": ["filter_rail", "result_grid"],
                                  "apis_used": []}],
                    "user_flows": []}
        tasks = {t["id"]: t for t in synthesize_task_tree(contract)}
        self.assertIn("impl.component.filter_rail", tasks)
        self.assertIn("impl.component.result_grid", tasks)
        self.assertEqual(tasks["impl.component.filter_rail"]["kind"], "implement_component")
        self.assertEqual(sorted(tasks["impl.page.catalog"]["depends_on"]),
                         ["impl.component.filter_rail", "impl.component.result_grid"])

    def test_component_implemented_completes_task(self):
        import tempfile
        from multi_agent.runtime.hub_registry import HubRegistry
        reg = HubRegistry(Path(tempfile.mkdtemp(prefix="cct_")))
        reg.workhub.create_task(title="impl.component.filter_rail",
                                task_id="impl.component.filter_rail",
                                description="", assignee="frontend",
                                agent="orchestrator", kind="implement_component")
        reg.workhub.update_ui_component("filter_rail", {"status": "implemented"},
                                        agent="orchestrator")
        self.assertEqual(reg.workhub.get_task("impl.component.filter_rail")["status"],
                         "completed")


class CustomRoutesHookTests(unittest.TestCase):
    """Contract-centric backend (user-approved): custom_routes.py is the ONE
    lane-owned backend file; the skeleton includes it and never writes it."""

    def test_skeleton_main_includes_custom_router(self):
        from multi_agent.runtime.backend_skeleton import render_skeleton_main
        body = render_skeleton_main(
            [{"method": "GET", "path": "/api/things", "auth_required": True}],
            {"things": {"schema": {"columns": [{"name": "id"}]}}})
        self.assertIn("from custom_routes import router as _custom_router", body)
        self.assertIn("app.include_router(_custom_router)", body)
        self.assertIn("except ImportError:", body)

    def test_skeleton_never_writes_custom_routes(self):
        import tempfile
        from multi_agent.runtime.backend_skeleton import write_backend_skeleton
        tmp = Path(tempfile.mkdtemp(prefix="crh_"))
        res = write_backend_skeleton(
            tmp, [{"method": "GET", "path": "/api/things", "auth_required": True}],
            {"things": {"schema": {"columns": [{"name": "id"}]}}})
        written = [str(x) for x in (res.get("written") or [])]
        self.assertFalse(any("custom_routes" in w for w in written))
        # lane file survives a regeneration
        cr = tmp / "app" / "backend" / "custom_routes.py"
        cr.write_text("from fastapi import APIRouter\nrouter = APIRouter()\n")
        write_backend_skeleton(
            tmp, [{"method": "GET", "path": "/api/things", "auth_required": True}],
            {"things": {"schema": {"columns": [{"name": "id"}]}}})
        self.assertIn("router = APIRouter()", cr.read_text())


class RegistryHubRenameTests(unittest.TestCase):
    def test_registryhub_canonical_no_legacy_name(self):
        import tempfile
        from multi_agent.runtime.hub_registry import HubRegistry
        reg = HubRegistry(Path(tempfile.mkdtemp(prefix="rh_")))
        self.assertTrue(hasattr(reg, "registryhub"))
        self.assertFalse(hasattr(reg, "apihub"))  # full rename, no back-compat
        # stores use the new prefix
        stores = list((reg.registryhub.hub_dir).glob("registryhub_*.json"))
        self.assertTrue(stores)


class ChainAuthoringFeedbackTests(unittest.TestCase):
    """Mechanism #53: with no framework fallback chain, the feedback loop must
    actually reach the verifier — orchestrator dispatches a P0 authoring task
    once per milestone when business_chain fails for a missing chains file."""

    def test_orchestrator_dispatches_chain_task(self):
        src = Path(__file__).resolve().parent.parent / (
            "env_generator/llm_generator/multi_agent/orchestrator.py")
        body = src.read_text()
        # verb-INDEPENDENT match (chain wording moved authored→registered when
        # chains became registry-backed; the literal match silently broke #53)
        self.assertIn('"no verification chains" in str(c.get("detail")', body)
        self.assertIn("_chain_task_dispatched", body)
        self.assertIn('assignee="verifier"', body)


class UiPageStatusAuthorityTests(unittest.TestCase):
    """Mechanism #54: only the framework (orchestrator audit) may flip a
    ui_page to implemented; agent self-claims downgrade to defined."""

    def test_agent_implemented_downgraded(self):
        import tempfile
        from multi_agent.runtime.hub_registry import HubRegistry
        reg = HubRegistry(Path(tempfile.mkdtemp(prefix="upsa_")))
        reg.workhub.update_ui_page("login", {"status": "implemented"}, agent="frontend")
        self.assertEqual(reg.workhub.get_ui_pages()["login"]["status"], "defined")
        reg.workhub.update_ui_page("login", {"status": "implemented"}, agent="orchestrator")
        self.assertEqual(reg.workhub.get_ui_pages()["login"]["status"], "implemented")

    def test_contract_carries_ui_pages_and_flows(self):
        from multi_agent.runtime.kickoff.run_kickoff import _build_contract
        drafts = {"backend": {"api_endpoints": [], "data_model": {}},
                  "frontend": {"ui_pages": [{"id": "p1", "route": "/p1"}],
                               "user_flows": [{"id": "f1"}],
                               "auth": {"required": True}}}
        c = _build_contract(drafts)
        self.assertEqual(c["ui_pages"][0]["id"], "p1")
        self.assertEqual(c["user_flows"][0]["id"], "f1")


class MonitorMilestonesTests(unittest.TestCase):
    """Monitor Overview milestone strip (user request): roadmap + per-
    milestone status derived from kickoff pages + releases."""

    def test_build_milestones_statuses(self):
        import sys, tempfile, json as _json
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent /
                              "env_generator" / "llm_generator"))
        import live_monitor_server as lms
        ws = Path(tempfile.mkdtemp(prefix="mms_"))
        hubs = ws / "shared" / "hubs"; hubs.mkdir(parents=True)
        (hubs / "workhub_pages.json").write_text(_json.dumps({
            "page_1": {"title": "M1 kickoff: build the core", "status": "active",
                       "metadata": {"decisions": [{"decision": {
                           "kind": "milestone_plan", "section": "roadmap",
                           "content": {"milestones": [
                               {"name": "M1-core", "version": "1.0.0"},
                               {"name": "M2-extra", "version": "1.1.0"},
                               {"name": "M3-polish", "version": "1.2.0"}]}}}]}},
            "page_2": {"title": "M2 kickoff: extras", "status": "active"},
        }))
        (hubs / "codehub_releases.json").write_text(_json.dumps({
            "1.0.0": {"tag": "1.0.0", "created_at": 1781200000.0}}))
        ms = lms.build_milestones(ws)
        self.assertEqual(ms["total"], 3)
        self.assertEqual(ms["released_count"], 1)
        by = {m["index"]: m for m in ms["milestones"]}
        self.assertEqual(by[1]["status"], "released")
        self.assertEqual(by[2]["status"], "active")
        self.assertEqual(by[3]["status"], "planned")
        self.assertEqual(ms["current_index"], 2)
        self.assertEqual(ms["source"], "agent_planned")


class DeclareToolSurfaceTests(unittest.TestCase):
    """Round 35: kickoff_declare_ui_component existed but was absent from the
    kickoff tool-surface allowlists — frontend literally could not call it
    (0 components declared). Pin ALL declare tools in both lists."""

    def test_all_declare_tools_in_both_allowlists(self):
        import re
        base = Path(__file__).resolve().parent.parent / "env_generator" / "llm_generator"
        hub_tools = (base / "tools" / "hub_tools.py").read_text()
        declared = set(re.findall(r'NAME = "(kickoff_declare_[a-z_]+)"', hub_tools))
        self.assertGreaterEqual(len(declared), 6)
        for fname in ("multi_agent/tool_bundles.py", "multi_agent/hub_tool_surface.py"):
            body = (base / fname).read_text()
            for tool in declared:
                self.assertIn(f'"{tool}"', body,
                              f"{tool} missing from {fname} — kickoff surface hole")


class UiClosureTests(unittest.TestCase):
    """User design 2026-06-11: pages must use REGISTERED components; components
    must use REGISTERED APIs — enforced by auto-enrollment + the implemented
    gate, never by rejection."""

    def test_page_reference_auto_registers_stub_component(self):
        from multi_agent.runtime.kickoff.run_kickoff import _build_contract
        drafts = {"backend": {"api_endpoints": [], "data_model": {}},
                  "frontend": {"ui_pages": [{"id": "p1", "route": "/p1",
                                             "component": "P1Page",
                                             "components": ["mystery_widget", "side_panel"]}],
                               "auth": {"required": True}}}
        c = _build_contract(drafts)
        ids = {x.get("id") for x in c["ui_components"]}
        self.assertIn("mystery_widget", ids)
        stub = next(x for x in c["ui_components"] if x["id"] == "mystery_widget")
        self.assertEqual(stub["source"], "auto_from_page_reference")

    def test_ui_declared_api_auto_appends_endpoint(self):
        from multi_agent.runtime.kickoff.run_kickoff import _build_contract
        drafts = {"backend": {"api_endpoints": [
                      {"method": "GET", "path": "/api/things"}], "data_model": {}},
                  "frontend": {"ui_components": [
                      {"id": "widget", "apis_used": ["POST /api/widgets",
                                                     "GET /api/things"]}],
                               "auth": {"required": True}}}
        c = _build_contract(drafts)
        eps = {(e["method"], e["path"]) for e in c["endpoints"]}
        self.assertIn(("POST", "/api/widgets"), eps)
        auto = next(e for e in c["endpoints"] if e["path"] == "/api/widgets")
        self.assertEqual(auto["source"], "auto_from_ui_declaration")
        # 已存在的不重复
        self.assertEqual(sum(1 for e in c["endpoints"] if e["path"] == "/api/things"), 1)

    def test_unregistered_api_blocks_implemented(self):
        import tempfile
        from multi_agent.runtime.hub_registry import HubRegistry
        from multi_agent.runtime.frontend_audit import sync_ui_page_statuses
        reg = HubRegistry(Path(tempfile.mkdtemp(prefix="ucl_")))
        proj = Path(tempfile.mkdtemp(prefix="uclp_"))
        src = proj / "app" / "frontend" / "src"; (src / "pages").mkdir(parents=True)
        (src / "pages" / "GhostPage.jsx").write_text(
            "import { apiGet } from './services/api';\n"
            "export default function GhostPage() { apiGet('/api/ghosts'); return null; }\n")
        (src / "App.jsx").write_text(
            '<Routes><Route path="/ghosts" element={<GhostPage />} /></Routes>')
        reg.workhub.update_ui_page("ghosts", {
            "status": "defined", "route": "/ghosts", "component": "GhostPage",
            "apis_used": ["GET /api/ghosts"]}, agent="orchestrator")
        # 契约未注册该端点 → 不能 implemented
        res = sync_ui_page_statuses(proj, reg.workhub, registryhub=reg.registryhub)
        self.assertNotIn("ghosts", res["implemented"])
        self.assertTrue(any("NOT in the registered contract" in m
                            for m in res["pending"]["ghosts"]))
        # 注册后 → implemented
        reg.registryhub.register_endpoint(method="GET", path="/api/ghosts",
                                          agent="backend")
        res2 = sync_ui_page_statuses(proj, reg.workhub, registryhub=reg.registryhub)
        self.assertIn("ghosts", res2["implemented"])


class ChainSchemaToleranceTests(unittest.TestCase):
    """Round 35: verifier wrote {endpoint, payload} steps — loader must
    normalize variants + apply platform-contract defaults (auto-save token on
    auth steps, auto-bearer on /api/*)."""

    def test_endpoint_payload_variant_normalized(self):
        import tempfile
        from multi_agent.runtime.chain_executor import load_verifier_chains
        from multi_agent.runtime.hub_registry import HubRegistry
        tmp = Path(tempfile.mkdtemp(prefix="cst_"))
        reg = HubRegistry(tmp)
        # 注册经过边界校验+规范化;naive 变体在注册时被归一
        res = reg.registryhub.register_verification_chain("auth", [
            {"endpoint": "POST /auth/register",
             "payload": {"username": "u", "password": "p"}},
            {"endpoint": "GET /api/feed"}], agent="verifier")
        self.assertNotIn("error", res)
        chains = load_verifier_chains(tmp)
        self.assertEqual(len(chains), 1)
        s1, s2 = chains[0]["steps"]
        self.assertEqual((s1["method"], s1["path"]), ("POST", "/auth/register"))
        self.assertEqual(s1["body"]["username"], "u")
        self.assertEqual(s1["save"], {"token": "access_token"})   # platform default
        self.assertEqual(s2["auth"], "token")                     # /api/* bearer default


class CanonicalLayoutAuditTests(unittest.TestCase):
    """User decision: fixed frontend layout — audit resolves declarations at
    src/pages/<Name>.jsx and src/components/<Name>.jsx."""

    def test_wrong_directory_reports_canonical_path(self):
        import tempfile
        from multi_agent.runtime.frontend_audit import audit_ui_page
        tmp = Path(tempfile.mkdtemp(prefix="cla_"))
        src = tmp / "src"; (src / "components").mkdir(parents=True)
        # 根组件被放进 components/(应在 pages/)
        (src / "components" / "HomePage.jsx").write_text(
            "export default function HomePage() { return null; }")
        (src / "App.jsx").write_text('<Routes><Route path="/" element={<HomePage />} /></Routes>')
        ok, missing = audit_ui_page(src, {"component": "HomePage", "route": "/",
                                          "apis_used": []})
        self.assertFalse(ok)
        self.assertTrue(any("canonical path src/pages/HomePage.jsx" in m for m in missing))

    def test_canonical_locations_pass(self):
        import tempfile
        from multi_agent.runtime.frontend_audit import audit_ui_page, audit_ui_component
        tmp = Path(tempfile.mkdtemp(prefix="clb_"))
        src = tmp / "src"; (src / "pages").mkdir(parents=True); (src / "components").mkdir()
        (src / "pages" / "HomePage.jsx").write_text(
            "export default function HomePage() { return null; }")
        (src / "components" / "NavBar.jsx").write_text(
            "export default function NavBar() { return null; }")
        (src / "App.jsx").write_text('<Routes><Route path="/" element={<HomePage />} /></Routes>')
        ok, m = audit_ui_page(src, {"component": "HomePage", "route": "/", "apis_used": []})
        self.assertTrue(ok, m)
        ok2, m2 = audit_ui_component(src, {"component": "NavBar", "apis_used": []})
        self.assertTrue(ok2, m2)


class PageCompositionRuleTests(unittest.TestCase):
    """User design: pages compose components, never other pages — page→page
    is navigation. The audit flags page-imports-page."""

    def test_page_importing_page_flagged(self):
        import tempfile
        from multi_agent.runtime.frontend_audit import audit_ui_page
        tmp = Path(tempfile.mkdtemp(prefix="pcr_"))
        src = tmp / "src"; (src / "pages").mkdir(parents=True)
        (src / "pages" / "FeedPage.jsx").write_text(
            "import ProfilePage from '../pages/ProfilePage';\n"
            "export default function FeedPage() { return <ProfilePage/>; }")
        (src / "App.jsx").write_text('<Routes><Route path="/feed" element={<FeedPage />} /></Routes>')
        ok, missing = audit_ui_page(src, {"component": "FeedPage", "route": "/feed",
                                          "apis_used": []})
        self.assertFalse(ok)
        self.assertTrue(any("pages may only compose" in m for m in missing))

    def test_component_import_is_fine(self):
        import tempfile
        from multi_agent.runtime.frontend_audit import audit_ui_page
        tmp = Path(tempfile.mkdtemp(prefix="pcr2_"))
        src = tmp / "src"; (src / "pages").mkdir(parents=True)
        (src / "pages" / "FeedPage.jsx").write_text(
            "import PostCard from '../components/PostCard';\n"
            "export default function FeedPage() { return <PostCard/>; }")
        (src / "App.jsx").write_text('<Routes><Route path="/feed" element={<FeedPage />} /></Routes>')
        ok, missing = audit_ui_page(src, {"component": "FeedPage", "route": "/feed",
                                          "apis_used": []})
        self.assertTrue(ok, missing)


class PageComponentFieldGuardTests(unittest.TestCase):
    """Round 36: frontend declared component='' + components=['LoginPage']
    where LoginPage is the ROOT component — a single components entry with no
    component is the root, promoted so the audit looks in src/pages/."""

    def test_single_components_entry_promoted_to_root(self):
        from multi_agent.runtime.kickoff.run_kickoff import _build_contract
        drafts = {"backend": {"api_endpoints": [], "data_model": {}},
                  "frontend": {"ui_pages": [{"id": "login", "route": "/login",
                                             "component": "", "components": ["LoginPage"]}],
                               "auth": {"required": True}}}
        c = _build_contract(drafts)
        pg = next(p for p in c["ui_pages"] if p["id"] == "login")
        self.assertEqual(pg["component"], "LoginPage")
        self.assertEqual(pg["components"], [])
        # not enrolled as a phantom ui_component
        self.assertNotIn("LoginPage", {x.get("id") for x in c["ui_components"]})

    def test_multi_components_stay_as_children(self):
        from multi_agent.runtime.kickoff.run_kickoff import _build_contract
        drafts = {"backend": {"api_endpoints": [], "data_model": {}},
                  "frontend": {"ui_pages": [{"id": "feed", "route": "/feed",
                                             "component": "FeedPage",
                                             "components": ["PostCard", "StoryBar"]}],
                               "auth": {"required": True}}}
        c = _build_contract(drafts)
        pg = next(p for p in c["ui_pages"] if p["id"] == "feed")
        self.assertEqual(pg["component"], "FeedPage")
        self.assertEqual(set(pg["components"]), {"PostCard", "StoryBar"})


class ContractShapeFloorTests(unittest.TestCase):
    """Round 37 death: UI auto-enrolled endpoints + any inline endpoint missing
    response_key made roadmap_validator hard-fail → 1200s validation_failed
    timeout. _build_contract now FLOORS response_key (derived from path) +
    auth_required (default True) for EVERY endpoint regardless of source."""

    def test_every_endpoint_has_response_key_and_auth(self):
        from multi_agent.runtime.kickoff.run_kickoff import _build_contract
        c = _build_contract({
            "backend": {"api_endpoints": [
                {"method": "GET", "path": "/api/users/{username}", "response_key": "user"},
                {"method": "POST", "path": "/api/posts"},       # missing response_key
                {"method": "GET", "path": "/api/feed", "auth_required": "yes"},  # bad auth type
            ], "data_model": {"tables": []}},
            "frontend": {
                "ui_pages": [{"id": "x", "route": "/x", "component": "XPage",
                              "apis_used": ["GET /api/explore"]}],  # auto-enroll
                "ui_components": [{"id": "c", "component": "C",
                                   "apis_used": ["POST /api/c/act"]}],  # auto-enroll
                "auth": {"required": True}}})
        for e in c["endpoints"]:
            self.assertTrue(str(e.get("response_key") or "").strip(),
                            f"{e['method']} {e['path']} missing response_key")
            self.assertIsInstance(e.get("auth_required"), bool,
                                  f"{e['method']} {e['path']} auth_required not bool")
        paths = {e["path"] for e in c["endpoints"]}
        self.assertIn("/api/explore", paths)   # ui_page api auto-enrolled
        self.assertIn("/api/c/act", paths)     # ui_component api auto-enrolled


class PageComponentsFlowTests(unittest.TestCase):
    """Round-37 data-flow audit: impl.page task metadata + the registered
    ui_page must carry the `components` list, else frontend_audit's rollup
    (every referenced component must be implemented) silently no-ops."""

    def test_components_reach_task_metadata(self):
        from multi_agent.runtime.kickoff.schema_tolerance import synthesize_task_tree
        tasks = {t["id"]: t for t in synthesize_task_tree({
            "endpoints": [], "data_model": {"tables": []}, "user_flows": [],
            "ui_components": [{"id": "nav", "component": "NavBar", "apis_used": []}],
            "ui_pages": [{"id": "feed", "route": "/feed", "component": "FeedPage",
                          "components": ["nav"], "apis_used": []}]})}
        self.assertEqual(tasks["impl.page.feed"]["metadata"]["components"], ["nav"])
        self.assertIn("impl.component.nav", tasks["impl.page.feed"]["depends_on"])


class ChainFeedbackMatchTests(unittest.TestCase):
    """Round-37 scheduling audit: chain_executor's 'no chains' wording moved
    authored→registered (registry-backed); orchestrator's #53 detector must
    match VERB-INDEPENDENTLY or the chain-authoring feedback loop silently
    dies (verifier never gets the P0 task → business_chain fails forever)."""

    def test_run_chains_missing_detail_matches_orchestrator_key(self):
        import tempfile
        from multi_agent.runtime.chain_executor import run_chains
        res = run_chains("http://localhost:1", Path(tempfile.mkdtemp()), [])
        self.assertEqual(res["source"], "missing")
        # the exact substring orchestrator #53 keys on
        self.assertIn("no verification chains", res["broken"][0])


class ContractShapeFloorRound38Tests(unittest.TestCase):
    """Round 38 death: empty done_def → done_def_missing → validation_failed →
    1200s timeout. Systematic pass: every recoverable validator hard-fail is
    floored in the MAIN synthesis path (not just the late reconcile)."""

    def test_done_def_floored_when_empty(self):
        from multi_agent.runtime.kickoff.run_kickoff import _build_roadmap
        rm = _build_roadmap({"backend": {"api_endpoints": [], "data_model": {"tables": []}},
                             "frontend": {"auth": {"required": True}}}, 2, "")
        self.assertTrue(rm["done_def"])
        self.assertTrue(all(isinstance(x, str) and x.strip() for x in rm["done_def"]))

    def test_table_missing_columns_floored(self):
        from multi_agent.runtime.kickoff.run_kickoff import _build_contract
        c = _build_contract({
            "backend": {"api_endpoints": [], "data_model": {"tables": [
                {"name": "widgets"},                       # no columns
                {"columns": [{"name": "x"}]},              # no name
            ]}},
            "frontend": {"auth": {"required": True}}})
        tbls = c["data_model"]["tables"]
        names = [t["name"] for t in tbls]
        self.assertEqual(names, ["widgets"])               # nameless dropped
        self.assertTrue(tbls[0]["columns"])                # columns floored


class UiPageCaseNormalizeTests(unittest.TestCase):
    """Round 38: frontend's legacy workhub_update_page with the PascalCase
    component name ('Login') forked a case-duplicate phantom beside the
    declared 'login'. update_ui_page now snake_case-normalizes the name so a
    PascalCase call MERGES onto the declared page."""

    def _wh(self):
        import tempfile
        from multi_agent.runtime.hub_registry import HubRegistry
        return HubRegistry(Path(tempfile.mkdtemp(prefix="ucn_"))).workhub

    def test_pascalcase_merges_to_declared_snake(self):
        wh = self._wh()
        wh.update_ui_page("login", {"status": "defined", "component": "LoginPage"},
                          agent="orchestrator")
        wh.update_ui_page("Login", {"path": "x.jsx"}, agent="frontend")
        pages = [v["title"] for v in wh.stores.pages.value().values()
                 if isinstance(v, dict) and v.get("kind") == "ui_page"]
        self.assertEqual(pages, ["login"])  # no case-duplicate phantom

    def test_snake_name_unchanged(self):
        wh = self._wh()
        wh.update_ui_page("create_account", {"status": "defined"}, agent="orchestrator")
        self.assertIn("create_account", wh.get_ui_pages())




class VerifierChainToolSurfaceTests(unittest.TestCase):
    """Round 39 deadlock: run_validation is tool-blocked until chains are
    registered, but registryhub_register_verification_chain was NOT in the
    verifier stage_tool_allowlist → verifier hit the wall with no tool to
    satisfy it → orchestrator's shared framework validation also blocked
    (data=None) → spin → killed. The tool the WALL demands MUST be on the
    verifier's surface."""

    def test_register_chain_in_verifier_allowlist(self):
        import yaml
        cfg = Path(__file__).resolve().parent.parent / (
            "env_generator/llm_generator/multi_agent/agents/agents_config.yaml")
        text = cfg.read_text()
        # both verifier allowlists that carry run_validation must also carry
        # the chain registration tool (else the wall is unsatisfiable)
        self.assertEqual(text.count("- run_validation"),
                         text.count("- registryhub_register_verification_chain"),
                         "every allowlist with run_validation must include "
                         "registryhub_register_verification_chain (the tool the "
                         "chains wall demands)")

    def test_orchestrator_detects_chains_blocked_exit(self):
        src = (Path(__file__).resolve().parent.parent /
               "env_generator/llm_generator/multi_agent/orchestrator.py").read_text()
        self.assertIn('"no verification chains" in _err.lower()', src)


class ChainBodyStringToleranceTests(unittest.TestCase):
    """Round 42 deadlock: verifier wrote chain step body as a JSON STRING not
    an object → _http json.dumps()es it → backend gets a quoted string literal
    → 422 'email and password required' → business_chain fails forever → watcher
    kills (stall x15). normalize_steps parses a JSON-string body to a dict."""

    def test_json_string_body_parsed(self):
        from multi_agent.runtime.chain_executor import normalize_steps
        steps, errs = normalize_steps([
            {"method": "POST", "path": "/auth/register",
             "body": '{"email": "u@t.io", "password": "p123", "name": "T"}',
             "expect": [201]}])
        self.assertEqual(errs, [])
        b = steps[0]["body"]
        self.assertIsInstance(b, dict)
        self.assertEqual(b["email"], "u@t.io")
        self.assertEqual(b["password"], "p123")

    def test_dict_body_unchanged(self):
        from multi_agent.runtime.chain_executor import normalize_steps
        steps, _ = normalize_steps([
            {"method": "POST", "path": "/api/x", "body": {"a": 1}, "expect": [200]}])
        self.assertEqual(steps[0]["body"], {"a": 1})

    def test_string_payload_variant_parsed(self):
        from multi_agent.runtime.chain_executor import normalize_steps
        steps, _ = normalize_steps([
            {"method": "POST", "path": "/auth/login",
             "payload": '{"email": "x@t.io", "password": "q"}', "expect": [200]}])
        self.assertEqual(steps[0]["body"]["email"], "x@t.io")


class ChainAuthFirstReorderTests(unittest.TestCase):
    """Round 45 deadlock: verifier wrote /api/* steps (use token) BEFORE
    /auth/register|login (mint token) → first step 401 'missing token' →
    business_chain fails forever. 'auth round-trip first' is a PLATFORM
    invariant — normalize_steps stably hoists auth steps to the front."""

    def test_auth_hoisted_to_front(self):
        from multi_agent.runtime.chain_executor import normalize_steps
        steps, _ = normalize_steps([
            {"method": "PUT", "path": "/api/users/me", "expect": [200]},
            {"method": "POST", "path": "/auth/register", "expect": [201],
             "save": {"token": "access_token"}},
        ])
        self.assertEqual(steps[0]["path"], "/auth/register")
        self.assertEqual(steps[1]["path"], "/api/users/me")

    def test_register_before_login_preserved(self):
        from multi_agent.runtime.chain_executor import normalize_steps
        steps, _ = normalize_steps([
            {"method": "GET", "path": "/api/feed", "expect": [200]},
            {"method": "POST", "path": "/auth/register", "expect": [201]},
            {"method": "POST", "path": "/auth/login", "expect": [200]},
        ])
        self.assertEqual([s["path"] for s in steps[:2]],
                         ["/auth/register", "/auth/login"])

    def test_non_auth_relative_order_preserved(self):
        from multi_agent.runtime.chain_executor import normalize_steps
        steps, _ = normalize_steps([
            {"method": "POST", "path": "/api/a", "expect": [201]},
            {"method": "POST", "path": "/auth/login", "expect": [200]},
            {"method": "GET", "path": "/api/b", "expect": [200]},
        ])
        self.assertEqual([s["path"] for s in steps], ["/auth/login", "/api/a", "/api/b"])


class FrontendBuildScriptInfraTests(unittest.TestCase):
    """Round 46 docker_up deadlock: a lane overwrote package.json with NO
    'scripts' → `npm run build` had no build script → docker build failed →
    docker_up FAILED forever → no release. Scripts are build infra; reconcile
    force-injects `build: vite build` regardless of what the lane wrote."""

    def _reconcile(self, pkg):
        import tempfile, json, os
        from multi_agent.runtime.frontend_scaffold import pin_frontend_build_tooling
        d = tempfile.mkdtemp(); os.makedirs(d + "/src", exist_ok=True)
        open(d + "/package.json", "w").write(json.dumps(pkg))
        open(d + "/src/main.jsx", "w").write("console.log(1)")
        pin_frontend_build_tooling(d)
        return json.load(open(d + "/package.json"))

    def test_missing_scripts_gets_build(self):
        pj = self._reconcile({"dependencies": {"react": "^18"}})
        self.assertEqual(pj["scripts"]["build"], "vite build")

    def test_null_scripts_gets_build(self):
        pj = self._reconcile({"scripts": None, "dependencies": {}})
        self.assertEqual(pj["scripts"]["build"], "vite build")

    def test_wrong_build_overwritten(self):
        pj = self._reconcile({"scripts": {"build": "echo nope", "test": "jest"}})
        self.assertEqual(pj["scripts"]["build"], "vite build")
        self.assertEqual(pj["scripts"]["test"], "jest")  # lane custom kept
