r"""#1203a0: the SSRF guard checked the URL the caller asked for, not the one fetched.

`_ssrf_check` exists in two tool modules because the URL is untrusted — it arrives
from a web search or an image search result. Both callers then fetched with redirects
followed: `web_tools._read_url` via `urlopen`'s default HTTPRedirectHandler,
`image_search_tools` via an explicit `allow_redirects=True`.

PROVEN, not inferred. With an entry host whose DNS resolves public and whose server
answers `302 Location: http://127.0.0.1:<port>/internal`:

    guard verdict for the entry URL -> None          (allowed)
    response.geturl()               -> http://127.0.0.1:.../internal
    body returned to the agent      -> the internal page

★ `web_tools` PUT THAT FINAL URL IN ITS PAYLOAD. The tool knew the URL had changed
and said so in its response, and the guard was never re-run on it — the fact reached
the response without reaching the decision. Same shape as the log-only findings this
codebase keeps turning up, except the thing not acted on is a security verdict.

WHAT IS NOT CHANGED, deliberately:
  * Legitimate hops still work. http->https and CDN redirects are the common case;
    refusing all redirects would have broken ordinary fetches to fix a narrow hole.
    Only a hop INTO a restricted range is refused, and it is refused by name.
  * `capture_webpage` still has no guard, and it is the ONLY one of these tools
    that is ever called: 154 calls across 9 runs, against ZERO for web_fetch,
    web_search, save_image, search_photos and search_icons in the 50 runs carrying
    stage-tool counts. Every one of its 1088 logged URLs is `http://localhost:<port>`
    — it screenshots the generated app. A guard there would refuse 100% of its real
    use. So the honest blast radius of THIS fix is zero measured calls; what it buys
    is that the guard now does what it claims on the day one of those tools is used,
    and #707 grants search_photos/save_image to the frontend lane.
  * `runtime_tools._execute_1134` still has no guard. It takes an arbitrary URL too,
    but its job is to hit the generated app on 127.0.0.1 — the restricted range IS
    the target. Guarding it would break its only purpose. Recorded so the next sweep
    does not "fix" it.
  * The two `_ssrf_check` bodies stay duplicated; the module comment gives the
    reason. What changed is that "kept in sync via grep" is now a test.
"""
import ast
import asyncio
import inspect
import os
import socket
import sys
import threading
import http.server
import socketserver

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import tools.web_tools as W  # noqa: E402
import tools.image_search_tools as I  # noqa: E402


# --------------------------------------------------------------------------
# a server that redirects, and a resolver that makes its host look public
# --------------------------------------------------------------------------
class _Redirector(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/to-loopback":
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:%d/internal" % self.server.server_address[1])
            self.end_headers()
        elif self.path == "/to-public":
            self.send_response(302)
            self.send_header("Location", "http://cdn.example.invalid:%d/page"
                             % self.server.server_address[1])
            self.end_headers()
        elif self.path == "/loop":
            self.send_response(302)
            self.send_header("Location", "http://cdn.example.invalid:%d/loop"
                             % self.server.server_address[1])
            self.end_headers()
        else:
            body = b"<html><title>t</title>REACHED-THE-BODY</html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, *a):
        pass


class _Server:
    def __enter__(self):
        self.srv = socketserver.TCPServer(("127.0.0.1", 0), _Redirector)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self._real = socket.getaddrinfo
        port = self.port
        real = self._real

        def fake(host, prt, *a, **k):
            # The guard resolves with port=None; the TCP connect carries a port.
            # So "cdn.example.invalid" is public to DNS and local to the socket —
            # exactly the shape of a public host that redirects inward.
            if host == "cdn.example.invalid":
                if prt is None:
                    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]
                return real("127.0.0.1", port, *a, **k)
            return real(host, prt, *a, **k)

        socket.getaddrinfo = fake
        return self

    def url(self, path):
        return "http://cdn.example.invalid:%d%s" % (self.port, path)

    def __exit__(self, *a):
        socket.getaddrinfo = self._real
        self.srv.shutdown()
        self.srv.server_close()


# --------------------------------------------------------------------------
# web_tools: urlopen's own redirect handler
# --------------------------------------------------------------------------
def test_the_entry_url_really_does_pass_the_guard():
    """★ The premise of the whole ticket. If this ever fails, the test below proves
    nothing — it would be refusing at the front door, not at the hop."""
    with _Server() as s:
        assert W._ssrf_check(s.url("/to-loopback")) is None


