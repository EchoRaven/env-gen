"""#336: the pinned auth guard hardcodes 'token' while the canonical key is
'access_token', so two framework passes rewrite the same file forever.

`pin_frontend_build_tooling` rewrites `src/bc_auth.js` to `_BC_AUTH_GUARD_JS`
whenever the file differs. That template hardcodes
`localStorage.removeItem('token')`. Then #317's `normalize_frontend_token_key`
rewrites every `localStorage.*Item('token')` to `_CANONICAL_TOKEN_KEY`
("access_token"). Both run on every framework-validation tick, in that order.

Proof of the ping-pong: `grep -c bc_auth.js gm_tiktok_r91.log` = 244 = 122 pin
rewrites + 122 normalize rewrites, an exact 1:1 split. r92 and r93 show the
same shape. In r91, 112 of the 122 pin lines list bc_auth.js as the ONLY
changed file -- pure self-inflicted churn with no lane involvement.

Neither pass is wrong about intent; only the literal disagrees. Interpolating
the canonical constant makes pin idempotent and normalize a no-op on
framework-owned files.

Side effect worth noting: today `pin_frontend_build_tooling` reports
`pinned=True` on every single tick, so that signal is permanently lying.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class GuardUsesTheCanonicalKey(unittest.TestCase):

    def _mod(self):
        from multi_agent.runtime import frontend_scaffold
        return frontend_scaffold

    def test_guard_template_contains_no_bare_token_key(self):
        m = self._mod()
        self.assertNotIn("removeItem('token')", m._BC_AUTH_GUARD_JS)
        self.assertNotIn('removeItem("token")', m._BC_AUTH_GUARD_JS)

    def test_guard_template_uses_the_canonical_constant(self):
        m = self._mod()
        self.assertIn(m._CANONICAL_TOKEN_KEY, m._BC_AUTH_GUARD_JS)

    def test_baseline_logout_uses_the_canonical_key(self):
        """The same literal appears in the baseline logout helper."""
        m = self._mod()
        src = Path(m.__file__).read_text()
        self.assertNotIn("export function logout() { localStorage.removeItem('token') }", src)


class NormalizeIsANoOpOnAFreshlyPinnedTree(unittest.TestCase):
    """The actual ping-pong condition: after pin writes the guard, the #317
    normalizer must have nothing left to change."""

    def test_normalizer_makes_no_swap_in_the_guard_template(self):
        from multi_agent.runtime import frontend_scaffold as m
        import re
        # #317 targets localStorage.*Item('token'); after the fix there is no
        # such occurrence in the framework's own template.
        hits = re.findall(r"localStorage\.\w+Item\(\s*['\"]token['\"]\s*\)",
                          m._BC_AUTH_GUARD_JS)
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
