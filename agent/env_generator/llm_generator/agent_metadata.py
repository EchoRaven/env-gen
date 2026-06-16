"""
Shared metadata for resident lanes.

This lightweight top-level module avoids pulling in the full `multi_agent`
package during tool package initialization.
"""

from __future__ import annotations

RESIDENT_LANE_IDS = (
    "orchestrator",
    "design",
    "database",
    "backend",
    "frontend",
    "verifier",
    "knowledge",
)


ROLE_DESCRIPTIONS = {
    "orchestrator": "Leads planning, coordination, and delivery",
    "design": "Creates architecture and specifications",
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
    "design",
    "verifier",
    "knowledge",
    "any",
)