def test_a_redirect_into_a_restricted_range_is_refused():
    with _Server() as s:
        try:
            body, _, final = W._read_url(s.url("/to-loopback"), timeout=5)
        except Exception as e:
            assert "refused for safety" in str(e), e
            assert "restricted range" in str(e), e
        else:
            raise AssertionError("the loopback hop was followed: %s -> %r" % (final, body[:60]))


def test_the_refusal_names_the_hop_not_just_a_failure():
    """A bare "fetch failed" would send the agent looking for a network fault."""
    with _Server() as s:
        try:
            W._read_url(s.url("/to-loopback"), timeout=5)
            raise AssertionError("not refused")
        except AssertionError:
            raise
        except Exception as e:
            assert "redirect to" in str(e), e


def test_a_legitimate_public_hop_is_still_followed():
    """★ The cost of over-correcting: http->https and CDN hops are the common case."""
    with _Server() as s:
        body, _, final = W._read_url(s.url("/to-public"), timeout=5)
        assert "REACHED-THE-BODY" in body, body[:120]
        assert final.endswith("/page"), final


def test_a_redirect_loop_still_terminates():
    with _Server() as s:
        try:
            W._read_url(s.url("/loop"), timeout=5)
        except Exception:
            pass          # urllib raises on too many redirects; it must not hang


def test_the_reader_uses_the_checked_opener():
    """★ I have tested a helper and not its caller repeatedly. Three properties: the
    fetch goes through the opener, the bare `urlopen` is gone from this function, and
    the handler the opener is built from is ours."""
    src = inspect.getsource(W._read_url)
    assert "_SSRF_OPENER_1203A0.open" in src, src
    assert "urllib.request.urlopen" not in src, "the unchecked call is still here"
    tree = ast.parse(inspect.getsource(W).lstrip())
    built = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "attr", "") == "build_opener"]
    assert len(built) == 1, "built %d openers" % len(built)
    assert any(getattr(a, "id", "") == "_SSRFCheckedRedirects1203a0" for a in built[0].args), \
        ast.dump(built[0])


def test_the_handler_refuses_rather_than_returning_none():
    """`HTTPRedirectHandler.redirect_request` returning None means "do not follow" —
    which would look like a plain 302 body to the caller and say nothing. The refusal
    has to be loud."""
    tree = ast.parse(inspect.getsource(W._SSRFCheckedRedirects1203a0.redirect_request).lstrip())
    raises = [n for n in ast.walk(tree) if isinstance(n, ast.Raise)]
    assert raises, "nothing is raised"
    for n in ast.walk(tree):
        if isinstance(n, ast.Return) and isinstance(n.value, ast.Constant) and n.value.value is None:
            raise AssertionError("a silent 'do not follow' crept back in")


# --------------------------------------------------------------------------
# image_search_tools: the aiohttp path
# --------------------------------------------------------------------------
class _public_dns:
    """Make every `*.example.com` name resolve to a public address.

    These tests exercise the hop loop with a fake session, but `_ssrf_check` inside
    it does a real `getaddrinfo`, and `images.example.com` does not resolve — the
    loop would then refuse every hop for the wrong reason and the tests would pass
    vacuously. Patching the RESOLVER rather than the guard keeps the guard under
    test.
    """

    def __enter__(self):
        self._real = socket.getaddrinfo
        real = self._real

        def fake(host, prt, *a, **k):
            if str(host or "").endswith(".example.com"):
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]
            return real(host, prt, *a, **k)

        socket.getaddrinfo = fake
        return self

    def __exit__(self, *a):
        socket.getaddrinfo = self._real


class _Resp:
    def __init__(self, status, location=None):
        self.status = status
        self.headers = {"Location": location} if location else {}
        self.released = False

    def release(self):
        self.released = True


class _Session:
    def __init__(self, script):
        self.script = list(script)
        self.asked = []

    async def get(self, url, **kw):
        self.asked.append((url, kw))
        return self.script.pop(0)


def _get(script, url="http://cdn.example.com/a.png"):
    sess = _Session(script)
    return sess, asyncio.run(I._ssrf_checked_get_1203a0(sess, url))


def test_the_image_fetch_never_asks_aiohttp_to_follow():
    """The hole here was an explicit `allow_redirects=True`."""
    sess, resp = _get([_Resp(200)])
    assert resp.status == 200
    assert sess.asked[0][1].get("allow_redirects") is False, sess.asked


