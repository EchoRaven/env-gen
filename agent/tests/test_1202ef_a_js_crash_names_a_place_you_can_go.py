r"""#1202ef: every generated app minifies, so every JS crash is unactionable.

`sourcemap` appeared ZERO times in the whole agent/ tree. The generated Vite config was

    build: { outDir: 'dist' },

so Rollup minified, and every runtime error in every generated app in every run was
reported at a position no reader could resolve:

    TypeError: (void 0) is not a function
        at http://localhost:8005/assets/index-CA-T_HGA.js:252:30568
        at $l (...)

That is tiktok-web-r96. All twelve routes rendered blank, the debugger triaged it to the
frontend lane at 02:08, and the run ended undelivered at $163 with the bug unlanded.

`$l` is the whole problem. A lane has `read` and `grep`, not a sourcemap resolver, and
Playwright reports the RAW stack -- so `minify: false` is the half that reaches the
reader, and `sourcemap: true` is the complement for anything that can consume a .map.
"""
from pathlib import Path

import pytest

THIS_DIR = Path(__file__).resolve().parent
SCAFFOLD = (THIS_DIR.parent / "env_generator" / "llm_generator" / "multi_agent"
            / "runtime" / "frontend_scaffold.py").read_text(encoding="utf-8")


def _build_line():
    i = SCAFFOLD.index("outDir: 'dist'")
    return SCAFFOLD[SCAFFOLD.rindex("build:", 0, i):SCAFFOLD.index("\n", i)]


def test_the_bundle_is_readable():
    """A minified frame names `$l`; an unminified one names the component."""
    assert "minify: false" in _build_line()


def test_a_sourcemap_is_emitted():
    assert "sourcemap: true" in _build_line()


def test_the_output_directory_is_unchanged():
    """nginx serves dist/ -- this fix must not move it."""
    assert "outDir: 'dist'" in _build_line()


def test_the_reasoning_survives_next_to_the_flags():
    """A future reader must find why, or the next size-conscious edit reverts it."""
    i = SCAFFOLD.index("#1202ef")
    seg = SCAFFOLD[i:SCAFFOLD.index("outDir: 'dist'", i)]
    assert "r96" in seg
    assert "minify" in seg


def test_unminified_is_the_half_that_needs_no_preserved_bundle():
    """Why `minify: false` carries this fix and `sourcemap: true` only assists.

    The Dockerfile is multi-stage -- `COPY --from=builder /app/dist ...` -- so the built
    bundle lives only inside the image and the builder layer is discarded. Measured: 0 of
    135 run directories on this box contain a dist/assets. A minified frame therefore
    names a position in a file that exists NOWHERE after the run, and neither the .map nor
    the bundle can be consulted.

    An UNMINIFIED frame names the component, and components exist in src/ -- which every
    run does preserve. That is what makes the crash findable after the fact.
    """
    line = _build_line()
    assert "minify: false" in line
    i = SCAFFOLD.index("#1202ef")
    assert "read" in SCAFFOLD[i:SCAFFOLD.index("outDir: 'dist'", i)]


def test_this_is_the_config_that_ships():
    """Guard against the flags landing in a template nothing renders."""
    i = SCAFFOLD.index("#1202ef")
    seg = SCAFFOLD[SCAFFOLD.rindex("export default defineConfig", 0, i):]
    assert "safeIconImports()" in seg, "not the rendered vite config"
