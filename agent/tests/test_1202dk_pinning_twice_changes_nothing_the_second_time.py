r"""#1202dk: the pin rewrites package.json every time and calls it a change.

`pin_frontend_build_tooling` is careful everywhere but one place. Each infra file is written
only when it differs:

    if (not p.exists()) or p.read_text(...) != content:
        _fw_write_1202cw(p, content); changed.append(rel)

`package.json` is the exception — it is serialized and written unconditionally, and
``changed.append("package.json")`` runs whether or not a byte moved. `pinned` is
``bool(changed)``, so the warning fires on every pass. netflix-r42 logged

    Frontend build tooling pinned to known-good: ['package.json']

**72 times**, and `nothing to commit after squash` 77 times beside it.

Three costs, in increasing order of seriousness:

  1. 72 identical rewrites of a file nobody changed.
  2. `changed` reports a change that did not happen, so the return value cannot be used to
     decide anything.
  3. #1114's hazard, which this repo has already paid for once: the framework re-projecting
     byte-identical content still moves mtime, and #1023 read that as progress — reporting a
     still-failing P0 as "possibly resolved". A write that announces itself as a change is
     the same lie one layer up.

The fix is the idiom the rest of the function already uses: serialize, compare, write only on
difference. Pinning must stay idempotent in EFFECT — the second call must still guarantee the
pinned versions and the forced `build` script — while reporting honestly that nothing moved.
"""
import json
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    pin_frontend_build_tooling,
)


def _fe(tmp_path: Path) -> Path:
    fe = tmp_path / "app" / "frontend"
    (fe / "src").mkdir(parents=True)
    (fe / "package.json").write_text(json.dumps({
        "name": "app", "version": "0.0.0",
        "dependencies": {"react": "18.2.0"},
        "scripts": {"build": "vite build"},
    }, indent=2) + "\n", encoding="utf-8")
    (fe / "src" / "main.jsx").write_text(
        "import './index.css';\nimport './bc_auth.js';\nconsole.log(1);\n", encoding="utf-8")
    return fe


def test_the_second_pin_reports_no_change(tmp_path):
    """The whole defect in one assertion."""
    fe = _fe(tmp_path)
    pin_frontend_build_tooling(fe)          # first pass does the real work
    second = pin_frontend_build_tooling(fe)
    assert second.get("changed") == [], (
        "the pin still reports a change on an unchanged tree — r42 logged this 72 times: %r"
        % (second.get("changed"),))
    assert not second.get("pinned")


def test_the_second_pin_does_not_rewrite_package_json(tmp_path):
    """Not just quieter — it must not touch the file."""
    fe = _fe(tmp_path)
    pin_frontend_build_tooling(fe)
    pj = fe / "package.json"
    before_text = pj.read_text(encoding="utf-8")
    before_mtime = pj.stat().st_mtime_ns
    pin_frontend_build_tooling(fe)
    assert pj.read_text(encoding="utf-8") == before_text
    assert pj.stat().st_mtime_ns == before_mtime, (
        "package.json was rewritten byte-identically; #1114 is the cost of that")


def test_the_pin_still_pins(tmp_path):
    """Idempotent in effect: the guarantees #44 exists for are unchanged."""
    fe = _fe(tmp_path)
    pin_frontend_build_tooling(fe)
    data = json.loads((fe / "package.json").read_text(encoding="utf-8"))
    assert data["scripts"]["build"] == "vite build"
    dev = data.get("devDependencies") or {}
    deps = data.get("dependencies") or {}
    assert "tailwindcss" in dev or "tailwindcss" in deps


def test_a_lane_that_breaks_the_build_script_is_repaired_again(tmp_path):
    """Reporting honestly must not become failing to act."""
    fe = _fe(tmp_path)
    pin_frontend_build_tooling(fe)
    pj = fe / "package.json"
    data = json.loads(pj.read_text(encoding="utf-8"))
    data["scripts"]["build"] = "echo nope"
    pj.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    res = pin_frontend_build_tooling(fe)
    assert "package.json" in (res.get("changed") or []), res
    assert json.loads(pj.read_text(encoding="utf-8"))["scripts"]["build"] == "vite build"


def test_a_lane_that_unpins_tailwind_is_repaired_again(tmp_path):
    fe = _fe(tmp_path)
    pin_frontend_build_tooling(fe)
    pj = fe / "package.json"
    data = json.loads(pj.read_text(encoding="utf-8"))
    for section in ("dependencies", "devDependencies"):
        if "tailwindcss" in (data.get(section) or {}):
            data[section]["tailwindcss"] = "latest"
    pj.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    res = pin_frontend_build_tooling(fe)
    assert "package.json" in (res.get("changed") or []), res
    data = json.loads(pj.read_text(encoding="utf-8"))
    merged = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
    assert merged["tailwindcss"] != "latest"