def test_a_hop_into_a_restricted_range_is_refused_before_it_is_fetched():
    """★ The ordering is the point: the second `get` must never happen."""
    with _public_dns():
        sess = _Session([_Resp(302, "http://127.0.0.1:8017/internal"), _Resp(200)])
        try:
            asyncio.run(I._ssrf_checked_get_1203a0(sess, "http://cdn.example.com/a.png"))
            raise AssertionError("the hop was followed")
        except AssertionError:
            raise
        except RuntimeError as e:
            assert "refused for safety" in str(e), e
            assert "restricted range" in str(e), e
        assert len(sess.asked) == 1, "it fetched the restricted URL anyway: %s" % (sess.asked,)


def test_a_public_hop_is_followed():
    with _public_dns():
        sess = _Session([_Resp(302, "https://images.example.com/a.png"), _Resp(200)])
        resp = asyncio.run(I._ssrf_checked_get_1203a0(sess, "http://cdn.example.com/a.png"))
        assert resp.status == 200
        assert len(sess.asked) == 2
        assert sess.asked[1][0] == "https://images.example.com/a.png"


def test_a_relative_location_is_resolved_before_it_is_checked():
    """`Location: /x` is legal. Checking the raw header value would check a string
    with no host in it and pass everything."""
    with _public_dns():
        sess = _Session([_Resp(302, "/other.png"), _Resp(200)])
        asyncio.run(I._ssrf_checked_get_1203a0(sess, "http://cdn.example.com/a.png"))
        assert sess.asked[1][0] == "http://cdn.example.com/other.png", sess.asked


def test_an_endless_chain_is_capped_and_says_so():
    with _public_dns():
        sess = _Session([_Resp(302, "https://a%d.example.com/x" % i) for i in range(12)])
        try:
            asyncio.run(I._ssrf_checked_get_1203a0(sess, "http://cdn.example.com/a.png"))
            raise AssertionError("it followed the whole chain")
        except AssertionError:
            raise
        except RuntimeError as e:
            assert "more than 5 redirects" in str(e), e


def test_a_redirect_without_a_location_is_not_treated_as_a_body():
    sess = _Session([_Resp(302)])
    try:
        asyncio.run(I._ssrf_checked_get_1203a0(sess, "http://cdn.example.com/a.png"))
        raise AssertionError("a Location-less 302 was returned as content")
    except AssertionError:
        raise
    except RuntimeError as e:
        assert "no Location" in str(e) or "carried no Location" in str(e), e


def test_intermediate_responses_are_released():
    """Not a leak test for its own sake — an unreleased aiohttp response holds the
    connection, and this loop can now make several."""
    with _public_dns():
        first = _Resp(302, "https://images.example.com/a.png")
        sess = _Session([first, _Resp(200)])
        asyncio.run(I._ssrf_checked_get_1203a0(sess, "http://cdn.example.com/a.png"))
        assert first.released


def test_the_downloader_calls_the_checked_helper():
    """★ Again: the caller, not the helper. The call must be there, it must be the
    thing the `async with` binds, and the old flag must be gone."""
    src = inspect.getsource(I.SaveImageTool.execute)
    assert "_ssrf_checked_get_1203a0" in src, src
    assert "allow_redirects=True" not in src, "the unchecked fetch is still here"
    assert "session.get(url" not in src, "a direct session.get survived"


def test_the_entry_url_is_still_checked_first():
    """The hop check is additive; the front-door check is what stops a direct
    `http://127.0.0.1:...` and must not have been replaced by it."""
    src = inspect.getsource(I.SaveImageTool.execute)
    i, j = src.index("_ssrf_check(url)"), src.index("_ssrf_checked_get_1203a0")
    assert i < j, "the entry check no longer runs before the fetch"


# --------------------------------------------------------------------------
# the duplication: #772 already owns it
# --------------------------------------------------------------------------
# tests/test_mirrored_logic_cannot_drift_772.py compares both `_ssrf_check` bodies
# (AST, docstrings stripped) and both verdicts on the cases that matter. I wrote
# that comparison again here before finding it — and worse, rewrote the comment
# #772 pins, which is how the suite caught me. The duplicate tests are gone; the
# one gap #772 left (the module-level `_ALLOWED_SCHEMES`, which is not part of any
# function body) is closed there, where the invariant lives.


def test_capture_webpage_is_deliberately_unguarded():
    """Recorded as a decision with its number: 1088 logged URLs, all localhost. If a
    guard appears here, the tool stops screenshotting the app it exists to screenshot."""
    src = inspect.getsource(I.CaptureWebpageTool.execute)
    assert "_ssrf_check" not in src, (
        "an SSRF guard appeared in capture_webpage — measured: all 1088 of its logged "
        "URLs are http://localhost:<port>, i.e. the generated app, so this refuses its "
        "only real use. If it is deliberate, say why localhost stays reachable.")
