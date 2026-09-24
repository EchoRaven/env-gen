"""App.jsx routes pointing at an INLINE placeholder div must be re-pointed to the
real page component that exists on disk. outlook run #9: /login -> <div>Login Page
Stub</div> (login DEAD) while functional LoginPage.jsx sat unrouted. LOCAL-ONLY."""
import sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; LLM = ROOT/"env_generator"/"llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path: sys.path.insert(0, str(_p))
from multi_agent.runtime.frontend_scaffold import reroute_inline_stub_routes  # noqa

def _mk():
    d = Path(tempfile.mkdtemp()); (d/"src"/"pages").mkdir(parents=True)
    (d/"src"/"pages"/"LoginPage.jsx").write_text("export default function LoginPage(){return <form onSubmit={x}>"+"x"*200+"</form>}")
    (d/"src"/"pages"/"InboxPage.jsx").write_text("export default function InboxPage(){return <div className=\"divide-y\">"+"x"*200+"</div>}")
    (d/"src"/"App.jsx").write_text('''import { Routes, Route } from 'react-router-dom';
export default function App(){return(<Routes>
<Route path="/login" element={<div>Login Page Stub</div>} />
<Route path="/inbox" element={<div>Inbox Page Stub</div>} />
<Route path="/messages" element={<MessagesPage/>} />
</Routes>);}''')
    return d

def test_inline_stub_routes_repointed_to_real_pages():
    d = _mk(); out = reroute_inline_stub_routes(d)
    app = (d/"src"/"App.jsx").read_text()
    assert set(out["rerouted"]) == {"/login -> LoginPage", "/inbox -> InboxPage"}
    assert "<LoginPage" in app and "<InboxPage" in app
    assert "Login Page Stub" not in app and "Inbox Page Stub" not in app
    assert "import LoginPage from './pages/LoginPage'" in app

def test_real_routes_untouched():
    d = _mk(); reroute_inline_stub_routes(d)
    app = (d/"src"/"App.jsx").read_text()
    assert "<MessagesPage/>" in app  # already-real route unchanged

if __name__ == "__main__":
    import pytest; raise SystemExit(pytest.main([__file__, "-q"]))
