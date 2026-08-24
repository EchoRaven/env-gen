"""Visual-fidelity gate: reference→route mapping, verdict parsing, thresholding,
and the remediation feedback — capture and judge are injected fakes."""

import asyncio
import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent))
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.visual_fidelity import (  # noqa: E402
    _parse_verdict,
    map_reference_screens,
    remediation_text,
    run_visual_fidelity,
)


def _make_refs(tmp, names):
    paths = []
    for n in names:
        p = tmp / f"{n}.png"
        p.write_bytes(b"\x89PNG fake")
        paths.append(str(p))
    return paths


class MapReferenceScreensTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="vf_"))

    def test_instagram_reference_set_maps(self):
        refs = _make_refs(self.tmp, ["home", "search", "video", "create",
                                     "create_account", "login", "profile", "more"])
        screens = {s["name"]: s for s in map_reference_screens(refs)}
        self.assertEqual(screens["home"]["route"], "/feed")
        self.assertEqual(screens["search"]["route"], "/explore")
        self.assertEqual(screens["video"]["route"], "/reels")
        self.assertEqual(screens["create"]["route"], "/create")
        # create_account must NOT be swallowed by the 'create' keyword
        self.assertEqual(screens["create_account"]["route"], "/signup")
        self.assertEqual(screens["login"]["route"], "/login")
        self.assertFalse(screens["login"]["auth"])
        self.assertEqual(screens["profile"]["route"], "/profile")
        # unmappable name → route None (skipped, not failed)
        self.assertIsNone(screens["more"]["route"])

    def test_maps_to_app_actual_routes_for_any_domain(self):
        # GENERALITY: an arbitrary (non-social) app's reference screens map to its
        # OWN declared routes — and a home/landing shot maps to "/" — with no
        # reliance on the social catalog (was: home→/feed, board→skipped).
        refs = _make_refs(self.tmp, ["board", "backlog", "home", "login"])
        known = {"/board", "/backlog", "/", "/login"}
        s = {x["name"]: x for x in map_reference_screens(refs, known)}
        self.assertEqual(s["board"]["route"], "/board")
        self.assertEqual(s["backlog"]["route"], "/backlog")
        self.assertEqual(s["home"]["route"], "/")          # root, not /feed
        self.assertEqual(s["login"]["route"], "/login")
        self.assertFalse(s["login"]["auth"])

    def test_keyword_route_not_served_falls_back_to_real_route(self):
        # "search.png" keyword-maps to /explore, but this app serves /search → use it
        refs = _make_refs(self.tmp, ["search"])
        s = {x["name"]: x for x in map_reference_screens(refs, {"/search", "/"})}
        self.assertEqual(s["search"]["route"], "/search")

    def test_social_keywords_preserved_when_actually_served(self):
        # an app that DOES serve the social routes → keyword mapping unchanged (no 误伤)
        refs = _make_refs(self.tmp, ["home", "search", "video"])
        s = {x["name"]: x for x in map_reference_screens(refs, {"/feed", "/explore", "/reels"})}
        self.assertEqual(s["home"]["route"], "/feed")
        self.assertEqual(s["search"]["route"], "/explore")
        self.assertEqual(s["video"]["route"], "/reels")

    def test_missing_files_dropped(self):
        screens = map_reference_screens([str(self.tmp / "ghost.png")])
        self.assertEqual(screens, [])


class ParseVerdictTests(unittest.TestCase):
    def test_flat_legacy_format_falls_back(self):
        v = _parse_verdict('noise {"similarity": 0.8, "deviations": ["no top bar"], "summary": "ok"} tail')
        self.assertEqual(v["similarity"], 0.8)
        self.assertEqual(v["deviations"], ["no top bar"])

    def test_junk_is_zero(self):
        self.assertEqual(_parse_verdict("I cannot compare these")["similarity"], 0.0)

    def test_clamped(self):
        self.assertEqual(_parse_verdict('{"similarity": 7}')["similarity"], 1.0)

class RunGateTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="vf_"))
        self.refs = _make_refs(self.tmp, ["home", "login"])
        self.shot = self.tmp / "shot.png"
        self.shot.write_bytes(b"\x89PNG fake shot")

    def _run(self, sims, capture_names=None):
        async def capture(screens):
            names = capture_names if capture_names is not None else [s["name"] for s in screens]
            return {n: str(self.shot) for n in names}

        async def judge(llm, screen, shot):
            return {"similarity": sims.get(screen["name"], 0.0),
                    "deviations": [f"{screen['name']} differs"], "summary": "s"}

        return asyncio.run(
            run_visual_fidelity(self.tmp, self.refs, llm=None, min_similarity=0.65,
                                capture_fn=capture, judge_fn=judge))

    def test_all_pass(self):
        res = self._run({"home": 0.9, "login": 0.8})
        self.assertTrue(res["passed"])
        self.assertEqual(len(res["screens"]), 2)

    def test_one_below_threshold_fails(self):
        res = self._run({"home": 0.9, "login": 0.4})
        self.assertFalse(res["passed"])
        failing = [s for s in res["screens"] if not s["passed"]]
        self.assertEqual(failing[0]["name"], "login")
        body = remediation_text(res)
        self.assertIn("/login", body)
        self.assertIn("login differs", body)
        self.assertNotIn("home", body.split("##")[0])  # passing screen not in remediation

    def test_uncaptured_route_fails_that_screen(self):
        res = self._run({"home": 0.9, "login": 0.9}, capture_names=["home"])
        self.assertFalse(res["passed"])
        login = next(s for s in res["screens"] if s["name"] == "login")
        self.assertEqual(login["similarity"], 0.0)
        # The phrase changed on purpose: "could not be captured" read as a verdict
        # on the PAGE, and appeared in 0 of 116 persisted verdicts because #500's
        # merge erased it. The message now separates harness failure from a broken
        # page, which is the property worth pinning.
        self.assertIn("produced NO capture", login["deviations"][0])
        self.assertIn("not a verdict on the page", login["deviations"][0])

    def test_no_mappable_refs_vacuous_pass(self):
        refs = _make_refs(self.tmp, ["more", "misc"])
        async def capture(screens):
            raise AssertionError("must not capture with no mappable screens")
        res = asyncio.run(
            run_visual_fidelity(self.tmp, refs, llm=None, capture_fn=capture))
        self.assertTrue(res["passed"])
        self.assertIn("vacuous", res["summary"])
        self.assertEqual(set(res["skipped"]), {"more", "misc"})


if __name__ == "__main__":
    unittest.main()


class FallbackVisibilityTests(unittest.TestCase):
    def test_smoke_reports_fallback_page_count(self):
        import tempfile
        from multi_agent.runtime.frontend_page_projector import _PAGE_MARKER
        from multi_agent.runtime.validation_runner import run_smoke_validation
        tmp = Path(tempfile.mkdtemp(prefix="vf_fb_"))
        pages = tmp / "app" / "frontend" / "src" / "pages"
        pages.mkdir(parents=True)
        (pages / "A.jsx").write_text(_PAGE_MARKER + "\nexport default () => null;\n")
        (pages / "B.jsx").write_text("export default () => null;\n")
        res = run_smoke_validation(tmp, [])  # no compose file → fails fast, but
        # the report shape for early-exit doesn't include the check; instead test
        # the counting against a tree WITH a compose file is heavy — assert via
        # the navigable+fallback path by giving a minimal App.jsx and compose.
        (tmp / "app" / "frontend" / "src" / "App.jsx").write_text(
            "import A from './pages/A';\n<Route path=\"/a\" element={<A />} />")
        (tmp / "docker").mkdir()
        (tmp / "docker" / "docker-compose.yml").write_text("services: {}\n")
        res = run_smoke_validation(tmp, [], up_timeout=1, health_timeout=1)
        fb = next((c for c in res["checks"] if c["name"] == "frontend_fallback_pages"), None)
        self.assertIsNotNone(fb)
        self.assertIn("1/2 pages are framework fallback", fb["detail"])


