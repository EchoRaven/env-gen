r"""#813: the design-prep screen enrichment produced nothing and never said why.

#812 ended by opening two fields deferred twice without looking. Applying the same to the third
declined item — `type_scale`, `radius_scale`, `build_notes` — changed the verdict again and
uncovered something larger.

`type_scale` and `radius_scale` are measured and paste-ready (`hero_title_h1` at 44px/700/1.05
line-height; `{card: 4, modal: 8, pill: 999}`). But `build_notes` opened onto this:

    12 recent runs, 4,006 components
        crop          3,675   (92%)   <- comes from the SKELETON path
        build_notes       1   (0.02%)
        typography        0
    component_specs/*.json, 318 components:   build_notes 0, typography 0

`build_notes` is `"required": ["id", "build_notes"]` in design_prep's own schema and its prompt
demands "1-3 concrete sentences from the SCREENSHOT". It arrives essentially never, while `crop` —
which comes from the skeleton rather than this call — arrives 92% of the time. So the enrichment
call is the part yielding nothing.

And it could not say so: a bare `except Exception: doc = None` then `continue`. **#769's exact
shape on a measurement path.** Transport error, non-dict reply, 6000-token truncation — all three
land in the same silent skip, leaving an unenriched skeleton.

★ Not cosmetic: the frontend prompt directs the lane to read per-component
`build_notes`/`typography` on EVERY component, so the lane is pointed at fields that are empty
4,005 times out of 4,006 — #788's class at component granularity.

The cause needs a live design-prep call and cannot be settled offline. What this guarantees is that
the next run names it per screen instead of leaving a mute skeleton.

★★ And one method correction: `ast.parse` has been my syntax gate all session, and it **passed**
the first version of this fix, which put `import logging` above `from __future__ import
annotations`. `ast.parse` does not enforce `__future__` placement; `compile()` does, and importing
the module does. A gate that accepts a file Python will refuse is a gate with a hole in it.
"""
import inspect
import logging

import pytest

from env_generator.llm_generator.multi_agent.runtime import design_prep as dp


def test_the_bare_handler_is_gone():
    assert "except Exception:\n            doc = None" not in inspect.getsource(dp)


def test_the_failure_names_the_screen_and_the_cause():
    # Anchored on code statements, not on the word "continue": the comment explaining this fix
    # quotes `continue` verbatim, so `index("continue", i)` landed inside the prose. Eleventh
    # self-match of the session — the same trap as #798's ticket-number anchor.
    src = inspect.getsource(dp)
    i = src.index("except Exception as exc:\n            # #813")
    blk = src[i:src.index("if not isinstance(doc, dict):", i)]
    assert "type(exc).__name__" in blk and 's.get("name")' in blk
    assert "_LOG_813.warning(" in blk


def test_it_states_the_downstream_consequence():
    """A log that says only 'failed' does not tell the reader the lane is now pointed at empty
    fields — the part that costs a round."""
    assert "points the lane at fields that will be empty" in inspect.getsource(dp)


def test_a_non_dict_reply_is_distinguished_from_an_exception():
    """'the call threw' and 'the model returned a list' need different fixes."""
    assert "not an object" in inspect.getsource(dp)


def test_the_measurement_travels_with_the_fix():
    src = " ".join(inspect.getsource(dp).replace("#", " ").split())
    assert "4,006" in src and "3,675" in src


def test_the_logger_exists():
    assert isinstance(dp._LOG_813, logging.Logger)


def test_the_module_actually_compiles():
    """★ `ast.parse` passed the first cut of this fix, which put an import above
    `from __future__ import annotations`. It does not enforce `__future__` placement. `compile()`
    does — so the gate is `compile`, not `ast.parse`."""
    import pathlib
    src = pathlib.Path(dp.__file__).read_text(encoding="utf-8")
    compile(src, dp.__file__, "exec")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
