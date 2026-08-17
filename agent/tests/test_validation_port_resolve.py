"""api_smoke port resolution must not wedge on podman (netflix r1 root cause).

`docker compose ps -q <service>` returns empty on podman-compose (no service
positional) → _service_host_port returned None → backend_port unresolved → api_smoke
early-returned before running any chain → every delivery gate stuck. The deterministic
fallback reads the published host port straight from the compose ports mapping.
"""
import tempfile, pathlib
from env_generator.llm_generator.multi_agent.runtime.validation_runner import (
    _declared_host_port_from_compose)

def _cf(body):
    d = pathlib.Path(tempfile.mkdtemp()) / "docker-compose.yml"
    d.write_text(body, encoding="utf-8")
    return d

def test_backend_published_port_from_ports_mapping():
    cf = _cf('services:\n  backend:\n    ports:\n      - "3000:8082"\n')
    assert _declared_host_port_from_compose(cf, "backend") == 3000

def test_bare_number_and_proto_suffix():
    cf = _cf('services:\n  db:\n    ports:\n      - "5432:5432/tcp"\n  x:\n    ports:\n      - "9000"\n')
    assert _declared_host_port_from_compose(cf, "db") == 5432
    assert _declared_host_port_from_compose(cf, "x") == 9000

def test_long_form_ports():
    cf = _cf('services:\n  backend:\n    ports:\n      - published: 3000\n        target: 8082\n')
    assert _declared_host_port_from_compose(cf, "backend") == 3000

def test_missing_service_or_ports():
    cf = _cf('services:\n  backend:\n    image: x\n')
    assert _declared_host_port_from_compose(cf, "backend") is None
    assert _declared_host_port_from_compose(cf, "nope") is None

if __name__ == "__main__":
    import pytest; raise SystemExit(pytest.main([__file__, "-q"]))
