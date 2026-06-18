import os
import sys
import tempfile

# Repo root importable so `import app...` works from `pytest tests/`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Shared backend-test env, set ONCE here before any test module imports `app`.
# The app's auth/db/ENVS_ROOT config binds at IMPORT time, so per-module
# env-setting made a combined `pytest tests/` run order-dependent (whichever
# module imported `app` first won, breaking the other). Centralizing the config
# keeps the whole backend suite consistent and order-independent. setdefault so
# a real outer env (CI) can still override.
os.environ.setdefault("AGENTSUITE_AUTH_ENABLED", "true")
os.environ.setdefault("AGENTSUITE_JWT_SECRET", "backend-test-secret")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.mktemp(suffix='.db')}")
os.environ.setdefault("ENVS_ROOT", tempfile.mkdtemp())  # empty → no disk envs synced
