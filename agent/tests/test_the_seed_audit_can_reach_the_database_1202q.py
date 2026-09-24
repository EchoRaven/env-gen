r"""#1202q: the agent-facing seed audit is given the project root, so its live check can run.

`audit_seed_data(hub_registry, project_dir)` has two paths. The live one (#1039) counts rows in
the running database. The fallback filters tables by `status == "defined"` and, per seed_audit's
own comments, "examines 0 tables in 145 of 147 runs" and "skips 1729 of 1745 corpus tables".

Both agent-facing tools called it with NO project_dir, so the live path could not even locate
the compose file: an agent asking "audit the seeds" structurally always got the dead filter.

Measured across r22-r25, r26 and r30: the live row count succeeded ZERO times in any run, while
`SEED AUDIT EXAMINED 0 OF N TABLES` fires 40 to 156 times per run (r26: 156 examinations of
nothing, 0 successful live counts).

r26 shipped on that silence, and the defect was real. Its seed declares 8 `continue_watching`
rows; the delivered database holds 1. The child rows reference `profile_id: 1` while the
parents were inserted with fresh ids (26-30), so seven rows had no parent to attach to —
`profiles` lost three the same way (8 declared, 5 present). Every gate passed.

This does not make the live check succeed on its own — 34 of r26's 40 live-path failures are
"no database container resolved", i.e. the audit ran inside the validation cycle's own
`down -v` window. It removes the failure that no amount of timing could fix.
"""

import sys
import tempfile
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from tools.seed_tools import _project_dir_1202q  # noqa: E402


def test_it_returns_the_hub_registrys_project_root():
    from multi_agent.runtime.hub_registry import HubRegistry
    root = Path(tempfile.mkdtemp()) / "proj"
    reg = HubRegistry(root)
    assert _project_dir_1202q(reg) == reg.base_dir
    # and that root is the one holding docker/, which is what the live path looks for
    assert Path(reg.registryhub.hub_dir).parents[1] == Path(reg.base_dir)


def test_a_registry_without_a_base_dir_does_not_raise():
    class _Bare:
        pass
    assert _project_dir_1202q(_Bare()) is None
    assert _project_dir_1202q(None) is None


def test_both_tools_pass_it_through():
    """The bug was two call sites that dropped the argument entirely."""
    src = (THIS_DIR.parent / "env_generator/llm_generator/tools/seed_tools.py").read_text(
        encoding="utf-8")
    assert src.count("audit_seed_data(self.hub_registry)") == 0
    assert src.count("audit_seed_data(self.hub_registry, _project_dir_1202q(") == 2


def test_the_live_path_is_actually_attempted_with_a_project_dir(tmp_path, caplog):
    """Before the fix the live path could not even start; now its failure names the project
    root it searched, which is the difference between "not tried" and "tried, nothing there"."""
    import logging
    from multi_agent.runtime.hub_registry import HubRegistry
    from multi_agent.runtime.seed_audit import audit_seed_data

    reg = HubRegistry(tmp_path / "proj")
    reg.schema_hub.register_table("profiles", schema={"columns": []},
                                  provider="backend", agent="backend")
    with caplog.at_level(logging.WARNING, logger="multi_agent.runtime.seed_audit"):
        audit_seed_data(reg, _project_dir_1202q(reg))
    assert "#1039" in caplog.text
    assert str(tmp_path / "proj") in caplog.text          # it searched the real root
    # and it says the verdict is not a clean bill of health
    assert "NOT CHECKED" in caplog.text
