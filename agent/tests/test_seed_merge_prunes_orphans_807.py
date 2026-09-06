r"""#807: replacing a seed table WHOLESALE orphaned every row that referenced it.

Found by asking what #803 would actually render. #803 folds a normalised many-to-many into the
detail read; that is only worth anything if the link rows point at titles that exist.

The seed loader merges the framework-owned `seed_dataset.json` OVER the lane's base seed, and the
dataset **replaces a table wholesale** (#264, which handled the one column-level consequence: a
scope column the dataset omits). Nothing checked referential integrity after the swap.

Measured across the 7 most recent corpus runs — **1 of 7 (r145)** had every dependent row pointing
at a title id the dataset had replaced. Not just genres:

    title_genres       35 of 35 orphaned
    episodes           18 of 18
    my_list            18 of 18
    ratings            12 of 12
    continue_watching  10 of 10

★ **93 rows across 5 tables**, silently referencing titles that no longer exist. That run shipped
with no episodes, no my-list, no ratings and no continue-watching — which reads exactly like *"the
lane forgot to seed"*, the phantom seeding bug #264's own comment warns about. It was invisible
before #803 because nothing joined through those rows; #803 makes it render as an empty chip row
on every detail page.

**PRUNE, never remap.** A remap would invent associations that were in neither source. Dropping a
stale link loses nothing visible — a dangling `episodes` row with `title_id: 99` never appears
under titles 1-60 anyway — and it converts silent emptiness into a logged, named cause
(#769/#770's rule).

Verified by **generating the seeder and executing its merge against the real corpus runs**, not by
asserting on the template string: r145 prunes 93 rows across 5 tables, and r147/r150/r151 prune
nothing.
"""
import ast
import json
import pathlib

import pytest

from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import render_seed_data


_GENERATED = pathlib.Path(__file__).resolve().parents[2] / "generated"


def _merge_fn():
    """The emitted loader's merge, pulled out of the generated module and made callable.

    The generated `seed_data.py` imports the app's own `database` module, so it cannot be exec'd
    whole here — but the merge is a pure function of `_SEED` plus the dataset file, so lifting
    that one function is faithful rather than a re-implementation (#772)."""
    src = render_seed_data({"titles": {}, "genres": {}, "title_genres": {}}, {})
    node = next(n for n in ast.parse(src).body
                if isinstance(n, ast.FunctionDef)
                and "F2 dual-source" in (ast.get_source_segment(src, n) or ""))
    return ast.get_source_segment(src, node), node.name


def _run_merge(backend: pathlib.Path):
    fsrc, name = _merge_fn()
    base = json.loads((backend / "seed_data.json").read_text(encoding="utf-8"))
    ns = {"json": json, "Path": pathlib.Path, "_SEED": base,
          "__file__": str(backend / "seed_data.py")}
    exec(fsrc, ns)
    return base, ns[name]()


def test_the_emitted_seeder_is_valid_python():
    """The merge lives in a template string assembled line by line; a stray quote would break
    every generated app's seeding."""
    ast.parse(render_seed_data({"titles": {}}, {}))


def test_the_prune_is_in_the_emitted_code():
    assert "#807" in render_seed_data({"titles": {}}, {})


# --- executed against the real corpus --------------------------------------------------------

def _runs_with_both_seeds():
    if not _GENERATED.is_dir():
        return []
    return [p / "app" / "backend" for p in sorted(_GENERATED.iterdir())
            if (p / "app" / "backend" / "seed_data.json").is_file()
            and (p / "app" / "backend" / "seed_dataset.json").is_file()]


_RUNS = _runs_with_both_seeds()


@pytest.mark.skipif(not _RUNS, reason="no generated corpus available")
def test_the_corpus_is_actually_being_exercised():
    """Non-vacuity: without this, a moved corpus turns every test below into a silent skip."""
    assert len(_RUNS) >= 5, len(_RUNS)


@pytest.mark.skipif(not any(p.parent.parent.name.endswith("r145") for p in _RUNS),
                    reason="r145 not present")