class GenericRouteMappingTests(unittest.TestCase):
    def test_unknown_screen_matches_actual_app_route(self):
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="vf_gr_"))
        refs = _make_refs(tmp, ["boards", "sprint_review"])
        screens = {s["name"]: s for s in map_reference_screens(
            refs, known_routes={"/boards", "/sprint-review", "/tasks"})}
        self.assertEqual(screens["boards"]["route"], "/boards")
        self.assertEqual(screens["sprint_review"]["route"], "/sprint-review")

    def test_keyword_route_app_lacks_falls_back_to_actual(self):
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="vf_gr_"))
        refs = _make_refs(tmp, ["home"])
        # keyword says /feed but this app routes /homes — generic match wins
        screens = map_reference_screens(refs, known_routes={"/homes"})
        self.assertEqual(screens[0]["route"], "/homes")


class DimensionKnowledgeTests(unittest.TestCase):
    def test_model_overall_similarity_is_used(self):
        """Similarity is the MODEL's holistic judgment — dimensions are
        structured evidence, not a code-side formula."""
        import json as _json
        payload = {"dimensions": {"layout": {"score": 0.9, "notes": "matches"},
                                  "components": {"score": 0.2, "notes": "thin",
                                                 "missing": ["search bar"]}},
                   "similarity": 0.5, "deviations": ["x"], "summary": "s"}
        v = _parse_verdict(_json.dumps(payload))
        self.assertEqual(v["similarity"], 0.5)
        self.assertEqual(v["dimensions"]["components"]["missing"], ["search bar"])

    def test_missing_overall_averages_dimensions(self):
        v = _parse_verdict('{"dimensions": {"layout": {"score": 0.8}, "color": {"score": 0.4}}}')
        self.assertAlmostEqual(v["similarity"], 0.6, places=2)

    def test_remediation_groups_by_dimension(self):
        result = {"screens": [{
            "name": "home", "route": "/feed", "similarity": 0.42, "passed": False,
            "dimensions": {
                "components": {"score": 0.3, "notes": "no right sidebar",
                               "missing": ["suggested panel"]},
                "style": {"score": 0.6, "notes": "corners too round"}},
            "deviations": ["overall too dark"]}]}
        body = remediation_text(result)
        self.assertIn("Missing components (build these first): suggested panel", body)
        self.assertLess(body.index("Component completeness"), body.index("Style character"))
        self.assertIn("overall too dark", body)

    def test_design_premises_cover_all_dimensions(self):
        """The frontend prompt's design premises and the judge rubric come from
        the same dimension set — both surfaces must mention every dimension."""
        from multi_agent.runtime.visual_fidelity import _DIMENSIONS, design_premises_text
        premises = design_premises_text()
        for d in _DIMENSIONS:
            self.assertIn(d["title"], premises)
        prompt = Path(THIS_DIR.parent / "env_generator" / "llm_generator" /
                      "multi_agent" / "prompts" / "v3" / "frontend_agent.j2").read_text()
        for token in ("LAYOUT STRUCTURE", "COMPONENT COMPLETENESS", "STYLE CHARACTER",
                      "COLOR & CONTRAST", "TYPOGRAPHY", "ICONOGRAPHY", "UI COPY"):
            self.assertIn(token, prompt)


