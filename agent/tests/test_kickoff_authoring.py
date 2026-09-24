"""Round 8f.2 — tests for runtime/kickoff/authoring.py.

The authoring module is pure-Python; these tests run with zero LLM
calls + zero hub fixtures. They pin the exact shape of the markdown
the kickoff driver emits to disk after a finalized kickoff, so a
regression in output formatting becomes a diff-visible test failure.
"""

from __future__ import annotations

import re
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # agent/
SRC = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.kickoff.authoring import (  # noqa: E402
    BRIEFING_ATTENDEES,
    append_milestone_to_roadmap,
    author_all,
    build_briefing_doc,
    build_milestone_doc,
)


_FROZEN_NOW = datetime(2026, 6, 3, 7, 30, 0, tzinfo=timezone.utc)


def _ready_synthesis():
    """Canonical synthesis_result shape (matches try_synthesize's
    ready return shape from run_kickoff.py)."""
    return {
        "status": "ready",
        "milestone_index": 1,
        "contract": {
            "endpoints": [
                {
                    "method": "POST", "path": "/api/auth/register",
                    "response_key": "token", "auth_required": False,
                    "response": {"tables": ["users"]},
                },
                {
                    "method": "POST", "path": "/api/auth/login",
                    "response_key": "token", "auth_required": False,
                    "response": {"tables": ["users"]},
                },
                {
                    "method": "GET", "path": "/api/posts",
                    "response_key": "items", "auth_required": True,
                    "response": {"tables": ["posts"]},
                },
                {
                    "method": "POST", "path": "/api/posts",
                    "response_key": "item", "auth_required": True,
                    "response": {"tables": ["posts"]},
                },
            ],
            "data_model": {"tables": [
                {"name": "users", "columns": [
                    {"name": "id", "type": "BIGSERIAL"},
                    {"name": "email", "type": "VARCHAR UNIQUE"},
                ]},
                {"name": "posts", "columns": [
                    {"name": "id", "type": "BIGSERIAL"},
                    {"name": "body", "type": "TEXT"},
                ]},
            ]},
            "auth": {"model": "jwt", "required": True},
        },
        "task_tree": [
            {"id": "t_register", "owner": "backend",
             "kind": "implement_endpoint", "summary": "Implement register endpoint"},
            {"id": "t_login", "owner": "backend",
             "kind": "implement_endpoint", "summary": "Implement login endpoint"},
            {"id": "t_feed", "owner": "frontend",
             "kind": "implement_screen", "summary": "Build post feed page"},
        ],
        "predicates": [
            {"id": "pred.auth_register.api", "flow": "auth_register",
             "form": {"kind": "api_smoke"}},
            {"id": "pred.view_posts.api", "flow": "view_posts",
             "form": {"kind": "api_smoke"}},
        ],
        "roadmap": {
            "milestone_index": 1,
            "feature_inventory": {
                "entities": ["users", "posts"],
                "flows": ["auth_register", "auth_login", "view_posts", "create_post"],
            },
            "done_def": ["docker compose up clean", "smoke test passes"],
            "frontend": {
                "screens": [
                    {"id": "login", "path": "/login"},
                    {"id": "feed", "path": "/"},
                ],
                "user_flows": [
                    {"id": "auth_login", "critical": True},
                    {"id": "view_posts", "critical": True},
                ],
            },
        },
    }


