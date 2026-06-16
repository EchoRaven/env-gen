"""
Shared metadata for resident lanes.

Keep runtime-visible lane IDs, descriptions, and common domain constants in one
place so tool schemas and orchestration helpers do not drift independently.
"""

from __future__ import annotations

RESIDENT_LANE_IDS = (
    "orchestrator",
    "database",
    "backend",
    "frontend",
    "verifier",
    "knowledge",
)


ROLE_DESCRIPTIONS = {
    "orchestrator": "Leads planning, coordination, and delivery",
    "database": "Handles database schema and seed data",
    "backend": "Implements backend APIs and logic",
    "frontend": "Builds UI components and frontend flows",
    "verifier": "Runs validation and routes issues",
    "knowledge": "Collects reusable knowledge and decisions",
}


DEV_TASK_DOMAINS = (
    "database",
    "backend",
    "frontend",
    "verifier",
    "knowledge",
    "any",
)
