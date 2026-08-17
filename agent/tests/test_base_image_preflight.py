"""task #32: pure primitives for base-image preflight / docker_up fail-fast.

Two dev-box outages (r22/r23) burned hours retrying UNRECOVERABLE base-image pulls
(pruned bases + mirror mTLS cert unfollowable by rootless podman + ghcr DNS-blocked)
up to the validation cap, then grinding to the 2h watchdog. These lock in the two
decisions the fix rests on: (1) which bases a build actually needs (parsed from the
app's own Dockerfiles/compose, not hardcoded — generalizes to any app), and (2)
whether a docker_up failure is unrecoverable here (retry is futile → fail fast).
Error strings are verbatim from the r22/r23 docker_up logs."""
from env_generator.llm_generator.multi_agent.runtime.base_image_preflight import (
    base_images_from_dockerfile,
    base_images_from_compose,
    base_images_required,
    unrecoverable_base_pull_error,
)

# --- real r23 Dockerfiles ---
_BACKEND_DF = "FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim\nRUN uv pip install --system -r pyproject.toml\n"
_FRONTEND_DF = "FROM node:20-alpine AS builder\nRUN npm ci && npm run build\nFROM nginx:alpine\nCOPY --from=builder /app/dist /usr/share/nginx/html\n"
_COMPOSE = (
    "services:\n"
    "  database:\n    image: postgres:16\n    ports: ['5432']\n"
    "  backend:\n    build: ../app/backend\n"
    "  frontend:\n    build: ../app/frontend\n"
)


def test_dockerfile_single_from():
    assert base_images_from_dockerfile(_BACKEND_DF) == [
        "ghcr.io/astral-sh/uv:python3.11-bookworm-slim"]


def test_dockerfile_multistage_drops_stage_ref():
    # `FROM node:20-alpine AS builder` + `FROM nginx:alpine`; a later `FROM builder`
    # (if present) must NOT be reported as a base image.
    out = base_images_from_dockerfile(_FRONTEND_DF)
    assert out == ["node:20-alpine", "nginx:alpine"], out
    assert "builder" not in out


def test_dockerfile_from_stage_alias_excluded():
    df = "FROM python:3.11-slim AS base\nFROM base\nRUN echo hi\n"
    assert base_images_from_dockerfile(df) == ["python:3.11-slim"]


def test_dockerfile_platform_flag_and_case_insensitive():
    df = "from --platform=linux/amd64 node:20-alpine as B\n"
    assert base_images_from_dockerfile(df) == ["node:20-alpine"]


def test_compose_image_refs_only():
    # only `image:` services are pulled; `build:` services come from their Dockerfiles
    assert base_images_from_compose(_COMPOSE) == ["postgres:16"]


def test_compose_quoted_image():
    assert base_images_from_compose('  image: "postgres:16"\n') == ["postgres:16"]


def test_required_is_union_dedup_ordered():
    req = base_images_required([_BACKEND_DF, _FRONTEND_DF], [_COMPOSE])
    assert req == [
        "ghcr.io/astral-sh/uv:python3.11-bookworm-slim",
        "node:20-alpine",
        "nginx:alpine",
        "postgres:16",
    ], req


def test_required_empty_inputs():
    assert base_images_required([], []) == []


# --- unrecoverable-error classifier: verbatim r22/r23 docker_up failures ---
def test_unrecoverable_ghcr_dns():
    e = ('docker_up:Error: creating build container: unable to copy from source '
         'docker://ghcr.io/astral-sh/uv:python3.11-bookworm-slim: initializing source: pinging '
         'container registry ghcr.io: Get "https://ghcr.io/v2/": dial tcp: lookup ghcr.io: no such host')
    assert unrecoverable_base_pull_error(e) is True


def test_unrecoverable_mirror_cert_symlink():
    e = ('unable to copy from source docker://node:20-alpine: (Mirrors also failed: '
         '[vmvm-registry.fbinfra.net/library/node:20-alpine: open '
         '/home/x/.config/containers/certs.d/vmvm-registry.fbinfra.net/client.cert: no such file or directory])')
    assert unrecoverable_base_pull_error(e) is True


def test_unrecoverable_manifest_unknown():
    e = ("reading manifest python3.11-bookworm-slim in "
         "vmvm-registry.fbinfra.net/astral-sh/uv: manifest unknown")
    assert unrecoverable_base_pull_error(e) is True


def test_recoverable_app_build_error_is_not_flagged():
    # a real app-code build failure must still get the normal retries — NOT fail-fast
    e = ("STEP 3/6: RUN uv pip install --system -r pyproject.toml\n"
         "error: distribution not found for package 'my-typo-dep==9.9.9'")
    assert unrecoverable_base_pull_error(e) is False


def test_recoverable_transient_and_empty():
    assert unrecoverable_base_pull_error("read: connection reset by peer") is False
    assert unrecoverable_base_pull_error("") is False
    assert unrecoverable_base_pull_error(None) is False


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
