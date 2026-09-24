"""#278 — a dead-nav-link remediation must be DECISIVE about the cheapest fix.

r61 (opus-4.7): the frontend rendered `<Link to="/shop">` and `<Link to="/upload">` in the
sidebar (copying TikTok's real chrome), but neither route exists in App.jsx or the contract's
ui_pages — so both are dead controls, and the run aborted on deliverability_dead_nav_link
after 81 min without converging. The app was otherwise green (11 chains passing, backend
healthy after #276).

The gate correctly flags the dead links; the failure was CONVERGENCE. The old remediation —
"Wire the route or point the link at an existing one" — offers two equal options, and the
lane oscillated between "author a whole new /shop page" (expensive: a new contract page +
backend endpoints + data) and "remove the link", never settling.

For a link whose target is NOT a declared ui_page, authoring a page is the wrong first move:
it drags in new contract surface the milestone never scoped. The cheapest, always-correct fix
is to REMOVE the extra nav item (or repoint it at an existing route). This is not a code fix
in the gate — it is a clearer instruction that orders the options, and it names whether the
target is a declared page so the lane knows which branch it is on.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from env_generator.llm_generator.multi_agent.runtime.frontend_audit import (  # noqa: E402
    dead_nav_link_remediation,
)


def test_undeclared_target_tells_the_lane_to_remove_or_repoint_first():
    msg = dead_nav_link_remediation("/shop", "LeftNavSidebar.jsx", declared_pages=set())
    low = msg.lower()
    assert "/shop" in msg and "LeftNavSidebar.jsx" in msg
    # decisive: removing/repointing must be presented as the FIRST/cheapest fix
    assert "remove" in low or "repoint" in low or "point the link" in low
    # and it must warn against authoring a brand-new page for an unscoped target
    assert "not a declared" in low or "not in the contract" in low or "unscoped" in low


def test_declared_target_tells_the_lane_to_wire_the_route():
    """If the target IS a declared ui_page, the fix is to wire its missing route — not remove."""
    msg = dead_nav_link_remediation("/settings", "TopNav.jsx",
                                    declared_pages={"/settings", "/explore"})
    low = msg.lower()
    assert "wire" in low or "route" in low
    assert "/settings" in msg


def test_message_always_names_the_target_and_file():
    for tgt, f in (("/upload", "Sidebar.jsx"), ("/x", "Nav.jsx")):
        msg = dead_nav_link_remediation(tgt, f, declared_pages=set())
        assert tgt in msg and f in msg


def test_it_is_a_single_actionable_line():
    msg = dead_nav_link_remediation("/shop", "Nav.jsx", declared_pages=set())
    assert "\n" not in msg.strip()
    assert msg.strip().endswith((".", ")"))
