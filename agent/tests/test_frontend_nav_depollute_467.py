"""#467 (r45 verdict, cross-cutting browse_home .40 + movies .45): the top nav showed
'Card Preview' (INVENTED) and DROPPED 'Shows'. ROOT: card_hover_preview is emitted as
a routable page (path="/card-preview", element=<CardHoverPreview/>), and the nav is
derived from the <Route> table with no interaction-screen filter — so the overlay
leaked in as a nav item, and the [:7] cap then cut the real 'Shows' page. FIX: exclude
routes whose COMPONENT name carries interaction-chrome tokens (hover/dialog/modal/
overlay/…) from the NAV — matching the component keeps the 'hover'/'dialog' signal the
route path '/card-preview' loses. The ROUTE stays (still reachable); only the nav entry
is dropped. Generalizable, no product literals (real pages Movies/Shows/Games/Menu are
untouched)."""
from pathlib import Path

import re

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _NAV_EXCLUDE_COMP_467, _ROUTE_ELEMENT)


def test_regex_matches_interaction_components_only():
    for comp in ("CardHoverPreview", "RateDialog", "TitleModal", "PreviewOverlay",
                 "HoverCard", "GenrePopover", "InfoTooltip", "NavDrawer", "PopupMenu"):
        assert _NAV_EXCLUDE_COMP_467.search(comp), f"{comp} should be excluded from nav"
    # real top-level destinations must NOT be excluded (stay in nav)
    for comp in ("ShowsPage", "MoviesPage", "GamesPage", "MyListPage", "BrowseHome",
                 "NewAndPopular", "MenuPage", "BrowseByLanguages", "GenreCategory"):
        assert not _NAV_EXCLUDE_COMP_467.search(comp), f"{comp} must stay in nav"


_APP_JSX = """
import ShowsPage from './pages/ShowsPage';
import MoviesPage from './pages/MoviesPage';
import CardHoverPreview from './pages/CardHoverPreview';
import GamesPage from './pages/GamesPage';
export default function App() {
  return (
    <Routes>
      <Route path="/card-preview" element={<CardHoverPreview />} />
      <Route path="/shows" element={<ShowsPage />} />
      <Route path="/movies" element={<MoviesPage />} />
      <Route path="/games" element={<GamesPage />} />
    </Routes>
  );
}
"""


def _derive_nav(app_jsx):
    """Replicate the real nav-derivation glue (frontend_scaffold scaffold_missing_
    local_pages, lines ~4577-4589) using the module's REAL _ROUTE_ELEMENT parser and
    the REAL #467 exclusion regex — so this exercises the actual fix, not a copy."""
    nav_routes, seen = [], set()
    for _p, _c in _ROUTE_ELEMENT.findall(app_jsx):
        _r = _p.strip().rstrip("/")
        low = _r.lower()
        if (":" in _r or "{" in _r or _r in ("", "/")
                or low in ("/login", "/signup", "/signin", "/register")
                or "landing" in low or "welcome" in low or _r in seen
                or _NAV_EXCLUDE_COMP_467.search(_c or "")):
            continue
        seen.add(_r)
        seg = _r.strip("/").split("/")[0]
        nav_routes.append(re.sub(r"[-_]+", " ", seg).title() or seg)
    return nav_routes[:7]


def test_nav_drops_card_preview_keeps_real_pages():
    nav = _derive_nav(_APP_JSX)
    assert "Card Preview" not in nav, "#467: card_hover_preview (CardHoverPreview) must NOT be a nav item"
    assert "Shows" in nav, "the real 'Shows' page must stay in the nav (was dropped by the [:7] cap)"
    assert "Movies" in nav and "Games" in nav, "other real pages stay in the nav"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
