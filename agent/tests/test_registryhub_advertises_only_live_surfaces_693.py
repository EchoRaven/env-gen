r"""#693: RegistryHub's one-line docstring promised five surfaces; two have never held a record.

This is the tail of EXPERIMENTS_PENDING item 16 ("19 of the 43 hub stores are created every run
and never written"), and it needed no run to settle — only the right instrument.

`JsonStore.update` always calls `_save_raw` and always calls `_bump_meta`; there is no branch that
skips either. So `_meta.version` counts writes exactly, and a store still at version 1 after a
whole run was created and never written. Reading that counter across all 146 kept runs splits the
19 supposedly-dead stores into three genuinely different states, which "empty on disk" had
collapsed into one:

    drained        pending_consumers  v29 (r145) / v33 (r146), 0 entries. Not dead — queued and
                   then promoted-and-deleted. 14 sets + 14 deletes + 1 create = 29 exactly.
    never written  examples, mocks, reviews, seed_registrations, table_consumers,
                   table_breaking_changes — a writer exists in the tree and has never fired.
    no writer      projects, providers, schemas — construction plus `.value()` reads and nothing
                   else anywhere in the tree, so every branch keyed on them is unreachable.

The remaining nine (codehub_* and workhub_*) are not constructed by the `JsonStore(... "name")`
form at all, so they are out of this fix's scope and stay recorded in item 16.

Only the docstring changes. The stores are not deleted: their readers still exist, an empty store
is a legitimate state, and deleting live-looking machinery on a static argument is exactly the
kind of change that should wait for evidence. What was wrong was a sentence telling the next
reader that `schema` and `mock` carry data.
"""
import json
import re
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime.registryhub import RegistryHub
from env_generator.llm_generator.multi_agent.runtime import json_store as js


# --- the instrument the finding rests on --------------------------------------------------------

def test_update_always_bumps_the_version():
    """The whole argument is that version counts writes; if update could skip, it would not."""
    import inspect
    src = inspect.getsource(js.JsonStore.update)
    body = src[src.index("with self._lock"):]
    assert "_bump_meta" in body and "_save_raw" in body
    # no early return between the mutation and the save
    between = body[body.index("result = mutator"):body.index("_save_raw")]
    assert "return" not in between, "an early return would make version undercount writes"


def test_a_fresh_store_starts_below_one(tmp_path: Path):
    s = js.JsonStore(tmp_path / "x.json")
    assert s.get_version() == 0


def test_one_write_is_one_version(tmp_path: Path):
    s = js.JsonStore(tmp_path / "x.json")
    s.update(lambda m: m.set("k", {"v": 1}, "tester"), change_info={"agent": "tester"})
    assert s.get_version() == 1


def test_a_delete_also_counts_as_a_write(tmp_path: Path):
    """The drained-queue arithmetic depends on this: sets AND deletes both bump."""
    s = js.JsonStore(tmp_path / "x.json")
    s.update(lambda m: m.set("k", {"v": 1}, "t"), change_info={"agent": "t"})
    s.update(lambda m: m.delete("k", "t"), change_info={"agent": "t"})
    assert s.get_version() == 2
    assert [k for k in json.loads((tmp_path / "x.json").read_text()) if not k.startswith("_")] == []


def test_a_drained_store_is_indistinguishable_from_an_unused_one_by_CONTENT(tmp_path: Path):
    """Why 'empty in 144 of 144 runs' was never evidence of a dead writer."""
    used, never = js.JsonStore(tmp_path / "a.json"), js.JsonStore(tmp_path / "b.json")
    used.update(lambda m: m.set("k", {}, "t"), change_info={"agent": "t"})
    used.update(lambda m: m.delete("k", "t"), change_info={"agent": "t"})
    never.update(lambda m: m, change_info={"agent": "creator"})

    def _entries(s):
        return [k for k in json.loads(s.file_path.read_text()) if not k.startswith("_")]

    assert _entries(used) == _entries(never) == []      # same content ...
    assert used.get_version() != never.get_version()    # ... different history


# --- the docstring now matches the measurement --------------------------------------------------

def _doc() -> str:
    return RegistryHub.__doc__ or ""


def test_the_three_states_are_named():
    d = _doc()
    for state in ("live", "drained", "never written", "no writer"):
        assert state in d


def test_the_writerless_stores_are_named():
    d = _doc()
    for store in ("projects", "providers", "SCHEMAS"):
        assert store in d


def test_it_says_which_promised_surfaces_are_empty():
    d = _doc()
    assert "`schema` and `mock` have never held a record" in d
    assert "`review` has a writer that has never run" in d


def test_the_instrument_is_explained_not_just_asserted():
    d = _doc()
    assert "counts writes exactly" in d
    assert "no conditional skip" in d


def test_the_drained_case_is_not_called_dead():
    """pending_consumers works; the docstring must not lump it in with the dead ones."""
    d = _doc()
    # Anchored on the NEXT state name rather than a character count: a fixed-width window
    # silently changes what it covers the moment the text above it grows.
    i = d.index("drained")
    section = d[i:d.index("never written", i)]   # search FROM i: the prose above says it first
    assert "promoted then deleted" in section


def test_it_says_why_nothing_was_deleted():
    assert "an empty store is a legitimate state" in _doc()


def test_the_original_sentence_survives():
    """The class is still what it was; only the claim about coverage is qualified."""
    assert _doc().startswith("Apifox-like API registry, schema, consumer, mock, test, and review hub.")


# --- the writerless claim is checked against the tree, not just asserted -------------------------

@pytest.mark.parametrize("attr", ["_projects", "_providers", "_schemas"])
def test_the_writerless_stores_really_have_no_mutation(attr):
    """If someone adds a writer later, this fails and the docstring must be updated with it."""
    root = Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"
    pat = re.compile(r"self\." + attr + r"\.(update|set|delete)\(")
    offenders = [p for p in root.rglob("*.py") if pat.search(p.read_text(errors="ignore"))]
    assert not offenders, f"{attr} now has a writer: {offenders}"


@pytest.mark.parametrize("attr", ["_endpoints", "_consumers"])
def test_the_control_stores_do_have_writers(attr):
    """The probe above must be capable of finding a writer, or it proves nothing."""
    root = Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"
    pat = re.compile(r"self\." + attr + r"\.update\(")
    assert any(pat.search(p.read_text(errors="ignore")) for p in root.rglob("*.py"))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
