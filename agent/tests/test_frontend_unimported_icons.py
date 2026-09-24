"""Used-but-unimported JSX identifiers get a lucide-react import (run-33, 2026-07-02).

`<Mail/>` with no import BUILDS (a free JSX identifier is a runtime global lookup) and then
CRASHES the page at render — `ReferenceError: Mail is not defined` → blank page + console
error → browser-gate deferral churn (run-33 M1 live: messages_page='Mail', events_page=
'Filter', 3 wasted re-test cycles). The repair imports every capitalized JSX tag that is
neither imported nor locally defined via lucide-react; the safe-icon Vite plugin renders
real icons and degrades unknown names to a placeholder SVG, so the repair is crash-proof
by construction. ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.frontend_scaffold import (  # noqa: E402
    _unimported_jsx_tags, repair_frontend_unimported_icons)


def test_run33_shape_detected():
    src = ("import React from 'react';\n"
           "import { Search } from 'lucide-react';\n"
           "export default function MessagesPage() {\n"
           "  return <div><Mail className='w-4' /><Search /></div>;\n"
           "}\n")
    assert _unimported_jsx_tags(src) == ["Mail"]


def test_imports_aliases_locals_and_builtins_are_known():
    src = ("import React, { Fragment } from 'react';\n"
           "import { Calendar as CalendarIcon } from 'lucide-react';\n"
           "import Layout from './Layout';\n"
           "const Row = () => <div/>;\n"
           "function Card() { return <span/>; }\n"
           "export default () => <Fragment><Layout><CalendarIcon/><Row/><Card/>"
           "<React.StrictMode/></Fragment>;\n")
    assert _unimported_jsx_tags(src) == []


def test_repair_adds_import_and_is_idempotent(tmp_path):
    src_dir = tmp_path / "src" / "pages"
    src_dir.mkdir(parents=True)
    f = src_dir / "EventsPage.jsx"
    f.write_text("import React from 'react';\n"
                 "export default function EventsPage() {\n"
                 "  return <div><Filter/><Clock/></div>;\n"
                 "}\n", encoding="utf-8")
    out = repair_frontend_unimported_icons(tmp_path)
    assert "pages/EventsPage.jsx" in out["repaired"]
    txt = f.read_text(encoding="utf-8")
    assert "import { Clock, Filter } from 'lucide-react';" in txt
    # idempotent: everything now imported → second pass repairs nothing
    out2 = repair_frontend_unimported_icons(tmp_path)
    assert out2["repaired"] == []


def test_clean_file_untouched(tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True)
    body = ("import { Mail } from 'lucide-react';\n"
            "export default () => <Mail/>;\n")
    (src_dir / "Ok.jsx").write_text(body, encoding="utf-8")
    assert repair_frontend_unimported_icons(tmp_path)["repaired"] == []
    assert (src_dir / "Ok.jsx").read_text(encoding="utf-8") == body


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
