"""#1203gp: #1126b 的 note 必须按本次流程的 auth 证据分支措辞, 不能一律说「重定向不对」。

判据在源码上断言(那段逻辑嵌在一个很长的 async 浏览器走查里, 无法单独调用), 用 AST/文本
钉住三件事: 两个新分支存在、C 类措辞逐字不变、ok 的 `or` 未被改动。
"""
import ast
import re
from pathlib import Path

LLM_DIR = Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"
SRC = (LLM_DIR / "multi_agent" / "runtime" / "test_user_validation.py").read_text(
    encoding="utf-8")


def _code_only(src: str) -> str:
    """注释剥掉 —— 否则「某串不存在」的断言会被解释性注释推翻(#1203e6/#1203gj 同形)。"""
    import io
    import tokenize
    lines = src.splitlines(keepends=True)
    try:
        spans = [(t.start[0], t.start[1], t.end[1])
                 for t in tokenize.generate_tokens(io.StringIO(src).readline)
                 if t.type == tokenize.COMMENT]
    except (tokenize.TokenError, IndentationError):
        return src
    for row, c0, c1 in sorted(spans, reverse=True):
        ln = lines[row - 1]
        lines[row - 1] = ln[:c0] + ln[c1:]
    return "".join(lines)


CODE = _code_only(SRC)


def test_a_flow_that_issued_no_auth_request_is_not_called_a_success():
    """A 类(4/16 条): `auth_requests == 0`, token 是同一浏览器上下文里先跑的 signup 留下的。"""
    assert re.search(r"issued NO auth request", CODE), (
        "缺少 A 类分支: 本次流程没发过 auth 请求时不能说 login SUCCEEDED")


def test_a_flow_that_stored_no_token_is_not_called_a_success():
    """B 类(2/16 条): `auth_status [200]` 但 `token_stored == false`。"""
    assert re.search(r"stored NO token", CODE), (
        "缺少 B 类分支: 没存 token 时不能说 login SUCCEEDED")


def test_the_landing_complaint_survives_for_the_case_it_was_written_for():
    """C 类(10/16 条, netflix-r3 那一类)的措辞必须逐字不变 —— 这是回归护栏。"""
    assert "which still shows a way to sign in" in CODE
    # ★源码里这句是跨行拼接的 —— 完整字面量在源码中不连续, 只在运行期的拼接值里连续。
    # 所以锚点必须是源码中**连续存在**的片段(同族: 测试禁用固定字面量窗口)。
    assert "Redirect to a route that " in CODE


def test_the_or_in_the_ok_predicate_is_untouched():
    """#1126b 的注释明说那个 `or` 是刻意保留的; 本补丁只动措辞。"""
    assert re.search(r"ok\s*=\s*bool\(token\)\s*or\s*moved", CODE), (
        "ok 的判据被改了 —— 本补丁不许动它")


def test_the_three_branches_read_this_flows_own_evidence():
    """分支必须看 `_auth_reqs` / `token`, 而不是只看落点。"""
    i = CODE.index("#1126b") if "#1126b" in CODE else CODE.index("1126b")
    window = CODE[i:i + 3000]
    assert "_auth_reqs" in window, "A 类分支没有读本次流程的请求计数"
