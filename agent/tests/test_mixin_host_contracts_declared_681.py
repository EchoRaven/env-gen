r"""#681: 45% of the type checker's output was mixins not knowing their host.

Not a bug fix — a noise removal, so the next sweep's real findings are not buried. The checker
reported 2218 errors and 990 of them (45%) were `missing-attribute` on mixin classes: a mixin
reads `self.agent_id` and `self._logger`, the host class supplies them, and a checker reading the
mixin's file alone cannot know that.

That noise is not free. The same sweep that produced it also found #658 (two constructors called
with keyword arguments the classes do not have — both guaranteed TypeErrors) and a dangling
`WorkHub` annotation, and both were sitting under 990 false positives.

Declaring the host contract under `TYPE_CHECKING` is annotation-only: no runtime import, no
runtime effect, and the suite is unchanged at 2880.

    total errors        2218 -> 1472   (-34%)
    missing-attribute    990 ->  244   (-75%)
    bad-assignment        55 ->   46

The bad-assignment line moved because resolving `self` made four pre-existing inconsistencies
visible in messaging.py: base.py declares `_active_phase` and `_focus_hub` as `Optional[str]`,
while the mixin assigns a str and later restores None. Mirroring the host's real types fixed
those four and five older ones. That is the cleanup paying for itself immediately — those reports
were unreachable while `self` was untyped.

17 files carry the block. The attribute lists were taken FROM THE DIAGNOSTICS rather than guessed,
and method-versus-data was decided by whether the source calls `self.NAME(`.
"""
import ast
import pathlib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1] / "env_generator/llm_generator"


def _declared_files():
    return sorted(p for p in _ROOT.rglob("*.py") if "#681" in p.read_text(encoding="utf-8"))


def test_the_block_is_present_where_it_was_measured():
    names = {p.name for p in _declared_files()}
    for expected in ("messaging.py", "tooling.py", "step_runner.py", "lifecycle.py"):
        assert expected in names


def test_every_declaration_file_still_parses():
    for p in _declared_files():
        ast.parse(p.read_text(encoding="utf-8"))


@pytest.mark.parametrize("mod", [
    "env_generator.llm_generator.multi_agent.agents.runtime.messaging",
    "env_generator.llm_generator.multi_agent.agents.runtime.tooling",
    "env_generator.llm_generator.multi_agent.agents.runtime.step_runner",
])
def test_the_runtime_modules_still_import(mod):
    __import__(mod)


# --- annotation-only: nothing may execute at runtime ---------------------------------------------

def test_every_block_is_guarded_by_TYPE_CHECKING():
    for p in _declared_files():
        src = p.read_text(encoding="utf-8")
        i = src.index("#681")
        head = src[i:src.index("\n\n", i)]
        assert "if TYPE_CHECKING:" in head, p.name


def test_no_block_introduces_a_runtime_import():
    """A TYPE_CHECKING body must not be where a real import sneaks in."""
    for p in _declared_files():
        src = p.read_text(encoding="utf-8")
        i = src.index("if TYPE_CHECKING:", src.index("#681"))
        body = src[i:src.index("\n\n", i)]
        assert "import " not in body, p.name


def test_the_declarations_are_bare_annotations_or_stubs():
    for p in _declared_files():
        src = p.read_text(encoding="utf-8")
        i = src.index("if TYPE_CHECKING:", src.index("#681"))
        for line in src[i:src.index("\n\n", i)].splitlines()[1:]:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            # either `name: Type` or a `def name(...) -> Any: ...` stub — never a statement
            assert s.startswith("def ") or ":" in s, f"{p.name}: {s}"
            if not s.startswith("def "):
                assert " = " not in s, f"{p.name}: assignment in a declaration: {s}"


# --- the host's real types are mirrored, not invented ----------------------------------------------

def test_the_optional_attributes_match_the_host():
    """base.py declares both Optional; an inferred `str` flagged the None restore."""
    msg = (_ROOT / "multi_agent/agents/runtime/messaging.py").read_text(encoding="utf-8")
    assert "_active_phase: Optional[str]" in msg
    assert "_focus_hub: Optional[str]" in msg

    base = (_ROOT / "multi_agent/agents/base.py").read_text(encoding="utf-8")
    assert "self._active_phase: Optional[str]" in base
    assert "self._focus_hub: Optional[str]" in base


def test_the_reason_for_mirroring_is_recorded():
    msg = (_ROOT / "multi_agent/agents/runtime/messaging.py").read_text(encoding="utf-8")
    assert "mirror base.py" in msg


# --- provenance -------------------------------------------------------------------------------

def test_the_measurement_is_recorded():
    src = (_ROOT / "multi_agent/agents/runtime/messaging.py").read_text(encoding="utf-8")
    i = src.index("#681")
    note = src[i:src.index("if TYPE_CHECKING:", i)]
    flat = " ".join(note.replace("#", " ").split())
    assert "990 of" in flat and "2218 diagnostics" in flat
    assert "45%" in flat


def test_the_noise_it_was_burying_is_named():
    """Why this is worth doing at all: real findings were under it."""
    src = (_ROOT / "multi_agent/agents/runtime/messaging.py").read_text(encoding="utf-8")
    i = src.index("#681")
    flat = " ".join(src[i:src.index("if TYPE_CHECKING:", i)].split())
    assert "658" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
