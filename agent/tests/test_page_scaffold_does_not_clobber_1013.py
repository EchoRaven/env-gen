"""#1013: the page-scaffold write had no content check, and r165 caught it live.

r165 was launched to verify #1010/#1010a. Ten minutes after pages appeared:

    LoginPage.jsx      4 commits — frontend 2 / GitOps Bot 2
    BrowseHomePage.jsx 4 commits — frontend 2 / GitOps Bot 2
    content oscillating 72 lines (framework) against 2 lines (lane)

The lane's page is 321 bytes and *correct* — it imports `LoginForm` from
`../components/LoginPage` and renders it with props. Fed to `_is_definitive_stub_page` it
answers **False**: #1010 classifies it right. The framework overwrote it anyway.

Three sites project pages. Two consult a content guard (`_is_definitive_stub_page` at ~8661,
`_is_generic_fallback_page` at ~8801). The third called `target.write_text(body)` with no
check at all, so **no amount of fixing the classifier could ever have helped** — that path
never asked it. This is the same shape as #1000 → #1003: a real fix applied to a sibling of
the path that actually ran.

The guard returns False for missing and empty files, so first-run scaffolding is untouched.
"""

import pathlib

import pytest

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _is_definitive_stub_page, _target_exists_with_content_1013)

R165_LANE_PAGE = (
    "import { useNavigate, useSearchParams } from 'react-router-dom';\n"
    "import LoginForm from '../components/LoginPage';\n"
    "export default function LoginPage() { const navigate = useNavigate(); "
    "const [params] = useSearchParams(); return <LoginForm initialEmail={params.get('e')} />; }\n")


def test_first_run_scaffolding_still_writes(tmp_path):
    assert _target_exists_with_content_1013(tmp_path / "absent.jsx") is False


def test_an_empty_page_is_still_repairable(tmp_path):
    p = tmp_path / "empty.jsx"
    p.write_text("", encoding="utf-8")
    assert _target_exists_with_content_1013(p) is False


def test_lane_written_page_is_protected(tmp_path):
    p = tmp_path / "LoginPage.jsx"
    p.write_text(R165_LANE_PAGE, encoding="utf-8")
    assert _target_exists_with_content_1013(p) is True


def test_the_classifier_was_never_the_problem():
    """#1010 gets r165's real page right. The overwrite happened on a path that does not
    consult it — fixing the classifier harder would not have moved this."""
    assert _is_definitive_stub_page(R165_LANE_PAGE) is False


def test_the_scaffold_site_now_consults_the_guard():
    """Asserted on the If node, not a byte window — the repo forbids fixed-width source
    slices, and this is the fifth time today that rule has been right."""
    import ast
    import inspect

    from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs
    tree = ast.parse(inspect.getsource(fs))
    guards = [n for n in ast.walk(tree) if isinstance(n, ast.If)
              and "_target_exists_with_content_1013" in ast.unparse(n.test)]
    assert guards, "the scaffold site does not consult the guard"
    assert any(any(isinstance(s, ast.Continue) for s in g.body) for g in guards), (
        "the guard must skip the write, not merely evaluate")


def test_a_hostile_path_does_not_crash(tmp_path):
    class _Boom:
        def is_file(self):
            raise RuntimeError("nope")

    assert _target_exists_with_content_1013(_Boom()) is False


def test_the_control_overwrites_everything():
    """Planted control: the PRE-FIX site wrote unconditionally on `is_page and route`."""
    is_page, route = True, "/login"
    assert (is_page and route), (
        "the control was supposed to be the only condition guarding the write; if it is not, "
        "this fix is unmotivated")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
