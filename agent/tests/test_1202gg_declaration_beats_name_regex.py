"""#1202gg — an explicit declaration must not be vetoed by a filename regex.

#747's own title is "A DECLARATION BEATS A NAME MATCH": the lane writes
`metadata.reference_image` on the page it built, stating which reference screen that page
IS. But the declaration search sat behind `if not (_overlay_by_name or _transient_by_name)`,
so a screen whose FILENAME contains `modal` / `menu` / `dropdown` never reached it.

tiktok-r97 paid for that. The lane registered both screens as routed pages AND declared the
link:

    login_modal         route=/login   reference_image=login_modal.png
    settings_more_menu  route=/more    reference_image=settings_more_menu.png

Both matched _OVERLAY_NAME_RE, got no route, and the gate reported "judged 9/11 ... NOT
judged: ['login_modal', 'settings_more_menu'] — an unmapped screen is skipped". 18% of the
reference went unexamined while the app served both routes.

design_prep already learned this exact lesson: "`kind` follows REACHABILITY, not the
filename ... the previous name-regex rule demoted r92's login_modal (route_hint `/login`) to
advisory and left the visual gate's blocking set empty." Same lesson, the other module.

TRANSIENT names stay excluded — #542a's reason is physical (a static route capture cannot
reproduce a hover state), not a naming heuristic — and a declared overlay stays ADVISORY, so
coverage is restored without quietly enlarging the blocking set.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"))

from multi_agent.runtime.visual_fidelity import map_reference_screens  # noqa: E402


def _imgs(tmp_path, *names):
    out = []
    for n in names:
        p = tmp_path / f"{n}.png"
        p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
        out.append(str(p))
    return out


def _page(name, route, ref):
    return {"name": name, "route": route, "component": "X", "reference_image": ref}


def test_a_declared_overlay_named_screen_gets_its_route(tmp_path):
    """The r97 case: the lane said which page this is, and it has a served route."""
    imgs = _imgs(tmp_path, "settings_more_menu")
    pages = [_page("settings_more_menu", "/more", "settings_more_menu.png")]
    out = map_reference_screens(imgs, {"/more"}, {}, pages)
    assert out[0]["route"] == "/more", out


def test_it_stays_advisory_so_the_blocking_set_is_unchanged(tmp_path):
    """Restoring coverage must not silently make the gate harder to pass."""
    imgs = _imgs(tmp_path, "login_modal")
    pages = [_page("login_modal", "/login", "login_modal.png")]
    out = map_reference_screens(imgs, {"/login"}, {}, pages)
    assert out[0]["route"] == "/login"
    assert out[0]["advisory"] is True, "a declared overlay was promoted to blocking"


def test_a_declared_plain_screen_is_still_blocking(tmp_path):
    imgs = _imgs(tmp_path, "explore_grid")
    pages = [_page("explore_grid", "/explore", "explore_grid.png")]
    out = map_reference_screens(imgs, {"/explore"}, {}, pages)
    assert out[0]["route"] == "/explore"
    assert out[0]["advisory"] is False


def test_an_undeclared_dropdown_is_never_blocking(tmp_path):
    """#128 holds where it was actually aimed. It never stopped an overlay-named screen
    from resolving a route — the generic filename-candidate match (`account_dropdown` ->
    `account` -> /account) was always ungated. What it protects is the BLOCKING set, and
    nothing bound this screen to a page, so it stays advisory."""
    imgs = _imgs(tmp_path, "account_dropdown")
    pages = [_page("account_settings", "/account", "account_settings.png")]
    out = map_reference_screens(imgs, {"/account"}, {}, pages)
    assert out[0]["advisory"] is True, out


def test_a_transient_name_is_still_excluded_even_when_declared(tmp_path):
    """#542a's reason is physical, not a naming heuristic — a declaration cannot fix
    that a static route capture never reproduces a hover state."""
    imgs = _imgs(tmp_path, "card_hover_preview")
    pages = [_page("card_hover_preview", "/browse", "card_hover_preview.png")]
    out = map_reference_screens(imgs, {"/browse"}, {}, pages)
    assert out[0]["advisory"] is True
    assert out[0]["route"] != "/browse", "a transient state inherited a page route"


def test_a_declaration_naming_an_unserved_route_is_not_honoured(tmp_path):
    imgs = _imgs(tmp_path, "settings_more_menu")
    pages = [_page("settings_more_menu", "/more", "settings_more_menu.png")]
    out = map_reference_screens(imgs, {"/other"}, {}, pages)
    assert out[0]["route"] != "/more"
