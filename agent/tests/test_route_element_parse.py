"""frontend_audit._route_element: resolve a route to the PAGE component it renders.

It used to bound the <Route> tag at the first '>', so it returned the WRAPPER of a guarded
route (element={<ProtectedRoute><InboxPage/></ProtectedRoute>} -> 'ProtectedRoute') and
missed element-before-path ordering / a '>' inside the element expression. The audit then
bound the page's dead-controls/page-import check to the wrong file. Now it parses the whole
<Route> tag (balanced braces) and returns the innermost page component, skipping known guards.

LOCAL-ONLY (agent/tests/ gitignored).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.frontend_audit import _route_element  # noqa: E402


def test_bare_element_resolves():
    assert _route_element('<Route path="/" element={<Home />} />', "/") == "Home"


def test_guarded_route_returns_page_not_wrapper():
    jsx = '<Route path="/inbox" element={<ProtectedRoute><InboxPage /></ProtectedRoute>} />'
    assert _route_element(jsx, "/inbox") == "InboxPage"


def test_layout_wrapper_returns_page():
    jsx = '<Route path="/settings" element={<Layout><SettingsPage /></Layout>} />'
    assert _route_element(jsx, "/settings") == "SettingsPage"


def test_element_before_path_attribute_order():
    jsx = '<Route element={<Dashboard />} path="/dash" />'
    assert _route_element(jsx, "/dash") == "Dashboard"


def test_greater_than_inside_element_expression():
    # a '>' inside the JSX expression must not truncate the tag scan
    jsx = '<Route path="/x" element={<Page show={count > 0} />} />'
    assert _route_element(jsx, "/x") == "Page"


def test_single_quoted_path():
    assert _route_element("<Route path='/p' element={<P />} />", "/p") == "P"


def test_no_match_returns_none():
    assert _route_element('<Route path="/a" element={<A />} />', "/missing") is None


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
