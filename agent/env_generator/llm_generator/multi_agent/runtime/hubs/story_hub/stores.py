"""StoryHubStores — JsonStore-backed persistence for Phase 3 stories.

Mirror of RunHubStores at runhub/stores.py. Single ``stories`` table
keyed by story_id; per-row records are the canonical dict returned
by ``story_hub.register_story`` at phase>=3.0.

The mechanism module (runtime/story_hub.py) is store-agnostic — when
StoryHub.__init__ is wired with stores=None (legacy free-function
call), register_story returns the canonical record without
persistence; when wired with this concrete StoryHubStores via
hub_registry, the record is persisted via the canonical-writer
``stores.stories.update(lambda m: m.set(story_id, record, actor))``
pattern.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...json_store import JsonStore


@dataclass
class StoryHubStores:
    stories: JsonStore

    @classmethod
    def create(cls, hub_dir: Path) -> "StoryHubStores":
        hub_dir = Path(hub_dir)
        hub_dir.mkdir(parents=True, exist_ok=True)
        return cls(stories=JsonStore(hub_dir / "story_hub_stories.json"))

    def ensure_documents(self) -> None:
        self.stories.update(
            lambda m: m,
            change_info={"system": "ensure_story_hub_document"},
        )

    def versions(self) -> dict:
        return {"story_hub_stories": self.stories.get_version()}

    def snapshot(self) -> dict:
        return {"stories": self.stories.value()}