class MilestoneDocTests(unittest.TestCase):
    def test_header_carries_milestone_index_and_project(self):
        md = build_milestone_doc(
            _ready_synthesis(), project_name="Blog M1", now=_FROZEN_NOW,
        )
        self.assertIn("# Milestone M1 — Blog M1", md)
        self.assertIn("Authored 2026-06-03T07:30:00", md)

    def test_endpoints_table_lists_every_endpoint(self):
        md = build_milestone_doc(_ready_synthesis(), now=_FROZEN_NOW)
        # Header + 4 endpoint rows.
        self.assertIn("| Method | Path | Auth | Response key |", md)
        for path in ("/api/auth/register", "/api/auth/login",
                     "/api/posts"):
            self.assertIn(f"`{path}`", md, msg=path)
        # Auth required POST /api/posts → ✓
        post_row = [l for l in md.splitlines()
                    if "POST" in l and "/api/posts" in l and "items" not in l]
        self.assertTrue(any("✓" in l for l in post_row), post_row)

    def test_data_model_section_lists_every_table_and_column(self):
        md = build_milestone_doc(_ready_synthesis(), now=_FROZEN_NOW)
        self.assertIn("**`users`**", md)
        self.assertIn("**`posts`**", md)
        self.assertIn("`id`: `BIGSERIAL`", md)
        self.assertIn("`email`: `VARCHAR UNIQUE`", md)

    def test_feature_inventory_validator_shape_renders_entities_and_flows(self):
        md = build_milestone_doc(_ready_synthesis(), now=_FROZEN_NOW)
        self.assertIn("**Entities**:", md)
        self.assertIn("`users`", md)
        self.assertIn("**Flows**:", md)
        self.assertIn("`view_posts`", md)

    def test_task_tree_table_carries_owner_and_kind(self):
        md = build_milestone_doc(_ready_synthesis(), now=_FROZEN_NOW)
        self.assertIn("| `t_register` | `backend` |", md)
        self.assertIn("| `t_feed` | `frontend` |", md)

    def test_acceptance_predicates_section(self):
        md = build_milestone_doc(_ready_synthesis(), now=_FROZEN_NOW)
        self.assertIn("**`pred.auth_register.api`**", md)
        self.assertIn("flow `auth_register`", md)

    def test_done_def_section(self):
        md = build_milestone_doc(_ready_synthesis(), now=_FROZEN_NOW)
        self.assertIn("docker compose up clean", md)
        self.assertIn("smoke test passes", md)

    def test_missing_milestone_index_raises(self):
        with self.assertRaises(ValueError):
            build_milestone_doc({"contract": {}}, now=_FROZEN_NOW)

    def test_utc_timestamp_uses_zulu_marker(self):
        """Round 8h adversarial-review follow-up: a UTC-aware ``now``
        MUST render with the conventional ``Z`` suffix, not
        ``+00:00``. Pre-fix the ternary was inverted and dropped the
        ``Z`` for tz-aware UTC inputs."""
        md = build_milestone_doc(
            _ready_synthesis(), project_name="Blog M1", now=_FROZEN_NOW,
        )
        self.assertIn("2026-06-03T07:30:00Z", md)
        self.assertNotIn("2026-06-03T07:30:00+00:00", md)

    def test_naive_timestamp_renders_without_suffix(self):
        """Round 8h adversarial-review follow-up: a naive datetime
        must NOT have a fake ``Z`` appended — that would lie about the
        timezone. Render the ISO form verbatim."""
        from datetime import datetime as _dt  # local import to avoid header sprawl
        naive_now = _dt(2026, 6, 3, 7, 30, 0)
        md = build_milestone_doc(
            _ready_synthesis(), project_name="Blog M1", now=naive_now,
        )
        self.assertIn("2026-06-03T07:30:00", md)
        # No Z suffix on naive timestamps.
        self.assertNotIn("2026-06-03T07:30:00Z", md)


class BriefingDocTests(unittest.TestCase):
    def test_backend_briefing_lists_endpoints_and_tables(self):
        md = build_briefing_doc(_ready_synthesis(), "backend",
                                project_name="Blog M1", now=_FROZEN_NOW)
        self.assertIn("# M1 Briefing — backend — Blog M1", md)
        self.assertIn("## API endpoints to implement", md)
        self.assertIn("`POST /api/auth/register`", md)
        self.assertIn("## Tables to implement", md)
        self.assertIn("`users`", md)

    def test_backend_briefing_owned_tasks_only(self):
        md = build_briefing_doc(_ready_synthesis(), "backend", now=_FROZEN_NOW)
        # backend owns t_register + t_login but NOT t_feed
        self.assertIn("`t_register`", md)
        self.assertIn("`t_login`", md)
        self.assertNotIn("`t_feed`", md)

    def test_frontend_briefing_shows_screens_and_flows(self):
        md = build_briefing_doc(_ready_synthesis(), "frontend", now=_FROZEN_NOW)
        self.assertIn("## Screens to implement", md)
        self.assertIn("`login`", md)
        self.assertIn("## Critical user flows", md)
        self.assertIn("`auth_login`", md)

    def test_frontend_briefing_owned_tasks(self):
        md = build_briefing_doc(_ready_synthesis(), "frontend", now=_FROZEN_NOW)
        self.assertIn("`t_feed`", md)
        self.assertNotIn("`t_register`", md)

    def test_verifier_briefing_lists_predicates(self):
        md = build_briefing_doc(_ready_synthesis(), "verifier", now=_FROZEN_NOW)
        self.assertIn("## Acceptance predicates to validate", md)
        self.assertIn("`pred.auth_register.api`", md)
        self.assertIn("flow `auth_register`", md)

    def test_unknown_agent_briefing_does_not_crash(self):
        md = build_briefing_doc(_ready_synthesis(), "knowledge", now=_FROZEN_NOW)
        # Renders a generic "no template" stub.
        self.assertIn("Slice for `knowledge`", md)

    def test_owner_with_no_tasks_renders_stub(self):
        synth = _ready_synthesis()
        # Strip all backend tasks to test the empty-tasks fallback.
        synth["task_tree"] = [t for t in synth["task_tree"]
                              if t["owner"] != "backend"]
        md = build_briefing_doc(synth, "backend", now=_FROZEN_NOW)
        self.assertIn("No tasks", md)

    def test_empty_agent_id_raises(self):
        with self.assertRaises(ValueError):
            build_briefing_doc(_ready_synthesis(), "", now=_FROZEN_NOW)


