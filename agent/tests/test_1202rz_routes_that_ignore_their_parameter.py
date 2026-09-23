r"""#1202rz: a frontend that routes `/video/:id` but can never read the id.

tiktok-r126, reported by an unprimed judge that had only been asked to find the
most-commented video on the platform:

  I clicked a spencerx tile in Explore whose href was /video/21; the URL bar changed to
  /video/21, but the page rendered bts_official_bighit's video 1, its caption, its 5 likes
  and its comment thread. I confirmed the same for /video/24, /video/32, /video/9. The page
  never calls a per-video endpoint; it calls GET /api/feed?limit=12&offset=0 and renders
  items[0]. As a result there is no way at all to reach any video except the first one
  through the UI, which is what forced me onto the API for the whole comparison step.

No deterministic gate saw it, and the app passed delivery. Every record past the first was
unreachable from the UI of a delivered app.

THE ZERO CASE ONLY, for the same reason as `#1202rq`. One page that ignores its parameter can
be a deliberate redirect, and proving it per-page needs component resolution -- my first
attempt at that fired on code fragments it had mistaken for routes, which is how it failed the
only test that matters (does it agree with hand-checked samples). But a frontend that declares
parameterised routes and contains NO `useParams`, `match.params` or `router.query` ANYWHERE
has no way to read one, so every such route is decorative by construction.

It costs coverage honestly: r126 itself is NOT flagged, because one of its components does
call useParams -- just not the one behind /video/:id. 6 of the 137 corpus frontends that
declare a parameterised route are in the zero state: r115, r128, r131, r46, r54, r85.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.deliverability import (
    _routes_that_ignore_their_parameter_1202rz as gate)


_ROUTES = ('<Routes><Route path="/" element={<Feed/>}/>'
           '<Route path="/video/:id" element={<VideoPage/>}/></Routes>')


def _app(tmp_path, app_src, extra=None):
    src = tmp_path / "frontend" / "src"
    src.mkdir(parents=True)
    (src / "App.jsx").write_text(app_src)
    for name, text in (extra or {}).items():
        (src / name).write_text(text)
    return tmp_path


# --- it fires -------------------------------------------------------------------------

def test_a_parameterised_route_with_no_way_to_read_the_parameter(tmp_path):
    out = gate(_app(tmp_path, _ROUTES, {"VideoPage.jsx":
                                        "export default function VideoPage(){"
                                        "const {data}=useLoad(()=>api.getFeed());"
                                        "return <Feed v={data.items[0]}/>}"}))
    assert out and "/video/:id" in out[0]


def test_the_count_and_the_list_agree(tmp_path):
    """#1034. The first draft counted one entry per FILE a route appeared in while printing
    the deduped set, and passed join_capped's `total` where I meant a cap -- so it said
    "1 parameterised page(s) (/video/:video_id/comments (+3 more not shown))".
    """
    routes = ('<Route path="/video/:id" element={<A/>}/>'
              '<Route path="/@:username" element={<B/>}/>')
    app = _app(tmp_path, routes, {"Dup.jsx": routes})  # same routes seen in two files
    out = gate(app)[0]
    assert "2 parameterised page(s)" in out, out
    assert "more not shown" not in out, out
    assert "/video/:id" in out and "/@:username" in out


# --- and what silences it -------------------------------------------------------------

@pytest.mark.parametrize("reader", [
    "const {id} = useParams();",
    "const id = match.params.id;",
    "const { id } = router.query;",
    "const m = useRouteMatch();",
])
def test_any_way_of_reading_a_parameter_silences_it(tmp_path, reader):
    assert gate(_app(tmp_path, _ROUTES, {"VideoPage.jsx": reader})) == []


def test_a_frontend_with_no_parameterised_route_is_not_judged(tmp_path):
    plain = '<Route path="/" element={<Feed/>}/><Route path="/explore" element={<E/>}/>'
    assert gate(_app(tmp_path, plain)) == []


def test_no_frontend_at_all_is_silent(tmp_path):
    assert gate(tmp_path) == []
    assert gate(tmp_path / "nope") == []


def test_an_operator_can_turn_it_off(tmp_path, monkeypatch):
    app = _app(tmp_path, _ROUTES, {"VideoPage.jsx": "export default () => <div/>"})
    assert gate(app), "precondition: it fires without the switch"
    monkeypatch.setenv("ENVGEN_ROUTE_PARAM_GATE", "0")
    assert gate(app) == []


def test_an_unreadable_tree_does_not_raise(tmp_path):
    src = tmp_path / "frontend" / "src"
    src.mkdir(parents=True)
    (src / "App.jsx").write_bytes(b"\xff\xfe<Route path=\"/x/:id\"")
    assert isinstance(gate(tmp_path), list)


# --- the wiring -----------------------------------------------------------------------

def test_the_delivery_gate_consults_it():
    """A gate nobody calls is the defect class this session keeps finding."""
    import inspect

    from env_generator.llm_generator.multi_agent.runtime import deliverability

    src = inspect.getsource(deliverability)
    assert "blockers.extend(_routes_that_ignore_their_parameter_1202rz(app_root))" in src
