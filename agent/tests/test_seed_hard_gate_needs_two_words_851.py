r"""#851: the seed hard gate's false-positive protection had no test.

`audit_authored_seed` is a BLOCKING content gate. Its placeholder half fires when a table carries
**>= 2 DISTINCT** words from `_HARD_MARKER_WORDS` on word boundaries. The comment beside that set
used to justify it with:

    this hard-gate set must never collide with legitimate vocabulary

which is false as written, and the counter-examples are exactly the non-Netflix domains this
framework exists to generate: `qwerty` is keyboard vocabulary, `placeholder` is form vocabulary,
`foo` is a band name, `dummy` is a crash-test noun. A blocking gate justified by an assertion its
own generality goal falsifies is #788's shape — a claim about the code with nothing checking it.

The real protection is the **>= 2 distinct, same table** rule, and nothing tested it. That matters
more than the rate: item 152 established that a blocking gate converts a false positive into a
DEAD RUN, so what has to hold is the shape of the guard, not its historical trigger count.

Exposure, measured: **0 of 151 corpus runs** contain even one of these words in any seed row. The
false-positive record is therefore not clean, it is EMPTY. These cases are the only evidence the
guard has, which is the argument for writing them down.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime import seed_audit


def _issues(data, **env):
    return seed_audit.audit_authored_seed(data)


def _dense(rows):
    """Enough structured rows to clear the density floor, so a case tests only the marker half."""
    return rows + [{"title": f"Believable Title {i}", "year": 2000 + i} for i in range(12)]


def test_the_gate_is_wired_at_all():
    """Non-vacuity: two distinct markers in one table must produce an issue, or every negative
    case below passes for the wrong reason."""
    out = _issues({"t": _dense([{"a": "lorem ipsum dolor sit"}])})
    assert any("placeholder" in i for i in out), out


def test_one_marker_alone_is_not_enough():
    """★ The protection. A typing tutor legitimately seeds 'QWERTY layout'; a CMS legitimately
    seeds a field named 'placeholder'; a music app legitimately seeds 'Foo Fighters'."""
    for legit in ("QWERTY layout, 60% keyboard", "placeholder text for the email field",
                  "Foo Fighters — Everlong", "crash test dummy regulations"):
        out = _issues({"t": _dense([{"a": legit}])})
        assert not any("placeholder" in i for i in out), (legit, out)


def test_two_markers_in_DIFFERENT_tables_do_not_combine():
    """The rule is per-table. A keyboard shop with a 'placeholder' form hint in another table is
    two single collisions, not one placeholder table."""
    out = _issues({"keyboards": _dense([{"a": "QWERTY layout"}]),
                   "form_fields": _dense([{"a": "placeholder text"}])})
    assert not any("placeholder" in i for i in out), out


def test_two_markers_in_one_table_still_fire():
    """And the guard must not be so weak that real lorem-ipsum slips through."""
    out = _issues({"t": _dense([{"a": "lorem"}, {"b": "asdf qwerty"}])})
    assert any("placeholder" in i for i in out), out


def test_the_same_word_twice_is_one_marker():
    """DISTINCT, not count — otherwise a keyboard catalogue saying 'qwerty' on 40 rows blocks."""
    out = _issues({"t": _dense([{"a": "QWERTY"} for _ in range(40)])})
    assert not any("placeholder" in i for i in out), out


@pytest.mark.parametrize("text", ["food foobar", "the latest release", "basil and bazaar",
                                  "quixotic", "example_username", "xxxxx"])
def test_word_boundaries_are_respected(text):
    """`foo` must not hit 'food', `baz` must not hit 'bazaar', `qux` must not hit 'quixotic'.
    The substring form of this check lives in the ADVISORY audit; the hard gate may not use it."""
    assert seed_audit._word_boundary_markers([{"a": text}]) == [], text


def test_a_separator_does_not_hide_a_marker():
    """The mirror: `lorem-ipsum` and `lorem_ipsum` are still two markers."""
    for t in ("lorem-ipsum", "lorem_ipsum", "lorem/ipsum", "(lorem) [ipsum]"):
        assert set(seed_audit._word_boundary_markers([{"a": t}])) == {"lorem", "ipsum"}, t


def test_the_over_claim_is_gone():
    """★ The comment asserted a property the word list does not have. A normative sentence in a
    comment is a claim about the code that decays silently (#788) — and this one was false on the
    day it was written, because the collisions are in the domains the framework is FOR."""
    import inspect
    src = inspect.getsource(seed_audit)
    assert "must never collide with legitimate vocabulary" not in src
    assert "qwerty` is keyboard vocabulary" in src, "the counter-examples must be recorded"
    assert "0 of 151 runs" in src, "an untriggered gate must say its record is empty, not clean"


def test_the_density_floor_and_the_markers_are_independent():
    """A thin seed with no markers reports only the row count, and vice versa — so a lane reading
    the remediation text is told the one thing that is actually wrong."""
    thin = _issues({"t": [{"title": "Believable"}]})
    assert len(thin) == 1 and "structured row" in thin[0], thin
    marked = _issues({"t": _dense([{"a": "lorem ipsum"}])})
    assert len(marked) == 1 and "placeholder" in marked[0], marked


def test_the_corpus_minimum_really_does_clear_the_floor():
    """151-run measurement, pinned as a case rather than only as a comment: the smallest seed any
    run actually authored is 60 rows against a floor of 10."""
    assert _issues({"t": [{"i": i} for i in range(60)]}) == []
    assert seed_audit._MIN_AUTHORED_TOTAL_ROWS == 10


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
