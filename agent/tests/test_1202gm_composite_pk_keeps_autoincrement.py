"""#1202gm — a composite primary key turns autoincrement off, and the projected create needs it.

SQLAlchemy only auto-generates a single-column Integer PK. When a join table declares its
natural key alongside the surrogate one — `Like(id, user_id, video_id)`, all three
primary_key=True — `id` stops autoincrementing, the projected `Model(**valid)` insert leaves
it NULL, and the commit/refresh that follows fails. tiktok-r98 answered every
`POST /api/videos/{id}/like` with

    500 create failed: Could not refresh instance '<Like at 0x...>'

and the video_engagement chain stayed red. The route is framework-PROJECTED and models.py is
framework-WRITTEN (every commit is "GitOps Bot: framework delivery"), so nothing the lane
could reach was at fault — while the error carried the label "[FRAMEWORK-PROJECTED route —
the lane cannot edit it]", which points at the projector rather than the model.

Measured over the 1270 model classes on this machine: 6 of them, across 3 runs, declare `id`
inside a composite PK. Rare, and fatal every time it happens — every create against that
table 500s.

The composite key is KEPT: `likes(user_id, video_id)` unique is real product meaning (one
like per user per video), and making `id` the sole PK would silently allow duplicates.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"))

from multi_agent.runtime.backend_skeleton import _render_column  # noqa: E402


def _col(name, type_="integer", **kw):
    return {"name": name, "type": type_, **kw}


def test_the_marked_column_asks_for_autoincrement():
    line = _render_column(_col("id", primary_key=True, _autoincrement_1202gm=True), None)
    assert "autoincrement=True" in line, line
    assert "primary_key=True" in line


def test_an_unmarked_pk_is_unchanged():
    """A single-column Integer PK autoincrements on its own; saying so would be noise."""
    line = _render_column(_col("id", primary_key=True), None)
    assert "autoincrement" not in line, line


def test_a_text_pk_keeps_its_uuid_default_and_gets_no_autoincrement():
    line = _render_column(_col("id", "text", primary_key=True), None)
    assert "uuid4" in line
    assert "autoincrement" not in line


def test_the_emitter_marks_only_the_id_of_a_composite_key():
    """End to end through the module's own model rendering."""
    from multi_agent.runtime import backend_skeleton as bs
    src = Path(bs.__file__).read_text(encoding="utf-8")
    i = src.index("_pks_gm = [c for c in real")
    block = src[i:src.index("lines = [c for c in (", i)]
    assert 'str(c.get("name", "")).lower() == "id"' in block, block
    assert "len(_pks_gm) > 1" in block, "it must only fire for a COMPOSITE key"
    assert '("text", "uuid")' in block, "a text/uuid id must not be given autoincrement"


def test_the_composite_key_is_not_dissolved():
    """Dropping the natural key to make `id` sole PK would allow duplicate likes."""
    from multi_agent.runtime import backend_skeleton as bs
    src = Path(bs.__file__).read_text(encoding="utf-8")
    i = src.index("_pks_gm = [c for c in real")
    block = src[i:src.index("lines = [c for c in (", i)]
    assert 'primary_key": False' not in block and '"pk": False' not in block, block
