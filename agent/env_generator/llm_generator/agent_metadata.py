"""
Shared metadata for resident lanes.

This lightweight top-level module avoids pulling in the full `multi_agent`
package during tool package initialization.
"""

from __future__ import annotations

# The 6 resident lanes (design merged into frontend, database into backend).
RESIDENT_LANE_IDS = (
    "orchestrator",
    "backend",
    "frontend",
    "verifier",
    "debugger",
    "knowledge",
)


ROLE_DESCRIPTIONS = {
    "orchestrator": "Leads planning, coordination, and delivery",
    "backend": "Implements backend APIs, DB schema, and seed data",
    "frontend": "Builds UI design + components and frontend flows",
    "verifier": "Runs validation and routes issues",
    "debugger": "Triages verifier-found bugs to their owning lane",
    "knowledge": "Collects reusable knowledge and decisions",
}


DEV_TASK_DOMAINS = (
    "backend",
    "frontend",
    "verifier",
    "knowledge",
    "any",
)
