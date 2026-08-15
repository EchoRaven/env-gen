r"""#763: the framework holds the lane to `node --check` and never checks the JS it emits itself.

`file_tools` runs `node --check` on what an AGENT writes. `frontend_scaffold` writes JavaScript
into the app directly — the two auto-stub repair passes (#753, #761), among others — and nothing
verifies it parses. A malformed snippet is not a small defect there: it breaks the vite build,
which wedges `docker compose up`, which is how a run loses its whole frontend (the failure family
#75x traces).

Found by asking what #471 could not: that file guards emitted JS with SUBSTRING assertions,
which is the only cheap option inside pytest — but node is available in this environment, so the
stronger check is affordable and was simply never made.

Both passes emit valid ESM today; this is the regression guard, not a bug report. It is written
as ESM (`.mjs`) deliberately: my first attempt checked a `.js` file and node rejected `export`
outright, which is a property of the harness and not of the emitted code.
"""
import pathlib
import shutil
import subprocess
import tempfile

import pytest

from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs


pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node is not available; the parse check needs it")


def _node_check(js: str):
    d = pathlib.Path(tempfile.mkdtemp())
    p = d / "emitted.mjs"          # ESM: the framework emits `export const ...`
    p.write_text(js, encoding="utf-8")
    r = subprocess.run(["node", "--check", str(p)], capture_output=True, text=True, timeout=60)
    return r.returncode, (r.stderr or "")[:400]


def _emit_api(names):
    d = pathlib.Path(tempfile.mkdtemp())
    src = d / "src"
    (src / "services").mkdir(parents=True)
    (src / "pages").mkdir(parents=True)
    (src / "services" / "api.js").write_text("export const other = 1;\n", encoding="utf-8")
    (src / "pages" / "P.jsx").write_text(
        "import { %s } from '../services/api';\n" % ", ".join(names), encoding="utf-8")
    fs.repair_frontend_api_exports(d)
    return (src / "services" / "api.js").read_text(encoding="utf-8")


def _emit_local(names):
    d = pathlib.Path(tempfile.mkdtemp())
    src = d / "src"
    (src / "pages").mkdir(parents=True)
    (src / "helpers.js").write_text("export const other = 1;\n", encoding="utf-8")
    (src / "pages" / "P.jsx").write_text(
        "import { %s } from '../helpers';\n" % ", ".join(names), encoding="utf-8")
    fs.repair_frontend_missing_local_exports(d)
    return (src / "helpers.js").read_text(encoding="utf-8")


_NAMES = ["isAuthenticated", "getActiveProfileId", "listTitles", "searchTitles",
          "hasAccess", "canPlay", "fetchOne", "HeroBillboard", "AuthContext"]


# --- the two passes this session touched -------------------------------------------------------

def test_the_api_stub_pass_emits_parseable_js():
    rc, err = _node_check(_emit_api(_NAMES))
    assert rc == 0, err


def test_the_local_export_pass_emits_parseable_js():
    rc, err = _node_check(_emit_local(_NAMES))
    assert rc == 0, err


@pytest.mark.parametrize("name", ["isAuthenticated", "listTitles", "getActiveProfileId",
                                  "HeroBillboard", "x", "_private", "$dollar"])
def test_each_stub_shape_parses_on_its_own(name):
    """One name at a time, so a failure names the shape rather than the batch."""
    rc, err = _node_check(_emit_api([name]))
    assert rc == 0, f"{name}: {err}"


def test_the_console_error_string_is_not_broken_by_the_message():
    """#753/#761 embed the NAME and an inferred literal inside a single-quoted JS string. The
    message is the part most likely to break the emitted file, so it is parsed, not eyeballed."""
    js = _emit_api(["listTitles"])
    assert "console.error('[auto-stub]" in js
    assert _node_check(js)[0] == 0


# --- non-vacuity: the check can fail --------------------------------------------------------------

def test_node_check_rejects_broken_js():
    """Without this, a green result could mean 'node silently accepted everything'."""
    rc, _err = _node_check("export const x = (( => {;\n")
    assert rc != 0


def test_node_check_accepts_the_baseline():
    assert _node_check("export const x = 1;\n")[0] == 0


# --- provenance -----------------------------------------------------------------------------------

def _doc() -> str:
    """Whitespace-collapsed, because a docstring WRAPS and an assertion that spans the break
    fails on where the line happened to end. Fourth time this trap has appeared in this suite."""
    return " ".join((__doc__ or "").split())


def test_the_asymmetry_is_recorded():
    d = _doc()
    assert "holds the lane to `node --check` and never checks the JS it emits itself" in d
    assert "breaks the vite build" in d


def test_the_harness_mistake_is_recorded():
    """A `.js` file makes node reject `export` outright — a property of the harness, not the
    emitted code. Recorded so the next reader does not re-derive it from a red run."""
    assert "checked a `.js` file and node rejected `export` outright" in _doc()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
