"""#1202qb: authored step headers are substituted like the path and body, and a still-unresolved
placeholder is dropped instead of sent. tiktok-r126's tenant list holds `${tenantA}` and
`${tenantId}` - init-tenant received the literal header text."""
from env_generator.llm_generator.multi_agent.runtime import chain_executor as CE


def _run(monkeypatch, steps):
    sent = []

    def _http(method, url, token=None, body=None, headers=None, form=False, **k):
        sent.append((method, url, dict(headers or {})))
        if url.endswith("/api/v1/tenants") and method == "POST":
            return {"status": 201, "body_text": '{"item": {"id": "tenant_a1"}}'}
        return {"status": 200, "body_text": "{}"}

    monkeypatch.setattr(CE, "_http", _http)
    CE.execute_chain("http://127.0.0.1:1", {"name": "tenant_flow", "steps": steps})
    return sent


def test_a_saved_tenant_reaches_the_header(monkeypatch):
    sent = _run(monkeypatch, [
        {"method": "POST", "path": "/api/v1/tenants", "body": {"id": "tenant_a1", "name": "A"},
         "expect": [201], "save": {"tenantA": "item.id"}},
        {"method": "POST", "path": "/api/v1/admin/init-tenant",
         "headers": {"X-Tenant-ID": "${tenantA}"}, "body": {}, "expect": [200]},
    ])
    init = [h for m, u, h in sent if u.endswith("/admin/init-tenant")]
    assert init and init[0].get("X-Tenant-ID") == "tenant_a1", sent


def test_an_unresolved_header_is_not_sent_literally(monkeypatch):
    sent = _run(monkeypatch, [
        {"method": "POST", "path": "/api/v1/admin/init-tenant",
         "headers": {"X-Tenant-ID": "${neverSaved}"}, "body": {}, "expect": [200]},
    ])
    init = [h for m, u, h in sent if u.endswith("/admin/init-tenant")]
    assert init and "X-Tenant-ID" not in init[0], sent
    assert not any("${" in v for v in init[0].values())
