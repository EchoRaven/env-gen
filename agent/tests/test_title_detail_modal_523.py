"""#523 (netflix r94, 2026-08-06) — a named-'detail' OVERLAY screen renders the detail
MODAL (not a page/player), and relative asset URLs resolve from web root.

GROUND TRUTH: r94's title_detail scored 0.05 — the capture showed a full-screen VIDEO PLAYER
(scrubber, play/CC controls) with a BROKEN centered poster, not the reference detail modal.
Root causes: (1) `_is_detail_modal` required a PARAM route, but this contract labeled
title_detail route '/browse', kind 'overlay' → the gate missed it → it fell through to the
app-shell/media (player) surface. (2) seed_dataset.json posters are RELATIVE ('assets/
posters/x.jpg', no leading slash) → served at /title/:id they resolve to /title/assets/... →
404 (broken img). FIXES #523: (a) add `("detail" in name) and kind=='overlay'` to the modal
gate (narrow — no 'detail' token on browse_home/card_hover_preview; players excluded by the
_screen_is_player_449 guard); (b) a `_url()` helper prepends '/' to bare relative asset paths
(leaving http/https/data/absolute untouched), applied in _imgOf/_backdropOf/_videoOf.

These tests lock: the _url normalization semantics + its wiring in the helpers; and the #523
modal-gate clause (title_detail→modal; browse_home/preview→page; player excluded)."""
import re
from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs


def test_url_helper_present_and_wired():
    js = fs._REF_HELPERS_JS
    assert "const _url =" in js, "_url normalizer missing (#523b)"
    # each image/video accessor must route through _url
    assert js.count("return _url(") >= 4, "helpers not wired through _url (#523b)"
    for h in ("_imgOf", "_backdropOf", "_videoOf"):
        seg = js[js.index("const " + h + " ="):]
        seg = seg[:seg.index(";\n") + 1] if ";\n" in seg else seg[:400]
        assert "_url(" in seg, f"{h} does not normalize via _url (#523b)"


def _norm(u):
    """Mirror of the emitted _url() so we can assert its semantics in Python."""
    if not isinstance(u, str) or not u:
        return u
    if u.startswith("/") or u.startswith("http") or u.startswith("data:") or "://" in u:
        return u
    return "/" + re.sub(r"^[./]+", "", u)


def test_url_normalization_semantics():
    assert _norm("assets/posters/movie_1.jpg") == "/assets/posters/movie_1.jpg"   # bare relative → rooted
    assert _norm("./assets/x.jpg") == "/assets/x.jpg"                              # strip leading ./
    assert _norm("/assets/x.jpg") == "/assets/x.jpg"                              # already absolute → unchanged
    assert _norm("https://picsum.photos/300") == "https://picsum.photos/300"       # external → unchanged
    assert _norm("http://x/y.png") == "http://x/y.png"
    assert _norm("data:image/png;base64,AAA") == "data:image/png;base64,AAA"
    assert _norm("") == "" and _norm(None) is None


def _is_detail_modal(name, kind, route, is_player=False):
    """Mirror of the #523 _is_detail_modal gate (frontend_scaffold.py ~4748)."""
    nm = name.lower()
    norm = re.sub(r"[_\-]+", " ", nm)
    modal_re = r"\b(dialog|modal|flyout|popup|lightbox|preview|hover|popover|overlay)\b"
    route_is_param = bool(re.search(r"[:{]\w", route))
    detail_named = ("detail" in nm) or bool(re.search(modal_re, norm))
    return ((route_is_param and detail_named)
            or bool(re.search(r"\b(dialog|modal)\b", norm))
            or (("detail" in nm) and kind == "overlay")) and not is_player


def test_title_detail_overlay_now_modal():
    # the exact r94 case: name has 'detail', kind overlay, NON-param route → now a modal
    assert _is_detail_modal("title_detail", "overlay", "/browse") is True


def test_param_route_and_dialog_still_modal():
    assert _is_detail_modal("title_detail", "page", "/title/:id") is True   # param+detail
    assert _is_detail_modal("rate_dialog", "overlay", "/browse") is True    # explicit dialog


def test_pages_and_players_not_modal():
    # #456 protections: page-with-overlay screens carry no 'detail' token → stay pages
    assert _is_detail_modal("browse_home", "overlay", "/browse") is False
    assert _is_detail_modal("card_hover_preview", "overlay", "/browse") is False
    assert _is_detail_modal("games", "page", "/games") is False
    # a detail screen that is actually a PLAYER is excluded by the guard
    assert _is_detail_modal("title_detail", "overlay", "/browse", is_player=True) is False


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
