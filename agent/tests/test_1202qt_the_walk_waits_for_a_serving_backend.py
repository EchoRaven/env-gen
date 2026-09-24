"""#1202qt: the browser test-user walk runs only against a serving stack. tiktok-r128 16:42 walked
a stack a validation had just recreated: nginx answered 502, every page logged console errors,
auth_ok=False, and a P0 went to the frontend for failures the app did not have."""
import ast
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime import heal_pipeline


def _walk_src():
    src = Path(heal_pipeline.__file__).read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == "_walk":
            return ast.get_source_segment(src, node)
    return ""


def test_the_walk_waits_for_readiness_inside_its_lease_before_walking():
    body = _walk_src()
    assert body, "the walk closure is gone"
    assert body.index("stack_lease_1202nx") < body.index("wait_backend_ready")
    assert body.index("wait_backend_ready") < body.index("run_browser_test_user(")


def test_a_booting_stack_is_reported_as_not_run_not_as_failures():
    body = _walk_src()
    i = body.index("wait_backend_ready")
    guard = body[i:body.index("run_browser_test_user(", i)]
    assert '"ran": False' in guard and "SKIPPED" in guard
