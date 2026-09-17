"""#1202qh: the browser write-flow asks for the writes the screens offer, not a full
create/open/edit/delete UI per table (tiktok-r126 M2: P0s for 'no UI to edit a video_like')."""
from env_generator.llm_generator.multi_agent.runtime.test_user_squad import plan_test_user_goals


def test_the_ui_write_goal_is_scoped_to_offered_controls():
    goals = plan_test_user_goals(
        business_eps=[{"method": "POST", "path": "/api/video_likes"},
                      {"method": "GET", "path": "/api/video_likes"}],
        ui_pages=[])
    ui = next(g for g in goals if g.get("kind") == "ui_crud")
    text = ui["goal"]
    assert "open it, edit it, and delete it" not in text
    assert "does not work" in text and "FILE A P0" in text
    assert "NOT a defect of this flow" in text
    api = next(g for g in goals if g.get("kind") == "api_crud")
    assert "update -> delete" in api["goal"]      # the full lifecycle still runs over the API
