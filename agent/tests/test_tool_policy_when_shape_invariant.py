"""PR5 final — invariant: every v3 prompt's tool_policy entry uses the
``{tool, when, cap?}`` shape. Legacy ``use:`` / ``avoid:`` keys are
banned (the user's "我不太希望prompt里面出现DO not use之类的东西"
guidance).

The shared macro at ``prompts/agents/shared/agent_definition_v3.j2``
renders only ``it.when``; if a profile reintroduces ``it.use`` /
``it.avoid``, the per-entry policy line would silently render empty
(Jinja2 undefined → empty). This test scans the prompts directory at
source level and fails fast on any regression.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

PROMPTS_V3_DIR = (
    Path(__file__).resolve().parents[1]
    / "env_generator"
    / "llm_generator"
    / "multi_agent"
    / "prompts"
    / "v3"
)


def _read_prompts() -> dict:
    """Return {lane_name: text} for every v3 lane prompt."""
    return {
        p.stem: p.read_text(encoding="utf-8")
        for p in sorted(PROMPTS_V3_DIR.glob("*_agent.j2"))
    }


class ToolPolicyShapeInvariant(unittest.TestCase):
    def test_every_lane_has_when_shape_only(self):
        """No v3 prompt may have ``"use":`` or ``"avoid":`` keys inside
        a tool_policy dict. Tested by AST-aware regex matching the
        dict-entry shape (``"<key>":``).
        """
        # Match ONLY the dict-key form: a quoted key followed by a colon.
        # This is the shape Jinja2's macro reads. Plain text matches
        # like "do not use" inside a docstring are NOT flagged.
        legacy_use = re.compile(r'"use"\s*:')
        legacy_avoid = re.compile(r'"avoid"\s*:')
        offenders = []
        for lane, text in _read_prompts().items():
            for m in legacy_use.finditer(text):
                line_no = text[: m.start()].count("\n") + 1
                offenders.append((lane, "use", line_no))
            for m in legacy_avoid.finditer(text):
                line_no = text[: m.start()].count("\n") + 1
                offenders.append((lane, "avoid", line_no))
        self.assertEqual(
            offenders,
            [],
            "Legacy tool_policy keys found — every entry must be "
            "{tool, when, cap?}. Offenders (lane, key, line):\n  "
            + "\n  ".join(f"{l} :: {k} @ L{n}" for l, k, n in offenders),
        )

    def test_every_lane_uses_when_key(self):
        """Each prompt that defines tool_policy MUST use ``"when":``
        keys (sanity check: not every prompt has tool_policy, but those
        that do must have at least one ``"when":`` to prove the
        migration landed)."""
        when_re = re.compile(r'"when"\s*:')
        for lane, text in _read_prompts().items():
            if "tool_policy=[" not in text:
                continue
            self.assertTrue(
                when_re.search(text),
                f"{lane}: tool_policy block exists but no \"when\": "
                f"key found — migration incomplete.",
            )


class ToolPolicyMacroShapeInvariant(unittest.TestCase):
    """The shared macro at agent_definition_v3.j2 must render only
    ``when`` + ``cap`` — no ``use``/``avoid`` references in the macro
    body."""

    def test_macro_body_has_no_use_or_avoid(self):
        macro_path = (
            Path(__file__).resolve().parents[1]
            / "env_generator"
            / "llm_generator"
            / "multi_agent"
            / "prompts"
            / "agents"
            / "shared"
            / "agent_definition_v3.j2"
        )
        text = macro_path.read_text(encoding="utf-8")
        # Find the _tool_policy macro body.
        m = re.search(
            r"{% macro _tool_policy.*?{% endmacro %}",
            text,
            re.DOTALL,
        )
        self.assertIsNotNone(m, "_tool_policy macro not found")
        body = m.group(0)
        # The body must not reference it.use or it.avoid.
        self.assertNotIn(
            "it.use",
            body,
            "macro body still references legacy ``it.use`` — "
            "PR5 final migration not complete.",
        )
        self.assertNotIn(
            "it.avoid",
            body,
            "macro body still references legacy ``it.avoid``.",
        )
        # And it MUST reference it.when (the new shape).
        self.assertIn("it.when", body, "macro body must reference it.when")


if __name__ == "__main__":
    unittest.main()