class BackendReferenceAnalysisTests(unittest.TestCase):
    """The backend derives its contract from the reference screens too — the
    prompt carries the analysis methodology and the agent can actually see the
    images (vision + reference tools + orchestrator handoff)."""

    def test_backend_prompt_carries_reference_methodology(self):
        prompt = Path(THIS_DIR.parent / "env_generator" / "llm_generator" /
                      "multi_agent" / "prompts" / "v3" / "backend_agent.j2").read_text()
        for token in ("Reference-driven contract design", "ENTITIES & FIELDS",
                      "RELATIONSHIPS", "INTERACTIONS -> ENDPOINTS",
                      "AGGREGATES & DERIVED DATA", "STATES & LIFECYCLE",
                      "AUTH & VISIBILITY", "COVERAGE CHECK"):
            self.assertIn(token, prompt)

    def test_backend_config_has_vision_and_reference(self):
        import yaml
        cfg = yaml.safe_load(Path(
            THIS_DIR.parent / "env_generator" / "llm_generator" / "multi_agent" /
            "agents" / "agents_config.yaml").read_text())
        be = cfg["profiles"]["backend"]
        self.assertTrue(be.get("include_vision"))
        self.assertIn("reference", be.get("tool_categories", []))
        self.assertIn("vision", be.get("tool_categories", []))
        self.assertIn("reference_images", be.get("tool_bundles", []))

    def test_orchestrator_hands_references_to_backend(self):
        src = Path(THIS_DIR.parent / "env_generator" / "llm_generator" /
                   "multi_agent" / "orchestrator.py").read_text()
        self.assertIn('for agent_id in ["frontend", "backend"]:', src)


class CaptureUnavailableTests(unittest.TestCase):
    def test_all_captures_failed_is_not_a_judgment(self):
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="vf_cu_"))
        refs = _make_refs(tmp, ["home", "login"])
        async def capture(screens):
            return {}
        async def judge(llm, screen, shot):
            raise AssertionError("must not judge with zero captures")
        res = asyncio.run(run_visual_fidelity(
            tmp, refs, llm=None, capture_fn=capture, judge_fn=judge))
        self.assertTrue(res.get("capture_unavailable"))
        self.assertEqual(res["screens"], [])


class AuthUnavailableTests(unittest.TestCase):
    """Round 31: every auth screen bounced to /login → the gate judged the
    login page against feed/profile references. Wholesale auth rejection is
    NOT a judgment — it's reported as auth_unavailable (attempt refunded)."""

    def test_mint_failure_reports_auth_unavailable(self):
        import tempfile
        from unittest import mock
        import urllib.request
        import multi_agent.runtime.visual_fidelity as vf
        tmp = Path(tempfile.mkdtemp(prefix="vf_au_"))
        refs = _make_refs(tmp, ["home", "login"])
        (tmp / "docker").mkdir()
        (tmp / "docker" / "docker-compose.yml").write_text("services: {}\n")

        # FIX #207 added a port-resolution poll that (a) resolves THIS app's
        # OWN host port and (b) confirms the frontend actually SERVES (GET
        # returns 200-499) before judging — refusing to screenshot a possibly-
        # unrelated :8080 service. The old mock (_service_host_port -> None)
        # therefore never resolves a port and the gate returns port_unresolved
        # after a 240s poll, never reaching the mint path. Mock a resolvable,
        # serving frontend so we exercise the actual mint-failure branch.
        class _FakeResp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with mock.patch.object(vf, "_compose_up", return_value=None), \
             mock.patch.object(vf, "_service_host_port", return_value=12345), \
             mock.patch.object(urllib.request, "urlopen",
                               return_value=_FakeResp()), \
             mock.patch.object(vf, "_mint_token", return_value=None):
            res = asyncio.run(vf.run_visual_fidelity(tmp, refs, llm=None))
        self.assertTrue(res.get("auth_unavailable"))
        self.assertFalse(res["passed"])
        self.assertIn("mint failed", res["summary"])

    def test_orchestrator_refunds_on_auth_unavailable(self):
        # The judge-and-refund loop moved to runtime.visual_fidelity.VisualFidelityGate
        # (PROPOSAL #8 — VisualFidelity slice B); the orchestrator delegates.
        src = Path(THIS_DIR.parent / "env_generator" / "llm_generator" /
                   "multi_agent" / "runtime" / "visual_fidelity.py").read_text()
        self.assertIn('result.get("capture_unavailable") or result.get("auth_unavailable")', src)

    def test_blocking_is_final_milestone_only(self):
        src = Path(THIS_DIR.parent / "env_generator" / "llm_generator" /
                   "multi_agent" / "orchestrator.py").read_text()
        self.assertIn('getattr(self, "_is_final_milestone", True)', src)
        self.assertIn('self._is_final_milestone = (_m_idx == len(milestones))', src)


