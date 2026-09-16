"""#1202pl: the unimported-tag heal must not turn a router name or a project component
into a lucide icon (r125: `<Link to=...>` became a chain-link glyph)."""
import json

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    repair_frontend_unimported_icons,
)


def _fe(tmp_path, router=True):
    src = tmp_path / "src"
    (src / "components").mkdir(parents=True)
    (src / "pages").mkdir()
    deps = {"react": "18"}
    if router:
        deps["react-router-dom"] = "6"
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": deps}))
    (src / "components" / "AppShell.jsx").write_text(
        "export default function AppShell({children}) { return <main>{children}</main>; }\n")
    (src / "components" / "MediaFrame.jsx").write_text(
        "export function Avatar() { return <img alt='' />; }\n")
    return src


def test_router_link_is_imported_from_the_router(tmp_path):
    src = _fe(tmp_path)
    page = src / "components" / "Feed.jsx"
    page.write_text("import React from 'react';\n"
                    "export default function Feed() { return <Link to='/c'><Heart /></Link>; }\n")
    repair_frontend_unimported_icons(tmp_path)
    out = page.read_text()
    assert "import { Link } from 'react-router-dom';" in out
    assert "import { Heart } from 'lucide-react';" in out
    assert "Link } from 'lucide-react'" not in out


def test_a_project_component_is_imported_from_its_file(tmp_path):
    src = _fe(tmp_path)
    page = src / "pages" / "HomePage.jsx"
    page.write_text("import React from 'react';\n"
                    "export default function HomePage() { return <AppShell><Avatar /></AppShell>; }\n")
    repair_frontend_unimported_icons(tmp_path)
    out = page.read_text()
    assert "import AppShell from '../components/AppShell';" in out
    assert "import { Avatar } from '../components/MediaFrame';" not in out  # file is MediaFrame, not Avatar
    assert "lucide-react" in out  # Avatar has no file of its own -> unchanged behaviour


def test_without_the_router_dependency_link_stays_with_lucide(tmp_path):
    src = _fe(tmp_path, router=False)
    page = src / "components" / "Feed.jsx"
    page.write_text("import React from 'react';\n"
                    "export default function Feed() { return <Link />; }\n")
    repair_frontend_unimported_icons(tmp_path)
    assert "import { Link } from 'lucide-react';" in page.read_text()


def test_idempotent(tmp_path):
    src = _fe(tmp_path)
    page = src / "pages" / "HomePage.jsx"
    page.write_text("import React from 'react';\n"
                    "export default function HomePage() { return <AppShell><Link to='/' /></AppShell>; }\n")
    repair_frontend_unimported_icons(tmp_path)
    once = page.read_text()
    assert repair_frontend_unimported_icons(tmp_path)["repaired"] == []
    assert page.read_text() == once
