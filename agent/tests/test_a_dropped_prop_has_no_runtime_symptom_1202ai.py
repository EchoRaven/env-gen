r"""#1202ai: a prop the component never declares is dropped, and nothing can see it.

React does not complain about an attribute a component fails to destructure, so this break has
NO runtime symptom — no console error, no failed request, no 404, no crash. Every gate this
repo owns stays green while the feature quietly does nothing. It is the mechanism behind
"looks complete but a lot of it does not work".

Measured over the 117 corpus environments, counting only props whose name appears NOWHERE in
the component's own source (so it cannot be read off `props` or forwarded):

    232 occurrences in 51 of 117 runs (44%)

    <ResultsSidebar hoveredPlaceId onHover>  declares {error, isPharmacy, loading}
                                             -> the map/list hover linkage is dead
    <PostHeader createdAt>                   declares {user}       -> no timestamp
    <PostHeader onFollowToggle>              declares {isFollowed, setIsFollowed, user}
    <LoginForm setToken>                     declares {setIsRegister} -> token never stored
    <NetflixChrome title subtitle>  (r32)    declares {children, activeLabel, menuOpen}

★ The measurement took three passes to get right, and the first two were wrong in this repo's
usual way. Pass 1 recognised only `function X({...})` and counted every prop given to an arrow
component as dropped (279 across 60 runs — mostly fiction). Pass 2 added arrow components but
still counted props a component reads off a rest element or a HOC wrapper. Only the third —
excluding memo/forwardRef/HOC/`props`-wholesale/rest, then requiring the name to be absent from
the entire component file — produces a number worth acting on.

★ REPORTS, does not block. #1199 was downgraded from rewriting `apis_used` to merely naming the
disagreement after its static inference produced false rewrites on tiktok, googlemaps and
instagram. Same discipline here.
"""

import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.frontend_audit import dropped_prop_findings_1202ai  # noqa: E402


def _tree(tmp_path, files):
    src = tmp_path / "src"
    (src / "components").mkdir(parents=True)
    for name, body in files.items():
        (src / "components" / name).write_text(body, encoding="utf-8")
    return src


def test_the_r32_shape_is_found(tmp_path):
    src = _tree(tmp_path, {
        "NetflixChrome.jsx":
            "export default function NetflixChrome({ children, activeLabel }) {\n"
            "  return <div>{children}</div>;\n}\n",
        "MoviesPage.jsx":
            "import NetflixChrome from './NetflixChrome';\n"
            "export default function MoviesPage(){\n"
            "  return <NetflixChrome title=\"Movies\" subtitle=\"All films\">x</NetflixChrome>;\n}\n",
    })
    found = dropped_prop_findings_1202ai(src)
    assert any("title" in f for f in found)
    assert any("subtitle" in f for f in found)


def test_a_prop_the_component_declares_is_not_flagged(tmp_path):
    src = _tree(tmp_path, {
        "Card.jsx": "export default function Card({ title }) { return <p>{title}</p>; }\n",
        "Page.jsx": "import Card from './Card';\n"
                    "export default function Page(){ return <Card title=\"x\" />; }\n",
    })
    assert dropped_prop_findings_1202ai(src) == []


def test_an_arrow_component_is_understood(tmp_path):
    """Pass 1 of this measurement counted every prop of an arrow component as dropped."""
    src = _tree(tmp_path, {
        "Row.jsx": "const Row = ({ label }) => <li>{label}</li>;\nexport default Row;\n",
        "List.jsx": "import Row from './Row';\n"
                    "export default function List(){ return <Row label=\"a\" />; }\n",
    })
    assert dropped_prop_findings_1202ai(src) == []


def test_a_rest_element_component_is_left_alone(tmp_path):
    """`{...rest}` means the component may forward anything; guessing there would be wrong."""
    src = _tree(tmp_path, {
        "Box.jsx": "export default function Box({ children, ...rest }) "
                   "{ return <div {...rest}>{children}</div>; }\n",
        "Use.jsx": "import Box from './Box';\n"
                   "export default function Use(){ return <Box data-x=\"1\" onDrop={f} />; }\n",
    })
    assert dropped_prop_findings_1202ai(src) == []


def test_a_prop_used_off_props_elsewhere_in_the_file_is_not_flagged(tmp_path):
    """The name appearing anywhere in the component's file clears it — that is the strong
    filter that took the count from 272 to 232."""
    src = _tree(tmp_path, {
        "Odd.jsx": "export default function Odd({ a }) {\n"
                   "  // extra is read dynamically below\n"
                   "  const extra = 1;\n  return <p>{a}{extra}</p>;\n}\n",
        "Use.jsx": "import Odd from './Odd';\n"
                   "export default function Use(){ return <Odd a=\"1\" extra=\"2\" />; }\n",
    })
    assert dropped_prop_findings_1202ai(src) == []


def test_layout_attributes_are_never_flagged(tmp_path):
    src = _tree(tmp_path, {
        "P.jsx": "export default function P({ v }) { return <b>{v}</b>; }\n",
        "U.jsx": "import P from './P';\n"
                 "export default function U(){ return <P v=\"1\" key=\"k\" className=\"c\" />; }\n",
    })
    assert dropped_prop_findings_1202ai(src) == []


