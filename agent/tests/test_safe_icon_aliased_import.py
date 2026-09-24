"""Regression: the safe-icon Vite plugin must survive ALIASED icon imports.

Real failure (outlook 2026-06-30): `import { Calendar as CalendarIcon } from
'lucide-react'`. The plugin rewrites the import but KEEPS the `as` alias, so the
rewritten import references the REAL export name (`Calendar`). The plugin's
``load`` used to export the LOCAL name (`CalendarIcon`) → the virtual module had
no `Calendar` export → Rollup "Calendar is not exported" → vite build fail →
docker_up wedge → the whole run aborted WITHOUT delivery.

The plugin must export the REAL name (the alias is applied by the import
statement). This test extracts the ACTUAL framework template (``_BASELINE_VITE``),
runs the plugin's transform+load in Node (pure string logic, no npm), and asserts
the export names match what the rewritten import references — for aliased, plain,
duplicate-real, and hallucinated specifiers.
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.frontend_scaffold import _BASELINE_VITE  # noqa: E402

node = shutil.which("node")
pytestmark = pytest.mark.skipif(not node, reason="node not available")


def _plugin_src() -> str:
    """Extract the standalone `function safeIconImports() {...}` (pure string
    logic; no vite/react import needed to exercise transform+load)."""
    m = re.search(r"function safeIconImports\(\)\s*\{.*?\n\}\n", _BASELINE_VITE, re.DOTALL)
    assert m, "safeIconImports() not found in _BASELINE_VITE"
    return m.group(0)


def _run(import_line: str) -> dict:
    """Transform `import_line`, then load the produced virtual module; return
    {referenced:[names the rewritten import asks the module for], exported:[names
    the module actually exports]}."""
    harness = _plugin_src() + r"""
const p = safeIconImports();
const CODE = %s;
const t = p.transform(CODE, "App.jsx");
const out = t && t.code ? t.code : CODE;
// the rewritten import: `import { <specs> } from "<virtual>"`. Capture the FULL
// quoted module-source literal and JSON.parse it — in a real Rollup pipeline the
// transform output is PARSED, decoding the unicode  escape back to the null-prefixed
// virtual id that resolveId/load match on (the plugin builds it via JSON.stringify).
const mm = out.match(/import\s*\{([^}]*)\}\s*from\s*("(?:[^"\\]|\\.)*")/);
const specs = mm[1].split(',').map(s => s.trim()).filter(Boolean);
// names the import REFERENCES from the module = the part before `as`
const referenced = specs.map(s => s.split(/\s+as\s+/)[0].trim());
const vid = JSON.parse(mm[2]);
const loaded = p.load(vid) || "";
const exported = [...loaded.matchAll(/export const (\w+)\s*=/g)].map(x => x[1]);
console.log(JSON.stringify({ referenced, exported }));
""" % json.dumps(import_line)
    r = subprocess.run([node, "--input-type=module", "-e", harness],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"node harness failed: {r.stderr}"
    return json.loads(r.stdout.strip().splitlines()[-1])


def _assert_covers(import_line: str):
    res = _run(import_line)
    missing = [n for n in res["referenced"] if n not in res["exported"]]
    assert not missing, (
        f"{import_line!r}: virtual module does NOT export {missing} that the "
        f"rewritten import references (exported={res['exported']}) — Rollup would "
        f"fail with 'is not exported'")


def test_aliased_real_icon():
    # the exact outlook failure
    _assert_covers("import { Calendar as CalendarIcon, CalendarDays } from 'lucide-react'")


def test_plain_named_icons():
    _assert_covers("import { Inbox, Mail, Send } from 'lucide-react'")


def test_mixed_alias_and_plain_and_hallucinated():
    _assert_covers("import { Calendar as Cal, Inbox, TotallyFakeIcon as Fake } from 'lucide-react'")


def test_same_real_name_twice_dedups_without_double_export():
    res = _run("import { Calendar, Calendar as Cal2 } from 'lucide-react'")
    for n in res["referenced"]:
        assert n in res["exported"]
    # `Calendar` exported exactly once (a double `export const Calendar` is a JS error)
    assert res["exported"].count("Calendar") == 1


def test_heroicons_aliased_too():
    _assert_covers("import { ArrowRightIcon as Next } from '@heroicons/react/24/outline'")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