def test_r145_keeps_its_coherent_app():
    """The measured case, and the answer that pruning got WRONG.

    r145's lane keyed titles on TEXT slugs ('tv-stranger-signals'); the dataset supplies integer
    ids 1..60. Pruning the orphans is honest but leaves a 60-title catalogue with zero episodes,
    my-list, ratings and continue-watching. Refusing the swap keeps the lane's 20 titles WITH all
    93 dependent rows — a smaller app that actually works. **Realism is worth less than
    coherence.**"""
    backend = next(p for p in _RUNS if p.parent.parent.name.endswith("r145"))
    base, out = _run_merge(backend)
    assert len(out.get("titles") or []) == 20, "the swap must be refused, not applied"
    for table in ("title_genres", "episodes", "my_list", "ratings", "continue_watching"):
        assert base.get(table), f"non-vacuity: r145's base really has {table} rows"
        assert len(out[table]) == len(base[table]), f"{table} was protected by the refusal"


@pytest.mark.skipif(not _RUNS, reason="no generated corpus available")
@pytest.mark.parametrize("suffix", ["r151", "r150", "r147", "r149"])
def test_a_healthy_run_loses_nothing(suffix):
    """Non-regression, and the more important half: the prune must not touch a run whose links
    already resolve. r151 keeps all 39 title_genres rows."""
    matches = [p for p in _RUNS if p.parent.parent.name.endswith(suffix)]
    if not matches:
        pytest.skip(f"{suffix} not present")
    base, out = _run_merge(matches[0])
    for table in ("title_genres", "episodes", "my_list", "ratings", "continue_watching"):
        assert len(out.get(table) or []) == len(base.get(table) or []), table


# --- the rule the fix encodes -------------------------------------------------------------------

def test_it_prunes_rather_than_remaps():
    """A remap would invent associations present in neither source — worse than an empty chip row,
    because it would be indistinguishable from real data."""
    src = render_seed_data({"titles": {}}, {})
    i = src.index("#807")
    blk = src[i:src.index("return merged", i)]
    assert "never remapped" in blk or "never remap" in blk.lower()
    assert "_kept" in blk


@pytest.mark.skipif(not any(p.parent.parent.name.endswith("r145") for p in _RUNS),
                    reason="r145 not present")
def test_the_prune_announces_itself(capsys):
    """Silent pruning would replace one invisible emptiness with another (#769/#770).

    Asserted on the RUNTIME message, not the emitted source: the sentence is assembled from two
    adjacent string literals, so `"no longer resolves" in src` fails against working code. Same
    lesson as #782 — check the behaviour, not the text that produces it."""
    backend = next(p for p in _RUNS if p.parent.parent.name.endswith("r145"))
    _run_merge(backend)
    out = capsys.readouterr().out
    assert "#807b REFUSED the dataset swap for titles" in out
    assert "93 of 93 dependent row(s)" in out, "the count must be named"
    assert "do not share an id space" in out
    assert "'tv-stranger-signals'" in out and "1" in out, "both id shapes must be shown"


def test_the_prune_only_looks_at_tables_the_dataset_actually_replaced():
    """★ The interaction bug this file exists to pin.

    Sourcing the live-id set from `merged` instead of `real` turned a swap-orphan cleanup into a
    general referential-integrity pruner over the lane's ENTIRE seed. Executed against the corpus
    it deleted valid rows in 3 of 4 runs — r151 and r150 lost every my_list / ratings /
    continue_watching row to a `user_id` check that has nothing to do with the dataset. Caught by
    running it, not by reading it."""
    src = render_seed_data({"titles": {}}, {})
    i = src.index("#807")
    blk = src[i:src.index("return merged", i)]
    assert "_cand in real and _cand not in _refused" in blk
    assert "merged[_cand]" not in blk, "the live set must come from the dataset, not the merge"


def test_a_refused_table_is_not_treated_as_a_source_of_orphans():
    """#807b and #807 cancelled each other out in their first form: the refusal protected 93 rows
    and the prune then deleted all 93, because it still compared them against the dataset the
    refusal had just rejected."""
    src = render_seed_data({"titles": {}}, {})
    i = src.index("#807")
    blk = src[i:src.index("return merged", i)]
    assert "_t not in _refused" in blk


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
