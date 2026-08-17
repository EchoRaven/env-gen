"""#566b (netflix r113 — fail-fast rc=1 on deliverability_ui_page_unwired): the frontend lane
builds a REAL page in its worktree, but the delivery gate audits the INTEGRATION tree, which can
still hold the projector stub until a lane->integration merge lands. Between merges the gate
re-reads the stub -> 'ui_page declared but unusable' -> after 7 stuck cycles the run FAIL-FAST
aborts. reconcile_integration_frontend_pages copies a real lane page onto integration (when
integration is a stub/fallback/missing) BEFORE the audit reads — mirroring #324's seed reconcile.
Never clobbers a real integration page; best-effort; generalizable (reuses frontend_audit
predicates, no product literals).
"""
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.heal_pipeline import (
    reconcile_integration_frontend_pages,
)

_REAL = (
    "import React, { useEffect, useState } from 'react';\n"
    "export default function TitleDetailPage() {\n"
    "  const [t, setT] = useState(null);\n"
    "  useEffect(() => { fetch('/api/titles/1').then(r => r.json()).then(setT); }, []);\n"
    "  return (<div><button onClick={() => {}}>Play</button><h1>{t && t.name}</h1></div>);\n"
    "}\n"
)
_STUB = (
    "import React from 'react';\n"
    "export default function TitleDetailPage() {\n"
    "  return <div>This section is being set up. Coming soon.</div>;\n"
    "}\n"
)


def _mk(repo: Path, rel: str, text: str):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_stub_integration_real_worktree_gets_reconciled(tmp_path):
    integ = _mk(tmp_path, "app/frontend/src/pages/TitleDetailPage.jsx", _STUB)
    _mk(tmp_path, "worktrees/frontend/app/frontend/src/pages/TitleDetailPage.jsx", _REAL)
    res = reconcile_integration_frontend_pages(tmp_path)
    assert res.get("count") == 1, res
    assert "TitleDetailPage.jsx" in res.get("reconciled", [])
    # integration now holds the real page
    assert "fetch('/api/titles/1')" in integ.read_text()


def test_real_integration_is_never_clobbered(tmp_path):
    integ = _mk(tmp_path, "app/frontend/src/pages/TitleDetailPage.jsx", _REAL)
    # a DIFFERENT real (shorter) version in the worktree — must NOT overwrite integration
    _mk(tmp_path, "worktrees/frontend/app/frontend/src/pages/TitleDetailPage.jsx",
        _REAL.replace("Play", "Watch"))
    before = integ.read_text()
    res = reconcile_integration_frontend_pages(tmp_path)
    assert res == {}, res
    assert integ.read_text() == before  # untouched


def test_worktree_also_stub_is_noop(tmp_path):
    integ = _mk(tmp_path, "app/frontend/src/pages/TitleDetailPage.jsx", _STUB)
    _mk(tmp_path, "worktrees/frontend/app/frontend/src/pages/TitleDetailPage.jsx", _STUB)
    res = reconcile_integration_frontend_pages(tmp_path)
    assert res == {}, res
    assert integ.read_text() == _STUB  # unchanged


def test_missing_integration_page_gets_created_from_real_worktree(tmp_path):
    # no integration file at all → treated as stub → real worktree page copied in
    _mk(tmp_path, "worktrees/frontend/app/frontend/src/pages/TitleDetailPage.jsx", _REAL)
    res = reconcile_integration_frontend_pages(tmp_path)
    assert res.get("count") == 1, res
    integ = tmp_path / "app/frontend/src/pages/TitleDetailPage.jsx"
    assert integ.exists() and "onClick" in integ.read_text()


def test_no_worktrees_dir_is_empty(tmp_path):
    _mk(tmp_path, "app/frontend/src/pages/TitleDetailPage.jsx", _STUB)
    assert reconcile_integration_frontend_pages(tmp_path) == {}


def test_longest_real_candidate_wins_across_worktrees(tmp_path):
    _mk(tmp_path, "app/frontend/src/pages/TitleDetailPage.jsx", _STUB)
    _mk(tmp_path, "worktrees/frontend/app/frontend/src/pages/TitleDetailPage.jsx", _REAL)
    longer = _REAL + "// extra real content: <button onClick={()=>{}}>My List</button>\n" * 3
    _mk(tmp_path, "worktrees/verifier/app/frontend/src/pages/TitleDetailPage.jsx", longer)
    res = reconcile_integration_frontend_pages(tmp_path)
    assert res.get("count") == 1, res
    integ = tmp_path / "app/frontend/src/pages/TitleDetailPage.jsx"
    assert "My List" in integ.read_text()  # the longer real candidate won


def test_never_raises_on_garbage_input():
    # non-existent path must not raise
    assert reconcile_integration_frontend_pages("/nonexistent/path/xyz") == {}


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
