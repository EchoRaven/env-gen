"""Pytest fixtures for the simple_blog oracle.

The north-star runner brings the app under test up (reference or
target) and exposes its base URL + filesystem path via env vars:

  ORACLE_API_URL — e.g. "http://localhost:8000". Required.
  ORACLE_APP_PATH — filesystem path to the app dir; optional but
    strongly preferred since ``resolve_base`` reads its
    ``design/spec.api.json`` conventions block to determine the
    correct base prefix without probing.

These fixtures expose those values to the per-flow test files.
"""

import os

import pytest


@pytest.fixture
def api_url():
    """Base URL of the app under test (no /api suffix — let
    ``resolve_base`` decide that from the spec or by probing)."""
    url = os.environ.get("ORACLE_API_URL")
    if not url:
        pytest.skip(
            "ORACLE_API_URL not set — oracle must be invoked by the "
            "north-star runner which starts the app and exports this var."
        )
    return url.rstrip("/")


@pytest.fixture
def app_path():
    """Filesystem path to the app under test, used by ``resolve_base``
    to read ``design/spec.api.json`` for the authoritative base_url
    prefix. Returns None if unset (resolve_base then falls back to
    /health probing)."""
    return os.environ.get("ORACLE_APP_PATH") or None