class ViewImagePixelPathTests(unittest.TestCase):
    """Mechanism #40: view_image must (a) tolerate alias param names and
    (b) put actual pixels on the wire — round 32 showed the frontend calling
    view_image(image_path=...) → TypeError, and even a correct call returned
    metadata only (multimodal_content had ZERO consumers in the runtime)."""

    def _tool(self, tmp):
        from tools.file_tools import ViewImageTool
        from workspace import Workspace
        return ViewImageTool(workspace=Workspace(tmp))

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="vi_"))
        # 1x1 png
        import base64
        (self.tmp / "ref.png").write_bytes(base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNg"
            "YGBgAAAABQABh6FO1AAAAABJRU5ErkJggg=="))

    def test_alias_param_accepted(self):
        tool = self._tool(self.tmp)
        res = tool.execute(image_path="ref.png")
        self.assertTrue(res.success, res.error_message)

    def test_pixels_attached_by_default(self):
        tool = self._tool(self.tmp)
        res = tool.execute(path="ref.png")
        self.assertTrue(res.success)
        mm = res.data.get("multimodal_content")
        self.assertIsInstance(mm, dict)
        self.assertEqual(mm["type"], "image_url")
        self.assertTrue(mm["image_url"]["url"].startswith("data:image/png;base64,"))
        self.assertNotIn("image_base64", res.data)  # raw text stays opt-in

    def test_step_pipeline_consumes_multimodal(self):
        src = Path(THIS_DIR.parent / "env_generator" / "llm_generator" /
                   "multi_agent" / "agents" / "runtime" / "step_pipeline" /
                   "tooling.py").read_text()
        self.assertIn('result.data.pop("multimodal_content", None)', src)
        self.assertIn("Message.user_multimodal", src)


class ImageCompressionCacheTests(unittest.TestCase):
    """Mechanism #41: oversized reference images are downscaled+recompressed
    once into /tmp cache; small images pass through untouched."""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="vic_"))

    def _make_png(self, name, w, h):
        from PIL import Image
        import random
        img = Image.new("RGB", (w, h))
        img.putdata([(random.randrange(256),) * 3 for _ in range(w * h)][:w * h])
        path = self.tmp / name
        img.save(path, format="PNG")
        return path

    def test_small_image_not_compressed(self):
        from tools.file_tools import _compressed_image_for_llm
        p = self._make_png("small.png", 64, 64)
        self.assertIsNone(_compressed_image_for_llm(p))

    def test_large_image_compressed_and_cached(self):
        from tools.file_tools import _compressed_image_for_llm, _TARGET_MAX_SIDE
        p = self._make_png("big.png", 2600, 2600)
        c1 = _compressed_image_for_llm(p)
        self.assertIsNotNone(c1)
        self.assertTrue(str(c1).startswith("/tmp/envgen_image_cache"))
        from PIL import Image
        with Image.open(c1) as im:
            self.assertLessEqual(max(im.size), _TARGET_MAX_SIDE)
        m1 = c1.stat().st_mtime_ns
        c2 = _compressed_image_for_llm(p)   # second call → cache hit, no rewrite
        self.assertEqual(c1, c2)
        self.assertEqual(c2.stat().st_mtime_ns, m1)

    def test_view_image_uses_compressed_payload(self):
        from tools.file_tools import ViewImageTool
        from workspace import Workspace
        self._make_png("ref_big.png", 2600, 2600)
        tool = ViewImageTool(workspace=Workspace(self.tmp))
        res = tool.execute(path="ref_big.png")
        self.assertTrue(res.success, res.error_message)
        self.assertIn("compressed", res.data)
        self.assertLess(res.data["compressed"]["compressed_bytes"],
                        res.data["compressed"]["original_bytes"])
        mm = res.data["multimodal_content"]
        self.assertTrue(mm["image_url"]["url"].startswith("data:image/jpeg;base64,"))


