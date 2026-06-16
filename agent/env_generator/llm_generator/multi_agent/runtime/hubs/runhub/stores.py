from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...json_store import JsonStore


@dataclass
class RunHubStores:
    runs: JsonStore

    @classmethod
    def create(cls, hub_dir: Path) -> "RunHubStores":
        hub_dir = Path(hub_dir)
        return cls(runs=JsonStore(hub_dir / "runhub_runs.json"))

    def ensure_documents(self) -> None:
        self.runs.update(lambda m: m, change_info={"system": "ensure_runhub_document"})

    def versions(self) -> dict:
        return {"runhub_runs": self.runs.get_version()}

    def snapshot(self) -> dict:
        return {"runs": self.runs.value()}
