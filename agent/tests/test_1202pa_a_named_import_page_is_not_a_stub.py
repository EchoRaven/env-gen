"""#1202pa: a lane page that renders its own component through a NAMED import is not a stub.

#1010's delegation check recognised only `import X from '../...'`. tiktok-r126's lane wrote

    import { CreatorSuggestions } from '../components/TiktokViews';
    export default function FollowingSuggestedCreatorsPage({ identity }) {
      return <CreatorSuggestions active="Following" identity={identity} />;
    }

(210 bytes, commit afac89f) and `_is_definitive_stub_page` called it a stub, so #488's heal
replaced it with the framework projection after every merge — 806 overwrites of named-import lane
pages across r114-r126, 12 of r126's pages shipping as the projection. Never-overwritten pages in
that run scored 0.68/0.77/0.76; overwritten ones 0.08/0.11/0.11/0.24.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.frontend_scaffold import (  # noqa: E402
    _is_definitive_stub_page, _locally_imported_components_1202pa)

R126_LANE_PAGE = """import { CreatorSuggestions } from '../components/TiktokViews';

export default function FollowingSuggestedCreatorsPage({ identity }) {
  return <CreatorSuggestions active="Following" identity={identity} />;
}
"""


def test_r126_the_named_import_page_is_not_a_stub():
    assert _is_definitive_stub_page(R126_LANE_PAGE) is False


def test_every_import_form_is_recognised():
    src = """import A from './a';
import { B, C as Cee } from '../b';
import D, { E } from '../d';
import * as NS from '../ns';
import React from 'react';
"""
    got = _locally_imported_components_1202pa(src)
    assert set(got) >= {"A", "B", "Cee", "D", "E", "NS"}, got
    assert "React" not in got                     # a library import is not the lane's own view


def test_a_namespace_render_counts():
    page = ("import * as Views from '../components/Views';\n"
            "export default function P() { return <Views.Feed />; }\n")
    assert _is_definitive_stub_page(page) is False


def test_a_real_lone_heading_placeholder_is_still_a_stub():
    """#488's own case — r61's LandingPage — must still be healed."""
    stub = "export default function LandingPage() {\n  return <h2>Landing</h2>;\n}\n"
    assert _is_definitive_stub_page(stub) is True


def test_importing_a_component_it_never_renders_is_still_a_stub():
    page = ("import { CreatorSuggestions } from '../components/TiktokViews';\n"
            "export default function P() { return <h2>Soon</h2>; }\n")
    assert _is_definitive_stub_page(page) is True
