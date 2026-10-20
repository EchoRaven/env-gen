r"""#1203qa: mutation testing stopped at the language boundary, so the config layer was unmutable.

`scripts/mutate.py` refuses to start when it has no syntax checker for the target's language,
and that refusal is right: #1203jq records what the alternative cost — py_compile was once
hard-wired, so the first shell target reported all four mutations BROKEN when every mutant was
valid bash, "the truth while naming the wrong cause". Returning None for an unknown language is
how a syntactically broken mutant is kept from running and coming back MISSED.

The consequence was that an entire load-bearing layer could not be mutated at all:
`agents_config.yaml` names the `(template, macro)` pairs every lane's system and task prompt
is built from, and NOTHING in Python spells those macro names — they are config strings
resolved by `getattr(template.module, macro_name, None)`. #1203q9 guards that contract; without
a checker for `.yaml` and `.j2` there was no way to show the guard actually bites.

So this adds two checkers and pins what each must answer:

  * `_yaml_ok` is `yaml.safe_load`, the same parse the real readers use.
  * `_j2_ok` is `jinja2.Environment().parse`, a compile of the template TEXT that raises on a
    broken tag and needs none of the render context.

THE DISCRIMINATION THAT MATTERS: a RENAMED macro is still valid Jinja. That mutation is a
contract break, not a syntax break, so the checker must pass it and the test must catch it. A
checker that rejected it would turn #1203q9's four mutations into four BROKENs and the guard
would look verified while nothing had been tested.

The import is checked in `_syntax_checker`, not inside either function: a missing pyyaml or
jinja2 has to leave the dispatcher returning None (main() then refuses to start) rather than
answering False, which would be #1203jq's defect reintroduced one language over.
"""
from __future__ import annotations

import importlib.util
import pathlib
import tempfile
import unittest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_MUTATE = _ROOT / "scripts" / "mutate.py"


def _load():
    spec = importlib.util.spec_from_file_location("_mutate_1203qa", _MUTATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = _load()

    def _verdict(self, suffix: str, body: str):
        with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False,
                                         encoding="utf-8") as fh:
            fh.write(body)
            path = fh.name
        try:
            checker = self.m._syntax_checker(path)
            return None if checker is None else checker(path)
        finally:
            pathlib.Path(path).unlink(missing_ok=True)


class TheCheckersAcceptWhatIsValid(_Base):

    def test_valid_yaml(self):
        self.assertIs(self._verdict(".yaml", "a: 1\nb:\n  - x\n"), True)

    def test_valid_jinja(self):
        self.assertIs(self._verdict(".j2", "{% macro foo(x) %}hi {{ x }}{% endmacro %}"), True)

    def test_a_renamed_macro_is_still_valid_jinja(self):
        """The #1203q9 mutations rename a macro. If the checker called that broken, all four
        would report BROKEN and the contract guard would be unverifiable."""
        self.assertIs(
            self._verdict(".j2", "{% macro foo_renamed(x) %}hi{% endmacro %}"), True)

    def test_a_renamed_key_is_still_valid_yaml(self):
        self.assertIs(self._verdict(".yaml", 'system_macro: "x_renamed"\n'), True)


class TheCheckersRejectWhatIsBroken(_Base):

    def test_broken_yaml_indentation(self):
        self.assertIs(self._verdict(".yaml", "a: 1\n  b: 2\n   c: 3\n"), False)

    def test_unclosed_yaml_flow_sequence(self):
        self.assertIs(self._verdict(".yaml", "a: [1,2\n"), False)

    def test_unclosed_jinja_macro(self):
        self.assertIs(self._verdict(".j2", "{% macro foo(x) %}hi {{ x }}"), False)

    def test_unclosed_jinja_expression(self):
        self.assertIs(self._verdict(".j2", "{{ unclosed "), False)


class TheDispatcherStillRefusesWhatItCannotCheck(_Base):
    """#1203jq's rule is the reason this file exists; adding languages must not weaken it."""

    def test_an_unknown_language_has_no_checker(self):
        self.assertIsNone(self._verdict(".rb", "puts 'hi'"))

    def test_the_known_languages_map_to_their_own_checker(self):
        cases = {
            "x.py": "_py_ok", "x.sh": "_sh_ok", "x.bash": "_sh_ok",
            "x.yaml": "_yaml_ok", "x.yml": "_yaml_ok",
            "x.j2": "_j2_ok", "x.jinja": "_j2_ok", "x.jinja2": "_j2_ok",
        }
        for name, want in cases.items():
            with self.subTest(name=name):
                got = self.m._syntax_checker(str(_ROOT / name))
                self.assertIsNotNone(got, name)
                self.assertEqual(got.__name__, want)

    def test_a_missing_parser_yields_no_checker_rather_than_False(self):
        """Hiding the import inside the checker would answer False for a reason that is not
        the mutant -- BROKEN naming the wrong cause, which is #1203jq exactly."""
        import builtins
        real = builtins.__import__

        def _no(name, *a, **k):
            if name in ("yaml", "jinja2"):
                raise ImportError("simulated: %s unavailable" % name)
            return real(name, *a, **k)

        builtins.__import__ = _no
        try:
            self.assertIsNone(self.m._syntax_checker(str(_ROOT / "x.yaml")))
            self.assertIsNone(self.m._syntax_checker(str(_ROOT / "x.j2")))
        finally:
            builtins.__import__ = real


class TheRealTargetsAreCovered(_Base):
    """The point of the change: these two files are now mutable."""

    def test_agents_config_and_the_v4_template_have_checkers(self):
        for rel in ("agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml",
                    "agent/env_generator/llm_generator/multi_agent/prompts/v4/backend_agent.j2"):
            p = _ROOT / rel
            self.assertTrue(p.exists(), rel)
            checker = self.m._syntax_checker(str(p))
            self.assertIsNotNone(checker, rel)
            self.assertIs(checker(str(p)), True, "%s does not parse as itself" % rel)


if __name__ == "__main__":
    unittest.main()