class UiTestUserTests(unittest.TestCase):
    """Mechanism #44: the recruited test-user SEES the app — first-time-user
    feedback over the visual-gate screenshots, advisory in the report."""

    def test_no_shots_or_llm_skips_gracefully(self):
        import tempfile
        from multi_agent.runtime.test_user_validation import _ui_test_user
        tmp = Path(tempfile.mkdtemp(prefix="utu_"))
        res = asyncio.run(_ui_test_user(tmp, llm=None))
        self.assertFalse(res["ran"])

    def test_feedback_parsed_from_model_json(self):
        import tempfile
        from multi_agent.runtime.test_user_validation import _ui_test_user
        tmp = Path(tempfile.mkdtemp(prefix="utu_"))
        gate = tmp / "design" / "visual_gate"; gate.mkdir(parents=True)
        (gate / "home.png").write_bytes(b"\x89PNG fake")

        class _Resp:  # mimic BaseLLMClient.chat response
            content = ('{"screens": [{"name": "home", "works": "nav", '
                       '"problems": ["feed is empty"]}], '
                       '"top_issues": ["seed demo data"]}')

        class _Client:
            async def chat(self, messages, **kw):
                assert isinstance(messages[0].content, list)  # multimodal
                return _Resp()

        class _LLM:
            _client = _Client()

        res = asyncio.run(_ui_test_user(tmp, llm=_LLM()))
        self.assertTrue(res["ran"], res)
        self.assertEqual(res["top_issues"], ["seed demo data"])
        self.assertEqual(res["screens"][0]["problems"], ["feed is empty"])

    def test_orchestrator_passes_llm(self):
        # _run_test_user_validation moved to runtime.heal_pipeline.HealPipeline
        # (PROPOSAL #8 — HealPipeline extraction); it passes the run's llm through.
        src = Path(THIS_DIR.parent / "env_generator" / "llm_generator" /
                   "multi_agent" / "runtime" / "heal_pipeline.py").read_text()
        # Per-component model config (2026-07-09): the test-user judge now resolves
        # its OWN llm (component 'test_user_judge'), falling back to the run's llm.
        self.assertIn('get_component_llm(orch, "test_user_judge")', src)
        self.assertIn("llm=_tu_llm)", src)


class JudgeFixesOutputTests(unittest.TestCase):
    """Mechanism #45 (user ask): the judge returns WHERE the differences are
    and CONCRETE fix suggestions — and the remediation task renders them."""

    def test_parse_keeps_fixes_and_dimension_fix(self):
        import json as _json
        v = _parse_verdict(_json.dumps({
            "dimensions": {"layout": {"score": 0.4, "notes": "rail too wide",
                                      "fix": "narrow rail to 245px"}},
            "similarity": 0.4,
            "deviations": ["header: logo centered; reference left-aligns it"],
            "fixes": ["left-align logo", "swap emoji icons for line icons"],
            "summary": "s"}))
        self.assertEqual(v["fixes"][0], "left-align logo")
        self.assertEqual(v["dimensions"]["layout"]["fix"], "narrow rail to 245px")

    def test_remediation_renders_fix_list(self):
        result = {"screens": [{
            "name": "home", "route": "/feed", "similarity": 0.4, "passed": False,
            "dimensions": {"layout": {"score": 0.4, "notes": "rail too wide",
                                      "fix": "narrow rail to 245px"}},
            "deviations": ["header: logo centered; reference left-aligns"],
            "fixes": ["left-align logo", "swap emoji icons for line icons"]}]}
        body = remediation_text(result)
        self.assertIn("FIX: narrow rail to 245px", body)
        self.assertIn("Differences (where + what):", body)
        self.assertIn("Do these, in order:", body)
        self.assertIn("1. left-align logo", body)
        self.assertIn("2. swap emoji icons", body)

    def test_judge_prompt_demands_fixes(self):
        from multi_agent.runtime.visual_fidelity import _JUDGE_INSTRUCTIONS
        self.assertIn('"fixes"', _JUDGE_INSTRUCTIONS)
        self.assertIn('"fix"', _JUDGE_INSTRUCTIONS)
        self.assertIn("WHERE", _JUDGE_INSTRUCTIONS)


