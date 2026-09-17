"""#1202qd: when a row already holds its real image in one image column, the seed loader copies
it into the empty sibling instead of an external picsum placeholder (tiktok-r126: dataset
`thumbnail` = /assets/real_videos/...jpg, page reads `thumbnail_url` -> picsum)."""
import ast
import re
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_skeleton import write_backend_skeleton  # noqa: E402

_ID = {"name": "id", "type": "serial primary key"}
_TABLES = {
    "users": {"schema": {"columns": [_ID, {"name": "email", "type": "text"},
                                     {"name": "name", "type": "text"}]}},
    "videos": {"schema": {"columns": [_ID, {"name": "thumbnail", "type": "text"},
                                      {"name": "thumbnail_url", "type": "text"}]}},
}


def _fill(tmp_path):
    write_backend_skeleton(tmp_path, [{"method": "GET", "path": "/api/videos"}], _TABLES)
    src = (tmp_path / "app" / "backend" / "seed_data.py").read_text()
    ast.parse(src)
    m = re.search(r"\n(\s*)_real_img = .*?\n(?:\1.*\n)+?\1\s+row\[_ic\] = .*\n", src)
    assert m, "the image fill block is not emitted"
    block = textwrap.dedent(m.group(0).strip("\n"))
    image_col = ast.literal_eval(re.search(r"^_IMAGE_COL = (.*)$", src, re.M).group(1))

    def run(row, t="videos", i=0):
        ns = {"row": row, "t": t, "i": i, "_IMAGE_COL": image_col}
        exec(block, ns)
        return ns["row"]
    return run


def test_the_real_sibling_is_copied(tmp_path):
    run = _fill(tmp_path)
    row = run({"id": 1, "thumbnail": "/assets/real_videos/a.jpg"})
    assert row["thumbnail_url"] == "/assets/real_videos/a.jpg"


def test_no_real_image_invents_none(tmp_path):
    """#1202qo: no picsum placeholder for a row with no image."""
    run = _fill(tmp_path)
    row = run({"id": 2})
    assert not row.get("thumbnail") and "picsum" not in str(row)
