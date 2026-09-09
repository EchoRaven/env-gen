r"""#1202ij: recording the materials' verdict is not honouring it.

`_apply_spec_visibility_1202hh` stamped `visibility` onto the table record and stopped,
while the shape probes a few lines up in scaffolder.py had just set
`owner_scoped_reads = True`. The two halves of #1202gd's exemption were then written by
different code and contradicted each other — `public_content_scoped_away_1202gv` says in
its own words that they are "direct opposites": `public` means "a reader who is not the
author still sees the row, and seeing it is the point", while `owner_scoped_reads`
projects `WHERE owner = caller`. The audit's corroboration then refuses the exemption and
`unscoped owner read` stands forever.

tiktok-r107, from its own ledger and event stream: the backend lane registered
`owner_scoped_reads=false` on `videos` SIX times between 08:37:24 and 08:39:28, and the
record afterwards read `visibility: public, owner_scoped_reads: True,
_updated_by: orchestrator`. The lane cleared it; the framework put it back on the next
scaffold. Four runs of that.

The early `continue` on an already-stamped `visibility` is why the guard could not save it
either: a table whose verdict was recorded correctly was exactly the table this never
looked at again.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import (
    _apply_spec_visibility_1202hh as apply_vis,
)


def _spec(tmp: Path, entities):
    d = tmp / "design"
    d.mkdir(parents=True, exist_ok=True)
    (d / "reference_spec.json").write_text(json.dumps({"entities": entities}))
    return tmp


def _rec(**md):
    return {"name": "t", "metadata": dict(md)}


def test_a_public_table_loses_the_probe_s_owner_filter(tmp_path):
    """The r107 case: materials public, probe said owner-scoped."""
    _spec(tmp_path, [{"name": "videos", "visibility": "public"}])
    tables = {"videos": _rec(owner_scoped_reads=True)}
    apply_vis(tables, tmp_path)
    assert tables["videos"]["metadata"]["owner_scoped_reads"] is False
    assert tables["videos"]["metadata"]["visibility"] == "public"


def test_it_still_fires_when_visibility_was_already_stamped(tmp_path):
    """The early `continue` skipped exactly the records that mattered."""
    _spec(tmp_path, [{"name": "videos", "visibility": "public"}])
    tables = {"videos": _rec(visibility="public", owner_scoped_reads=True)}
    apply_vis(tables, tmp_path)
    assert tables["videos"]["metadata"]["owner_scoped_reads"] is False


def test_an_owner_declared_table_keeps_its_filter(tmp_path):
    """The teeth. `video_likes` is per-user and must stay scoped."""
    _spec(tmp_path, [{"name": "video_likes", "visibility": "owner"}])
    tables = {"video_likes": _rec(visibility="owner", owner_scoped_reads=True)}
    apply_vis(tables, tmp_path)
    assert tables["video_likes"]["metadata"]["owner_scoped_reads"] is True


def test_an_undeclared_table_is_untouched(tmp_path):
    """#1202gd's rule: the materials said nothing, which is not an invitation to guess."""
    _spec(tmp_path, [{"name": "videos", "visibility": "public"}])
    tables = {"secrets": _rec(owner_scoped_reads=True)}
    apply_vis(tables, tmp_path)
    assert tables["secrets"]["metadata"]["owner_scoped_reads"] is True


def test_a_public_table_without_the_flag_is_not_given_one(tmp_path):
    """It clears a filter the probes imposed; it does not invent a False from nothing."""
    _spec(tmp_path, [{"name": "videos", "visibility": "public"}])
    tables = {"videos": _rec()}
    apply_vis(tables, tmp_path)
    assert "owner_scoped_reads" not in tables["videos"]["metadata"]


def test_no_spec_changes_nothing(tmp_path):
    tables = {"videos": _rec(owner_scoped_reads=True)}
    before = json.dumps(tables, sort_keys=True)
    apply_vis(tables, tmp_path)
    assert json.dumps(tables, sort_keys=True) == before


def test_it_never_raises(tmp_path):
    _spec(tmp_path, [{"name": "videos", "visibility": "public"}])
    for tables in ({}, {"videos": None}, {"videos": "x"}, None):
        apply_vis(tables, tmp_path)          # must not raise


def test_the_clearing_is_announced(tmp_path, caplog):
    """It overrides a probe; a silent override is how the two halves drifted apart."""
    import logging
    _spec(tmp_path, [{"name": "videos", "visibility": "public"}])
    tables = {"videos": _rec(visibility="public", owner_scoped_reads=True)}
    with caplog.at_level(logging.WARNING):
        apply_vis(tables, tmp_path)
    assert any("#1202ij" in r.getMessage() for r in caplog.records)


# --- against r107's own ledger --------------------------------------------------------

def test_r107s_videos_would_be_released_and_its_likes_would_not():
    root = Path(__file__).resolve().parents[2]
    led = root / "generated/tiktok-web-r107/shared/hubs/registryhub_tables.json"
    if not led.is_file():
        pytest.skip("r107 corpus not on this machine")
    raw = json.loads(led.read_text())
    tables = {k: v for k, v in raw.items() if k != "_meta"}
    assert (tables["videos"]["metadata"] or {}).get("owner_scoped_reads") is True, \
        "premise: the ledger still carries the flag the lane cleared six times"
    apply_vis(tables, root / "generated/tiktok-web-r107")
    assert tables["videos"]["metadata"]["owner_scoped_reads"] is False
    assert tables["video_likes"]["metadata"]["owner_scoped_reads"] is True


# --- the OTHER emitter: kickoff, where a fresh run writes the record ------------------

def test_kickoff_does_not_register_a_public_table_owner_scoped():
    """#1202ij is a PAIR. Fixing only the scaffolder would leave a FRESH run writing the
    contradiction at its first registration — kickoff lifts a declared `owner_scoped_reads`
    into the same dict it stamps `visibility` onto."""
    import ast, inspect
    from env_generator.llm_generator.multi_agent.runtime.kickoff import run_kickoff as RK
    src = inspect.getsource(RK.finalize_kickoff)
    i = src.index('table_meta["visibility"] = _v1202hh')
    seg = src[i:src.index("_SPINE_OWNED_TABLES_1202HK", i)]
    assert 'table_meta["owner_scoped_reads"] = False' in seg, (
        "kickoff still registers a materials-public table as owner-scoped")
    assert '"public"' in seg, "the clearing must be conditioned on the PUBLIC verdict"


def test_the_kickoff_clearing_is_guarded_on_true_only():
    """It clears a flag that was set; it does not invent one."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime.kickoff import run_kickoff as RK
    src = inspect.getsource(RK.finalize_kickoff)
    i = src.index('table_meta["owner_scoped_reads"] = False')
    guard = src[src.rindex("if ", 0, i):i]
    assert "is True" in guard, "an `is not False` here would fabricate a verdict"


def test_both_emitters_carry_the_same_ticket():
    """One fact, two writers — a reader of either must find the same reasoning."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime.kickoff import run_kickoff as RK
    from env_generator.llm_generator.multi_agent.runtime import backend_skeleton as BS
    assert "#1202ij" in inspect.getsource(RK.finalize_kickoff)
    assert "#1202ij" in inspect.getsource(BS._apply_spec_visibility_1202hh)
