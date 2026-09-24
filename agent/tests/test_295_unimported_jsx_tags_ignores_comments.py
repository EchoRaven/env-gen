"""#295 — the unimported-JSX-icon healer must not scan COMMENTS.

r78 STUCK-aborted: docker_up vite build failed on `import { Route } from
'lucide-react'` (Rollup: Route not exported) → 9 post-cap cycles → FAIL-FAST.

Root cause: LeftNavSidebar.jsx used `Route` ONLY inside comments
(`// EVERY <Link to=...> MUST resolve to a wired <Route>`), never as real JSX.
`repair_frontend_unimported_icons` → `_unimported_jsx_tags` runs
`_JSX_TAG_RE.findall(src)` on RAW text, so `<Route>` in the comment matched →
`Route` treated as an unimported icon → `import { Route } from 'lucide-react'`
injected. lucide-react has no `Route` export → build fails. The healer re-injects
every validation cycle (after the lane removes it) → the frontend can never
converge → STUCK ("framework artifact regenerated every cycle").

Fix: strip comments before scanning for used JSX tags (keep real usage +
imports/local-defs intact). A tag that appears only in a comment must not be
imported.
"""

import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.frontend_scaffold import _unimported_jsx_tags  # noqa: E402


class UnimportedJsxTagsIgnoresCommentsTests(unittest.TestCase):
    def test_tag_only_in_line_comment_not_flagged(self):
        # The exact r78 shape.
        src = (
            "import { Link, useLocation } from 'react-router-dom';\n"
            "// IMPORTANT: EVERY <Link to=...> MUST resolve to a wired <Route>\n"
            "export default function Nav() { return <Link to='/x'>x</Link>; }\n"
        )
        self.assertNotIn("Route", _unimported_jsx_tags(src))

    def test_tag_only_in_jsx_block_comment_not_flagged(self):
        src = (
            "export default function P() {\n"
            "  return <div>{/* every nav item needs a <Route> in App.jsx */}</div>;\n"
            "}\n"
        )
        self.assertNotIn("Route", _unimported_jsx_tags(src))

    def test_tag_only_in_block_comment_not_flagged(self):
        src = "/* a <Route> lives in App.jsx */\nexport const X = () => <div/>;\n"
        self.assertNotIn("Route", _unimported_jsx_tags(src))

    def test_real_unimported_icon_still_flagged(self):
        # Must NOT over-strip: a genuine unimported <Mail/> is still repaired.
        src = "export default function P(){ return <Mail className='x'/>; }\n"
        self.assertIn("Mail", _unimported_jsx_tags(src))

    def test_url_line_comment_does_not_hide_a_real_tag(self):
        # `//` in a URL must not cause over-stripping that drops a real tag.
        src = (
            "const u = 'https://example.com/a';\n"
            "export default function P(){ return <Bell/>; }\n"
        )
        self.assertIn("Bell", _unimported_jsx_tags(src))

    def test_imported_tag_not_flagged(self):
        src = ("import { Route } from 'react-router-dom';\n"
               "export default function P(){ return <Route path='/'/>; }\n")
        self.assertNotIn("Route", _unimported_jsx_tags(src))


if __name__ == "__main__":
    unittest.main()
