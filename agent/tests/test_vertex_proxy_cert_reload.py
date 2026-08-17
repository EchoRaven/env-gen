"""#413 (2026-08-02, live): the vertex-anthropic proxy load_cert_chain'd the mTLS cert ONCE at
startup. fb x509 certs rotate every few days; a 3-day-old proxy served the SINCE-EXPIRED cert →
every LLM call got 502 'SSLV3_ALERT_CERTIFICATE_EXPIRED' (+ 819 client AssertionErrors) → a whole
generation run (r10) died with no valid design_system. The proxy's /health stayed 200 the entire
time (health never touches the upstream mTLS), so the launcher reused the stale proxy. FIX: rebuild
the shared httpx client when the cert file's (realpath, mtime) changes — the proxy self-heals across
rotations instead of serving stale until a manual restart. This locks the reload logic in.
"""
import importlib.util
import pathlib

_PP = pathlib.Path(__file__).resolve().parents[2] / (
    "tools/vertex_anthropic_proxy/vertex_anthropic_proxy.py")


def _load():
    # the module no longer builds the client at import (lazy _client()), so it imports
    # WITHOUT a real cert on disk — we then stub _build_ssl_context + httpx.Client.
    spec = importlib.util.spec_from_file_location("vxproxy413", str(_PP))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _install_fakes(mod):
    builds = []

    class _FakeClient:
        def __init__(self, **kw):
            self.closed = False
            builds.append(self)

        def close(self):
            self.closed = True

    mod._build_ssl_context = lambda: object()   # no real cert needed
    mod.httpx.Client = _FakeClient
    mod._CLIENT = None
    mod._CLIENT_KEY = None
    return builds


def test_client_cached_when_cert_unchanged():
    mod = _load()
    builds = _install_fakes(mod)
    mod._cert_key = lambda: ("/x/cert.pem", 100.0)
    c1 = mod._client()
    c2 = mod._client()
    assert c1 is c2, "same cert → same client (no rebuild)"
    assert len(builds) == 1


def test_client_rebuilds_on_mtime_change():
    mod = _load()
    builds = _install_fakes(mod)
    mod._cert_key = lambda: ("/x/cert.pem", 100.0)
    c1 = mod._client()
    mod._cert_key = lambda: ("/x/cert.pem", 200.0)   # cert rotated (mtime bumped)
    c2 = mod._client()
    assert c2 is not c1, "cert changed → client rebuilt (reloads the fresh cert)"
    assert c1.closed is True, "old client closed on rebuild"
    assert len(builds) == 2


def test_client_rebuilds_on_symlink_retarget():
    mod = _load()
    builds = _install_fakes(mod)
    mod._cert_key = lambda: ("/x/old.pem", 100.0)
    c1 = mod._client()
    mod._cert_key = lambda: ("/x/new.pem", 100.0)   # symlink now points elsewhere
    c2 = mod._client()
    assert c2 is not c1, "realpath change → rebuilt"


def test_unreadable_cert_keeps_existing_client():
    # a transient read failure (_cert_key None) must NOT drop the working client
    mod = _load()
    _install_fakes(mod)
    mod._cert_key = lambda: ("/x/cert.pem", 100.0)
    c1 = mod._client()
    mod._cert_key = lambda: None
    c2 = mod._client()
    assert c2 is c1, "unreadable cert → keep the existing client"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
