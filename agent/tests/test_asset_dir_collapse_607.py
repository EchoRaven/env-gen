r"""#607: a CODE listing should list code, not 503 staged binaries.

Fourth finding on the cost axis, after #604 / #605 / #606. `list_generated_files` was logged at
**93,396 chars (~23k tokens) per call**. Its own description says it exists to answer *"what
already exists before generating new files"* — a code-authoring aid — yet on a real delivered
tree its 589 files under `app/` are:

    app/frontend/public   503 files   330 .png  119 .jpg  38 .svg  10 .woff2  6 .mp4
    app/frontend/src       58 files
    app/backend            17 files
    (the rest)             11 files

**503 of 589 are staged binary assets** no agent will ever author or edit. They are collapsed to
ONE aggregate row per directory, which keeps everything a caller actually needs from them — that
they exist, where, how many, how big — at a fraction of the size.

Second defect in the same loop: `read_text()` was called on every one of those binaries just to
count lines. The decode raised and a bare `except` swallowed it — after the megabytes had already
been read off disk, on every call. The suffix is checked FIRST now, so a binary is never opened.
"""
import pytest

from env_generator.llm_generator.tools import project_tools as pt


def _tree(tmp_path):
    (tmp_path / "app" / "frontend" / "src" / "pages").mkdir(parents=True)
    (tmp_path / "app" / "frontend" / "public" / "assets").mkdir(parents=True)
    (tmp_path / "app" / "backend").mkdir(parents=True)
    (tmp_path / "app" / "frontend" / "src" / "pages" / "LoginPage.jsx").write_text(
        "export default function LoginPage(){}\n", encoding="utf-8")
    (tmp_path / "app" / "backend" / "main.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
    for i in range(40):
        (tmp_path / "app" / "frontend" / "public" / "assets" / f"p{i}.png").write_bytes(
            b"\x89PNG\r\n\x1a\n" + bytes(400))
    for i in range(5):
        (tmp_path / "app" / "frontend" / "public" / "assets" / f"v{i}.mp4").write_bytes(bytes(900))
    (tmp_path / "app" / "frontend" / "public" / "robots.txt").write_text("ok\n", encoding="utf-8")
    return tmp_path


def _rows(tmp_path):
    from env_generator.llm_generator.workspace import Workspace
    ws = Workspace(str(tmp_path))
    tool = pt.ListGeneratedFilesTool(workspace=ws)
    res = tool.execute() if hasattr(tool, "execute") else None
    assert res is not None and res.success, res
    data = res.data or {}
    out = []
    for v in (data.get("files") or data.get("files_by_category") or data).values() \
            if isinstance(data.get("files") or data.get("files_by_category") or data, dict) else []:
        if isinstance(v, list):
            out += [f for f in v if isinstance(f, dict)]
    return out


# --- the suffix table -------------------------------------------------------------------------

def test_the_asset_suffixes_cover_the_real_tree():
    for s in (".png", ".jpg", ".svg", ".woff2", ".mp4"):
        assert s in pt._ASSET_SUFFIXES_607, s


def test_code_suffixes_are_NOT_assets():
    for s in (".jsx", ".js", ".py", ".json", ".css", ".html", ".md", ".sql", ".yml", ".txt"):
        assert s not in pt._ASSET_SUFFIXES_607, s


# --- the collapse ------------------------------------------------------------------------------

def test_assets_collapse_to_one_row_per_directory(tmp_path):
    rows = _rows(_tree(tmp_path))
    agg = [r for r in rows if r.get("asset_dir")]
    assert len(agg) == 1, [r["path"] for r in rows]
    assert agg[0]["asset_count"] == 45           # 40 png + 5 mp4
    assert ".png" in agg[0]["path"] and ".mp4" in agg[0]["path"]


def test_the_aggregate_keeps_location_count_and_size(tmp_path):
    agg = next(r for r in _rows(_tree(tmp_path)) if r.get("asset_dir"))
    assert "public/assets" in agg["path"].replace("\\", "/")
    assert agg["size"] > 0 and agg["lines"] == 0


def test_no_individual_binary_is_listed(tmp_path):
    rows = _rows(_tree(tmp_path))
    assert not [r for r in rows if r["path"].endswith((".png", ".mp4"))]


def test_code_files_are_listed_individually_with_line_counts(tmp_path):
    rows = _rows(_tree(tmp_path))
    jsx = next(r for r in rows if r["path"].endswith("LoginPage.jsx"))
    py = next(r for r in rows if r["path"].endswith("main.py"))
    assert jsx["lines"] == 1 and py["lines"] == 2


def test_a_non_asset_text_file_beside_the_binaries_survives(tmp_path):
    """`robots.txt` sits in public/ but is text — it must still be listed on its own."""
    rows = _rows(_tree(tmp_path))
    assert any(r["path"].endswith("robots.txt") for r in rows)


def test_a_tree_with_no_assets_gains_no_aggregate_row(tmp_path):
    (tmp_path / "app" / "backend").mkdir(parents=True)
    (tmp_path / "app" / "backend" / "main.py").write_text("x=1\n", encoding="utf-8")
    assert not [r for r in _rows(tmp_path) if r.get("asset_dir")]


# --- the I/O half ---------------------------------------------------------------------------------

def test_a_binary_is_never_opened_to_count_lines():
    import inspect
    src = inspect.getsource(pt.ListGeneratedFilesTool)
    i = src.index("_ASSET_SUFFIXES_607")
    j = src.index("read_text(encoding='utf-8')", i)
    assert i < j, "the suffix check must precede the read"
    assert "continue" in src[i:j]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
