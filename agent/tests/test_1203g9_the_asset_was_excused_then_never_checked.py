"""#1203g9 — #1165 excused asset paths from the route check, and nothing then checked the file.

`#1165`'s dead-nav-link scan skips `/assets/`, `/static/`, `/img/` … with a correct reason in its
own comment: "An `href` can also point at a STATIC FILE, which is not a route and must not be
reported as a dead one." Nothing afterwards verifies that the file is THERE. So an asset
reference is removed from the route check and never examined as a file — the shape where fixing
one class blinds the detector for the next.

Measured over the 80 delivered runs with a frontend on disk: 3186 literal asset references, of
which 104 across 22 RUNS point at a file that exists nowhere in the run. Not a layout quirk:
googlemaps-gmrun3 ships `public/assets/icons/` with 72 real icons beside `house_24.svg` and
`logout_24.svg`, which are referenced and were never produced — no `vite.config.js` base
override, no `onError` fallback in those components. In a browser each is a 404 and a broken
image, in an app that shipped.

RECORD-ONLY, like `#1202ui` next to it and for the same stated reason: 22 of 80 delivered runs
carry one, so blocking would have held 27% of the corpus's deliveries, and that is a policy
decision with risk in both directions. What it cannot be is invisible after the run.
"""
import json
import sys
from pathlib import Path

import pytest

_AGENT = Path(__file__).resolve().parents[1]
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

from env_generator.llm_generator.multi_agent.runtime.frontend_audit import (  # noqa: E402
    missing_static_assets_1203g9 as missing)
from env_generator.llm_generator.multi_agent.runtime.scaffolder import (  # noqa: E402
    record_missing_assets_1203g9 as record)

_ART = Path("logs") / "missing_static_assets_1203g9.jsonl"


@pytest.fixture
def app(tmp_path):
    src = tmp_path / "frontend" / "src"
    pub = tmp_path / "frontend" / "public" / "assets" / "icons"
    src.mkdir(parents=True)
    pub.mkdir(parents=True)
    (pub / "present.svg").write_text("<svg/>", encoding="utf-8")
    return tmp_path, src, pub


def test_a_reference_with_no_file_is_found(app):
    root, src, _ = app
    (src / "Page.jsx").write_text(
        'const a = "/assets/icons/absent.svg";\n', encoding="utf-8")
    out = missing(root)
    assert len(out) == 1
    assert "/assets/icons/absent.svg" in out[0]
    assert "Page.jsx" in out[0], "the referencing file must be named"


def test_a_reference_with_a_file_is_silent(app):
    root, src, _ = app
    (src / "Page.jsx").write_text(
        'const a = "/assets/icons/present.svg";\n', encoding="utf-8")
    assert missing(root) == []


def test_both_kinds_in_one_file(app):
    root, src, _ = app
    (src / "Page.jsx").write_text(
        'a="/assets/icons/present.svg"; b="/assets/icons/absent.svg";\n', encoding="utf-8")
    out = missing(root)
    assert len(out) == 1 and "absent.svg" in out[0]


@pytest.mark.parametrize("ext", [".jsx", ".js", ".tsx", ".ts", ".css", ".html"])
def test_every_source_kind_is_scanned(app, ext):
    """A broken icon referenced from CSS is as broken as one from JSX."""
    root, src, _ = app
    (src / ("F" + ext)).write_text('x "/assets/icons/absent.svg"\n', encoding="utf-8")
    assert len(missing(root)) == 1


@pytest.mark.parametrize("prefix", ["/assets", "/images", "/img", "/icons", "/static",
                                    "/media", "/fonts"])
def test_every_excused_prefix_is_covered(app, prefix):
    """#1165 excuses exactly these; each one must now be checked as a file."""
    root, src, _ = app
    (src / "Page.jsx").write_text('x = "%s/nope.svg"\n' % prefix, encoding="utf-8")
    assert len(missing(root)) == 1, prefix