class VerifierChainCheckTests(unittest.TestCase):
    """Mechanism #48b: the verifier's validation includes the API chain
    (register→login→create→read-back) as a HARD check."""

    def test_validation_runner_has_business_chain(self):
        src = Path(THIS_DIR.parent / "env_generator" / "llm_generator" /
                   "multi_agent" / "runtime" / "validation_runner.py").read_text()
        self.assertIn('"business_chain"', src)
        self.assertIn("from .chain_executor import run_chains", src)

    def test_chain_failure_marks_check_failed(self):
        # simulate: chain runner returns one broken step
        from multi_agent.runtime import validation_runner as vr
        import types
        steps = {"steps": [{"method": "POST", "path": "/auth/register",
                            "status": 500, "kind": "broken", "note": "boom"}]}
        broken = [f"{s.get('method')} {s.get('path')} → {s.get('status')} ({s.get('note')})"
                  for s in steps["steps"] if s.get("kind") == "broken"]
        self.assertTrue(broken)


class GeneralityFixTests(unittest.TestCase):
    """Generality audit (user-ordered, 2026-06-11): the framework must not
    carry app-category bias. These tests pin the de-biased behaviors."""

    def test_no_instagram_brand_in_scaffold_templates(self):
        src = Path(THIS_DIR.parent / "env_generator" / "llm_generator" /
                   "multi_agent" / "runtime" / "frontend_scaffold.py").read_text()
        self.assertNotIn(">Instagram<", src)
        self.assertIn("__APP_NAME__", src)

    def test_no_chain_fallback_gate_fails_with_instructions(self):
        import tempfile
        from multi_agent.runtime.chain_executor import run_chains
        tmp = Path(tempfile.mkdtemp(prefix="glc_"))
        res = run_chains("http://localhost:1", tmp, [])
        self.assertEqual(res["source"], "missing")
        self.assertIn("registryhub_register_verification_chain", res["broken"][0])

    def test_verifier_chain_executes_with_vars(self):
        import tempfile, json as _json
        from multi_agent.runtime import chain_executor as ce
        from unittest import mock
        tmp = Path(tempfile.mkdtemp(prefix="glx_"))
        d = tmp / "shared" / "hubs"; d.mkdir(parents=True)
        (d / "registryhub_verification_chains.json").write_text(_json.dumps({
            "t": {"name": "t", "steps": [
                {"action": "reg", "method": "POST", "path": "/auth/register",
                 "body": {"email": "x${rand}@t.io"}, "expect": [201],
                 "save": {"token": "access_token"}},
                {"action": "me", "method": "GET", "path": "/api/me",
                 "auth": "token", "expect": [200]}]}}))
        calls = []
        def fake_http(method, url, token=None, body=None, **kw):
            calls.append({"method": method, "url": url, "token": token, "body": body})
            if url.endswith("/auth/register"):
                return {"status": 201, "body_text": '{"access_token": "TOK"}', "error": None}
            return {"status": 200, "body_text": "{}", "error": None}
        with mock.patch.object(ce, "_http", side_effect=fake_http):
            res = ce.run_chains("http://b", tmp, [])
        self.assertEqual(res["source"], "verifier")
        self.assertFalse(res["broken"])
        self.assertEqual(calls[1]["token"], "TOK")          # saved var used as auth
        self.assertIn("@t.io", calls[0]["body"]["email"])   # ${rand} substituted
        self.assertNotIn("${rand}", calls[0]["body"]["email"])

    def test_dead_controls_rule_flags_unbound_form(self):
        src = Path(THIS_DIR.parent / "env_generator" / "llm_generator" /
                   "multi_agent" / "runtime" / "validation_runner.py").read_text()
        self.assertIn('"frontend_dead_controls"', src)
        self.assertIn("onSubmit", src)
