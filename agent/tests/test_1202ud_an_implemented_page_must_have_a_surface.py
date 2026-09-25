r"""#1202ud: a ui_page with no route and no component was accepted as IMPLEMENTED.

r133 (delivered) carried this record:

    __noop_invalid_do_not_create__   route ""   component ""   apis_used []   status implemented

There is nothing to render and nowhere to navigate, so no audit can have watched it work --
yet it counts toward the implemented total and satisfies coverage with an empty shell. Only
the orchestrator's own audit may flip a page to implemented (#54), so the framework stamped
this one itself.

STRUCTURAL, NOT A NAME BLACKLIST. Rejecting that sentinel string would bind the framework to
one agent's private convention and miss whatever the next agent invents; "has somewhere to
live" is the property that actually distinguishes a page and it holds in every domain. A test
below pins that generality by using an ordinary name with the same empty shape.

Registration stays permissive: a name may be reserved first and filled in later, so only the
IMPLEMENTED claim is refused -- the record is held at `defined` and says why.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.registryhub import RegistryHub  # noqa: E402


def _hub():
    return RegistryHub(str(Path(tempfile.mkdtemp())))


def _status(hub, name):
    rec = (hub.list_ui_pages() or {}).get(name) or {}
    return rec.get("status")


def test_an_empty_shell_cannot_be_implemented():
    """The r133 record, reduced."""
    hub = _hub()
    hub.register_ui_page(name="noop_shell", route="", component="",
                         status="implemented", agent="orchestrator")
    assert _status(hub, "noop_shell") == "defined"


def test_a_page_with_a_route_may_be_implemented():
    hub = _hub()
    hub.register_ui_page(name="feed", route="/feed", component="",
                         status="implemented", agent="orchestrator")
    assert _status(hub, "feed") == "implemented"


def test_a_page_with_only_a_component_may_be_implemented():
    """A modal or panel has no route of its own and is still a real surface."""
    hub = _hub()
    hub.register_ui_page(name="login_modal", route="", component="LoginModal",
                         status="implemented", agent="orchestrator")
    assert _status(hub, "login_modal") == "implemented"


def test_a_surface_registered_earlier_still_counts():
    """The two-step flow must keep working: reserve the name, fill it in, then implement."""
    hub = _hub()
    hub.register_ui_page(name="later", route="/later", agent="orchestrator")
    hub.register_ui_page(name="later", status="implemented", agent="orchestrator")
    assert _status(hub, "later") == "implemented"


def test_registration_itself_is_not_refused():
    """Only the CLAIM is refused -- the record still exists, at `defined`."""
    hub = _hub()
    hub.register_ui_page(name="reserved", status="implemented", agent="orchestrator")
    assert "reserved" in (hub.list_ui_pages() or {})
    assert _status(hub, "reserved") == "defined"


def test_the_guard_is_not_bound_to_the_sentinel_name():
    """★ Generality. An ordinary name with the same empty shape must be caught too, and the
    sentinel with a real surface must NOT be."""
    hub = _hub()
    hub.register_ui_page(name="dashboard", route="  ", component="  ",
                         status="implemented", agent="orchestrator")
    assert _status(hub, "dashboard") == "defined"
    hub.register_ui_page(name="__noop_invalid_do_not_create__", route="/x",
                         status="implemented", agent="orchestrator")
    assert _status(hub, "__noop_invalid_do_not_create__") == "implemented"