def test_a_concatenated_reference_is_not_judged(app):
    """`"/assets/" + name` has its value supplied at runtime; source cannot decide it, and
    guessing would report a file that is fine."""
    root, src, _ = app
    (src / "Page.jsx").write_text(
        'const a = "/assets/icons/" + kind + ".svg";\n', encoding="utf-8")
    assert missing(root) == []


def test_each_path_is_reported_once(app):
    root, src, _ = app
    for n in ("A.jsx", "B.jsx"):
        (src / n).write_text('x = "/assets/icons/absent.svg"\n', encoding="utf-8")
    assert len(missing(root)) == 1


def test_node_modules_is_not_scanned(app):
    root, src, _ = app
    nm = src / "node_modules" / "pkg"
    nm.mkdir(parents=True)
    (nm / "x.js").write_text('"/assets/icons/vendor_absent.svg"\n', encoding="utf-8")
    assert missing(root) == []


@pytest.mark.parametrize("root", [None, "", "/no/such/place", object()])
def test_it_is_silent_without_a_real_app(root):
    assert missing(root) == []


def test_no_public_dir_is_not_a_finding(tmp_path):
    """Without `public/` there is nothing to compare against; reporting every reference as
    missing would be the overmatching this project keeps catching."""
    src = tmp_path / "frontend" / "src"
    src.mkdir(parents=True)
    (src / "P.jsx").write_text('x = "/assets/a.svg"\n', encoding="utf-8")
    assert missing(tmp_path) == []


# --------------------------------------------------------------------- the artifact

def test_the_artifact_lands_and_appends(tmp_path):
    assert record(tmp_path, ["/assets/a.svg (referenced by X.jsx)"]) is True
    assert record(tmp_path, ["/assets/b.svg (referenced by Y.jsx)"]) is True
    recs = [json.loads(l) for l in (tmp_path / _ART).read_text().splitlines() if l.strip()]
    assert [r["assets"][0].split()[0] for r in recs] == ["/assets/a.svg", "/assets/b.svg"]
    assert recs[0]["count"] == 1


@pytest.mark.parametrize("dest", [None, "", object(), "/no/such/dir"])
def test_a_bad_destination_writes_nothing_anywhere(dest, tmp_path, monkeypatch):
    """#1203g8's defect, not repeated: `str()` of anything is a usable RELATIVE path, so a
    writer that mkdirs it creates junk in the current working directory."""
    monkeypatch.chdir(tmp_path)
    assert record(dest, ["/assets/a.svg"]) is False
    assert list(tmp_path.iterdir()) == [], sorted(p.name for p in tmp_path.iterdir())


def test_nothing_found_writes_nothing(tmp_path):
    assert record(tmp_path, []) is False
    assert not (tmp_path / _ART).exists()


# ----------------------------------------------------------- wiring + the real corpus

def test_the_detector_is_wired_and_recorded():
    """#1178: a detector nothing calls is the standing failure mode here."""
    import ast
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import scaffolder as sc
    tree = ast.parse(inspect.getsource(sc))
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "missing_static_assets_1203g9" in called
    assert "record_missing_assets_1203g9" in called


def test_it_does_not_add_a_blocker():
    """Record-only, like #1202ui. If this ever becomes a gate it must be a deliberate ticket,
    not a side effect — 22 of 80 delivered runs carry one."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import scaffolder as sc
    src = inspect.getsource(sc)
    i = src.index("missing_static_assets_1203g9(Path(out_dir)")
    j = src.index("warn_once_1201(\"missing_static_assets_1203g9\"", i)
    assert "blockers.append" not in src[i:j]


def test_the_corpus_case_this_describes_still_exists():
    root = Path(__file__).resolve().parents[2] / "generated"
    app = root / "googlemaps-core-di.SUCCESS-gmrun3-3milestones-realdata" / "app"
    if not (app / "frontend" / "public").is_dir():
        pytest.skip("gmrun3 artifacts not on disk")
    out = missing(app)
    assert len(out) >= 10, len(out)
    assert any("icons/" in x for x in out), out[:3]
