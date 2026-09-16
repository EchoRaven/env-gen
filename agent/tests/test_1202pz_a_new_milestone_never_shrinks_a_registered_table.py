"""#1202pz: a new milestone's finalize may add columns to a registered table, never drop them.
tiktok-r126's M2 finalize registered `videos` and `sounds` as `[id]` over M1's full tables."""
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
from test_1202mv_a_resume_does_not_re_hold_a_settled_kickoff import (  # noqa: E402
    _finalize, _kickoff)


def _hubs(tmp):
    (Path(tmp) / "shared").mkdir()
    return HubRegistry(Path(tmp))


def _names(hubs, table):
    return [c["name"] for c in hubs.schema_hub.get_table(table)["schema"]["columns"]]


def test_m2_finalize_keeps_the_columns_m1_built():
    with tempfile.TemporaryDirectory() as tmp:
        hubs = _hubs(tmp)
        _finalize(hubs, _kickoff(hubs, ms=1))
        t = hubs.schema_hub.get_table("posts")
        cols = list(t["schema"]["columns"]) + [{"name": "lane_added_caption", "type": "text"}]
        hubs.schema_hub.register_table(name="posts", schema=dict(t["schema"], columns=cols),
                                       provider="backend", agent="backend", status="implemented")
        before = _names(hubs, "posts")
        _finalize(hubs, _kickoff(hubs, ms=2))
        after = _names(hubs, "posts")
        assert "lane_added_caption" in after
        assert set(before) <= set(after)


def test_the_merge_keeps_registered_columns_and_appends_only_new_ones():
    cur = {"schema": {"columns": [{"name": "id", "type": "int primary_key"},
                                  {"name": "caption", "type": "text"}]}}
    draft = {"name": "videos", "columns": [{"name": "id", "type": "integer"},
                                           {"name": "duration", "type": "int"}]}
    out = RK._merged_with_registered_columns_1202pz(draft, lambda: cur)
    assert [c["name"] for c in out["columns"]] == ["id", "caption", "duration"]
    assert out["columns"][0]["type"] == "int primary_key"


def test_an_unregistered_table_is_untouched():
    draft = {"name": "videos", "columns": [{"name": "id"}]}
    assert RK._merged_with_registered_columns_1202pz(draft, lambda: None) is draft
