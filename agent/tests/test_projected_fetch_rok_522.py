"""#522 (netflix r93, 2026-08-06) — projected-page fetches must check r.ok, so a
non-2xx (401/500) resolves to an error state instead of an infinite "Loading...".

GROUND TRUTH: r93's catalog pages (games, browse_by_languages) scored 0.08-0.12 — the
games.png capture showed just a "Games" heading + "Loading..." (no content). curl on the
running container: /api/games → 401. The projected-page fetch template did
`.then((r) => r.json())` WITHOUT checking r.ok, so a 401 whose body is valid JSON parsed
fine → setData({detail:'Not authenticated'}) → rows=[] → the display
`rows.length===0 && !error ? "Loading..." : null` stuck on "Loading..." FOREVER (error
never set, data never valid). Infinite "Loading..." tanks fidelity AND violates the
contract's "honest empty states". FIX #522a: the fetch checks r.ok and throws on non-2xx
→ the .catch sets error → the page resolves (error/empty state) instead of hanging.
Generalizable (every projected data fetch); the deeper auth fix (capture must send a valid
token so catalog GETs return data) is #522b / task#46.

These tests lock: the projector emits the r.ok guard and NOT the bare r.json() fetch."""
from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs


def _project_a_page():
    """Invoke the generic projected-page path with a GET endpoint so a fetch is emitted."""
    page = {"name": "GamesPage", "route": "/games", "components": []}
    # _project_page_component emits the fetch template when a GET endpoint is provided.
    try:
        return fs._project_page_component("GamesPage", page, nav_routes=[("Home", "/browse")],
                                          design={"design_system": {"palette": {}}},
                                          get_ep="/api/games")
    except TypeError:
        # signature fallback (get_ep passed positionally / different kw); still emits a page
        return fs._project_page_component("GamesPage", page)


def test_projected_fetch_has_rok_guard():
    src = _project_a_page()
    # If this invocation path emitted a data fetch, it MUST carry the r.ok guard. (Some
    # projector paths render a param/no-GET page with no fetch — then the source-migration
    # test below is the guarantee.)
    if "fetch(" in src and ".then((r) =>" in src:
        assert "if (!r.ok)" in src, "projected fetch must check r.ok (#522) — got:\n" + src[:600]


def test_projected_fetch_not_bare_rjson():
    src = _project_a_page()
    # the bare, status-blind form must be gone (it's the infinite-Loading bug)
    assert ".then((r) => r.json())" not in src, "bare status-blind r.json() fetch still present (#522)"


def test_source_template_fully_migrated():
    # belt-and-suspenders: the module source has NO bare status-blind fetch left anywhere.
    import inspect
    mod_src = inspect.getsource(fs)
    assert ".then((r) => r.json())" not in mod_src, "a bare r.json() fetch template remains (#522)"
    assert mod_src.count("if (!r.ok) throw new Error('HTTP ' + r.status)") >= 4  # all 4 sites migrated


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
