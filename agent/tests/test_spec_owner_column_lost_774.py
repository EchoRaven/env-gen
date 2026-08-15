r"""#774: the contract can satisfy every consistency check and still not implement the spec.

r150 shipped `my_list`, `ratings` and `continue_watching` keyed on `user_id` while its own
description said `profile_id` and stated the one privacy rule in the task: *"Each profile sees
only its own My List, ratings and Continue Watching."* Two profiles on one account shared all
three. The DDL, the RegistryHub contract and the handlers all agreed with each other and all
disagreed with the spec — **so every consistency check the framework runs passed.** Nothing
compares the contract to the REQUIREMENT.

Measured over the corpus once #773 restored the extractor:

    runs comparable                      111
    runs where a spec column is missing   20   -- all RENAMES (spec `poster`, app `poster_url`)
    runs losing an OWNER column            8   -- 7%, and every one is profile_id

**The discriminator is the whole check.** A first version used substring matching and reported
ZERO owner losses — because every table has an `id` column and `id` is a substring of
`profile_id`, so the real defect read as a rename. That is the same over-loose matching #765
refuses one module over, made again one turn later. Token overlap with `id` excluded separates
them.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import delivery_gate as dg


class _Reg:
    def __init__(self, tables):
        self._t = tables

    def get_tables(self):
        return {n: {"name": n, "schema": {"columns": [{"name": c} for c in cols]}}
                for n, cols in self._t.items()}


class _Ms:
    def __init__(self, slice_text):
        self._s = slice_text

    def list_milestones(self):
        return [{"description_slice": self._s}]


class _Hubs:
    def __init__(self, slice_text, tables):
        self.milestones = _Ms(slice_text)
        self.registryhub = _Reg(tables)


_R150_SLICE = ("- table: my_list: id, profile_id, title_id\n"
               "- table: ratings: id, profile_id, title_id, value\n"
               "- table: continue_watching: id, profile_id, title_id, progress_seconds\n")


# --- the r150 case ------------------------------------------------------------------------------

def test_the_r150_shape_is_reported():
    hubs = _Hubs(_R150_SLICE, {
        "my_list": ["id", "user_id", "title_id", "added_at"],
        "ratings": ["id", "user_id", "title_id", "rating"],
        "continue_watching": ["id", "user_id", "title_id", "progress_seconds"]})
    lost = dg._spec_owner_columns_lost_774(hubs)
    assert {(x["table"], x["column"]) for x in lost} == {
        ("my_list", "profile_id"), ("ratings", "profile_id"),
        ("continue_watching", "profile_id")}


def test_it_names_what_the_table_DOES_have():
    """So the reader can see it is a different owner, not a missing key."""
    hubs = _Hubs("- table: my_list: id, profile_id, title_id",
                 {"my_list": ["id", "user_id", "title_id"]})
    assert dg._spec_owner_columns_lost_774(hubs)[0]["has"] == "title_id, user_id"


# --- the discriminator, which is the whole check ---------------------------------------------------

def test_a_bare_substring_would_have_missed_it():
    """Non-vacuity for the fix: `id` is a substring of `profile_id`, and every table has an
    `id`. The first version reported zero for exactly this reason."""
    assert "id" in "profile_id"
    hubs = _Hubs("- table: my_list: id, profile_id, title_id",
                 {"my_list": ["id", "user_id", "title_id"]})
    assert dg._spec_owner_columns_lost_774(hubs), "the id-substring trap must not silence it"


@pytest.mark.parametrize("spec_col,have", [
    ("profile_id", ["id", "profile_uuid"]),      # same entity, different key type
    ("user_id", ["id", "user_ref"]),
])
def test_a_genuine_rename_of_the_same_owner_is_not_reported(spec_col, have):
    hubs = _Hubs(f"- table: t: id, {spec_col}", {"t": have})
    assert dg._spec_owner_columns_lost_774(hubs) == []


def test_a_non_owner_column_is_never_reported():
    """20 of 111 runs differ on ordinary columns (poster/poster_url). Out of scope by design."""
    hubs = _Hubs("- table: titles: id, poster, backdrop",
                 {"titles": ["id", "poster_url", "backdrop_url"]})
    assert dg._spec_owner_columns_lost_774(hubs) == []


def test_a_table_the_contract_does_not_have_is_skipped():
    """Absent tables are a different finding with its own checks; this one is about columns."""
    hubs = _Hubs("- table: ghost: id, profile_id", {"other": ["id"]})
    assert dg._spec_owner_columns_lost_774(hubs) == []


def test_a_matching_contract_reports_nothing():
    hubs = _Hubs(_R150_SLICE, {
        "my_list": ["id", "profile_id", "title_id"],
        "ratings": ["id", "profile_id", "title_id", "value"],
        "continue_watching": ["id", "profile_id", "title_id", "progress_seconds"]})
    assert dg._spec_owner_columns_lost_774(hubs) == []


# --- it can never break the gate --------------------------------------------------------------------

@pytest.mark.parametrize("hubs", [None, object(), _Hubs("", {})])
def test_junk_never_raises(hubs):
    assert dg._spec_owner_columns_lost_774(hubs) == []


def test_it_only_reports():
    src = inspect.getsource(dg.validate_delivery_gate)
    i = src.index("#774")
    blk = src[i:src.index("_bugs743 = unresolved_bug_tasks_743", i)]
    assert "failed_checks" not in blk
    assert "Reported, not enforced" in blk


# --- provenance ---------------------------------------------------------------------------------------

def test_the_corpus_numbers_are_recorded():
    d = " ".join((dg._spec_owner_columns_lost_774.__doc__ or "").split())
    assert "runs comparable 111" in d
    assert "runs losing an OWNER column 8" in d


def test_the_id_substring_trap_is_recorded():
    d = " ".join((dg._spec_owner_columns_lost_774.__doc__ or "").split())
    assert "every table has an `id`" in d
    assert "same over-loose matching #765 refuses one module over" in d


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
