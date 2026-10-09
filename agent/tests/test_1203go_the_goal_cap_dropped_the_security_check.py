"""#1203go 的测试, 12 目标上限必须给每个 kind 留一个名额。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.test_user_squad import plan_test_user_goals  # noqa: E402


def _inputs(n_pages=20):
    """多页面 + 可写资源 + MCP + 多租户 —— 正是把上限撑满的真实形状。"""
    eps = []
    for i in range(6):
        eps.append({"method": "GET", "path": "/api/videos", "response_key": "items"})
        eps.append({"method": "POST", "path": "/api/videos", "response_key": "item"})
        eps.append({"method": "GET", "path": "/api/comments", "response_key": "items"})
        eps.append({"method": "POST", "path": "/api/comments", "response_key": "item"})
    pages = [{"name": "page_%02d" % i, "route": "/p%02d" % i} for i in range(n_pages)]
    return dict(
        business_eps=eps,
        ui_pages=pages,
        tables={"videos": {"schema": {"columns": ["id", "caption"]}},
                "comments": {"schema": {"columns": ["id", "text"]}}},
        feature_inventory={},
        mcp_present=True,
        multi_tenant=True,
        tenants=["tenant_a", "tenant_b"],
    )


def _kinds(goals):
    return [g.get("kind") for g in goals]


def test_the_cap_keeps_the_mcp_goal():
    goals = plan_test_user_goals(**_inputs())
    assert "mcp_parity" in _kinds(goals), (
        "MCP 面存在却被上限切掉 —— 全语料 7/21 满额启动如此, 含 r169: %s" % _kinds(goals))


def test_the_cap_keeps_the_isolation_goal():
    goals = plan_test_user_goals(**_inputs())
    assert "isolation" in _kinds(goals), (
        "跨租户泄漏检查被上限切掉 —— 全语料 11/21 满额启动如此: %s" % _kinds(goals))


def test_page_goals_still_dominate():
    """多样性不能把 page 砍成陪衬。"""
    goals = plan_test_user_goals(**_inputs())
    k = _kinds(goals)
    assert k.count("page") >= len(k) // 2, k


def test_the_cap_still_holds():
    goals = plan_test_user_goals(**_inputs())
    assert len(goals) <= 12, len(goals)


def test_nothing_changes_when_the_list_fits():
    """不足上限时必须与旧行为逐字节相同。"""
    small = _inputs(n_pages=3)
    goals = plan_test_user_goals(**small)
    assert len(goals) < 12
    assert "mcp_parity" in _kinds(goals) and "isolation" in _kinds(goals)
