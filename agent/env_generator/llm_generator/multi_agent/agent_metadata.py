"""
Shared metadata for resident lanes.

Keep runtime-visible lane IDs, descriptions, and common domain constants in one
place so tool schemas and orchestration helpers do not drift independently.
"""

from __future__ import annotations

# The 5 resident lanes (design merged into frontend, database into backend; #1202ch
# retired knowledge — it only ever booted, and knowledge collection now lives outside
# the pipeline).
RESIDENT_LANE_IDS = (
    "orchestrator",
    "backend",
    "frontend",
    "verifier",
    "debugger",
)


ROLE_DESCRIPTIONS = {
    "orchestrator": "Leads planning, coordination, and delivery",
    "backend": "Implements backend APIs, DB schema, and seed data",
    "frontend": "Builds UI design + components and frontend flows",
    "verifier": "Runs validation and routes issues",
    "debugger": "Triages verifier-found bugs to their owning lane",
}


# #1202ch dropped "knowledge": no task in the corpus was ever assigned to that domain
# (0 of 18315), so nothing routed through it.
DEV_TASK_DOMAINS = (
    "backend",
    "frontend",
    "verifier",
    "any",
)