def test_a_missing_tree_is_not_a_finding(tmp_path):
    assert dropped_prop_findings_1202ai(tmp_path / "nope") == []


def test_it_is_wired_as_a_report_not_a_blocker():
    base = THIS_DIR.parent / "env_generator/llm_generator/multi_agent/runtime"
    sc = (base / "scaffolder.py").read_text(encoding="utf-8")
    assert "dropped_prop_findings_1202ai" in sc
    dl = (base / "deliverability.py").read_text(encoding="utf-8")
    assert "dropped_prop_findings_1202ai" not in dl      # never a blocker


def test_the_finding_is_filed_as_a_frontend_task_not_only_logged():
    """#1202aj: a finding nobody is assigned is a finding nobody fixes.

    #780 exists for that reason and measured its own log-only fallback at ONE filed task
    across 154 runs. This defect has no runtime symptom at all, so the log line is the only
    thing between it and shipping — 232 occurrences across 51 of 117 environments, every gate
    green in all of them.
    """
    sc = (THIS_DIR.parent
          / "env_generator/llm_generator/multi_agent/runtime/scaffolder.py"
          ).read_text(encoding="utf-8")
    block = sc[sc.index("# #1202aj:"):sc.index("except Exception as _t1202aj")]
    assert "workhub.create_task(" in block
    assert 'assignee="frontend"' in block
    # the lane needs to know it cannot be found any other way
    assert "NO runtime symptom" in block


def test_a_failure_to_file_says_so():
    """Filing is best-effort, but a silent failure would put the finding back to log-only —
    the exact state #1202aj exists to end, so it announces."""
    sc = (THIS_DIR.parent
          / "env_generator/llm_generator/multi_agent/runtime/scaffolder.py"
          ).read_text(encoding="utf-8")
    # #943: a landmark, not a fixed byte window.
    i = sc.index("except Exception as _t1202aj")
    tail = sc[i:sc.index("            try:", i)]
    assert "could not file the dropped-prop task" in tail
    assert "log-only again" in tail


def test_filing_is_behind_the_state_memo_so_it_files_once():
    """create_task's #672 twin-check is the second guard; the first is not calling it every
    scaffold pass with an unchanged finding set."""
    sc = (THIS_DIR.parent
          / "env_generator/llm_generator/multi_agent/runtime/scaffolder.py"
          ).read_text(encoding="utf-8")
    i = sc.index("dropped_props:%s")
    j = sc.index("# #1202aj:")
    assert i < j                      # the memo guard opens the block the filing sits in


def test_two_components_with_the_same_name_are_told_apart(tmp_path):
    """#1202ak — the correction that took the count from 232 to 152.

    r32 has two components called `TitleCard`: `TitleGrid.jsx` declares {title, rank} and
    `NetflixUI.jsx` declares {title, rank, onOpen, showLabel}. A name-keyed map judged one
    file's call site against the other file's declaration and reported `onOpen` as dropped —
    on a component that declares it AND wires it to an onClick. I shipped that detector before
    catching it; resolution now follows the caller's own import.
    """
    src = tmp_path / "src"
    (src / "components").mkdir(parents=True)
    (src / "components" / "GridCard.jsx").write_text(
        "export function TitleCard({ title }) { return <p>{title}</p>; }\n", encoding="utf-8")
    (src / "components" / "RailCard.jsx").write_text(
        "export function TitleCard({ title, onOpen }) "
        "{ return <p onClick={onOpen}>{title}</p>; }\n", encoding="utf-8")
    (src / "components" / "Rail.jsx").write_text(
        "import { TitleCard } from './RailCard';\n"
        "export default function Rail(){ return <TitleCard title=\"x\" onOpen={f} />; }\n",
        encoding="utf-8")
    assert dropped_prop_findings_1202ai(src) == []


def test_an_unresolvable_component_is_skipped_not_guessed(tmp_path):
    """No import to disambiguate -> say nothing. Guessing is what produced the false report."""
    src = tmp_path / "src"
    (src / "components").mkdir(parents=True)
    (src / "components" / "A.jsx").write_text(
        "export function Card({ a }) { return <i>{a}</i>; }\n", encoding="utf-8")
    (src / "components" / "Use.jsx").write_text(       # no import of Card at all
        "export default function Use(){ return <Card a=\"1\" b=\"2\" />; }\n", encoding="utf-8")
    assert dropped_prop_findings_1202ai(src) == []


def test_a_locally_declared_component_beats_an_imported_one(tmp_path):
    src = tmp_path / "src"
    (src / "components").mkdir(parents=True)
    (src / "components" / "Other.jsx").write_text(
        "export function Row({ a }) { return <i>{a}</i>; }\n", encoding="utf-8")
    (src / "components" / "Page.jsx").write_text(
        "import { Row } from './Other';\n"
        "function Row({ a, b }) { return <i>{a}{b}</i>; }\n"
        "export default function Page(){ return <Row a=\"1\" b=\"2\" />; }\n", encoding="utf-8")
    assert dropped_prop_findings_1202ai(src) == []
