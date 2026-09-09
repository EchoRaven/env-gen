r"""#1202io: refuse the materials/contract contradiction at the write boundary.

`owner_scoped_reads` projects `WHERE owner = caller`; the materials' `public` means "a
reader who is not the author still sees the row, and seeing it is the point".
`public_content_scoped_away_1202gv` calls them direct opposites, and a record holding both
makes the projector and the audit permanently disagree — #1202hm aligned them on
"materials public AND not owner-scoped", so whoever writes the True wins and the public
feed stays filtered.

Live evidence from both directions:
  r109  `videos` carried `visibility: public` + `owner_scoped_reads: True` with
        `_updated_by: backend` — the LANE wrote it, and `unscoped owner read` fired 7×.
  r107  the lane CLEARED it six times between 08:37:24 and 08:39:28 and it came back.

Neither side can win a fight it has to keep re-winning, so the record is normalised where
it is written. #1202ij's scaffolder half — which corrected only the projector's in-memory
copy — is what made r109 worse than r108 (7 leak reports against 0), and has been removed.
"""
from __future__ import annotations

import logging
import pathlib
import tempfile

import pytest

from env_generator.llm_generator.multi_agent.runtime.registryhub import RegistryHub


@pytest.fixture
def hub():
    return RegistryHub(pathlib.Path(tempfile.mkdtemp()))


def _md(h, name):
    return (h._tables.value().get(name) or {}).get("metadata") or {}


def test_a_lane_cannot_store_a_public_table_owner_scoped(hub):
    """The r109 case."""
    hub.register_table("videos", schema={"columns": [{"name": "id", "type": "int"}]},
                       agent="orchestrator", visibility="public")
    hub.register_table("videos", agent="backend", owner_scoped_reads=True)
    assert _md(hub, "videos")["owner_scoped_reads"] is False


def test_an_owner_declared_table_keeps_its_filter(hub):
    """The teeth. `video_likes` is per-user and must stay scoped."""
    hub.register_table("video_likes", schema={"columns": [{"name": "id", "type": "int"}]},
                       agent="orchestrator", visibility="owner")
    hub.register_table("video_likes", agent="backend", owner_scoped_reads=True)
    assert _md(hub, "video_likes")["owner_scoped_reads"] is True


def test_an_undeclared_table_is_untouched(hub):
    """#1202gd's rule: the materials said nothing, which is not an invitation to guess."""
    hub.register_table("secrets", schema={"columns": [{"name": "id", "type": "int"}]},
                       agent="backend", owner_scoped_reads=True)
    assert _md(hub, "secrets")["owner_scoped_reads"] is True


def test_it_does_not_invent_a_false(hub):
    """It clears a flag that was set; a table with no flag gets none."""
    hub.register_table("videos", schema={"columns": [{"name": "id", "type": "int"}]},
                       agent="orchestrator", visibility="public")
    assert "owner_scoped_reads" not in _md(hub, "videos")


def test_the_clearing_names_who_wrote_it(hub):
    """The breadcrumb makes the override diagnosable offline."""
    hub.register_table("videos", agent="orchestrator", visibility="public")
    hub.register_table("videos", agent="backend", owner_scoped_reads=True)
    assert _md(hub, "videos").get("owner_scoped_reads_cleared_by_1202io") == "backend"


def test_it_is_announced(hub, caplog):
    hub.register_table("videos", agent="orchestrator", visibility="public")
    with caplog.at_level(logging.WARNING):
        hub.register_table("videos", agent="backend", owner_scoped_reads=True)
    assert any("#1202io" in r.getMessage() for r in caplog.records)


def test_a_later_registration_does_not_reintroduce_it(hub):
    """r107's shape: the lane cleared it six times and it came back. Idempotent both ways."""
    hub.register_table("videos", agent="orchestrator", visibility="public")
    for _ in range(3):
        hub.register_table("videos", agent="backend", owner_scoped_reads=True)
        assert _md(hub, "videos")["owner_scoped_reads"] is False


def test_the_visibility_can_arrive_after_the_flag(hub):
    """Registration merges, so the verdict may be stamped later than the flag."""
    hub.register_table("videos", agent="backend", owner_scoped_reads=True)
    assert _md(hub, "videos")["owner_scoped_reads"] is True   # nothing declared yet
    hub.register_table("videos", agent="orchestrator", visibility="public")
    assert _md(hub, "videos")["owner_scoped_reads"] is False


def test_the_scaffolder_stamp_no_longer_corrects_a_copy():
    """#1202ij's in-memory clearing is gone — correcting one reader is what broke r109."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import backend_skeleton as BS
    src = inspect.getsource(BS._apply_spec_visibility_1202hh)
    assert 'meta["owner_scoped_reads"] = False' not in src
    assert "#1202io" in src, "the replacement must be named where the old one stood"