class RoadmapDocTests(unittest.TestCase):
    def test_fresh_roadmap_writes_header_and_milestone(self):
        md = append_milestone_to_roadmap(
            "", _ready_synthesis(), project_name="Blog M1", now=_FROZEN_NOW,
        )
        self.assertIn("# Roadmap — Blog M1", md)
        self.assertIn("## M1", md)
        self.assertIn("**Endpoints**: 4", md)
        self.assertIn("**Tables**: 2", md)
        self.assertIn("**Tasks**: 3", md)
        self.assertIn("**Acceptance predicates**: 2", md)

    def test_second_milestone_appends_without_overwriting_first(self):
        # Author M1 first.
        md1 = append_milestone_to_roadmap(
            "", _ready_synthesis(), project_name="Blog M1", now=_FROZEN_NOW,
        )
        # Now author M2.
        m2 = _ready_synthesis()
        m2["milestone_index"] = 2
        m2["contract"]["endpoints"] = m2["contract"]["endpoints"][:2]
        md2 = append_milestone_to_roadmap(
            md1, m2, project_name="Blog M1", now=_FROZEN_NOW,
        )
        # M1 section preserved.
        self.assertIn("## M1", md2)
        self.assertIn("**Endpoints**: 4", md2)
        # M2 section appended.
        self.assertIn("## M2", md2)
        # M1 still appears BEFORE M2.
        self.assertLess(md2.index("## M1"), md2.index("## M2"))

    def test_re_finalize_replaces_milestone_section_in_place(self):
        # Author M1, then re-author M1 with a different endpoint count
        # (simulating a finalize re-entry after a revision round).
        md1 = append_milestone_to_roadmap(
            "", _ready_synthesis(), project_name="Blog M1", now=_FROZEN_NOW,
        )
        synth_v2 = _ready_synthesis()
        synth_v2["contract"]["endpoints"] = synth_v2["contract"]["endpoints"][:2]
        md2 = append_milestone_to_roadmap(
            md1, synth_v2, project_name="Blog M1", now=_FROZEN_NOW,
        )
        # Only ONE M1 section (no duplicates).
        self.assertEqual(md2.count("## M1"), 1, msg=md2)
        # The count was updated to 2.
        self.assertIn("**Endpoints**: 2", md2)
        # The original 4-endpoint section is gone.
        self.assertNotIn("**Endpoints**: 4", md2)


class AuthorAllTests(unittest.TestCase):
    def test_returns_milestone_roadmap_briefings_and_paths(self):
        out = author_all(_ready_synthesis(), project_name="Blog M1", now=_FROZEN_NOW)
        self.assertIn("milestone", out)
        self.assertIn("roadmap", out)
        self.assertIn("briefings", out)
        self.assertIn("paths", out)
        # All 3 default attendees get a briefing.
        for agent_id in BRIEFING_ATTENDEES:
            self.assertIn(agent_id, out["briefings"])
            self.assertIn(f"BRIEFING_M1_{agent_id}.md", out["paths"]["briefings"][agent_id])
        # Milestone + roadmap paths follow the convention.
        self.assertEqual(out["paths"]["milestone"], "docs/milestones/MILESTONE_M1.md")
        self.assertEqual(out["paths"]["roadmap"], "docs/ROADMAP.md")

    def test_attendees_override_limits_briefings(self):
        out = author_all(_ready_synthesis(), attendees=["backend"], now=_FROZEN_NOW)
        self.assertEqual(list(out["briefings"].keys()), ["backend"])

    def test_prior_roadmap_md_preserved(self):
        prior = "# Roadmap — Other\n\n## M1\n\n_Older content_\n"
        out = author_all(_ready_synthesis(), project_name="Other",
                         prior_roadmap_md=prior, now=_FROZEN_NOW)
        # The M1 section was replaced (it's the same milestone), but
        # the project header stuck (only the milestone block was edited).
        self.assertIn("## M1", out["roadmap"])
        self.assertNotIn("Older content", out["roadmap"])

    def test_non_mapping_synthesis_raises(self):
        with self.assertRaises(ValueError):
            author_all("not a mapping", now=_FROZEN_NOW)  # type: ignore[arg-type]

    def test_milestone_doc_is_deterministic_at_fixed_now(self):
        # Same synthesis + same `now` → byte-identical output.
        md1 = author_all(_ready_synthesis(), project_name="Blog M1", now=_FROZEN_NOW)["milestone"]
        md2 = author_all(_ready_synthesis(), project_name="Blog M1", now=_FROZEN_NOW)["milestone"]
        self.assertEqual(md1, md2)


if __name__ == "__main__":
    unittest.main()
