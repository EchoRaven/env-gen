r"""#694/#694b: the seed blocker named an action without saying where the action lives.

`seed_audit` flags a table that was never seed-registered and hands the owner a hint. The hint
used to read, in full, "call register_seed_data after seeding" — which reads like a startup call
the generated backend is missing. That is exactly how it was read, and the corpus shows the cost:

    [backend] GREP pattern=register_seed_data scope=app/backend    84 times, 18 runs
    every one of them                                              "0 matches"
    escalated to `P0 delivery-gate: register_seed_data for all 12 tables (0/12 registered)`
                                                                   3 runs

It can never match. `register_seed_data` is an agent-facing HUB TOOL (tools/seed_tools.py:19),
not a symbol in the generated app, so searching app/backend for it is guaranteed to fail.

Two things make this worth wording carefully rather than re-detecting:

  * It is rare and expensive. `missing_seed` fires 14 times in 253 logs, because the loop only
    examines tables still marked `defined` and 1632 of the corpus's 1648 table records are
    `implemented` by then. Low frequency, high per-firing cost.
  * It has never once succeeded. 0 `seed_registered` events, and
    registryhub_seed_registrations sits at `_meta.version` 1 — create only, never written — in
    146 of 146 runs.

And one thing that is not wording at all: the `seed` bundle is granted to orchestrator and
verifier only. backend, frontend and debugger do not hold it. "Call it yourself" is right for the
audit's caller and impossible for whoever the blocker is dispatched to — `backend` in all 18 of
those runs. So the hint now also says what to do when you do NOT have the tool. Changing the
grant is a routing decision with blast radius past this audit and is deliberately not made here.

Same class as #682 and #690: the remediation text, not the detection, is what costs the rounds.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime import seed_audit as sa


def _src() -> str:
    """The SOURCE of the missing_seed branch that carries the HINT — comments included.

    ★ Anchored on the hint, not on the FIRST `"reason": "missing_seed"`. #956's live-row-count
    repair added a second, earlier `missing_seed` branch (the live-COUNT(*) path, which needs
    no hint — it reports a measured row count instead), and this locator silently retargeted
    onto it, failing four provenance assertions at once. A locator that means "the branch with
    the hint" must say so ([[a-bare-name-search-is-never-a-locator]]).
    """
    import inspect
    src = inspect.getsource(sa)
    start = 0
    while True:
        i = src.index('"reason": "missing_seed"', start)
        end = src.index('"low_row_count"', i)
        block = src[i:end]
        if '"hint"' in block:
            return block
        start = i + 1


def _hint() -> str:
    """The assembled hint STRING, not its source.

    Reading the source instead was the first draft's bug: adjacent string literals leave
    `... add a " "register_seed_data() ...` in the text, so an assertion about the sentence the
    agent actually receives silently tested the quoting instead. ast folds the concatenation.
    """
    import ast
    import inspect
    for node in ast.walk(ast.parse(inspect.getsource(sa))):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if (isinstance(k, ast.Constant) and k.value == "hint"
                        and isinstance(v, ast.Constant) and "register_seed_data" in str(v.value)
                        and "HUB" in str(v.value)):
                    return v.value
    raise AssertionError("the missing_seed hint is no longer a plain string literal")


# --- it says what the thing IS ------------------------------------------------------------------

def test_it_calls_it_a_hub_tool():
    assert "HUB " in _hint() and "TOOL" in _hint()


def test_it_forbids_the_wrong_repair_explicitly():
    """The observed failure was a backend task to add a startup call."""
    h = _hint()
    assert "Do NOT add a" in h
    assert "not app code" in h


def test_it_says_nothing_in_the_app_can_call_it():
    assert "nothing in the app can call it" in _hint()


# --- #694b: it says what to do when you cannot call it -------------------------------------------

def test_it_tells_a_toolless_owner_not_to_search():
    h = _hint()
    assert "do not go looking for it in the app" in " ".join(h.split())


def test_it_tells_them_to_hand_the_item_back():
    assert "hand the item back" in _hint()


def test_it_names_the_bundle_rather_than_a_role():
    """Naming the bundle keeps this true if the grant is later changed."""
    h = _hint()
    assert "`seed` bundle" in h
    assert "not every role" in h


def test_it_states_the_ordering_requirement():
    assert "registered first" in _hint()


# --- the wrong repair is not accidentally re-suggested -------------------------------------------

def test_the_hint_never_suggests_editing_the_backend():
    # One contiguous phrase, so no window is needed to prove the two halves are adjacent.
    h = " ".join(_hint().split()).lower()
    assert "do not add a register_seed_data() call to the generated backend" in h


def test_the_hint_is_one_clean_sentence_run():
    """No stray quote artifacts: this is what the agent actually reads."""
    h = _hint()
    assert '" "' not in h
    assert "  " not in h


def test_the_detector_itself_is_unchanged():
    """Only the wording moved; the flag and its reason code must stay."""
    import inspect
    src = inspect.getsource(sa)
    assert '"reason": "missing_seed"' in src
    assert '"min_seed_rows": min_rows' in src


# --- provenance -----------------------------------------------------------------------------------

def test_the_grep_cost_is_recorded():
    flat = " ".join(_src().replace("#", " ").split())
    assert "84 times across 18 runs" in flat
    assert "0 matches" in flat


def test_the_never_succeeded_measurement_is_recorded():
    flat = " ".join(_src().replace("#", " ").split())
    assert "146 of 146 runs" in flat
    assert "0 `seed_registered` events" in flat


def test_the_rarity_argument_is_recorded():
    """Why the wording was fixed instead of the detector."""
    flat = " ".join(_src().replace("#", " ").split())
    assert "14 times across 253 logs" in flat
    assert "fixing the wording rather than the detector" in flat


def test_the_grant_asymmetry_is_recorded():
    flat = " ".join(_src().replace("#", " ").split())
    assert "orchestrator and verifier only" in flat
    assert "is deliberately not made here" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
