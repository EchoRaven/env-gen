"""#1202vr: a `visibility` no reader understands is not a stricter verdict — it is an unread one.

tiktok-r137, end to end, and the whole run is the cost:

    21:20:46  the backend lane registers `videos` with metadata.visibility = "text"
              design/reference_spec.json says `videos: public`, and cannot be applied --
              both spec stamps are BACKFILL ONLY and skip any non-empty value
    ->        `_declared_public_content_1202hh` is False, so the shape heuristic decides
              alone: `videos` carries a users FK beside a sounds FK -> per-user private
    ->        `auth = auth or _owner_scoped` puts Depends(get_current_user) on the
              projected GET /api/feed/for-you, plus an owner filter
    21:33     curl against the run's own stack: 401 for a tokenless request, while the
              contract says auth_required=False and owner_scoped_reads=False
    ->        #1202kx, the warning that would name the two legitimate fixes, tests
              `public` vs `owner` and so never fired: 0 times in the run
    ->        with no path it could take, the lane reached into _FW_PUBLIC_API_1202KH from
              custom_routes.py -- the "third way" #1202kx forbids
    21:38:47  NO-CONVERGENCE ABORT on deliverability_guard_tampering
              81 minutes, $190.49, nothing delivered

Every reader tests one of two literals, so an unknown word means the STRICTEST reading while
also blocking the only thing that could correct it. Dropped at the write boundary, following
#590's precedent in this same function: the registration still lands, the spec backfill can
now do its job, and what was thrown away stays on the record.
"""
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import registryhub as _rh_mod              # noqa: E402
from multi_agent.runtime.hub_registry import HubRegistry            # noqa: E402
from multi_agent.runtime import route_projector as RP               # noqa: E402
from multi_agent.runtime.backend_skeleton import (                  # noqa: E402
    _apply_spec_visibility_1202hh)


def _hub(tmp_path):
    return HubRegistry(tmp_path).registryhub


def _register(rh, visibility):
    return rh.register_table(
        "videos", schema={"columns": [{"name": "id", "type": "integer primary_key"}]},
        agent="backend", visibility=visibility, owner_scoped_reads=False)


@pytest.mark.parametrize("verdict", sorted(_rh_mod.VISIBILITY_VERDICTS_1202vr))
def test_a_verdict_a_reader_understands_is_kept(tmp_path, verdict):
    rh = _hub(tmp_path)
    _register(rh, verdict)
    md = rh.get_table("videos")["metadata"]
    assert md.get("visibility") == verdict
    assert "visibility_unreadable_1202vr" not in md


def test_the_r137_value_is_dropped_and_left_diagnosable(tmp_path):
    rh = _hub(tmp_path)
    _register(rh, "text")
    md = rh.get_table("videos")["metadata"]
    assert "visibility" not in md, (
        "an unread word is stored as the strictest verdict and blocks the materials")
    assert md.get("visibility_unreadable_1202vr") == "text", (
        "what was thrown away must stay on the record (#590's precedent)")


def test_the_materials_can_now_correct_it(tmp_path):
    """The point of dropping rather than keeping: the spec backfill only fills an EMPTY
    field, so while the bad value sat there the design-time authority could never apply."""
    rh = _hub(tmp_path)
    _register(rh, "text")
    (tmp_path / "design").mkdir(parents=True, exist_ok=True)
    (tmp_path / "design" / "reference_spec.json").write_text(json.dumps(
        {"entities": [{"name": "videos", "visibility": "public", "fields": ["id"]}]}))

    tables = dict(rh.list_tables())
    _apply_spec_visibility_1202hh(tables, tmp_path)
    assert (tables["videos"]["metadata"] or {}).get("visibility") == "public"


def test_the_shape_heuristic_stops_deciding_once_the_verdict_lands(tmp_path):
    """The step that turned a front page into a 401. `videos` has a users FK beside another
    entity's FK, which is #598's per-user-private shape — until the materials speak."""
    be = tmp_path / "backend"
    be.mkdir()
    (be / "models.py").write_text(
        "from sqlalchemy import Column, Integer, String, ForeignKey\n"
        "from sqlalchemy.orm import declarative_base\n"
        "Base = declarative_base()\n"
        "class Feeditem(Base):\n"
        "    __tablename__ = 'feed_items'\n"
        "    id = Column(Integer, primary_key=True)\n"
        "    user_id = Column(Integer, ForeignKey('users.id'))\n"
        "    topic_id = Column(Integer, ForeignKey('topics.id'))\n"
        "    body = Column(String)\n"
        "class User(Base):\n"
        "    __tablename__ = 'users'\n"
        "    id = Column(Integer, primary_key=True)\n"
        "class Topic(Base):\n"
        "    __tablename__ = 'topics'\n"
        "    id = Column(Integer, primary_key=True)\n", encoding="utf-8")
    models = RP._orm_models(be)
    assert RP._structurally_private_resource_633("GET", "/api/feed_items", models) is True

    models["feed_items"]["visibility"] = "public"
    assert RP._structurally_private_resource_633("GET", "/api/feed_items", models) is False


