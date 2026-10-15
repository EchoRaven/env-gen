"""#1203l2/#1203l3: #576 looked for an import shape the lanes mostly do not write.

`mount_shared_nav_on_projected_pages` (#576) gives a chrome-less projected page the app's own
shared shell, and it discovers that shell by counting default component imports across the
app's own `src/pages/*.jsx`. The pattern required the `.jsx` extension:

    from '../components/AppShell.jsx'      <- required
    from '../components/AppShell'          <- 337 of the corpus's 530, and invisible

MEASURED over the 39 modern runs' delivered frontends: the required shape is the MINORITY,
193 of 530 component imports. Replaying the discovery as it stands, #576 finds no candidate at
all in 24 runs and no dominant one in 12 more -- it can fire in 3 of 39. With the extension
optional: 14 of 39, and every pick is the app's own shell (AppShell, TikTokAppShell,
AuthenticatedAppShell, TikTokShell, SecondaryShell, DesktopShell, TikTokUI). What not firing
costs is in #576's own docstring: r139's chrome-less projected page scored 0.28 against its
sibling's 0.85 and alone held the blocking average under the bar.

Widening the pattern also makes an existing weakness in the SELECTION reachable, and that
half was WITHDRAWN rather than landed. The test is `n >= 3 and n >= 2 * runner_up`, and with
no runner-up the second clause is free, so r152's only candidate -- `TenantPicker` at 3 of 12
pages -- is elected the shell. A share-of-pages floor at the ratio the feature was built for
(r139's TopNav, 6 of 14 = 43%) refuses r152 and keeps r164's `TikTokUI` (10 of 12), but it
also refuses #1203f5's own fixture, where `Shell` is default-imported by 3 of 9 pages and is
legitimately the shell. Separating 3-of-12 from 3-of-9 is a threshold tuned to two data
points, and the function's docstring already rejected a share rule for a reason that still
holds. The imperfection is written down in the code instead.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import frontend_scaffold as FS  # noqa: E402

SHELL = ("import React from 'react';\n"
         "export default function AppShell({ children }) {\n"
         "  return <div className=\"shell\"><nav>chrome</nav>{children}</div>;\n}\n")


def _app(tmp_path, pages, shell_name="AppShell", shell_src=None):
    fd = tmp_path / "frontend"
    (fd / "src" / "pages").mkdir(parents=True)
    (fd / "src" / "components").mkdir(parents=True)
    (fd / "src" / "components" / (shell_name + ".jsx")).write_text(
        shell_src if shell_src is not None else SHELL.replace("AppShell", shell_name),
        encoding="utf-8")
    for name, body in pages.items():
        (fd / "src" / "pages" / name).write_text(body, encoding="utf-8")
    return fd


def _page(imports, projected=True, mounts=None):
    # Every page carries a real import. The pass anchors its inserted import to the FIRST
    # `^import` in the file, so a page with none is skipped -- true of the function before
    # this ticket too, and not a shape the framework's own projected pages have.
    head = "import React from 'react';\n" + "".join("import %s from '../components/%s';\n" % (n, n) if not ext
                   else "import %s from '../components/%s.jsx';\n" % (n, n)
                   for n, ext in imports)
    mark = ' data-projected="ref"' if projected else ""
    inner = ("      <%s />\n" % mounts) if mounts else ""
    return (head + "export default function P() {\n"
            '  return <div%s className="flex min-h-screen">\n%s    <main>x</main>\n'
            "  </div>;\n}\n" % (mark, inner))


def test_the_import_without_the_extension_is_seen():
    txt = ("import AppShell from '../components/AppShell';\n"
           "import Icon from '../components/Icon.jsx';\n")
    assert set(FS._DEFAULT_COMP_IMPORT_1203F5.findall(txt)) == {"AppShell", "Icon"}, txt
    # NON-VACUITY: it is still an import of a COMPONENT module, not any string
    assert FS._DEFAULT_COMP_IMPORT_1203F5.findall(
        "const NAMES = ['AppShell', 'Icon'];\n") == []
    assert FS._DEFAULT_COMP_IMPORT_1203F5.findall(
        "import { AppShell } from '../components/AppShell';\n") == []


def test_the_shell_is_mounted_when_the_pages_leave_the_extension_off(tmp_path):
    pages = {}
    for i in range(4):                       # 4 of 6 import the shell, no extension
        pages["P%d.jsx" % i] = _page([("AppShell", False)], projected=False)
    pages["Proj1.jsx"] = _page([("Other", False)])
    pages["Proj2.jsx"] = _page([("Other", False)])
    fd = _app(tmp_path, pages)
    (fd / "src" / "components" / "Other.jsx").write_text(
        "export default function Other(){return null}\n", encoding="utf-8")
    rep = FS.mount_shared_nav_on_projected_pages(fd)
    assert rep.get("nav") == "AppShell", rep
    assert sorted(rep.get("mounted") or []) == ["Proj1", "Proj2"], rep
    got = (fd / "src" / "pages" / "Proj1.jsx").read_text(encoding="utf-8")
    assert "<AppShell />" in got, got
    assert got.count("from '../components/AppShell") == 1, got


def test_a_page_that_already_imports_it_without_the_extension_is_left_alone(tmp_path):
    """The write adds `'../components/X.jsx'`; a page importing `'../components/X'` must not
    get a second binding, which is a build error. The corpus has none today -- #1203l2 is
    what makes the shape common, so it is handled here."""
    pages = {}
    for i in range(4):
        pages["P%d.jsx" % i] = _page([("AppShell", False)], projected=False)
    # projected AND already importing the shell without the extension, but not mounting it
    pages["Proj1.jsx"] = _page([("AppShell", False)])
    fd = _app(tmp_path, pages)
    rep = FS.mount_shared_nav_on_projected_pages(fd)
    assert rep.get("mounted") == [], rep
    got = (fd / "src" / "pages" / "Proj1.jsx").read_text(encoding="utf-8")
    assert got.count("from '../components/AppShell") == 1, got


def test_a_longer_component_name_does_not_pass_for_the_shell(tmp_path):
    """The quote in the already-imported pattern is what stops it matching a PREFIX. Without
    it, a page importing `AppShellHeader` reads as already importing `AppShell` and never
    gets the shell. Found by mutation on the line this ticket added."""
    pages = {}
    for i in range(4):
        pages["P%d.jsx" % i] = _page([("AppShell", False)], projected=False)
    pages["Proj.jsx"] = _page([("AppShellHeader", False)])
    fd = _app(tmp_path, pages)
    (fd / "src" / "components" / "AppShellHeader.jsx").write_text(
        "export default function AppShellHeader(){return null}\n", encoding="utf-8")
    rep = FS.mount_shared_nav_on_projected_pages(fd)
    assert rep.get("mounted") == ["Proj"], rep
    got = (fd / "src" / "pages" / "Proj.jsx").read_text(encoding="utf-8")
    assert "<AppShell />" in got, got
    assert "from '../components/AppShell.jsx'" in got, got


def test_three_sharers_is_the_floor(tmp_path):
    """#576's absolute minimum, which the widened pattern makes reachable in more runs. Two
    sharers is not a shared shell however few pages there are."""
    pages = {}
    for i in range(2):
        pages["P%d.jsx" % i] = _page([("AppShell", False)], projected=False)
    pages["Proj.jsx"] = _page([])
    fd = _app(tmp_path, pages)
    assert FS.mount_shared_nav_on_projected_pages(fd).get("nav") is None

    # NON-VACUITY: a third sharer mounts it
    pages["P2.jsx"] = _page([("AppShell", False)], projected=False)
    fd2 = _app(tmp_path / "c", pages)
    assert FS.mount_shared_nav_on_projected_pages(fd2).get("nav") == "AppShell"


def test_a_runner_up_still_decides_by_dominance(tmp_path):
    """#1203l3 only fills the empty-comparison case: with a runner-up present, the original
    2x rule is unchanged -- including refusing a leader that does not dominate."""
    pages = {}
    for i in range(4):
        pages["P%d.jsx" % i] = _page([("AppShell", False), ("Sidebar", False)],
                                     projected=False)
    pages["Proj.jsx"] = _page([])
    fd = _app(tmp_path, pages)
    (fd / "src" / "components" / "Sidebar.jsx").write_text(
        "export default function Sidebar(){return null}\n", encoding="utf-8")
    rep = FS.mount_shared_nav_on_projected_pages(fd)
    assert rep.get("mounted") == [], ("4 vs 4 is not dominance", rep)


def test_the_corpus_gains_the_shells_it_already_has():
    """The measurement in the docstring, read-only: it replays the DISCOVERY (counting and
    the selection gates) over the delivered frontends and never calls the mounting pass,
    which writes to pages. Skipped when the corpus is absent."""
    import collections
    import pytest
    picked = {}
    runs = 0
    for run in sorted((ROOT.parent / "generated").glob("*")):
        m = re.search(r"r(\d+)$", run.name)
        if not m or int(m.group(1)) < 150:
            continue
        pages, comps = (run / "app/frontend/src/pages"), (run / "app/frontend/src/components")
        if not pages.is_dir() or not comps.is_dir():
            continue
        runs += 1
        counts = collections.Counter()
        npages = 0
        for p in sorted(pages.glob("*.jsx")):
            npages += 1
            try:
                t = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for name in set(FS._DEFAULT_COMP_IMPORT_1203F5.findall(t)):
                counts[name] += 1
        if not counts:
            continue
        ranked = counts.most_common()
        comp, n = ranked[0]
        ru = ranked[1][1] if len(ranked) > 1 else 0
        ok = n >= 2 * ru
        if n >= 3 and ok and (comps / ("%s.jsx" % comp)).is_file() and comp[0].isupper():
            picked[run.name] = comp
    if runs < 20:
        pytest.skip("too few corpus frontends on this disk (%d)" % runs)
    assert len(picked) >= 10, (len(picked), picked)
    # every pick is the app's own shell, not an incidental widget
    # every pick but one is the app's own shell; the exception is the withdrawn case above
    odd = {r: c for r, c in picked.items()
           if not re.search(r"(shell|ui|app|layout|chrome|nav)", c, re.I)}
    assert set(odd.values()) <= {"TenantPicker"}, odd
