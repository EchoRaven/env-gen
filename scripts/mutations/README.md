# Mutation specs (`#1203pe`)

Each file here is one `scripts/mutate.py` spec: a target file, a test file, and a list of
mutations that each break ONE property the test is supposed to be about. The verdicts are
CAUGHT / MISSED / NOT APPLIED / BROKEN, and only CAUGHT means the test has falsifying power
for that property.

## Why they live in the repo rather than in /tmp

`scripts/README.md` used to say `cat > /tmp/spec.json`, so the spec — the only record of
WHICH property each mutation falsifies — was thrown away at the end of every session.

That broke a discipline that depends on history: **a later patch can rewrite an earlier
patch's mutation anchor**, and when it does, that property silently stops being verified while
the suite stays green. Catching it means re-checking every past spec against the current tree,
which is impossible once the past specs are gone. MEASURED when this directory was created:
62 specs / 253 mutations existed for the current session and ZERO for any earlier one, so the
cross-session half of the check had never actually been runnable. `mutate.py`'s own header
quotes #826 for exactly this: "a check that lives in a habit is not a check".

## The census

`scripts/mutation_census.py` reads every spec here and reports, per mutation, whether its
anchor appears EXACTLY ONCE in the target file today:

    scripts/mutation_census.py            # anchors only (free, no tests run)
    scripts/mutation_census.py --strict   # exit non-zero on an UNEXPLAINED loss

An anchor that no longer appears exactly once is not automatically a problem — the code may
have been deliberately rewritten. It must be EXPLAINED, by putting one of these in the
mutation's `label`:

  * `[SUPERSEDED <date>: ...]`  — the property moved; say where it is carried now
  * `[NOT RUNNABLE: ...]`      — the spec cannot run (e.g. its test was retired)
  * `[BAD-ANCHOR: ...]`        — the anchor was wrong when written

An unexplained loss means a property that was once verified no longer is, and the census says
so. `agent/tests/test_1203pe_the_census_the_habit_could_not_do.py` fails when one appears.
