"""#1203ku: an SVG that draws nothing is staged, and the lane finds it by globbing the folder.

The frontend lane does not only read the catalogue in `design.md`; it lists the staged folder.
r177's own agent log, verbatim:

    glob({'path': 'app/frontend/public/assets/icons', 'pattern': '*.svg'})
      → {'matches': [... 'icon_0065272a.svg', 'icon_24cf2bb5.svg', ...]}

— a list of names with no quality information attached, and a hash name gives the lane nothing
to judge by. Among those names the scraper had left the reference site's empty sprite HOST:

    <svg xmlns="http://www.w3.org/2000/svg" style="position:absolute;width:0;height:0"
         id="svg-sprite-container"></svg>

115 bytes, no drawable element at all — the real page injects its `<symbol>`s from elsewhere.
So the file reaches the app looking like an icon and renders nothing. MEASURED: 31 references
across 11 runs, r169 and r177 among them (`icon_0065272a.svg` serves r177's "Go LIVE" nav item
and `icon_732aaf84.svg` its "Shop"), both invisible. An invisible icon is the worst case of the
standing requirement that a UI's icons look like icons.

PREDICATE EVIDENCE: across 8978 staged SVGs in the corpus the drop applies to exactly two
distinct filenames, both this sprite host, and keeps the other 8976. A sprite SHEET is kept,
because it draws through `<symbol>`/`<use>`.
"""
import ast
import inspect
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import material_prep as MP  # noqa: E402

# r177's file, byte for byte.
SPRITE_HOST = ('<svg xmlns="http://www.w3.org/2000/svg" style="position:absolute;width:0;'
               'height:0" id="svg-sprite-container"></svg>')
REAL_ICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" '
             'height="24"><path d="M12 2 L22 22 H2 Z" fill="currentColor"/></svg>')
SPRITE_SHEET = ('<svg xmlns="http://www.w3.org/2000/svg" style="display:none">'
                '<symbol id="heart" viewBox="0 0 24 24"><path d="M12 21 L2 11"/></symbol>'
                '</svg>')


def _ingest(tmp_path, files):
    src = tmp_path / "assets" / "icons"
    src.mkdir(parents=True)
    for name, body in files.items():
        if isinstance(body, bytes):
            (src / name).write_bytes(body)
        else:
            (src / name).write_text(body, encoding="utf-8")
    stage = tmp_path / "public" / "assets"
    manifest = MP.ingest_assets(tmp_path / "assets", stage)
    staged = sorted(p.name for p in (stage / "icons").iterdir()) if (
        stage / "icons").is_dir() else []
    return manifest, staged


