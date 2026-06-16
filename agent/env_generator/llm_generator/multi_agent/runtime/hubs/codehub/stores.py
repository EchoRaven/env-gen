from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...json_store import JsonStore


@dataclass
class CodeHubStores:
    repos: JsonStore
    branches: JsonStore
    commits: JsonStore
    pull_requests: JsonStore
    review_threads: JsonStore
    code_reviews: JsonStore
    checks: JsonStore
    releases: JsonStore

    @classmethod
    def create(cls, hub_dir: Path) -> "CodeHubStores":
        hub_dir = Path(hub_dir)
        return cls(
            repos=JsonStore(hub_dir / "codehub_repos.json"),
            branches=JsonStore(hub_dir / "codehub_branches.json"),
            commits=JsonStore(hub_dir / "codehub_commits.json"),
            pull_requests=JsonStore(hub_dir / "codehub_pull_requests.json"),
            review_threads=JsonStore(hub_dir / "codehub_review_threads.json"),
            code_reviews=JsonStore(hub_dir / "codehub_code_reviews.json"),
            checks=JsonStore(hub_dir / "codehub_checks.json"),
            releases=JsonStore(hub_dir / "codehub_releases.json"),
        )

    def ensure_documents(self) -> None:
        for store in [
            self.repos, self.branches, self.commits, self.pull_requests,
            self.review_threads, self.code_reviews, self.checks, self.releases,
        ]:
            store.update(lambda m: m, change_info={"system": "ensure_codehub_document"})

    def versions(self) -> dict:
        return {
            "codehub_repos": self.repos.get_version(),
            "codehub_branches": self.branches.get_version(),
            "codehub_commits": self.commits.get_version(),
            "codehub_pull_requests": self.pull_requests.get_version(),
            "codehub_review_threads": self.review_threads.get_version(),
            "codehub_code_reviews": self.code_reviews.get_version(),
            "codehub_checks": self.checks.get_version(),
            "codehub_releases": self.releases.get_version(),
        }

    def snapshot(self) -> dict:
        return {
            "repos": self.repos.value(),
            "branches": self.branches.value(),
            "commits": self.commits.value(),
            "pull_requests": self.pull_requests.value(),
            "review_threads": self.review_threads.value(),
            "code_reviews": self.code_reviews.value(),
            "checks": self.checks.value(),
            "releases": self.releases.value(),
        }
