r"""#805: the session's re-runnable corpus measurements, promoted out of throwaway heredocs.

Nine measurement errors in one session, every one in ad-hoc analysis written fresh in a shell
heredoc, every one producing a confident number that described my probe rather than the system:

    milestone_registry.json      the file is `milestones.json`        -> "0 comparable runs"
    list(d.values())             includes the `_meta` bootstrap doc   -> "0 failing chains"
    raw codehub_checks rows      need #193/#236's normaliser first    -> "0% contradicted UI"
    CREATE TABLE under backend   the DDL is in app/database/init/     -> "0% year mismatch"
    columns unioned across tables hides titles.release_year           -> undercount
    a hand-written candidate set omitted duration_minutes/_seconds    -> "2%" for a real 17%

★ `tools/check_pending_experiments.sh` does **not** have this defect — all 55 of its `grep_log`
patterns still match live framework strings. (Checking that produced a tenth error in the same
family: a first pass reported 7 patterns "missing" because it searched for whole literals, while
log strings are f-string-assembled. Every fragment was present.)

The difference is not care at the moment of writing. It is that the checker is committed, re-run
and reviewed, while a heredoc is written once under time pressure and never seen again. So the
measurements worth keeping now live in `tools/corpus_audit.py`, where they are versioned, and
these tests keep them honest.

Two properties are enforced by construction rather than by remembering:
  * every line prints its **denominator** — a rate without one is unreadable;
  * every line prints how many runs the probe **actually saw** — a zero with a low `saw` count is
    a claim about the instrument.
"""
import importlib.util
import pathlib

import pytest


_TOOL = pathlib.Path(__file__).resolve().parents[2] / "tools" / "corpus_audit.py"


def _mod():
    spec = importlib.util.spec_from_file_location("corpus_audit", _TOOL)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ca = _mod()


# --- the traps that produced the nine errors, each pinned -------------------------------------

def test_the_meta_document_is_not_a_record():
    """#755/#798: `_meta` is a bootstrap doc. Counting it as a record is how `{"version": 1}`
    became "a release" and how a chains file reported zero failing chains."""
    recs = ca._records({"_meta": {"version": 1}, "a": {"x": 1}, "b": {"x": 2}})
    assert len(recs) == 2
    assert all("version" not in r for r in recs)


@pytest.mark.parametrize("doc,n", [
    ([{"a": 1}, {"b": 2}], 2),
    ({"tasks": [{"a": 1}]}, 1),
    ({"k1": {"a": 1}, "k2": {"b": 2}}, 2),
    ({}, 0), (None, 0), ("nope", 0),
])
def test_every_hub_document_shape_is_handled(doc, n):
    assert len(ca._records(doc)) == n


def test_the_ddl_is_read_from_the_database_dir(tmp_path):
    """A probe that searched `app/backend` for CREATE TABLE matched 2 OAuth tables and reported a
    0% column-mismatch rate across the whole corpus."""
    d = tmp_path / "app" / "database" / "init"
    d.mkdir(parents=True)
    (d / "01_init.sql").write_text(
        'CREATE TABLE IF NOT EXISTS "titles" (\n  "id" INTEGER,\n  "release_year" INTEGER\n);\n',
        encoding="utf-8")
    (tmp_path / "app" / "backend").mkdir(parents=True)
    tables = ca._ddl_tables(tmp_path)
    assert tables == {"titles": ["id", "release_year"]}


def test_fk_targets_are_read_not_guessed_from_names(tmp_path):
    """#784/#803: a link table is a label relation or a per-user one depending on what its FKs
    POINT AT. A name-based guard missed `recipient_id` precisely because it was not on the list."""
    d = tmp_path / "app" / "database" / "init"
    d.mkdir(parents=True)
    (d / "01.sql").write_text(
        'CREATE TABLE IF NOT EXISTS "my_list" (\n'
        '  "id" INTEGER,\n'
        '  "profile_id" INTEGER REFERENCES profiles(id),\n'
        '  "title_id" INTEGER REFERENCES titles(id)\n);\n', encoding="utf-8")
    refs = ca._ddl_refs(tmp_path)
    assert refs["my_list"] == {"profile_id": "profiles", "title_id": "titles"}


# --- the two properties enforced by construction -----------------------------------------------

def test_a_rate_is_never_printed_without_its_denominator(capsys):
    ca._report("x", saw=0, total=0, hits=0)
    out = capsys.readouterr().out
    assert "%" not in out
    assert "no comparable runs" in out


def test_every_line_states_what_the_probe_saw(capsys):
    ca._report("x", saw=7, total=5, hits=1)
    out = capsys.readouterr().out
    assert "1/5" in out and "20%" in out
    assert "probe saw 7 run(s)" in out


def test_the_tool_refuses_to_report_on_an_empty_selection(tmp_path, capsys):
    """A `--since` that matches nothing must say so, not print a page of zeroes."""
    (tmp_path / "unrelated").mkdir()
    rc = ca.main(["--generated", str(tmp_path), "--since", "9999"])
    assert rc == 1
    assert "nothing to measure" in capsys.readouterr().out


def test_a_missing_directory_is_an_error_not_a_zero(tmp_path, capsys):
    rc = ca.main(["--generated", str(tmp_path / "nope")])
    assert rc == 2


