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


def test_the_stamp_only_records_the_verdict(tmp_path):
    """#1202ij's scaffolder half CLEARED `owner_scoped_reads` here. #1202io moved that to
    the write boundary and this copy went with it — r109 proved why.

    Clearing here fixed only the projector's view: the audit reads
    `registryhub_tables.json`, still saw `True`, and reported `unscoped owner read` seven
    times against a projector that had correctly stopped filtering, where r108 reported
    none. #1202hm had aligned both readers on "materials public AND not owner-scoped";
    correcting one reader's copy broke that alignment instead of resolving anything.
    """
    _spec(tmp_path, [{"name": "videos", "visibility": "public"}])
    tables = {"videos": _rec(owner_scoped_reads=True)}
    apply_vis(tables, tmp_path)
    md = tables["videos"]["metadata"]
    assert md["visibility"] == "public", "the verdict must still be recorded"
    assert md["owner_scoped_reads"] is True, (
        "the stamp must not correct one reader's copy — #1202io normalises the record")


def test_an_undeclared_table_is_untouched(tmp_path):
    """#1202gd's rule: the materials said nothing, which is not an invitation to guess."""
    _spec(tmp_path, [{"name": "videos", "visibility": "public"}])
    tables = {"secrets": _rec(owner_scoped_reads=True)}
    apply_vis(tables, tmp_path)
    assert "visibility" not in tables["secrets"]["metadata"]


def test_no_spec_changes_nothing(tmp_path):
    tables = {"videos": _rec(owner_scoped_reads=True)}
    before = json.dumps(tables, sort_keys=True)
    apply_vis(tables, tmp_path)
    assert json.dumps(tables, sort_keys=True) == before


def test_it_never_raises(tmp_path):
    _spec(tmp_path, [{"name": "videos", "visibility": "public"}])
    for tables in ({}, {"videos": None}, {"videos": "x"}, None):
        apply_vis(tables, tmp_path)          # must not raise


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
