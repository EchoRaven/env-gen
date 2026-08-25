"""#1090 — the framework mandates TenantPicker, provisions its endpoint, and never looks at it.

`agents_config.yaml` gates the frontend lane's finish on the file existing:

    # mandatory auth/tenancy UI (login_tenant_template)
    - ["app/frontend/src/components/TenantPicker.jsx", ".../TenantPicker.tsx"]

`backend_skeleton` mounts `GET /api/v1/tenants` for it by name: *"the login template's
TenantPicker calls GET /api/v1/tenants on MOUNT … a picker that can't validate its tenant can
WEDGE the whole login"*. And the prompt makes `LoginPage.jsx` embed `<TenantPicker/>`.

Three places mandate it; none checks the outcome. Measured over the delivered corpus: **63
apps carry the file, 39 of them (62%) never mount it** — no `<TenantPicker>` anywhere in src.
The backend provisions an endpoint for a picker the app does not show, and the multi-tenancy
UI is invisible. #1089 added the check that would catch this, but it is registry-driven and
**TenantPicker is registered in 0 of 63 runs**, so it stayed invisible.

Register what you mandate: with the record present, #1089's existing SOFT check reports it,
which is the actionable truth ("render it from the page that owns it"), through a channel that
cannot wedge a run.

Only TenantPicker, not its LoginPage sibling from the same YAML group — the two are mandated
as FILES but differ in KIND. LoginPage is a routed page (in the corpus every `/login` renders
one) and registering a page as a component would be the mis-declaration #1087 had to undo.
A drift guard here reads the YAML, so the constant cannot quietly stop matching what the
framework actually mandates.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.frontend_audit import (  # noqa: E402
    _MANDATED_UI_COMPONENTS_1090, audit_ui_component,
    register_mandated_ui_components_1090)
from multi_agent.runtime.registryhub import RegistryHub  # noqa: E402

_PICKER = """import { useEffect, useState } from 'react';
export default function TenantPicker() {
  const [rows, setRows] = useState([]);
  useEffect(() => { fetch('/api/v1/tenants').then(r => r.json()).then(d => setRows(d.items || [])); }, []);
  return (<select onChange={(e) => localStorage.setItem('X_TENANT_ID', e.target.value)}>
    {rows.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}</select>);
}
"""


class _Out:
    def __init__(self, with_picker=True, mounted=False):
        self.root = Path(tempfile.mkdtemp(prefix="mand_1090_"))
        src = self.root / "app" / "frontend" / "src"
        (src / "components").mkdir(parents=True)
        (src / "pages").mkdir(parents=True)
        body = ("import TenantPicker from '../components/TenantPicker';\n"
                "export default function LoginPage(){ return <TenantPicker/>; }\n"
                if mounted else
                "export default function LoginPage(){ return <form/>; }\n")
        (src / "pages" / "LoginPage.jsx").write_text(body, encoding="utf-8")
        (src / "App.jsx").write_text(
            "import LoginPage from './pages/LoginPage';\n"
            "export default function App(){ return <LoginPage/>; }\n", encoding="utf-8")
        if with_picker:
            (src / "components" / "TenantPicker.jsx").write_text(_PICKER, encoding="utf-8")
        self.src = src

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)


class ItRegistersTheMandatedComponent(unittest.TestCase):

    def setUp(self):
        self.hub = Path(tempfile.mkdtemp(prefix="hub_1090_"))
        self.rh = RegistryHub(self.hub)

    def tearDown(self):
        shutil.rmtree(self.hub, ignore_errors=True)

    def test_a_present_picker_is_registered(self):
        out = _Out()
        try:
            register_mandated_ui_components_1090(out.root, self.rh)
            comps = self.rh.list_ui_components() or {}
            self.assertIn("tenant_picker", comps)
            self.assertEqual(comps["tenant_picker"].get("component"), "TenantPicker")
        finally:
            out.close()

    def test_an_absent_picker_registers_nothing(self):
        out = _Out(with_picker=False)
        try:
            register_mandated_ui_components_1090(out.root, self.rh)
            self.assertEqual(self.rh.list_ui_components() or {}, {})
        finally:
            out.close()

    def test_an_existing_registration_is_left_alone(self):
        out = _Out()
        try:
            self.rh.register_ui_component(name="tenant_picker", component="TenantPickerX",
                                          agent="frontend")
            register_mandated_ui_components_1090(out.root, self.rh)
            comps = self.rh.list_ui_components() or {}
            self.assertEqual(comps["tenant_picker"].get("component"), "TenantPickerX")
        finally:
            out.close()

    def test_no_hub_never_raises(self):
        out = _Out()
        try:
            self.assertEqual(register_mandated_ui_components_1090(out.root, None), [])
        finally:
            out.close()


class AndThenTheAuditSeesIt(unittest.TestCase):
    """The point of registering: #1089's soft check finally applies to it."""

    def setUp(self):
        self.hub = Path(tempfile.mkdtemp(prefix="hub2_1090_"))
        self.rh = RegistryHub(self.hub)

    def tearDown(self):
        shutil.rmtree(self.hub, ignore_errors=True)

    def test_an_unmounted_picker_is_reported(self):
        out = _Out(mounted=False)
        try:
            register_mandated_ui_components_1090(out.root, self.rh)
            comp = (self.rh.list_ui_components() or {})["tenant_picker"]
            ok, missing = audit_ui_component(out.src, comp)
            self.assertFalse(ok)
            self.assertTrue([m for m in missing if "never rendered" in m], missing)
        finally:
            out.close()

    def test_a_mounted_picker_is_clean(self):
        out = _Out(mounted=True)
        try:
            register_mandated_ui_components_1090(out.root, self.rh)
            comp = (self.rh.list_ui_components() or {})["tenant_picker"]
            ok, missing = audit_ui_component(out.src, comp)
            self.assertTrue(ok, missing)
        finally:
            out.close()


class TheConstantCannotDriftFromTheYaml(unittest.TestCase):

    def test_the_yaml_still_mandates_every_name_we_carry(self):
        cfg = (LLM_DIR / "multi_agent" / "agents" / "agents_config.yaml").read_text(
            encoding="utf-8")
        for name in _MANDATED_UI_COMPONENTS_1090:
            self.assertIn(f"components/{name}.jsx", cfg,
                          f"{name} is no longer mandated by agents_config.yaml")


if __name__ == "__main__":
    unittest.main()
