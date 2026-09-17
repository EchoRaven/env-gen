"""#1202ql: the QA demo login comes from the users the loader actually inserts - the design-prep
dataset replaces the users table when it carries users (tiktok-r127: the walk logged in as
seed_data.json's maya.rivera, whom the database never held -> auth_ok=False every walk)."""
import json

from env_generator.llm_generator.multi_agent.runtime.visual_fidelity import _seed_demo_login


def _proj(tmp_path, lane_users, dataset_users=None):
    be = tmp_path / "app" / "backend"
    be.mkdir(parents=True)
    (be / "seed_data.json").write_text(json.dumps({"users": lane_users}))
    if dataset_users is not None:
        (be / "seed_dataset.json").write_text(json.dumps({"users": dataset_users}))
    return tmp_path


LANE = [{"email": "maya.rivera@example.com", "name": "Maya Rivera"}]


def test_dataset_users_win_with_the_loader_email_backfill(tmp_path):
    proj = _proj(tmp_path, LANE, [{"id": 1, "username": "bts_official_bighit"}])
    assert _seed_demo_login(proj) == {"email": "bts_official_bighit@example.com",
                                      "password": "password", "name": "bts_official_bighit"}


def test_without_dataset_users_the_lane_seed_is_used(tmp_path):
    assert _seed_demo_login(_proj(tmp_path, LANE))["email"] == "maya.rivera@example.com"
    assert _seed_demo_login(_proj(tmp_path / "b", LANE, []))["email"] == "maya.rivera@example.com"
