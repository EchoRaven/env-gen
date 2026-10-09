"""#1203gm 的测试, 链上每一跳的默认值必须一致, 预算算术必须成立。"""
import ast
import inspect
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

SRC = LLM_DIR / "multi_agent" / "runtime" / "test_user_squad.py"
GOALS = 12
WAVE_OVERHEAD_S = 7
TAIL_S = 180
CHAIN = ("run_squad_for_delivery", "_run_squad_for_delivery_impl", "run_test_user_squad")


def _defaults_by_ast():
    """每一跳的 max_concurrent / per_agent_timeout 默认值, 用 AST 读 —— 不用 grep。"""
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    out = {}
    for n in ast.walk(tree):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) or n.name not in CHAIN:
            continue
        a = n.args
        pairs = list(zip(a.kwonlyargs, a.kw_defaults))
        pos = a.posonlyargs + a.args
        if a.defaults:
            pairs += list(zip(pos[len(pos) - len(a.defaults):], a.defaults))
        got = {}
        for arg, d in pairs:
            if arg.arg in ("max_concurrent", "per_agent_timeout") and isinstance(d, ast.Constant):
                got[arg.arg] = d.value
        out[n.name] = got
    return out


def _escape_wall_s():
    from multi_agent.runtime.test_user_squad import squad_release_decision
    return float(inspect.signature(squad_release_decision).parameters["wall_s"].default)


def test_every_hop_in_the_chain_agrees_on_the_wave_size():
    d = _defaults_by_ast()
    vals = {name: g.get("max_concurrent") for name, g in d.items() if "max_concurrent" in g}
    assert len(vals) == len(CHAIN), vals
    assert len(set(vals.values())) == 1, (
        "链上每一跳的 max_concurrent 必须相等, 否则生产入口会静默覆盖被量过的那个: %s" % vals)


def test_the_production_entry_point_is_the_one_1202us_measured():
    d = _defaults_by_ast()
    prod = d["run_squad_for_delivery"]["max_concurrent"]
    helper = d["run_test_user_squad"]["max_concurrent"]
    assert prod == helper, ("生产入口 %s vs 被量过的 helper %s" % (prod, helper))


def test_the_budget_arithmetic_holds_at_the_production_default():
    d = _defaults_by_ast()
    mc = d["run_squad_for_delivery"]["max_concurrent"]
    to = d["run_test_user_squad"]["per_agent_timeout"]
    waves = math.ceil(GOALS / mc)
    projected = waves * (to + WAVE_OVERHEAD_S) + TAIL_S
    assert projected < _escape_wall_s(), (
        "%d 波 x %ss = %ss, 逃生窗 %ss" % (waves, to, projected, _escape_wall_s()))


def test_the_timeout_is_untouched():
    d = _defaults_by_ast()
    assert d["run_test_user_squad"]["per_agent_timeout"] == 300.0


def test_the_reachability_check_is_not_line_scoped():
    """修法本身要被钉住: #1202us 那条可达性检查不得再用单行 grep。"""
    t = (ROOT / "tests" / "test_1202us_the_squad_must_fit_inside_its_own_budget.py").read_text()
    body = t[t.index("def test_the_defaults_are_what_the_callers_get"):]
    assert "subprocess" not in body and '"grep"' not in body, (
        "跨行调用会让单行 grep 永远通过 —— 必须改用 AST")
