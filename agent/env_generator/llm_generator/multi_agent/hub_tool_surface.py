"""
Declarative hub tool surface — the single source of truth for which READ and
which ACTION (write) tools each hub provides to an agent.

This backs the *hub-focus* tool model (see agents/runtime/step_pipeline/action.py):

  Layer 1  fixed intrinsic tools (read/write/edit/think/finish/comms) — always present.
  Layer 2  cross-hub awareness: every hub's READ tools + `hub_snapshot` — always present.
  Layer 3  hub ACTION tools — offered only while the agent is *focused* on that hub.

So an agent can always observe any hub, but only acts on the hub it has moved to
(via the `focus_hub` tool). This keeps the per-decision tool surface small and the
workflow legible ("backend is in CodeHub") without losing cross-hub visibility.

Tool names here are the authoritative NAMEs from tools/hub_tools.py + tools/run_tools.py.
Keep this table in sync when adding a hub tool — it is the one place that decides
read-vs-write and hub ownership.
"""
from __future__ import annotations

from typing import Dict, Optional, Set, Tuple

# hub -> {"reads": {...}, "writes": {...}}
HUB_TOOL_SURFACE: Dict[str, Dict[str, Set[str]]] = {
    "codehub": {
        "reads": {
            "codehub_get_blob",
            "codehub_get_diff",
            "codehub_get_file_content",
            "codehub_list_checks",
            "codehub_list_inline_comments",
            "codehub_list_prs",
            "codehub_suggest_reviewers",
        },
        "writes": {
            "codehub_commit",
            "codehub_create_release",
            "codehub_force_merge",
            "codehub_open_pr",
            "codehub_record_commit",
            "codehub_register_repo",
            "codehub_resolve_conflict",
            "codehub_resolve_merge_conflict",
            "codehub_revert_commit",
        },
    },
    "workhub": {
        "reads": {
            "workhub_available_tasks",
            "workhub_comments_for",
            "workhub_get_page",
            "workhub_get_task",
            "workhub_list_blocked",
            "workhub_list_pages",
            "workhub_list_ready",
            "workhub_list_tasks",
            "workhub_list_ui_pages",
            "workhub_list_ui_components",
        },
        "writes": {
            "workhub_archive_page",
            "workhub_cancel_task",
            "workhub_comment",
            "workhub_create_page",
            "workhub_update_page",
            "workhub_fail_task",
            "workhub_invite_attendee",
            "workhub_link_task_to_apis",
            "workhub_link_task_to_pr",
            "workhub_record_decision",
            "workhub_remove_attendee",
            "workhub_reply",
            "workhub_set_priority",
            "workhub_share_implementation",
            "workhub_task",
            "workhub_update_block",
            "workhub_create_meeting",
            "workhub_add_meeting_decision",
            "kickoff_declare_ui_page",
            "kickoff_declare_ui_component",
            "kickoff_declare_user_flow",
            "kickoff_declare_predicate",
            "kickoff_declare_endpoint",
            "kickoff_declare_table",
            "workhub_close_meeting",
        },
    },
    "registryhub": {
        "reads": {
            "registryhub_get_breaking_changes",
            "registryhub_get_dependencies_for_file",
            "registryhub_get_endpoint",
            "registryhub_get_table_breaking_changes",
            "registryhub_list_endpoints",
            "registryhub_check_endpoint_drift",
            "registryhub_list_tables",
        },
        "writes": {
            "registryhub_deprecate_endpoint",
            "registryhub_record_contract_test",
            "registryhub_register_consumer",
            "registryhub_register_endpoint",
            "registryhub_register_table",
            "registryhub_register_table_consumer",
            "registryhub_update_schema",
            "registryhub_update_table_schema",
            "registryhub_register_verification_chain",
        },
    },
    "eventhub": {
        "reads": {
            "eventhub_get_agent_status",
            "eventhub_get_thread",
            "eventhub_inbox",
            "eventhub_list_subscriptions",
        },
        "writes": {
            "eventhub_mark_all_read",
            "eventhub_reply_in_thread",
            "eventhub_subscribe",
            "eventhub_unsubscribe",
        },
    },
    "runhub": {
        "reads": {
            "run_get",
            "run_list",
            "run_status",
        },
        "writes": {
            "run_start",
        },
    },
}

# Cross-hub reads that are never gated by focus.
CROSS_HUB_READS: Set[str] = {"hub_snapshot"}

HUB_NAMES: Tuple[str, ...] = tuple(HUB_TOOL_SURFACE.keys())


def _union(key: str) -> Set[str]:
    out: Set[str] = set()
    for spec in HUB_TOOL_SURFACE.values():
        out |= spec.get(key, set())
    return out


ALL_HUB_READS: Set[str] = _union("reads") | set(CROSS_HUB_READS)
ALL_HUB_WRITES: Set[str] = _union("writes")
ALL_HUB_TOOLS: Set[str] = ALL_HUB_READS | ALL_HUB_WRITES

# write tool name -> owning hub
_WRITE_TO_HUB: Dict[str, str] = {
    name: hub for hub, spec in HUB_TOOL_SURFACE.items() for name in spec.get("writes", set())
}


def known_hub(hub: Optional[str]) -> bool:
    return bool(hub) and hub in HUB_TOOL_SURFACE


def hub_of_write_tool(name: str) -> Optional[str]:
    return _WRITE_TO_HUB.get(name)


def writes_for_hub(hub: Optional[str]) -> Set[str]:
    return set(HUB_TOOL_SURFACE.get(hub or "", {}).get("writes", set()))
