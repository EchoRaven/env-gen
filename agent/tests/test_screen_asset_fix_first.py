"""A1 (quality direction: visual similarity) — screen-scoped FIRST-POSITION real-asset fixes.

verify-cause基础 (run70/run68 归档实证): design_system assets 无 wordmark、type=文件格式非语义;
但 63/98 组件已带 components[].assets 映射 (login hero → instagram glyph)。所以 A1 不加 analyst
字段, 而是把已有的 per-component 映射升级为 per-screen 首条 remediation fix:
- audit_asset_usage 增 unused_by_screen (per-screen scoping, unused_mapped 语义不变);
- remediation_text 在每个 FAILING+未latch 屏 section 的最前面插 "use the real staged asset"
  块, 目标文件用 screen.route ↔ ui_page.route 对齐解析 (shared/hubs/registryhub_ui_pages.json),
  不做名字模糊匹配;
- 已在首条块出现的 (component, asset) 不再重复出现在尾部全局 advisory;
- 每次构建打一行稳定前缀日志 "BRAND-ASSET AUDIT:" (跨 run grep 趋势);
- ENVGEN_BRAND_ASSET_FIX=0 关闭首条化, 回退现状 (纯尾部 advisory)。
LOCAL-ONLY (agent/tests/ gitignored).
"""

import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.frontend_audit import audit_asset_usage  # noqa: E402
from multi_agent.runtime.visual_fidelity import remediation_text  # noqa: E402


def _ds():
    return {
        "assets": [
            {"id": "ig-glyph", "file": "icons/Instagram_efa13859.svg",
             "staged_path": "public/assets/icons/Instagram_efa13859.svg", "type": "svg"},
            {"id": "heart", "file": "icons/heart.svg", "type": "svg"},
        ],
        "screens": [
            {"name": "login_light", "route": "/login", "kind": "page", "components": [
                {"id": "hero-section", "assets": ["ig-glyph"]},
            ]},
            {"name": "home", "route": "/", "kind": "page", "components": [
                {"id": "post-actions", "assets": ["heart"]},
            ]},
        ],
    }


def _mk_out(tmp_path, src_files=None, ui_pages=None):
    out = tmp_path / "out"
    (out / "design").mkdir(parents=True)
    (out / "design" / "design_system.json").write_text(json.dumps(_ds()))
    src = out / "app" / "frontend" / "src"
    src.mkdir(parents=True)
    for rel, content in (src_files or {"App.jsx": "export default () => <div/>;"}).items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    if ui_pages is not None:
        hubs = out / "shared" / "hubs"
        hubs.mkdir(parents=True)
        (hubs / "registryhub_ui_pages.json").write_text(json.dumps(ui_pages))
    return out


_UI_PAGES = {
    "_meta": {"version": 2},
    "login": {"name": "login", "route": "/login", "component": "LoginPage",
              "status": "implemented"},
    "home_feed": {"name": "home_feed", "route": "/", "component": "HomeFeedPage",
                  "status": "implemented"},
}


def _failing_login_result():
    return {"screens": [
        {"name": "login_light", "route": "/login", "similarity": 0.30, "passed": False,
         "dimensions": {}, "deviations": [], "fixes": ["fix the button color"]},
    ]}


def test_audit_returns_unused_by_screen(tmp_path):
    out = _mk_out(tmp_path)
    res = audit_asset_usage(out / "app" / "frontend", _ds())
    # back-compat: unused_mapped unchanged (both assets unreferenced)
    assert {(u["component"], u["asset"]) for u in res["unused_mapped"]} == {
        ("hero-section", "ig-glyph"), ("post-actions", "heart")}
    by = res["unused_by_screen"]
    assert {(u["component"], u["asset"]) for u in by["login_light"]} == {
        ("hero-section", "ig-glyph")}
    assert {(u["component"], u["asset"]) for u in by["home"]} == {
        ("post-actions", "heart")}


def test_failing_screen_gets_first_position_asset_fix(tmp_path):
    out = _mk_out(tmp_path, ui_pages=_UI_PAGES)
    text = remediation_text(_failing_login_result(), str(out))
    sect = text[text.index("## login_light"):]
    assert "/assets/icons/Instagram_efa13859.svg" in sect
    assert "LoginPage" in sect, "route /login must resolve to the ui_page component file"
    # FIRST position: the asset mandate precedes the judge fixes in the section
    assert sect.index("Instagram_efa13859.svg") < sect.index("fix the button color")
    # the pair already fixed first-position must NOT be duplicated in the tail advisory
    tail = text[text.index("Real assets not used"):] if "Real assets not used" in text else ""
    assert "Instagram_efa13859.svg" not in tail
    # home screen is not failing → its heart asset stays in the tail advisory
    assert "heart.svg" in text


def test_latched_screen_keeps_tail_advisory_only(tmp_path):
    out = _mk_out(tmp_path, ui_pages=_UI_PAGES)
    text = remediation_text(_failing_login_result(), str(out), latched={"login_light"})
    assert "## login_light" not in text  # latched → whole section skipped (existing #129)
    assert "Instagram_efa13859.svg" in text, "still visible in the tail advisory"


def test_disable_switch_restores_old_behavior(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVGEN_BRAND_ASSET_FIX", "0")
    out = _mk_out(tmp_path, ui_pages=_UI_PAGES)
    text = remediation_text(_failing_login_result(), str(out))
    sect = text[text.index("## login_light"):text.index("Real assets not used")]
    assert "Instagram_efa13859.svg" not in sect, "disabled → no first-position block"
    assert "Instagram_efa13859.svg" in text, "tail advisory unchanged"


def test_brand_asset_audit_log_line(tmp_path):
    out = _mk_out(tmp_path, ui_pages=_UI_PAGES)
    recs = []
    h = logging.Handler()
    h.emit = lambda r: recs.append(r.getMessage())
    lg = logging.getLogger("multi_agent.runtime.visual_fidelity")
    lg.addHandler(h)
    lg.setLevel(logging.INFO)
    try:
        remediation_text(_failing_login_result(), str(out))
    finally:
        lg.removeHandler(h)
    hits = [m for m in recs if m.startswith("BRAND-ASSET AUDIT:")]
    assert hits, "a stable-prefix per-round count line must be logged"
    assert "1" in hits[0]  # 1 unused asset on failing screens this round


def test_no_uipages_registry_is_graceful(tmp_path):
    out = _mk_out(tmp_path, ui_pages=None)  # no shared/hubs at all
    text = remediation_text(_failing_login_result(), str(out))
    sect = text[text.index("## login_light"):]
    assert "/assets/icons/Instagram_efa13859.svg" in sect, \
        "no registry → still mandate the asset (file resolution degrades gracefully)"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
