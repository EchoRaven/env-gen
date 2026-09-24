"""Retired in Tier B B3c (docs/plan_task_stage_tier_b_design_2026_06_03.md).

Every test in this file pinned behaviors of the agent-keyed
``WorkHub.upsert_plan_snapshot`` / ``get_plan`` / ``list_plans``
surfaces, all of which were retired together with the
``stores.plans`` JsonStore.

The canonical per-task plan now lives at ``task.plan`` and its
behavior is pinned in:
  * ``tests/test_workhub_task_plan_subfield.py``
    (claim_task + update_task_plan APIs)
  * ``tests/test_plantool_task_binding.py``
    (PlanTool attach_to_task / detach / flush)
  * ``tests/test_hub_tools_plantool_binding.py``
    (LLM-facing hub tool wiring of attach/detach)

This file is kept (empty) so historical grep references against the
filename still surface the migration trail; delete entirely on the
next sweep if no one looks here for a year."""