def test_the_era_split_is_a_first_class_argument():
    """Three corpus figures this session described already-fixed defects and three UNDERSTATED
    live ones — neither direction is the default, so the split must be one flag away."""
    import inspect
    src = inspect.getsource(ca.main)
    assert "--since" in src
    assert "era-split" in src


def test_the_gate_decision_numbers_are_in_the_tool():
    """#806: they drove four live switch decisions and lived only as a markdown table in
    EXPERIMENTS_PENDING — the same throwaway-measurement problem one level up, where a reader has
    to trust prose or re-derive by hand, and re-deriving by hand produced nine wrong numbers."""
    import inspect
    src = inspect.getsource(ca.audit_gate_decisions)
    for t in ("#751", "#752", "#743", "#671"):
        assert t in src, t
    assert "[ENABLED]" in src and "[rejected]" in src, "the switch state must be visible"


def test_it_uses_the_shipped_normaliser_not_a_copy():
    """#772: mirrored logic drifts from the check that actually blocks. Feeding raw store rows
    straight to the detector returns 0% on every slice — status is `success` and the check kind
    is nested under `evidence` until #193/#236 flatten them."""
    import inspect
    src = inspect.getsource(ca.audit_gate_decisions)
    assert "_canon_validation_status" in src and "_flatten_validation_metadata" in src
    assert "_ui_evidence_breadth_739" in src


def test_the_ui_audit_reports_its_own_denominator_separately():
    """Only some runs carry any UI record; a #752 rate over ALL runs would understate it, and a
    rate over none of them would be an instrument zero."""
    import inspect
    src = inspect.getsource(ca.audit_gate_decisions)
    assert "carry any UI record at all" in src


def test_the_terminal_state_audit_asks_how_runs_ENDED():
    """#821. I analysed a whole corpus without asking whether its runs delivered — r151, the one
    I read most closely, aborted STUCK (#820). The census is starker than any release count:
    25 success / 32 completed-unsuccessful / 94 killed before a terminal event, of 151."""
    import inspect
    src = inspect.getsource(ca.audit_terminal_state)
    assert "generation_complete" in src and "generation_error" in src
    assert "killed before any terminal event" in src


def test_it_names_what_the_abort_messages_blamed():
    """`business_chain_failing` leads at x5 — the same task #798/#799/#811 taught to name its own
    broken step. Where the effort went is checkable rather than asserted."""
    import inspect
    src = inspect.getsource(ca.audit_terminal_state)
    assert "named in abort messages" in src


def test_the_silent_window_is_stated():
    """62% of runs die between `phase_start` and the end, and the log emits nothing in between —
    so there is no phase attribution for the majority outcome. Recorded, not silently rounded."""
    import inspect
    assert "silent between phase_start" in inspect.getsource(ca.audit_terminal_state)


def test_the_enrichment_census_separates_the_two_producers():
    """#824. `crop` reaches design_system.json from the SKELETON; build_notes/typography/copy only
    through the analyst enrichment. Comparing them is what localises a failure to the enrichment
    rather than to the design phase — 93% vs 1% over 49,286 components."""
    import inspect
    src = inspect.getsource(ca.audit_design_prep_enrichment)
    assert "SKELETON path" in src and "analyst enrichment" in src
    for k in ("crop", "build_notes", "typography", "copy"):
        assert f'"{k}"' in src, k


def test_the_seed_orphan_audit_names_the_worst_run():
    """#825. A rate alone does not tell you where to look; r138 strands 159 rows, more than the
    r145 case #807b was built around."""
    import inspect
    src = inspect.getsource(ca.audit_seed_orphans)
    assert "worst" in src and "stranded" in src


def test_both_new_audits_are_wired():
    import inspect
    src = inspect.getsource(ca)
    assert "audit_design_prep_enrichment" in src.split("_AUDITS = ")[1]
    assert "audit_seed_orphans" in src.split("_AUDITS = ")[1]


def test_an_unparsed_run_is_reported_as_EXCLUDED(capsys):
    """#846. #843's shape, generalised into this tool: a run the probe cannot parse leaves the
    numerator AND the denominator, so the rate looks healthy on a quietly shrunken base. Every
    audit here is written `if not tables: continue`, so every audit can lose runs the same way.
    An exclusion that is not printed is a denominator nobody can check."""
    ca._report("x", saw=10, total=10, hits=2, skipped=5)
    out = capsys.readouterr().out
    assert "2/10" in out
    assert "5 EXCLUDED" in out


def test_no_exclusions_prints_no_noise(capsys):
    """It must stay silent when nothing was dropped, or it becomes the line readers skip (#793)."""
    ca._report("x", saw=10, total=10, hits=2)
    assert "EXCLUDED" not in capsys.readouterr().out


def test_the_corpus_audits_actually_count_their_exclusions():
    """Not just the helper — the callers must pass it. Both DDL-shaped audits drop runs."""
    import inspect
    for fn in (ca.audit_link_tables, ca.audit_projected_bare_reads):
        src = inspect.getsource(fn)
        assert "skipped += 1" in src, fn.__name__
        assert "EXCLUDED" in src or "skipped=skipped" in src, fn.__name__


def test_the_footer_states_the_zero_rule():
    import inspect
    assert "claim about the instrument" in inspect.getsource(ca.main)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
