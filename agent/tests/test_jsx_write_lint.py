"""FIX #165 — the write-time syntax guardrail must actually check .jsx (gmrun8 SearchPage.jsx).

file_tools.run_lint reverts a write whose new content has a syntax error (SWE-agent
guardrail: .py→py_compile, .js→node --check, .ts/.tsx→tsc, .json/.yaml→parse). But .jsx
returned ``(True, "")`` UNCONDITIONALLY — `node --check` can't parse JSX (ERR_UNKNOWN_FILE_
EXTENSION), so it was skipped and deferred to the docker build (esbuild). A .jsx truncated
to a missing ``}`` (gmrun8 SearchPage.jsx: 331 ``{`` vs 330 ``}``) therefore sailed through
every write and only surfaced at the post-delivery docker_up (frontend build) → stuck_abort.
esbuild (a JSX-native parser) IS available (npx --no-install esbuild) and catches it at write
time. Degrades gracefully (esbuild absent/timeout → skip, no regression). LOCAL-ONLY.
"""
import shutil
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest  # noqa: E402

from tools.file_tools import run_lint  # noqa: E402

# esbuild is reachable via npx in this env; skip the live-parser tests where it isn't.
def _probe_esbuild() -> bool:
    """`npx` on PATH is not the same as esbuild being usable.

    The linter runs `npx --no-install esbuild <file>` and, by design, degrades to
    "file is fine" whenever the tool is missing — so on a box where esbuild is not
    cached, the broken-JSX test reads that skip as a passing lint and fails. npm
    also exits 0 while printing "npx canceled due to missing packages", so the exit
    code alone cannot answer this either; require esbuild to actually report a
    version on stdout.
    """
    if shutil.which("npx") is None:
        return False
    try:
        import subprocess
        r = subprocess.run(["npx", "--no-install", "esbuild", "--version"],
                           capture_output=True, text=True, timeout=25)
    except Exception:
        return False
    return bool((r.stdout or "").strip()) and "canceled" not in (r.stderr or "")


_HAS_ESBUILD = _probe_esbuild()

_VALID_JSX = (
    "import React from 'react';\n"
    "export default function Card({ items }) {\n"
    "  const label = `count ${items.length} {not a brace}`;  // trailing } { in a comment\n"
    "  const s = \"a string with { an unbalanced brace\";\n"
    "  return (\n"
    "    <div className=\"x\">\n"
    "      {items.map((i) => <span key={i.id}>{i.name}</span>)}\n"
    "    </div>\n"
    "  );\n"
    "}\n"
)

# the gmrun8 failure shape: a component truncated before its final `}`
_BROKEN_JSX = (
    "export default function Search() {\n"
    "  const [q, setQ] = useState('');\n"
    "  return (\n"
    "    <div>\n"
    "      {q && (\n"
    "        <ul>\n"
    "          <li>{q}</li>\n"
    "        </ul>\n"
    "      )}\n"
    "    </div>\n"
    "  );\n"
    "  // missing the closing brace of the function\n"
)


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


@pytest.mark.skipif(not _HAS_ESBUILD, reason="npx/esbuild not available")
def test_valid_jsx_passes(tmp_path):
    ok, err = run_lint(_write(tmp_path, "Card.jsx", _VALID_JSX))
    assert ok is True, err  # tricky-but-valid JSX must not false-positive


@pytest.mark.skipif(not _HAS_ESBUILD, reason="npx/esbuild not available")
def test_broken_jsx_is_flagged(tmp_path):
    ok, err = run_lint(_write(tmp_path, "Search.jsx", _BROKEN_JSX))
    assert ok is False
    assert err  # non-empty error the write path surfaces to the lane


@pytest.mark.skipif(not _HAS_ESBUILD, reason="npx/esbuild not available")
def test_valid_tsx_passes(tmp_path):
    # .tsx already goes through tsc; ensure the change doesn't regress a valid one
    ok, err = run_lint(_write(tmp_path, "Ok.tsx", "export const A = () => <div/>;\n"))
    assert ok is True, err


def test_missing_esbuild_degrades_to_skip(tmp_path, monkeypatch):
    # if esbuild can't run, a .jsx must NOT be flagged (no regression vs the old skip)
    import tools.file_tools as ft

    def _boom(*a, **k):
        raise FileNotFoundError("npx")

    monkeypatch.setattr(ft.subprocess, "run", _boom)
    ok, err = run_lint(_write(tmp_path, "X.jsx", _BROKEN_JSX))
    assert ok is True and err == ""


def test_npx_package_error_not_flagged_as_syntax(tmp_path, monkeypatch):
    # npx failing to resolve esbuild (non-zero, but NOT an esbuild syntax error citing the
    # file) must degrade to skip, not be reported as a syntax error in the file.
    import tools.file_tools as ft

    def _pkg_err(*a, **k):
        return types.SimpleNamespace(
            returncode=1, stdout="",
            stderr="npm ERR! could not determine executable to run")

    monkeypatch.setattr(ft.subprocess, "run", _pkg_err)
    ok, err = run_lint(_write(tmp_path, "Y.jsx", _VALID_JSX))
    assert ok is True and err == ""


def test_non_jsx_paths_unchanged(tmp_path):
    # the fix must not disturb the other branches
    okpy, _ = run_lint(_write(tmp_path, "m.py", "x = 1\n"))
    assert okpy is True
    badpy, epy = run_lint(_write(tmp_path, "b.py", "def f(:\n"))
    assert badpy is False and epy
    okjson, _ = run_lint(_write(tmp_path, "d.json", '{"a": 1}\n'))
    assert okjson is True
    badjson, _ = run_lint(_write(tmp_path, "e.json", '{"a": }\n'))
    assert badjson is False


# ------------------------- real gmrun8 archive empiricism -------------------------

_GM8_SEARCH = (ROOT.parent / "generated" /
               "googlemaps-core-di.gmrun8-3ms-delivered-postdeliver-dockerup-stuck" /
               "app" / "frontend" / "src" / "pages" / "SearchPage.jsx")


@pytest.mark.skipif(not (_HAS_ESBUILD and _GM8_SEARCH.exists()),
                    reason="esbuild or gmrun8 archive absent")
def test_real_gmrun8_searchpage_is_flagged():
    ok, err = run_lint(_GM8_SEARCH)
    assert ok is False, "the real broken SearchPage.jsx must be caught at write time now"
    assert "end of file" in err.lower() or "913" in err
