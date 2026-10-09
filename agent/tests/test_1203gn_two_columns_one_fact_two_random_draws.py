"""#1203gn 的测试, 命名同一事实的两列必须拿到同一个数(#1203gn)。"""
import sys
from pathlib import Path

LLM_DIR = Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.backend_skeleton import _seed_number, _seed_spread_1202tv  # noqa: E402
from multi_agent.runtime.material_prep import (  # noqa: E402
    _counter_stem_1202ru, _singular_1202ru,
)

# 全语料里真实出现过的「同一事实两种拼法」(从 registryhub_tables.json 的 15 组碰撞里取)
SAME_FACT = [
    ("followers", "followers_count"),
    ("likes", "likes_count"),
    ("following", "following_count"),
    ("comments", "comment_count"),
    ("views", "view_count"),
    ("shares", "share_count"),
    ("saves", "save_count"),
    ("replies", "replies_count"),
]
# 本该不同的事实
DIFFERENT_FACT = [
    ("followers", "following"),
    ("like_count", "view_count"),
    ("comment_count", "share_count"),
]


def test_the_key_maps_both_spellings_to_one_stem():
    """判据不是我发明的 —— 它就是 #1202ru 的约定。"""
    for a, b in SAME_FACT:
        ka = _counter_stem_1202ru(a) or _singular_1202ru(a)
        kb = _counter_stem_1202ru(b) or _singular_1202ru(b)
        assert ka == kb, (a, b, ka, kb)


def test_two_columns_naming_one_fact_get_one_number():
    bad = []
    for a, b in SAME_FACT:
        for i in range(10):
            if _seed_number(a, i) != _seed_number(b, i):
                bad.append((a, b, i, _seed_number(a, i), _seed_number(b, i)))
                break
    assert not bad, "同一事实的两列各抽了一次随机数: %s" % bad[:4]


def test_different_facts_still_differ():
    same = []
    for a, b in DIFFERENT_FACT:
        if all(_seed_number(a, i) == _seed_number(b, i) for i in range(10)):
            same.append((a, b))
    assert not same, "归一化把本该不同的事实折到一起了: %s" % same


def test_the_branch_selection_is_untouched():
    """分支选择必须仍按原始列名 —— rating 1-5 / year 2018-2024 / rank 顺序 / 互动带 120-4100。"""
    for i in range(10):
        assert 1 <= _seed_number("rating", i) <= 5
        assert 2018 <= _seed_number("year", i) <= 2024
        assert _seed_number("rank", i) == i + 1
        assert 120 <= _seed_number("followers_count", i) <= 4100
        assert 120 <= _seed_number("followers", i) <= 4100


def test_the_spread_itself_still_differs_by_column():
    """归一化只能发生在 _seed_number 里, 不能改 _seed_spread_1202tv 的语义。"""
    assert _seed_spread_1202tv("alpha", 0, 0, 1000) != _seed_spread_1202tv("beta", 0, 0, 1000)
