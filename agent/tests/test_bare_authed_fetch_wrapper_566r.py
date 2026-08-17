r"""#566r (netflix r126 — 79-min no-convergence abort on deliverability_bare_authed_fetch): a bare
frontend fetch('/api/…') without the token wedged M1 — the lane's fix reached the gate-read INTEGRATION
tree only AFTER the abort (worktree→integration reconcile timing) and the remediation was dispatched once,
at the abort. Deterministic fix: install a global window.fetch wrapper (index.html) that attaches the
bearer token to same-origin /api/ requests, and make bare_authed_fetch_blockers self-clear when the
wrapper is present — independent of lane/dispatch/reconcile timing (mirrors the #566b/#566e reconcile).
"""
from env_generator.llm_generator.multi_agent.runtime.frontend_audit import (
    bare_authed_fetch_blockers, inject_auth_fetch_wrapper, _has_global_auth_fetch_wrapper,
    _FW_AUTH_FETCH_MARKER,
)

_BARE_PAGE = """export default function P(){
  const load = () => fetch('/api/my-list').then(r => r.json());
  return <button onClick={load}>go</button>;
}
"""
_INDEX = "<!doctype html><html><head><title>x</title></head><body><div id=root></div></body></html>"


def _mk(tmp_path, with_index=True):
    fe = tmp_path / "frontend"
    (fe / "src" / "pages").mkdir(parents=True)
    (fe / "src" / "pages" / "P.jsx").write_text(_BARE_PAGE)
    if with_index:
        (fe / "index.html").write_text(_INDEX)
    return fe


def test_bare_fetch_flagged_without_wrapper(tmp_path):
    fe = _mk(tmp_path)
    blockers = bare_authed_fetch_blockers(fe / "src")
    assert any("my-list" in b or "/api/" in b or ".jsx" in b for b in blockers), blockers


def test_inject_wrapper_is_idempotent_and_clears_the_gate(tmp_path):
    fe = _mk(tmp_path)
    assert inject_auth_fetch_wrapper(fe) is True             # installed
    assert inject_auth_fetch_wrapper(fe) is False            # idempotent (already present)
    html = (fe / "index.html").read_text()
    assert _FW_AUTH_FETCH_MARKER in html and "</head>" in html and "Bearer" in html
    assert _has_global_auth_fetch_wrapper(fe / "src") is True
    # with the wrapper installed, the SAME bare fetch is no longer a blocker
    assert bare_authed_fetch_blockers(fe / "src") == []


def test_wrapper_marker_in_a_src_file_also_clears(tmp_path):
    fe = _mk(tmp_path, with_index=False)
    (fe / "src" / "_fw_auth_fetch.js").write_text("window.%s = true;" % _FW_AUTH_FETCH_MARKER)
    assert _has_global_auth_fetch_wrapper(fe / "src") is True
    assert bare_authed_fetch_blockers(fe / "src") == []


def test_inject_noop_when_no_index_html(tmp_path):
    fe = _mk(tmp_path, with_index=False)
    assert inject_auth_fetch_wrapper(fe) is False            # nothing to write into
    # public endpoints still never flagged (sanity)
    (fe / "src" / "pages" / "Pub.jsx").write_text(
        "export default ()=> fetch('/auth/login',{method:'POST'})")
    assert all("/auth/" not in b for b in bare_authed_fetch_blockers(fe / "src"))


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