def test_an_absent_visibility_is_untouched(tmp_path):
    """A table the materials say nothing about must stay untouched — #1202gd's rule for
    staying strict, and the difference between this guard and a rewrite."""
    rh = _hub(tmp_path)
    rh.register_table(
        "videos", schema={"columns": [{"name": "id", "type": "integer primary_key"}]},
        agent="backend", owner_scoped_reads=False)
    md = rh.get_table("videos")["metadata"]
    assert "visibility" not in md
    assert "visibility_unreadable_1202vr" not in md


def test_the_verdict_set_is_the_one_the_readers_test():
    """Not an invented enum. Every reader in the runtime compares `visibility` against a
    string literal; the set here must be exactly the literals they use, or this guard drops
    a word some reader would have honoured."""
    import ast

    runtime = pathlib.Path(_rh_mod.__file__).parent
    literals = set()
    for py in runtime.glob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Compare)
                    and len(node.ops) == 1 and isinstance(node.ops[0], ast.Eq)
                    and len(node.comparators) == 1
                    and isinstance(node.comparators[0], ast.Constant)
                    and isinstance(node.comparators[0].value, str)):
                continue
            if "visibility" not in ast.unparse(node.left):
                continue
            literals.add(node.comparators[0].value)
    assert literals, "no reader compares visibility to a literal — the detector is broken"
    assert literals == set(_rh_mod.VISIBILITY_VERDICTS_1202vr), (
        f"the readers test {sorted(literals)} but the guard accepts "
        f"{sorted(_rh_mod.VISIBILITY_VERDICTS_1202vr)}")


def test_the_whole_chain_from_registration_to_the_front_page(tmp_path):
    """End to end through the REAL functions, in the order the run runs them.

    Replayed against tiktok-r137's own artifacts before it was written: `visibility='text'`
    -> shape says private -> the projected feed takes an actor; with the guard the spec
    backfill supplies 'public' -> shape says public -> an anonymous caller gets through.
    The links are tested separately above; this is the one that broke, and only the
    composition shows it.
    """
    from multi_agent.runtime.backend_skeleton import _models_meta

    (tmp_path / "design").mkdir(parents=True, exist_ok=True)
    (tmp_path / "design" / "reference_spec.json").write_text(json.dumps(
        {"entities": [{"name": "feed_items", "visibility": "public",
                       "fields": ["id", "user_id", "topic_id", "body"]}]}))

    rh = _hub(tmp_path)
    cols = [{"name": "id", "type": "integer primary_key"},
            {"name": "user_id", "type": "integer references users.id",
             "references": "users(id)"},
            {"name": "topic_id", "type": "integer references topics.id",
             "references": "topics(id)"},
            {"name": "body", "type": "string"}]

    def _chain(visibility):
        rh.register_table("feed_items", schema={"columns": cols}, agent="backend",
                          owner_scoped_reads=False, **(
                              {"visibility": visibility} if visibility else {}))
        tables = dict(rh.list_tables())
        _apply_spec_visibility_1202hh(tables, tmp_path)
        meta = _models_meta(tables)
        return RP._structurally_private_resource_633("GET", "/api/feed_items", meta)

    # The guard is in the hub, so registering the bad word already clears it. Reproduce the
    # pre-fix state by writing it past the boundary, the way the record looked on r137.
    rh.register_table("feed_items", schema={"columns": cols}, agent="backend",
                      owner_scoped_reads=False)
    raw = dict(rh.list_tables())
    raw["feed_items"] = {**raw["feed_items"],
                         "metadata": {**(raw["feed_items"].get("metadata") or {}),
                                      "visibility": "text"}}
    _apply_spec_visibility_1202hh(raw, tmp_path)
    assert RP._structurally_private_resource_633(
        "GET", "/api/feed_items", _models_meta(raw)) is True, (
        "the pre-fix state must reproduce, or this test proves nothing")

    assert _chain("text") is False, (
        "with the guard, the unreadable word never lands and the materials decide")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
