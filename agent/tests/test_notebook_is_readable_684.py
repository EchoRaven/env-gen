r"""#684: the only memory file an agent can WRITE was the one file it could not READ.

Found in r145's failure scan, and it settles an open question rather than just fixing a typo.

    update_memory_bank   writes EXCLUSIVELY to notebook.md — "your private, writable notebook
                         … it persists across all your steps"
    read_memory_bank     `notebook` was absent from the schema enum, from `file_map`, and from
                         the error text, so every attempt was refused

r145 refused 8 of them. Seven notebook.md files were sitting on disk in that same run, four of
them carrying real content, and 1715 exist across the corpus.

That also answers the standing question about why the notebook looked unused (experiments item
12): it was not unused, it was unreadable. A write-only memory is inert by construction — an
agent can record what it learned and can never consult it.

`MemoryBank.CORE_FILES` has always listed notebook as the sixth core file, so the writer, the
store and the on-disk layout all agreed; only the reader disagreed.
"""
import inspect

import pytest

from env_generator.llm_generator.tools import agent_interaction_tools as ait


def _src():
    return inspect.getsource(ait)


# --- the reader accepts it in all three places ---------------------------------------------

def test_the_schema_enum_offers_notebook():
    """Absent here, the model is never told the option exists."""
    assert '"progress", "notebook"]' in _src()


def test_the_file_map_resolves_notebook():
    assert '"notebook": "notebook.md"' in _src()


def test_the_error_message_lists_notebook():
    """r145's refusal text enumerated five of the six files."""
    assert "progress, notebook" in _src()


def test_all_six_core_files_are_reachable():
    from env_generator.llm_generator.memory.memory_bank import MemoryBank
    src = _src()
    for key in MemoryBank.CORE_FILES:
        assert f'"{key}": "{key}.md"' in src or f'"{key}"' in src, key


# --- the writer's target and the reader's key are the same name -------------------------------

def test_the_writer_still_targets_the_notebook():
    assert "append_notebook(" in _src()


def test_the_writer_and_reader_agree_on_the_filename():
    from env_generator.llm_generator.memory.memory_bank import MemoryBank
    assert MemoryBank.CORE_FILES["notebook"]["filename"] == "notebook.md"
    assert '"notebook": "notebook.md"' in _src()


# --- the other five are untouched ---------------------------------------------------------------

@pytest.mark.parametrize("key", ["project_brief", "tech_context", "system_patterns",
                                 "active_context", "progress"])
def test_the_existing_options_are_unchanged(key):
    src = _src()
    assert f'"{key}": "{key}.md"' in src
    assert f'"{key}"' in src.split('"enum":')[1][:200]


def test_all_is_still_accepted():
    assert '"all"' in _src().split('"enum":')[1][:200]


# --- provenance -------------------------------------------------------------------------------

def test_the_measurement_is_recorded():
    flat = " ".join(_src().replace("#", " ").split())
    assert "r145 refused 8 of them" in flat
    assert "1715 of them exist across the corpus" in flat


def test_the_open_question_it_answers_is_recorded():
    """Whoever reads item 12 next must find the answer here."""
    flat = " ".join(_src().replace("#", " ").split())
    assert "it was not unused, it was unreadable" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
