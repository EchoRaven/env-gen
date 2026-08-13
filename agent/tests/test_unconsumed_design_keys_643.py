r"""#643: 74% of the design system is written into a void.

Measured over the 45 delivered `design/design_system.json` files:

    82 distinct keys written under `design_system`
    61 of them (74%) read by NO runtime code
    28% of every key-instance written

These are not typos — they are whole specifications that land nowhere:

    motion               written in 27 of 45 runs   read by nobody
    collapse_checklist                24 of 45      read by nobody
    brand_boundary                     8 of 45      read by nobody
    spacing_scale_px / spacing_scale  13 combined   read by nobody (only `spacing` is read)

The tail is free-form synonym invention, the same shape as #360's rejected tool arguments:
`spacing`/`spacing_scale`/`spacing_scale_px`, `font_stack`/`font_family`/`font_families`,
`grid`/`grids`, and one `collapse_checklist_塌缩点`. Only the first of each group is consumed.

Consuming the extras would be feature work. What is wrong is that the analyst cannot TELL: it
spends a section on `motion` in three runs out of five and gets no signal that nothing reads it.
#360 solved the identical problem for tool arguments by dropping them loudly; this reports at the
write boundary.

Getting the measurement right took two corrections, both caught before shipping: the file is
NESTED (`{"design_system": {...}}`), so a top-level scan reported "0 of 45" for `palette`, which
is present in all 45; and a reader-grep for `"key"` alone misses `'key'`, which would have called
four consumed keys unconsumed.
"""
import subprocess

import pytest

from env_generator.llm_generator.multi_agent.runtime.design_prep import (
    _CONSUMED_DESIGN_KEYS_643 as CONSUMED,
    unconsumed_design_keys_643 as unconsumed,
)


# --- what it reports ------------------------------------------------------------------------------

def test_a_key_nothing_reads_is_reported():
    assert unconsumed({"design_system": {"palette": {}, "motion": {}}}) == ["motion"]


def test_a_fully_consumed_document_reports_nothing():
    assert unconsumed({"design_system": {"palette": {}, "theme": "dark", "type_scale": {}}}) == []


def test_the_measured_offenders_are_all_caught():
    doc = {"design_system": {k: {} for k in
                             ("motion", "collapse_checklist", "brand_boundary",
                              "spacing_scale", "spacing_scale_px")}}
    assert unconsumed(doc) == ["brand_boundary", "collapse_checklist", "motion",
                               "spacing_scale", "spacing_scale_px"]


def test_the_consumed_member_of_a_synonym_group_survives():
    """`spacing` is read; `spacing_scale` and `spacing_scale_px` are not."""
    doc = {"design_system": {"spacing": {}, "spacing_scale": {}, "spacing_scale_px": {}}}
    assert unconsumed(doc) == ["spacing_scale", "spacing_scale_px"]


def test_a_non_ascii_variant_is_caught_too():
    """One run wrote `collapse_checklist_塌缩点`."""
    assert unconsumed({"design_system": {"collapse_checklist_塌缩点": []}}) \
        == ["collapse_checklist_塌缩点"]


def test_the_result_is_sorted_and_stable():
    doc = {"design_system": {"zeta": 1, "alpha": 2, "palette": {}}}
    assert unconsumed(doc) == ["alpha", "zeta"]


# --- the file is nested ---------------------------------------------------------------------------

def test_it_reads_the_NESTED_document():
    """The artifact is {"design_system": {...}, "assets": ..., "screens": ...}. Scanning the top
    level reported "palette present in 0 of 45 runs" — it is in all 45."""
    assert unconsumed({"design_system": {"palette": {}}, "assets": {}, "screens": []}) == []


def test_a_flat_document_still_works():
    assert unconsumed({"palette": {}, "motion": {}}) == ["motion"]


def test_junk_input_never_raises():
    for bad in (None, [], "x", {"design_system": "not a dict"}, {"design_system": None}):
        assert unconsumed(bad) == []


# --- the list must not rot ---------------------------------------------------------------------

def test_every_key_claimed_as_consumed_is_really_read():
    """The whole point is a truthful list. If a name here stops being read, this becomes a second
    fiction — so the claim is checked against the source, not trusted."""
    unread = []
    for k in sorted(CONSUMED):
        r = subprocess.run(["grep", "-rl", "-e", f'"{k}"', "-e", f"'{k}'",
                            "--include=*.py", "env_generator/"],
                           capture_output=True, text=True)
        if not [x for x in r.stdout.split() if x.strip()]:
            unread.append(k)
    assert not unread, f"claimed consumed but read nowhere: {unread}"


def test_the_warning_fires_at_the_write_boundary():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import design_prep
    src = inspect.getsource(design_prep._write_design_system)
    i = src.index("#643: say which sections will be ignored")
    assert src.index("unconsumed_design_keys_643(ds)", i) < src.index('design_system.json', i)


def test_it_never_blocks_the_write():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import design_prep
    src = inspect.getsource(design_prep._write_design_system)
    block = src[src.index("_ignored = unconsumed"):src.index('(design_dir / "design_system.json")')]
    assert "except Exception" in block and "return" not in block


def test_the_measurement_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import design_prep
    flat = " ".join(inspect.getsource(design_prep).replace("#", " ").split())
    assert "61 of them (74%) are read by no runtime code" in flat
    assert "`motion` in **27 of 45 runs**" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
