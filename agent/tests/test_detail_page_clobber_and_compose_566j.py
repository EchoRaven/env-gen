r"""#566j (netflix r117/r120 M1 75-min no-deliver abort on deliverability_ui_page_unwired): two
compounding framework bugs that clobbered a real detail page and then mis-flagged it inert.

(a) wire_detail_modal_534 overwrote a REAL lane-authored detail PAGE (a 230-line TitleDetailPage that
    fetches + renders the detail) with an 11-line modal-mount. Its only guard skipped when the page
    already mounted the modal — not when the page was a genuine lane page. Fix: never clobber a real
    lane page (has real api call + no framework marker); only re-project a framework mis-projection/stub.

(b) frontend_audit._composes_child regex `components/\w+['"]` missed a `.jsx`-extension import
    (`import X from '../components/X.jsx'`), so a page that mounts `<X/>` from a .jsx import was falsely
    flagged an inert placeholder stub → ui_page_unwired. Fix: make the import path extension-agnostic.
"""
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.frontend_audit import audit_ui_page
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import wire_detail_modal_534

# ── (b) audit: a page composing a child via a .jsx import is NOT inert ──────────────────────
_APP = """import { BrowserRouter, Routes, Route } from 'react-router-dom';
import TitleDetailPage from './pages/TitleDetailPage.jsx';
export default function App(){return(<BrowserRouter><Routes>
<Route path="/title/:id" element={<TitleDetailPage />} />
</Routes></BrowserRouter>);}
"""
_PAGE_COMPOSES_JSX = """import { useParams } from 'react-router-dom';
import TitleDetailModal from '../components/TitleDetailModal.jsx';
export default function TitleDetailPage(){
  const p = useParams();
  return <TitleDetailModal titleId={p.id} />;
}
"""


def _mk(fsrc: Path, name: str, text: str):
    p = fsrc / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_composes_child_via_jsx_import_not_flagged_inert(tmp_path):
    fsrc = tmp_path / "src"
    _mk(fsrc, "App.jsx", _APP)
    _mk(fsrc, "pages/TitleDetailPage.jsx", _PAGE_COMPOSES_JSX)
    page = {"name": "title_detail", "route": "/title/:id",
            "component": "TitleDetailPage", "apis_used": ["GET /api/titles/{id}"]}
    ok, missing = audit_ui_page(fsrc, page)
    stub = [m for m in missing if "placeholder stub" in m]
    assert not stub, f"composing (.jsx import) page wrongly flagged inert: {missing}"


# ── (a) #534: never clobber a real lane detail page ────────────────────────────────────────
_MODAL = """export default function TitleDetailModal({ titleId, onClose }){
  return <div className="modal">detail {titleId}</div>;
}
"""
_REAL_PAGE = """import { useParams } from 'react-router-dom';
import { useEffect, useState } from 'react';
export default function TitleDetailPage(){
  const { id } = useParams();
  const [t,setT]=useState(null);
  useEffect(()=>{ fetch(`/api/titles/${id}`).then(r=>r.json()).then(setT); },[id]);
  return (<div><h1>{t&&t.name}</h1><button onClick={()=>{}}>Play</button>
    <section>hero + metadata + episodes …</section></div>);
}
"""
_STUB_PLAYER = """export default function TitleDetailPage(){
  return <video src="" controls />;
}
"""


def _frontend(tmp_path, page_text):
    fd = tmp_path
    _mk(fd / "src", "components/TitleDetailModal.jsx", _MODAL)
    _mk(fd / "src", "App.jsx", _APP)
    _mk(fd / "src", "pages/TitleDetailPage.jsx", page_text)
    return fd


def test_534_does_not_clobber_real_lane_detail_page(tmp_path):
    fd = _frontend(tmp_path, _REAL_PAGE)
    before = (fd / "src/pages/TitleDetailPage.jsx").read_text()
    res = wire_detail_modal_534(fd)
    assert res.get("wired") is None, res              # skipped
    assert (fd / "src/pages/TitleDetailPage.jsx").read_text() == before  # real page preserved


def test_534_still_wires_modal_over_a_stub_player(tmp_path):
    fd = _frontend(tmp_path, _STUB_PLAYER)
    res = wire_detail_modal_534(fd)
    assert res.get("wired") == "TitleDetailPage", res  # a thin non-fetching page → re-projected
    now = (fd / "src/pages/TitleDetailPage.jsx").read_text()
    assert "TitleDetailModal" in now and "framework-wired detail modal" in now


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
