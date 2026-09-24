r"""#1202du: the seed audit tells a lane to seed the orchestrator's own probe table.

The framework registers its own probe tables in RegistryHub. netflix-r44's
`registryhub_tables.json` holds fourteen, two of which are ours:

    __noop_orchestrator_probe__          __noop_orchestrator_state_check__

Run the audit against that run's real registry and `__noop_orchestrator_state_check__` comes
back flagged `missing_seed`. No lane wrote it, no lane can seed it, and it is not app content.

It is not cosmetic. The backend lane went looking, repeatedly, across the corpus:

    GREP: pattern=__noop_monitoring_probe__|__noop__          scope=app/backend
    GREP: pattern=__noop_orchestrator_read_only_probe__       scope=app
    GREP: pattern=__noop_orchestrator_read_only_probe__|response_key|noop  scope=.

...searching `app/backend` for something the FRAMEWORK registered, which is nowhere in its
scope. `missing_seed` co-occurring with a noop name appears in r40 and r44-resume.

This is #251's lesson a third time — after #1202ds fixed the same shape in the response_key
gate — and the exemption must not depend on metadata the lane has to set. `provider` here
reads "backend", so only the framework's own naming convention identifies it: a `__` prefix,
which app tables do not use. `_spine_tables_1039` already exempts the other two framework
bookkeeping tables (`_seed_meta`, `alembic_version`) by name, and this is the same category.

The check must sit ahead of BOTH audit paths: the `_live` branch consults `_spine` and the
legacy `status == "defined"` branch consults nothing, so a fix in the first alone would leave
the second still flagging.
"""
import sys
from pathlib import Path

import pytest

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.seed_audit import (  # noqa: E402
    audit_seed_data,
    record_live_counts_1202dj,
)


class _Schema:
    def __init__(self, tables):
        self._t = tables

    def list_tables(self):
        return self._t

    def list_seed_registrations(self):
        return {}


class _Hubs:
    def __init__(self, tables):
        self.schema_hub = _Schema(tables)


def _t(status="implemented"):
    return {"status": status, "metadata": {"min_seed_rows": 1}}


NOOPS = {
    "__noop_orchestrator_state_check__": _t(),
    "__noop_orchestrator_probe__": _t(),
}


def test_the_live_path_does_not_flag_the_probe(tmp_path):
    """r44's shape: counts recorded, probe empty."""
    record_live_counts_1202dj(tmp_path, {"__noop_orchestrator_state_check__": 0, "titles": 40})
    rep = audit_seed_data(_Hubs({**NOOPS, "titles": _t()}), project_dir=tmp_path)
    assert [f["table"] for f in rep.flagged_tables] == [], rep.flagged_tables


def test_the_legacy_path_does_not_flag_the_probe_either(tmp_path):
    """The `status == 'defined'` branch consults no spine set at all."""
    rep = audit_seed_data(_Hubs({k: _t("defined") for k in NOOPS}), project_dir=tmp_path)
    assert [f["table"] for f in rep.flagged_tables] == [], rep.flagged_tables


def test_a_real_empty_app_table_is_still_flagged(tmp_path):
    """The defect this audit exists for — #1105's shape — must still be caught."""
    record_live_counts_1202dj(tmp_path, {"titles": 0})
    rep = audit_seed_data(_Hubs({"titles": _t()}), project_dir=tmp_path)
    assert [f["table"] for f in rep.flagged_tables] == ["titles"], rep.flagged_tables


def test_the_probe_is_not_counted_as_examined(tmp_path):
    """#1023d: `examined` must report tables actually audited, not skipped ones."""
    record_live_counts_1202dj(tmp_path, {"__noop_orchestrator_probe__": 5, "titles": 40})
    rep = audit_seed_data(_Hubs({**NOOPS, "titles": _t()}), project_dir=tmp_path)
    assert rep.examined == 1, rep.to_dict()


def test_an_app_table_cannot_hide_behind_a_single_underscore(tmp_path):
    """The convention is the framework's double underscore, not any leading underscore."""
    record_live_counts_1202dj(tmp_path, {"_titles": 0})
    rep = audit_seed_data(_Hubs({"_titles": _t()}), project_dir=tmp_path)
    assert [f["table"] for f in rep.flagged_tables] == ["_titles"], rep.flagged_tables
