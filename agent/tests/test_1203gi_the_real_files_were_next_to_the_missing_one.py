"""#1203gi -- the check said "add the file" while the real files sat under public/.

`#1203g9` reports asset paths the frontend references that do not exist under `public/`, and its
message ended "Add the file or stop referencing it". On the run where it actually fired, that was
the wrong remedy: tiktok-r166 ships five invented video names in `api.js`

    /assets/videos/mara-market-dance.mp4 ... /assets/videos/alina-ridge-sunrise.mp4

while 35 REAL videos sit under `public/assets/real_videos/`, named
`khaby.lame__7660566666803154206.mp4`. The lane could not guess that convention, so it wrote
names that read plausibly. The file did not need adding; it needed finding.

Measured over the corpus: of the 25 runs with a missing reference, **21 have real files of the
SAME extension** -- 94 references, three domains:

    tiktok-r166          5 missing .mp4  beside 35 real
    googlemaps-gmrun3   18 missing .svg  beside 78 real, in the SAME directory and the same
                        `name_24.svg` convention (`apps_24.svg` was simply never produced)
    tiktok-r146          7 missing .jpg  beside 70, plus 2 missing .mp4 beside 35
    instagram x6         3-7 missing .svg each, beside 60-63 real

Same shape as #1203ft and #1203fx: the framework held both halves of the fact and handed over
one. Naming the directory and three real names turns an unactionable line into a one-step fix.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.frontend_audit import (  # noqa: E402
    missing_static_assets_1203g9,
    _available_like_1203gi,
    _INVENTORY_SHOWN_1203GI,
)
from multi_agent.runtime import frontend_audit as FA  # noqa: E402


def _tree(tmp, refs, real):
    """A frontend whose source references `refs` and whose public/ holds `real`."""
    src = tmp / "app" / "frontend" / "src"
    src.mkdir(parents=True)
    (src / "api.js").write_text(
        "\n".join("const v%d = '%s';" % (i, r) for i, r in enumerate(refs)), encoding="utf-8")
    for rel in real:
        p = tmp / "app" / "frontend" / "public" / rel.lstrip("/")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    (tmp / "app" / "frontend" / "public").mkdir(parents=True, exist_ok=True)
    return tmp / "app"


# --- the defect: the remedy was "add the file" and the file existed --------------------------

def test_the_inventory_is_named_beside_the_missing_reference(tmp_path):
    app = _tree(tmp_path,
                ["/assets/videos/mara-market-dance.mp4"],
                ["/assets/real_videos/khaby__111.mp4",
                 "/assets/real_videos/khaby__222.mp4",
                 "/assets/real_videos/gordon__333.mp4"])
    out = missing_static_assets_1203g9(app)
    assert len(out) == 1, out
    line = out[0]
    assert "mara-market-dance.mp4" in line
    assert "3 real .mp4 exist" in line, line
    assert "assets/real_videos" in line, line
    # the NAMES matter: they are what shows the convention the lane could not guess
    assert "khaby__111.mp4" in line, line


def test_the_directory_named_is_the_one_holding_the_most(tmp_path):
    """gmrun3's 78 icons are in one directory; a stray file elsewhere must not win."""
    app = _tree(tmp_path, ["/assets/icons/apps_24.svg"],
                ["/assets/icons/add_24.svg", "/assets/icons/arrow_back_24.svg",
                 "/assets/icons/accessible_24.svg", "/misc/stray.svg"])
    line = missing_static_assets_1203g9(app)[0]
    assert "4 real .svg exist" in line, line
    assert "assets/icons" in line, line
    assert "stray.svg" not in line, line


def test_nothing_is_added_when_no_real_file_of_that_type_exists(tmp_path):
    """4 of the 25 runs are like this. The old wording is correct there and must survive."""
    app = _tree(tmp_path, ["/assets/videos/only.mp4"], ["/assets/icons/a.svg"])
    out = missing_static_assets_1203g9(app)
    assert len(out) == 1
    assert "real .mp4 exist" not in out[0], out[0]
    assert out[0].endswith("(referenced by api.js)"), out[0]


def test_the_sample_is_capped_and_the_count_is_the_full_one(tmp_path):
    """#1034: a count must not sit beside a silent cut — the count is of ALL of them, the
    examples are capped, and the two must not be confused."""
    real = ["/assets/icons/i%02d.svg" % i for i in range(40)]
    app = _tree(tmp_path, ["/assets/icons/missing_24.svg"], real)
    line = missing_static_assets_1203g9(app)[0]
    assert "40 real .svg exist" in line, line
    assert line.count(".svg") == 1 + 1 + _INVENTORY_SHOWN_1203GI, line


# --- it must never break its caller -----------------------------------------------------------

def test_a_reference_with_no_extension_adds_nothing(tmp_path):
    app = _tree(tmp_path, ["/assets/videos/noext"], ["/assets/videos/real.mp4"])
    out = missing_static_assets_1203g9(app)
    assert out and "real" not in out[0].split("referenced by")[1], out


def test_the_empty_case_is_handled_explicitly_not_by_the_exception_guard():
    """#1203gi: `test_nothing_is_added_...` passes even with the `if not hits` guard deleted --
    an empty list then makes `most_common(1)[0]` raise IndexError and the outer
    `except Exception: return ""` produces the same answer. Same outcome, different reason, and
    a refactor that tightened the except clause would start emitting a bogus inventory. The
    no-real-files case is 4 of the 25 corpus runs, so pin that it is a DECISION.
    """
    fn = next(n for n in ast.walk(ast.parse(Path(FA.__file__).read_text(encoding="utf-8")))
              if isinstance(n, ast.FunctionDef) and n.name == "_available_like_1203gi")
    guarded = False
    for node in ast.walk(fn):
        if not isinstance(node, ast.If):
            continue
        test = ast.unparse(node.test)
        if "hits" not in test or "not" not in test:
            continue
        if any(isinstance(x, ast.Return) for x in node.body):
            guarded = True
    assert guarded, (
        "no explicit `if not hits: return` -- the empty case now relies on the exception "
        "handler, which is the same answer for the wrong reason")


def test_the_helper_is_silent_on_a_fault():
    assert _available_like_1203gi(None, "/a/b.mp4") == ""
    assert _available_like_1203gi(object(), "/a/b.mp4") == ""
    assert _available_like_1203gi(Path("/definitely/not/here"), "/a/b.mp4") == ""


def test_the_detector_still_returns_a_list_on_a_broken_tree(tmp_path):
    assert missing_static_assets_1203g9(tmp_path / "nope") == []


# --- the shape must not regress ----------------------------------------------------------------

def test_the_inventory_is_computed_inside_the_detector_not_by_the_caller():
    """Every caller of the check gets the other half, not just the one that logs it — the
    'fixed one reader' shape this codebase has paid for before."""
    src = Path(FA.__file__).read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "missing_static_assets_1203g9")
    body = ast.unparse(fn)
    assert "_available_like_1203gi" in body, (
        "the inventory is no longer attached inside the detector, so only whoever remembers "
        "to call the helper gets it")
