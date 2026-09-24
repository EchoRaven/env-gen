"""#1202cj — a routed authenticated page that shares nothing with its siblings.

REPORTS, does not block: a page legitimately owns its whole surface sometimes (a full-screen
player is the honest example), which is why the finding names the sibling count rather than
asserting a rule.

Two earlier versions of this scan were wrong in opposite directions and both shaped the
predicate: matching component NAMES (`NavBar|Header|Shell`) reported 49% because instagram
calls its chrome `NavRail`; requiring a MAJORITY of pages to share it reported 9% because it
silently skipped every app whose chrome is used by a minority — which is exactly the app with
the problem. LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.frontend_audit import (  # noqa: E402
    orphan_auth_page_findings_1202cj as F)

APP = """
<Routes>
  <Route path="/login" element={<LoginPage />} />
  <Route path="/a" element={<RequireAuth><APage /></RequireAuth>} />
  <Route path="/b" element={<RequireAuth><BPage /></RequireAuth>} />
  <Route path="/c" element={<RequireAuth><CPage /></RequireAuth>} />
</Routes>
"""


def _fe(tmp_path, pages, app=APP):
    src = tmp_path / "src"
    (src / "pages").mkdir(parents=True, exist_ok=True)
    (src / "App.jsx").write_text(app, encoding="utf-8")
    for name, body in pages.items():
        (src / "pages" / f"{name}.jsx").write_text(body, encoding="utf-8")
    return src


SHARED = "import NavThing from '../components/NavThing';\nexport default () => <NavThing/>;\n"
NAMED = "import { Chrome } from '../components/Shell.jsx';\nexport default () => <Chrome/>;\n"
ALONE = "export default function P(){ return <div>all mine</div>; }\n"


def test_a_page_sharing_nothing_is_named(tmp_path):
    out = F(_fe(tmp_path, {"APage": SHARED, "BPage": SHARED, "CPage": ALONE}))
    assert len(out) == 1 and "CPage.jsx" in out[0] and "2 sibling" in out[0]


def test_a_named_import_counts_as_sharing(tmp_path):
    """The first version of this scan matched `import Foo from` only and missed
    `import { Foo } from` — the exact grep error that produced a false story about r35's
    GamesPage."""
    assert F(_fe(tmp_path, {"APage": SHARED, "BPage": NAMED, "CPage": NAMED})) == []


def test_component_names_are_never_matched(tmp_path):
    """instagram's chrome is `NavRail`, netflix's is `NetflixHeader`; a name list reported
    49% on the corpus. The predicate is the IMPORT, not what it is called."""
    weird = "import Zqx from '../components/Zqx';\nexport default () => <Zqx/>;\n"
    assert F(_fe(tmp_path, {"APage": weird, "BPage": weird, "CPage": weird})) == []


def test_an_app_where_nobody_shares_is_not_reported(tmp_path):
    """A whole-app shape, not a per-page one; naming a single page for it would be
    arbitrary."""
    assert F(_fe(tmp_path, {"APage": ALONE, "BPage": ALONE, "CPage": ALONE})) == []


def test_unauthenticated_pages_are_out_of_scope(tmp_path):
    """A landing or login page has no browse chrome BY DESIGN."""
    src = _fe(tmp_path, {"APage": SHARED, "BPage": SHARED, "CPage": SHARED})
    (src / "pages" / "LoginPage.jsx").write_text(ALONE, encoding="utf-8")
    assert F(src) == []


def test_a_tiny_app_is_not_judged(tmp_path):
    """Under three auth pages there is no sibling consensus to compare against."""
    app = '<Route path="/a" element={<RequireAuth><APage /></RequireAuth>} />'
    assert F(_fe(tmp_path, {"APage": ALONE}, app=app)) == []


def test_a_missing_frontend_returns_nothing(tmp_path):
    assert F(tmp_path / "nope") == []


def test_it_finds_the_real_clustered_case():
    """Ground truth: netflix-r13 has eight such pages; instagram-run70 has none (NavRail),
    and r35 has only PlayerPage, which is the legitimate full-screen exception."""
    base = Path("/data/common/haibotong/forgingground-gen/generated")
    r13 = base / "netflix-local-r13" / "app" / "frontend" / "src"
    ig = base / "instagram-core-di.SUCCESS-run70-4milestones-138x2" / "app" / "frontend" / "src"
    if r13.is_dir():
        assert len(F(r13)) >= 5
    if ig.is_dir():
        assert F(ig) == []


def test_the_finding_reaches_a_consumer():
    """#947: a detector that reaches no artifact is not a check. It must be called, guarded,
    and state-gated so it announces a CHANGE rather than repeating every scaffold pass."""
    src = (LLM / "multi_agent" / "runtime" / "scaffolder.py").read_text(encoding="utf-8")
    i = src.index("orphan_auth_page_findings_1202cj(fe / \"src\")")
    stanza = src[src.rindex("try:", 0, i):src.index("warn_once_1201(\"orphan_auth_page", i)]
    assert "state_changed_1202ad" in stanza or "_sc1202cj" in stanza
    assert "join_capped" in stanza or "_jc1202cj" in stanza


def test_it_reports_rather_than_blocks():
    """The same disposition as #1202ai, and for the same reason: static inference has been
    wrong in this repo before, and a full-screen player is a legitimate exception."""
    src = (LLM / "multi_agent" / "runtime" / "scaffolder.py").read_text(encoding="utf-8")
    i = src.index("#1202cj [%s] %d authenticated page(s)")
    # #943: landmarks, not a byte window — the stanza runs from its own try to its warn_once.
    stanza = src[src.rindex("try:", 0, i):src.index("warn_once_1201(\"orphan_auth_page", i)]
    assert "_logger.warning" in stanza
    assert "raise" not in stanza


def test_the_warning_names_the_tree_it_scanned():
    """r37 reported this twenty times in an hour with the count swinging 11/3/12/10/4. The
    state gate was keyed correctly — the scaffolder runs per lane worktree and each number
    was true of a DIFFERENT tree — but the message did not say which, so the oscillation read
    as noise instead of as a measurement."""
    src = (LLM / "multi_agent" / "runtime" / "scaffolder.py").read_text(encoding="utf-8")
    i = src.index("#1202cj [%s] %d authenticated page(s)")
    stanza = src[src.rindex("try:", 0, i):i]
    assert "worktrees/" in stanza, "the tree must be identifiable, not just a bare name"
    assert "_where" in src[i:src.index("_jc1202cj", i)]


def test_the_state_gate_is_keyed_per_tree():
    """Two trees legitimately differ, so one key for both would suppress the second tree's
    finding entirely — the opposite failure from the noise."""
    src = (LLM / "multi_agent" / "runtime" / "scaffolder.py").read_text(encoding="utf-8")
    assert '_sc1202cj("orphan_auth_pages:%s" % out_dir' in src
