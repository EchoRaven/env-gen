"""#1089 — `audit_ui_component` never asked whether anything renders the component.

Its checks are file presence, declared APIs referenced, and no dead controls in its own file.
A component whose file exists and whose apis are called from a service module therefore flips
to `implemented` while no page ever mounts it — dead UI, which is the one thing the project's
standing rule about UI forbids outright.

Measured over the 67 delivered frontends: **144 of the 1003 registered components whose file
exists are never rendered** — no `<Name>` anywhere in src. LoginForm (8 runs), SignupForm (7),
FooterLinks (6), MessagesDock, SideNavigation, PostDetailModal, TopBar (4 each).

The same shape, one layer out and worse, is the auth UI. The prompt makes
`src/components/TenantPicker.jsx` MANDATORY and says LoginPage "embeds `<TenantPicker/>`";
`backend_skeleton` mounts `GET /api/v1/tenants` specifically *"because the login template's
TenantPicker calls it on MOUNT"*. In the delivered corpus **63 apps carry the file and 39 of
them (62%) never mount it** — the backend provisions an endpoint for a picker the app does not
show, and the multi-tenancy UI is invisible. That one is invisible to this audit for a
separate reason (TenantPicker is registered in 0 of 63 runs), and is recorded here because it
is the same defect measured from the other side.

Deliberately SOFT. The component audit's verdict flips a component between `implemented` and
`defined` and does NOT reach the delivery gate (`components_implemented` appears nowhere in
delivery_gate/deliverability), and the message is kept clear of `_HARD_MISS_MARKERS` so it
cannot become one by accident. A run must not wedge on this; the lane must simply stop being
told a component is finished when nothing shows it.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import mkdtemp

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.frontend_audit import (_is_hard_miss,  # noqa: E402
                                                audit_ui_component)

_PICKER = """import { useEffect, useState } from 'react';
export default function TenantPicker() {
  const [rows, setRows] = useState([]);
  useEffect(() => { fetch('/api/v1/tenants').then(r => r.json()).then(d => setRows(d.items || [])); }, []);
  return (<select onChange={(e) => localStorage.setItem('X_TENANT_ID', e.target.value)}>
    {rows.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
  </select>);
}
"""

_COMP = {"name": "tenant_picker", "component": "TenantPicker",
         "apis_used": ["GET /api/v1/tenants"]}


def _tree(login_body: str) -> Path:
    src = Path(mkdtemp()) / "src"
    (src / "pages").mkdir(parents=True)
    (src / "components").mkdir(parents=True)
    (src / "App.jsx").write_text(
        "import LoginPage from './pages/LoginPage';\n"
        "export default function App(){ return <LoginPage/>; }\n", encoding="utf-8")
    (src / "pages" / "LoginPage.jsx").write_text(login_body, encoding="utf-8")
    (src / "components" / "TenantPicker.jsx").write_text(_PICKER, encoding="utf-8")
    return src


_MOUNTS = """import TenantPicker from '../components/TenantPicker';
export default function LoginPage() {
  return (<form><input name="email"/><TenantPicker/>
    <button onClick={() => {}}>Sign in</button></form>);
}
"""
_DOES_NOT = """export default function LoginPage() {
  return (<form><input name="email"/>
    <button onClick={() => {}}>Sign in</button></form>);
}
"""
_CREATE_ELEMENT = """import React from 'react';
import TenantPicker from '../components/TenantPicker';
export default function LoginPage() {
  return React.createElement('form', null, React.createElement(TenantPicker, null));
}
"""


class AComponentNothingMountsIsNotImplemented(unittest.TestCase):

    def test_an_unmounted_component_is_reported(self):
        ok, missing = audit_ui_component(_tree(_DOES_NOT), dict(_COMP))
        self.assertFalse(ok, "an unmounted component still audits as implemented")
        hit = [m for m in missing if "TenantPicker" in m and "never rendered" in m]
        self.assertTrue(hit, missing)

    def test_a_mounted_component_is_unaffected(self):
        ok, missing = audit_ui_component(_tree(_MOUNTS), dict(_COMP))
        self.assertTrue(ok, missing)

    def test_create_element_counts_as_rendering(self):
        ok, missing = audit_ui_component(_tree(_CREATE_ELEMENT), dict(_COMP))
        self.assertTrue(ok, missing)


class TheFindingIsSoft(unittest.TestCase):
    """The safety property. This must never wedge a run — see the module docstring."""

    def test_it_is_not_a_hard_miss(self):
        _, missing = audit_ui_component(_tree(_DOES_NOT), dict(_COMP))
        for m in missing:
            if "never rendered" in m:
                self.assertFalse(_is_hard_miss(m),
                                 f"the new finding became a delivery blocker: {m}")


class TheExistingChecksAreUnchanged(unittest.TestCase):

    def test_a_missing_file_still_says_not_found(self):
        src = _tree(_DOES_NOT)
        (src / "components" / "TenantPicker.jsx").unlink()
        ok, missing = audit_ui_component(src, dict(_COMP))
        self.assertFalse(ok)
        self.assertTrue([m for m in missing if "not found" in m], missing)

    def test_an_unreferenced_api_still_reports(self):
        comp = dict(_COMP, apis_used=["GET /api/absent/thing"])
        _, missing = audit_ui_component(_tree(_MOUNTS), comp)
        self.assertTrue([m for m in missing if "never referenced" in m], missing)


if __name__ == "__main__":
    unittest.main()
