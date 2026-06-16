from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...json_store import JsonStore


@dataclass
class WorkHubStores:
    workspaces: JsonStore
    pages: JsonStore
    blocks: JsonStore
    databases: JsonStore
    tasks: JsonStore
    comments: JsonStore
    attendees: JsonStore
    decisions: JsonStore
    acceptance: JsonStore
    reactions: JsonStore

    @classmethod
    def create(cls, hub_dir: Path) -> "WorkHubStores":
        hub_dir = Path(hub_dir)
        return cls(
            workspaces=JsonStore(hub_dir / "workhub_workspaces.json"),
            pages=JsonStore(hub_dir / "workhub_pages.json"),
            blocks=JsonStore(hub_dir / "workhub_blocks.json"),
            databases=JsonStore(hub_dir / "workhub_databases.json"),
            tasks=JsonStore(hub_dir / "workhub_tasks.json"),
            comments=JsonStore(hub_dir / "workhub_comments.json"),
            attendees=JsonStore(hub_dir / "workhub_attendees.json"),
            decisions=JsonStore(hub_dir / "workhub_decisions.json"),
            acceptance=JsonStore(hub_dir / "workhub_acceptance_criteria.json"),
            reactions=JsonStore(hub_dir / "workhub_reactions.json"),
        )

    def ensure_documents(self) -> None:
        for store in [
            self.workspaces, self.pages, self.blocks, self.databases,
            self.tasks, self.comments, self.attendees, self.decisions, self.acceptance,
            self.reactions,
        ]:
            store.update(lambda m: m, change_info={"system": "ensure_workhub_document"})

    def versions(self) -> dict:
        return {
            "workhub_pages": self.pages.get_version(),
            "workhub_blocks": self.blocks.get_version(),
            "workhub_tasks": self.tasks.get_version(),
            "workhub_comments": self.comments.get_version(),
            "workhub_attendees": self.attendees.get_version(),
        }

    def snapshot(self) -> dict:
        return {
            "workspaces": self.workspaces.value(),
            "pages": self.pages.value(),
            "blocks": self.blocks.value(),
            "databases": self.databases.value(),
            "tasks": self.tasks.value(),
            "comments": self.comments.value(),
            "attendees": self.attendees.value(),
            "decisions": self.decisions.value(),
            "acceptance_criteria": self.acceptance.value(),
            "reactions": self.reactions.value(),
        }
