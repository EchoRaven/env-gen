"""#1202gl — tell the lane that making the contract public does not trade one blocker for another.

`#1202fr`'s note says "declare auth_required=false". A lane does exactly that, then watches
`unscoped owner read: returns every row of X to ANY caller` appear, and reverts — landing
back on the 401 it started from. tiktok-r98 went round that loop: the contract was made
public after the note, then set back to auth_required=true, and the logged-out flows failed
on 401 again.

#1202gd's exemption already resolves it — when the materials declare the collection public,
the unscoped-read audit exempts a public read of it — but silently. The lane cannot see that
from either blocker, so the note has to say it.

Adding the sentence to the OTHER blocker would not work: the unscoped-read audit only fires
when the exemption does NOT apply, i.e. when the materials never declared the collection
public, and then there is nothing reassuring to say. The note is the only place this
information has a reader.
"""
import json
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"))

from multi_agent.runtime.deliverability import (  # noqa: E402
    _auth_wedge_note_1202fr, _root_spec_entities_1202gl)

PAGES = {"p": {"name": "feed_page", "route": "/", "apis_used": ["GET /api/videos"]}}
EPS = {"GET /api/videos": {"method": "GET", "path": "/api/videos",
                           "schema": {"auth_required": True}}}


def _hubs(tmp_path, entities):
    root = tmp_path / "env"
    (root / "design").mkdir(parents=True)
    (root / "design" / "reference_spec.json").write_text(
        json.dumps({"entities": entities}))

    class _Reg:
        @staticmethod
        def list_ui_pages():
            return PAGES

        @staticmethod
        def get_endpoints():
            return EPS

    class _H:
        # The attribute the REAL HubRegistry defines. #1202gn: the first cut of this fix
        # guessed output_dir / root / base_root / project_dir, the class has none of them,
        # and the reader returned [] on every production call.
        base_dir = root / "shared"
        registryhub = _Reg()

    (root / "shared").mkdir(exist_ok=True)
    return _H()


def test_it_names_the_public_collections(tmp_path):
    h = _hubs(tmp_path, [{"name": "videos", "visibility": "public"},
                         {"name": "saved_items", "visibility": "owner"}])
    note = _auth_wedge_note_1202fr(h, ["feed_page"])
    assert "videos" in note and "PUBLIC content" in note, note
    assert "does NOT trade this" in note


def test_an_owner_collection_is_not_named(tmp_path):
    h = _hubs(tmp_path, [{"name": "saved_items", "visibility": "owner"}])
    note = _auth_wedge_note_1202fr(h, ["feed_page"])
    assert "PUBLIC content" not in note, note


def test_the_base_note_is_unchanged_without_a_spec(tmp_path):
    """The original guidance must survive on its own — the reassurance is additive."""
    h = _hubs(tmp_path, [])
    note = _auth_wedge_note_1202fr(h, ["feed_page"])
    assert "GET /api/videos" in note and "auth_required=false" in note
    assert "PUBLIC content" not in note


def test_no_failing_flow_still_says_nothing(tmp_path):
    assert _auth_wedge_note_1202fr(_hubs(tmp_path, [{"name": "videos",
                                                     "visibility": "public"}]), []) == ""


def test_the_spec_reader_is_not_dead(tmp_path):
    """#1202gd's first cut shipped dead because json/Mapping were unimported and its own
    except swallowed the NameError. This one is checked directly."""
    h = _hubs(tmp_path, [{"name": "videos", "visibility": "public"}])
    ents = _root_spec_entities_1202gl(h)
    assert ents and ents[0]["name"] == "videos", ents


def test_a_missing_spec_is_not_a_crash(tmp_path):
    h = _hubs(tmp_path, [{"name": "videos", "visibility": "public"}])
    (Path(h.base_dir).parent / "design" / "reference_spec.json").unlink()
    assert _root_spec_entities_1202gl(h) == []
    assert "PUBLIC content" not in _auth_wedge_note_1202fr(h, ["feed_page"])


def test_the_reader_works_against_the_REAL_HubRegistry(tmp_path):
    """#1202gn — the guard that would have caught the first cut.

    A stand-in with the right attribute proves nothing if the real class names it something
    else. This constructs an actual HubRegistry over a real hub dir and asserts the reader
    finds the spec through it — the third time this batch a fix read an attribute the live
    object does not have (#1202gd's unimported names, #1202fw's self.logger)."""
    from multi_agent.runtime.hub_registry import HubRegistry
    root = tmp_path / "proj"
    (root / "shared" / "hubs").mkdir(parents=True)
    (root / "design").mkdir()
    (root / "design" / "reference_spec.json").write_text(
        json.dumps({"entities": [{"name": "videos", "visibility": "public"}]}))
    hr = HubRegistry(root / "shared")
    assert hasattr(hr, "base_dir"), "the reader is anchored on base_dir; the class moved it"
    ents = _root_spec_entities_1202gl(hr)
    assert [e["name"] for e in ents] == ["videos"], ents