def test_the_empty_sprite_host_is_neither_staged_nor_catalogued(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        manifest, staged = _ingest(tmp_path, {
            "icon_0065272a.svg": SPRITE_HOST,
            "for-you_9be6781e.svg": REAL_ICON,
        })
    # NON-VACUITY: the real icon goes through, so the absence below is about the content.
    assert "for-you_9be6781e.svg" in staged, staged
    assert any("for-you" in str(e.get("id")) for e in manifest), manifest

    assert "icon_0065272a.svg" not in staged, (
        "#1203ku: the lane globs this folder, so a file left here is a candidate icon")
    assert not any("0065272a" in str(e.get("id", "")) + str(e.get("file", ""))
                   for e in manifest), manifest
    # the drop is NOT silent: the record names the file and says why
    said = " ".join(r.getMessage() for r in caplog.records)
    assert "icon_0065272a.svg" in said and "1203ku" in said, said
    assert "no drawable element" in said, said


def test_a_sprite_sheet_still_draws_and_is_kept(tmp_path):
    manifest, staged = _ingest(tmp_path, {"sheet.svg": SPRITE_SHEET})
    assert staged == ["sheet.svg"], staged
    assert len(manifest) == 1, manifest


# Each surviving element of the predicate, ISOLATED — no other drawable in the file, so the
# element under test is the only thing keeping it. SPRITE_SHEET above does not do this: it
# carries a `<path>` inside the `<symbol>`, and mutation showed that removing `symbol` from
# the pattern therefore changed no test at all.
_ISOLATED_1203KU = {
    # a sheet that draws by REFERENCE: the symbols live in another document
    "use.svg": '<svg xmlns="http://www.w3.org/2000/svg"><use href="sprites.svg#heart"/></svg>',
    # an <image> is the whole picture
    "image.svg": '<svg xmlns="http://www.w3.org/2000/svg"><image href="logo.png"/></svg>',
    # HTML inside a foreignObject is real pixels
    "fo.svg": ('<svg xmlns="http://www.w3.org/2000/svg"><foreignObject width="24" '
               'height="24"><div xmlns="http://www.w3.org/1999/xhtml">A</div>'
               '</foreignObject></svg>'),
    # a wordmark is often nothing but <text>
    "text.svg": '<svg xmlns="http://www.w3.org/2000/svg"><text x="0" y="10">Brand</text></svg>',
}


def test_each_drawable_element_is_isolated_and_keeps_the_file(tmp_path):
    for name, body in _ISOLATED_1203KU.items():
        _m, staged = _ingest(tmp_path / name.replace(".", "_"), {name: body})
        assert staged == [name], (name, staged, "this element alone must keep the file")


def test_an_empty_symbol_draws_nothing_and_is_dropped(tmp_path):
    """Why `<symbol>` is not in the predicate. A symbol with drawable content already matches
    on that content, so listing it would change the answer in exactly one case — an EMPTY
    symbol — and that file draws nothing, which is what the predicate is for."""
    _m, staged = _ingest(tmp_path, {
        "hollow.svg": ('<svg xmlns="http://www.w3.org/2000/svg" style="display:none">'
                       '<symbol id="heart" viewBox="0 0 24 24"></symbol></svg>'),
        "ok.svg": REAL_ICON})
    assert staged == ["ok.svg"], staged
    assert "symbol" not in MP._SVG_DRAWS_1203KU.pattern, MP._SVG_DRAWS_1203KU.pattern


def test_a_zero_byte_svg_goes_with_the_drop_and_an_unreadable_one_does_not(tmp_path,
                                                                          monkeypatch):
    # read fine, draws nothing -> dropped, same as the sprite host
    _m, staged = _ingest(tmp_path / "empty", {"blank.svg": "", "ok.svg": REAL_ICON})
    assert staged == ["ok.svg"], staged

    # read FAILED -> left alone. #647: no corpus evidence about such a file, so the guard
    # does not reach it, and a file we could not read may well draw.
    real_read = Path.read_text

    def _boom(self, *a, **k):
        if self.name == "mystery.svg":
            raise OSError("decode blew up")
        return real_read(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", _boom)
    _m2, staged2 = _ingest(tmp_path / "unread", {"mystery.svg": REAL_ICON})
    assert staged2 == ["mystery.svg"], staged2


def test_the_decision_is_the_reads_outcome_not_the_texts_emptiness():
    """Pinned by AST: `text.strip()` would conflate two different facts, and the test above
    is the only thing distinguishing them — a reader could satisfy it by accident."""
    tree = ast.parse(inspect.getsource(MP._ingest_one))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.If)
             and any(isinstance(c, ast.Call)
                     and isinstance(c.func, ast.Attribute)
                     and c.func.attr == "search"
                     and getattr(c.func.value, "id", "") == "_SVG_DRAWS_1203KU"
                     for c in ast.walk(n.test))]
    assert len(calls) == 1, ast.dump(tree)[:400]
    names = {n.id for n in ast.walk(calls[0].test) if isinstance(n, ast.Name)}
    assert "_read_ok_1203ku" in names, names
    attrs = {n.attr for n in ast.walk(calls[0].test) if isinstance(n, ast.Attribute)}
    assert "strip" not in attrs, attrs


def test_the_predicate_keeps_every_other_staged_svg_in_the_corpus():
    """The measurement the docstring quotes, re-run. Skipped when the corpus is absent."""
    import pytest
    root = ROOT.parent / "generated"
    if not root.is_dir():
        pytest.skip("corpus not present")
    total = 0
    dropped = set()
    for d in sorted(root.glob("*/app/frontend/public/assets")):
        for f in d.rglob("*.svg"):
            total += 1
            try:
                t = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if not MP._SVG_DRAWS_1203KU.search(t):
                dropped.add(f.name)
    if total < 100:
        pytest.skip("too few staged svgs on this disk to say anything (%d)" % total)
    assert dropped == {"icon_0065272a.svg", "icon_732aaf84.svg"}, sorted(dropped)
