"""#99 EFFICIENCY (r97-r99 delivery-tail sink) — seed image-URL localization must leave the
runtime re-seed FINGERPRINT stable so a mid-run localization never triggers a re-seed.

GROUND TRUTH: the shipped seed loader stores ``sha256(json.dumps(seed, sort_keys=True))`` and
re-seeds when it changes. ``localize_seed_external_images`` rewrites EXTERNAL image URLs
(http(s)://…) in ``app/backend/seed_data.json`` to local ``/assets/…`` refs. When that rewrite
ran LATE (decoupled from the authoritative clean boot), api_smoke seeded the external-URL seed,
the later rewrite flipped the fingerprint, and the visual gate's reuse boot (``up -d``, same
volume) then RE-SEEDED mid-capture → data-starved pages (~0.05) → DELIVERY DEFERRED churn every
run. The fix runs the localization BEFORE the clean boot (validation_runner), so this boot stores
the localized fingerprint.

These tests lock the properties the fix relies on:
  * localization resolves external image URLs to /assets/ targets that EXIST (never 404);
  * it is IDEMPOTENT — a second pass rewrites nothing and leaves the file byte-identical, so the
    runtime fingerprint is STABLE once localized (no repeated re-seed);
  * it is a byte-identical NO-OP when the seed has nothing to localize (byte-identical seeding
    when no localization is needed);
  * once localized, the runtime fingerprint (the loader's own hash) no longer churns across a
    re-run — which is exactly why localizing before the first boot removes the re-seed dip.
"""
import hashlib
import json
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    localize_seed_external_images)


def _runtime_fingerprint(seed_path: Path) -> str:
    """The EXACT hash the generated seed loader computes (backend_skeleton seed_if_empty):
    sha256 over json.dumps(data, sort_keys=True, default=str)."""
    data = json.loads(seed_path.read_text(encoding="utf-8"))
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _make_app(tmp_path: Path, seed: dict, staged=("posters/poster_one.jpg",)) -> Path:
    """A minimal app tree: app/backend/seed_data.json + app/frontend/public/assets/<staged>."""
    be = tmp_path / "app" / "backend"
    fe = tmp_path / "app" / "frontend"
    be.mkdir(parents=True)
    (fe / "public" / "assets").mkdir(parents=True)
    for rel in staged:
        f = fe / "public" / "assets" / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"\xff\xd8\xff\xe0jpeg-bytes")  # a real staged asset file
    (be / "seed_data.json").write_text(json.dumps(seed, indent=2), encoding="utf-8")
    return tmp_path


def test_unmatched_external_urls_are_left_as_they_are(tmp_path):
    # #1202qo: without a staged asset to match, the URL stays; no placeholder is generated.
    app = _make_app(tmp_path, {
        "titles": [{"name": "Poster One", "poster_url": "https://images.unsplash.com/photo-abc"}],
        "users": [{"name": "Ava", "avatar": "https://i.pravatar.cc/150?img=1",
                   "email": "a@x.com"}],
    })
    be, fe = app / "app" / "backend", app / "app" / "frontend"
    res = localize_seed_external_images(be, fe)
    assert res.get("localized") + res.get("unmatched") == 2, res
    data = json.loads((be / "seed_data.json").read_text(encoding="utf-8"))
    for v in (data["titles"][0]["poster_url"], data["users"][0]["avatar"]):
        assert "/assets/placeholders/" not in v, v
        assert v.startswith("https://") or (fe / "public" / v.lstrip("/")).is_file(), v
    assert data["users"][0]["email"] == "a@x.com"


def test_localization_is_idempotent_and_fingerprint_stable(tmp_path):
    app = _make_app(tmp_path, {
        "titles": [{"name": "Poster One", "poster_url": "https://images.unsplash.com/photo-abc"}],
    })
    be, fe = app / "app" / "backend", app / "app" / "frontend"
    seed = be / "seed_data.json"

    # First pass localizes; content (and therefore the runtime fingerprint) changes — which is
    # exactly why running it AFTER a boot forces a re-seed. The fix runs it BEFORE the boot.
    fp_external = _runtime_fingerprint(seed)
    assert localize_seed_external_images(be, fe).get("localized") == 1
    fp_local = _runtime_fingerprint(seed)
    assert fp_local != fp_external

    # Second pass (a later heal tick) must rewrite NOTHING and leave the file byte-identical →
    # the runtime fingerprint is STABLE once localized → no repeated mid-run re-seed.
    bytes_after_first = seed.read_bytes()
    assert localize_seed_external_images(be, fe).get("localized") == 0
    assert seed.read_bytes() == bytes_after_first          # byte-identical
    assert _runtime_fingerprint(seed) == fp_local          # fingerprint unchanged


def test_noop_byte_identical_when_nothing_to_localize(tmp_path):
    # A seed already using /assets/ refs (or no images at all) must be a byte-identical no-op —
    # byte-identical seeding behavior when no localization is needed.
    app = _make_app(tmp_path, {
        "titles": [{"name": "Poster One", "poster_url": "/assets/posters/poster_one.jpg"}],
        "users": [{"name": "Ava", "email": "a@x.com"}],
    })
    be, fe = app / "app" / "backend", app / "app" / "frontend"
    seed = be / "seed_data.json"
    before = seed.read_bytes()
    fp_before = _runtime_fingerprint(seed)
    assert localize_seed_external_images(be, fe).get("localized") == 0
    assert seed.read_bytes() == before
    assert _runtime_fingerprint(seed) == fp_before


def test_missing_seed_is_safe_noop(tmp_path):
    # No seed_data.json (e.g. very early boot) → clean no-op, never raises.
    fe = tmp_path / "app" / "frontend"
    (fe / "public" / "assets").mkdir(parents=True)
    be = tmp_path / "app" / "backend"
    be.mkdir(parents=True)
    assert localize_seed_external_images(be, fe).get("localized") == 0


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
