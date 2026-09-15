"""#1202mq: the icon heal must not import a name the file binds itself.

`_unimported_jsx_tags` knew imports and line-start declarations. Generated components bind
dynamic icons through destructured parameters and minified mid-line declarations, so the
heal added `import { Icon } from 'lucide-react'` to lane files, the lane removed it, and the
next framework delivery put it back — tiktok-r124's LeftNavSidebar.jsx and TikTokAppShell.jsx.

Corpus (framework delivery commits, every run except the poisoned googlemaps-r16): 152 names
imported by this heal, 54 of them bound in the same file, across 27 runs. Three were checked
by hand: r88 (`icon: I` — its lane had written "do NOT import `I`"), r120
(`const Follows = pages.Follows;`), r100 (`const C = m[type] || Home;`).
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime import frontend_scaffold as FS  # noqa: E402

R124_SIDEBAR = """import { NavLink } from 'react-router-dom';
import { Home, Compass, Users } from 'lucide-react';
const items = [['/', 'For You', Home], ['/explore', 'Explore', Compass], ['/following', 'Following', Users]];
export default function LeftNavSidebar({ active }) {
  return (<nav>
      {items.map(([to,label,Icon]) => {
        const is = active === to;
        return (<NavLink key={to} to={to}>
          <Icon size={29} strokeWidth={label === 'For You' && is ? 0 : 2.4} fill={is ? '#ea445a' : 'none'} />
          <span>{label}</span></NavLink>);
      })}
  </nav>);
}
"""


def test_r124s_destructured_icon_is_not_imported():
    assert FS._unimported_jsx_tags(R124_SIDEBAR) == []


def test_r124s_sidebar_is_left_byte_identical_by_the_heal():
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "src" / "components" / "LeftNavSidebar.jsx"
        f.parent.mkdir(parents=True)
        f.write_text(R124_SIDEBAR, encoding="utf-8")
        out = FS.repair_frontend_unimported_icons(Path(tmp))
        assert out["repaired"] == [], out
        assert f.read_text(encoding="utf-8") == R124_SIDEBAR


def test_the_corpus_binding_shapes_are_all_recognised():
    for src in (
            # r88: a renamed destructured prop, followed by another parameter
            "{NAV_ITEMS.map(({ to, label, icon: I, end, dot }, idx) => <I size={20} />)}",
            # r120: a declaration in the middle of a minified line
            "export default function FollowsPage(){ const Follows = pages.Follows; return <Follows />; }",
            # r100
            "export function Glyph({type}){ const m = {}; const C = m[type] || Home; return <C />; }",
            "function Row({ Icon = Dot, label }) { return <Icon/> }",
            "for (const [k, Tab] of entries) { out.push(<Tab key={k}/>) }",
            "const { Comp } = registry; export default () => <Comp/>;",
            "const { a: { Panel } } = x; export default () => <Panel/>;"):
        assert FS._unimported_jsx_tags(src) == [], src


def test_a_name_that_is_only_read_still_gets_its_import():
    """The heal exists for these (#40: a used-but-unimported icon crashes the page)."""
    for src, want in (
            ("export default () => <Mail size={16} />;", ["Mail"]),
            ("export default function A(){ if (Heart) { return <Heart/> } return null }", ["Heart"]),
            ("export default function A(){ track(Bell, 2); return <Bell/> }", ["Bell"]),
            ("export default () => <Nav items={[Home, Search]}><Home/></Nav>;", ["Home", "Nav"]),
            ("export default function A(){ useEffect(() => { set(Star) }, [Star]); return <Star/> }",
             ["Star"]),
            ("const x = { Home: 1 }; export default () => <Home/>;", ["Home"])):
        assert FS._unimported_jsx_tags(src) == want, (src, FS._unimported_jsx_tags(src))


def test_a_module_scope_declaration_is_never_imported_a_second_time():
    """#970's failure mode: the added import would be a duplicate binding → build error."""
    src = ("import React from 'react'; const Badge = ({n}) => <b>{n}</b>; "
           "export default function Card(){ return <Badge n={1}/> }")
    assert FS._unimported_jsx_tags(src) == []
