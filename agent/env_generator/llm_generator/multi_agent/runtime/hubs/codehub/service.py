from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import time

from ...eventhub import EventHub
from .git_ops import GitOps
from .stores import CodeHubStores

log = logging.getLogger(__name__)


class CodeHub:
    """GitHub/GitLab-like collaboration kernel for agent code work."""

    def __init__(self, repo_root: Path, hub_dir: Path, eventhub: EventHub | None = None):
        self.repo_root = Path(repo_root)
        self.hub_dir = Path(hub_dir)
        self.eventhub = eventhub
        self._workhub = None
        self.git = GitOps(self.repo_root)
        self.stores = CodeHubStores.create(self.hub_dir)
        self.stores.ensure_documents()

    def attach_workhub(self, workhub) -> None:
        """Attach a WorkHub instance for cross-hub task creation."""
        self._workhub = workhub

    def attach_registryhub(self, registryhub) -> None:
        """Attach an RegistryHub instance for linked_apis manifest validation."""
        self._registryhub = registryhub

    # ------------------------------------------------------------------
    # Real-git lifecycle helpers
    # ------------------------------------------------------------------

    def ensure_repo(self) -> None:
        """Initialise the git repo at repo_root if it doesn't already exist."""
        git_dir = self.repo_root / ".git"
        if not git_dir.is_dir():
            self.git.init()

    def register_agent_worktree(self, agent_id: str) -> Path:
        """
        Create a git worktree for *agent_id* under repo_root/worktrees/.

        The branch name follows the convention ``agent/<agent_id>``.
        Returns the worktree path.
        """
        self.ensure_repo()
        # Ensure there is at least one commit so worktrees can be created
        git_dir = self.repo_root / ".git"
        head_file = git_dir / "HEAD"
        if head_file.exists():
            head_content = head_file.read_text().strip()
            # Check if HEAD points to a valid commit (not just a symbolic ref with no commits)
            try:
                self.git.current_head()
            except Exception:
                # No commits yet — create an empty initial commit
                self.git.commit("Initial commit (CodeHub bootstrap)", allow_empty=True)

        branch = f"agent/{agent_id}"
        wt_path = self.repo_root / "worktrees" / agent_id
        if wt_path.exists():
            return wt_path
        self.git.add_worktree(wt_path, branch)
        # Emit path relative to repo_root — the inbox event must not
        # leak the host's absolute prefix to the agent.
        self._emit(
            "worktree_registered",
            {"agent_id": agent_id, "branch": branch, "path": f"worktrees/{agent_id}"},
            recipients=[agent_id],
        )
        return wt_path

    def cleanup_worktree(self, agent_id: str) -> bool:
        """
        Remove the git worktree AND its branch for *agent_id*.

        Without removing the branch, every spawned worker leaves an
        ``agent/<worker_id>`` ref behind — over a long run the project
        accumulates hundreds of dead branches, polluting ``git branch``
        and the CodeHub UI.

        Returns True if anything was removed.
        """
        wt_path = self.repo_root / "worktrees" / agent_id
        removed_anything = False
        if wt_path.exists():
            self.git.remove_worktree(wt_path, force=True)
            removed_anything = True

        # Best-effort branch delete — okay to fail (branch may have been
        # merged or never created).
        try:
            self.git._run("branch", "-D", f"agent/{agent_id}")
            removed_anything = True
        except Exception:
            pass

        if removed_anything:
            self._emit(
                "worktree_cleaned",
                {"agent_id": agent_id, "path": f"worktrees/{agent_id}"},
                recipients=[agent_id],
            )
        return removed_anything

    def commit_runtime_scaffold(self, rel_paths: List[str], message: str) -> Optional[str]:
        """Commit runtime-owned files to the BASE branch (repo_root's HEAD),
        BEFORE any agent worktree is created, so every ``agent/<id>`` worktree
        (branched off HEAD) and the ``integration`` branch (bootstrapped from the
        first agent branch) inherit them by construction.

        This is the consistency-by-construction substrate for files that are
        FIXED and imported by a lane (e.g. the embedded OAuth2 AS modules the
        backend's ``main.py`` imports): committing them to the base means the
        backend lane physically has them in its worktree (imports/lint resolve)
        and git — not a prompt convention — owns the "do not author these"
        boundary. Contrast ``write_database_scaffold`` output, which only
        postgres reads at docker time and therefore stays an untracked
        ``output_dir`` write.

        ``rel_paths`` are repo_root-relative (e.g. ``app/backend/jwt_manager.py``)
        and must already be written to disk. Idempotent: re-committing identical
        content is a no-op (git reports "nothing to commit"); returns None then.
        Returns the commit SHA on a real commit, else None.

        Charter §8 (no silent fallback): a path that does not exist on disk is a
        caller bug and raises — we never commit a phantom scaffold."""
        self.ensure_repo()
        existing = [p for p in rel_paths if (self.repo_root / p).exists()]
        missing = [p for p in rel_paths if p not in existing]
        if missing:
            raise FileNotFoundError(
                f"commit_runtime_scaffold: paths not on disk under {self.repo_root}: {missing}"
            )
        if not existing:
            return None
        self.git.add(*existing)
        # Stage-empty guard: if the files are already committed verbatim, the
        # index has no delta and `git commit` would fail with "nothing to
        # commit". Detect via `diff --cached --quiet` (rc 1 == staged changes).
        rc = self.git._run("diff", "--cached", "--quiet", check=False).returncode
        if rc == 0:
            return None
        sha = self.git.commit(message)
        self._emit(
            "runtime_scaffold_committed",
            {"files": existing, "sha": sha, "message": message},
            recipients=[],
        )
        return sha

    def _emit(self, event_type: str, payload: dict, recipients: Optional[List[str]] = None, priority: str = "normal") -> None:
        if self.eventhub:
            # Phase 4.1c: caller="codehub" → owner-equals admit.
            self.eventhub.publish_event(
                "codehub", event_type, payload,
                recipients=recipients or [], priority=priority,
                caller="codehub",
            )

    def register_agent_repo(self, agent_id: str, worktree_path: str, repo_id: str = "main") -> dict:
        now = time.time()
        repo = self.stores.repos.get(repo_id) or {"id": repo_id, "main_branch": "main", "agents": {}}
        repo.setdefault("agents", {})[agent_id] = {"worktree_path": worktree_path, "registered_at": now}
        self.stores.repos.update(
            lambda m: m.set(repo_id, repo, agent_id),
            change_info={"agent": agent_id},
        )
        branch = self.ensure_branch(agent_id=agent_id, branch=f"agent/{agent_id}", repo_id=repo_id)
        self._emit("repo_registered", {"repo_id": repo_id, "agent_id": agent_id, "branch": branch["name"]}, [agent_id])
        return repo

    def ensure_branch(self, agent_id: str, branch: str, repo_id: str = "main", base: str = "main") -> dict:
        now = time.time()
        key = f"{repo_id}:{branch}"
        existing = self.stores.branches.get(key) or {}
        payload = {
            **existing,
            "id": key,
            "repo_id": repo_id,
            "name": branch,
            "base": base,
            "owner": existing.get("owner") or agent_id,
            "status": existing.get("status") or "active",
            "_updated_by": agent_id,
            "_updated_at": now,
        }
        self.stores.branches.update(
            lambda m: m.set(key, payload, agent_id),
            change_info={"agent": agent_id},
        )
        return payload

    def record_commit(self, agent_id: str, branch: str, files: List[str], diff_summary: str, commit_hash: Optional[str] = None, repo_id: str = "main") -> dict:
        now = time.time()
        self.ensure_branch(agent_id, branch, repo_id=repo_id)
        commit_hash = commit_hash or f"meta_{uuid.uuid4().hex[:12]}"
        commit = {
            "id": commit_hash,
            "repo_id": repo_id,
            "branch": branch,
            "author": agent_id,
            "files": files or [],
            "diff_summary": diff_summary,
            "created_at": now,
            "_updated_by": agent_id,
            "_updated_at": now,
        }
        self.stores.commits.update(
            lambda m: m.set(commit_hash, commit, agent_id),
            change_info={"agent": agent_id},
        )
        branch_key = f"{repo_id}:{branch}"
        branch_doc = self.stores.branches.get(branch_key) or self.ensure_branch(agent_id, branch, repo_id=repo_id)
        branch_doc["head"] = commit_hash
        branch_doc.setdefault("commits", []).append(commit_hash)
        self.stores.branches.update(
            lambda m: m.set(branch_key, branch_doc, agent_id),
            change_info={"agent": agent_id},
        )
        self._emit("commit_recorded", commit, recipients=[])
        return commit

    def open_pull_request(
        self,
        branch: str,
        target: str = "main",
        reviewers: Optional[List[str]] = None,
        linked_tasks: Optional[List[str]] = None,
        linked_apis: Optional[List[str]] = None,
        linked_pages: Optional[List[str]] = None,
        linked_consumers: Optional[List[str]] = None,
        title: str = "",
        author: str = "",
        repo_id: str = "main",
        checks_authorized: Optional[List[str]] = None,
    ) -> dict:
        reviewers = list(reviewers or [])
        linked_tasks = list(linked_tasks or [])
        linked_apis = list(linked_apis or [])
        linked_pages = list(linked_pages or [])
        linked_consumers = list(linked_consumers or [])
        # Phase 4.6.1 data-model plumbing: per-PR allowlist of agents
        # permitted to call record_check. Mirrors the `reviewers`
        # plumbing pattern. When unset OR empty, the record_check gate
        # falls back to the PR's reviewers ∪ {orchestrator}. When set,
        # adds those agents to the admit set without removing the
        # reviewer/orchestrator fallback.
        checks_authorized = list(checks_authorized or [])

        # Gate 1: at least one linked task required
        if not linked_tasks:
            return {
                "error": "linked_tasks_required",
                "hint": "Every PR must reference at least one WorkHub task. "
                        "Create one with workhub_create_task or link an existing one.",
            }

        # Gate 2: orchestrator auto-injection (unless author is orchestrator)
        if author != "orchestrator" and "orchestrator" not in reviewers:
            reviewers.append("orchestrator")

        # Gate 3: at least 2 distinct reviewers (excluding author)
        distinct = [r for r in reviewers if r != author]
        if len(distinct) < 2:
            return {
                "error": "insufficient_reviewers",
                "current": distinct,
                "required": 2,
                "hint": "Call codehub_suggest_reviewers(branch, linked_apis, ...) for candidates.",
            }

        # Gate 4: every linked_api must exist in RegistryHub
        registryhub = getattr(self, "_registryhub", None)
        if linked_apis and registryhub is not None:
            known = set(registryhub.get_endpoints().keys())
            unknown = [a for a in linked_apis if a not in known]
            if unknown:
                return {
                    "error": "linked_apis_unknown",
                    "unknown": unknown,
                    "hint": "Register the endpoint first via registryhub_register_endpoint.",
                }

        # Gate 5: every linked_task must exist in WorkHub
        workhub = getattr(self, "_workhub", None)
        if workhub is not None:
            unknown_tasks = [t for t in linked_tasks if workhub.get_task(t) is None]
            if unknown_tasks:
                return {
                    "error": "linked_tasks_unknown",
                    "unknown": unknown_tasks,
                    "hint": "Create the WorkHub task first via workhub_create_task.",
                }

        # Gate 6: every linked_page must exist in WorkHub
        if linked_pages and workhub is not None:
            unknown_pages = [
                p for p in linked_pages
                if workhub.get_page(p, with_blocks=False) is None
            ]
            if unknown_pages:
                return {
                    "error": "linked_pages_unknown",
                    "unknown": unknown_pages,
                    "hint": "Create the WorkHub page first via workhub_create_page.",
                }

        # Gate 7: every linked_consumer must exist in RegistryHub consumers
        if linked_consumers and registryhub is not None:
            consumer_keys = set(registryhub._consumers.value().keys())
            unknown_consumers = [c for c in linked_consumers if c not in consumer_keys]
            if unknown_consumers:
                return {
                    "error": "linked_consumers_unknown",
                    "unknown": unknown_consumers,
                    "hint": "Register the API consumer first via registryhub_register_consumer.",
                }

        # All gates passed — proceed with PR creation
        actor = author or "codehub"
        now = time.time()
        pr_id = f"pr_{uuid.uuid4().hex[:10]}"

        # Validate branch exists in real git (only when repo_root has a .git dir)
        git_dir = self.repo_root / ".git"
        if git_dir.is_dir():
            if not self.git.branch_exists(branch):
                return {"error": f"Branch does not exist: {branch}"}
            # Determine the real head SHA: prefer worktree cwd, fall back to rev-parse
            wt_path = self.repo_root / "worktrees" / branch.replace("agent/", "", 1) if branch.startswith("agent/") else None
            try:
                if wt_path and wt_path.is_dir():
                    head = self.git.current_head(cwd=wt_path)
                else:
                    head = self.git.rev_parse_branch(branch)
            except Exception:
                branch_doc = self.stores.branches.value().get(f"{repo_id}:{branch}") or {}
                head = branch_doc.get("head")
        else:
            # No real git repo — fall back to stored metadata
            branch_doc = self.stores.branches.value().get(f"{repo_id}:{branch}") or {}
            head = branch_doc.get("head")

        pr = {
            "id": pr_id,
            "repo_id": repo_id,
            "title": title or f"Merge {branch} into {target}",
            "source_branch": branch,
            "target_branch": target,
            "author": author,
            "status": "open",
            "reviewers": reviewers,
            "checks_authorized": checks_authorized,  # Phase 4.6.1
            "linked_tasks": linked_tasks,
            "linked_apis": linked_apis,
            "linked_pages": linked_pages,
            "linked_consumers": linked_consumers,
            "head": head,
            "checks": [],
            "reviews": [],
            "merge_state": "blocked" if reviewers else "ready",
            "created_at": now,
            "_updated_by": author,
            "_updated_at": now,
        }
        self.stores.pull_requests.update(
            lambda m: m.set(pr_id, pr, actor),
            change_info={"agent": actor},
        )
        self._emit("pull_request_opened", pr, recipients=reviewers, priority="high")
        return pr

    def request_review(self, pr_id: str, reviewers: List[str], paths: Optional[List[str]] = None, reason: str = "") -> dict:
        pr = self.stores.pull_requests.get(pr_id)
        if not pr:
            return {"error": f"PR not found: {pr_id}"}
        pr["reviewers"] = sorted(set([*pr.get("reviewers", []), *(reviewers or [])]))
        pr["merge_state"] = "blocked"
        self.stores.pull_requests.update(
            lambda m: m.set(pr_id, pr, "codehub"),
            change_info={"agent": "codehub"},
        )
        payload = {"pr_id": pr_id, "paths": paths or [], "reason": reason}
        self._emit("review_requested", payload, recipients=reviewers or [], priority="high")
        return pr

    def submit_review(
        self,
        pr_id: str,
        reviewer: str,
        state: str,
        comments: Optional[List[dict]] = None,
        inline_comments: Optional[List[dict]] = None,
        considered_alternatives: Optional[List[str]] = None,
    ) -> dict:
        pr = self.stores.pull_requests.get(pr_id)
        if not pr:
            return {"error": f"PR not found: {pr_id}"}
        # PR-LIFECYCLE-ALLOWLIST (inline dict-return shape matching
        # merge_pull_request / resolve_conflict): caller must be the
        # orchestrator OR one of the reviewers requested on this PR
        # via open_pull_request(reviewers=...) or request_review(...).
        # Empty/unset reviewer falls through (system/HTTP shim paths).
        allowed = {"orchestrator"} | set(pr.get("reviewers") or [])
        if reviewer and reviewer not in allowed:
            return {
                "error": "submit_review_role_denied",
                "hint": (
                    "Only the orchestrator or a reviewer requested on "
                    "this PR may submit a review. Add the reviewer "
                    "either by including them in the open-PR reviewers "
                    "list (codehub_open_pr reviewers=[...]) or by "
                    "calling codehub.request_review on the PR."
                ),
                "reviewer": reviewer,
                "allowed": sorted(allowed),
            }
        # Cutover 13: substantive-approve gate
        if state == "approve":
            if not inline_comments:
                return {"error": "approve requires at least one entry in inline_comments citing a diff line"}
            alts_check = [a for a in (considered_alternatives or [])
                          if isinstance(a, str) and a.strip()]
            if not alts_check:
                return {"error": "approve requires at least one non-empty considered_alternatives entry"}
        now = time.time()
        review_id = f"review_{uuid.uuid4().hex[:10]}"
        normalized_inline: List[dict] = []
        for raw in inline_comments or []:
            if not isinstance(raw, dict):
                return {"error": "inline_comments items must be dicts"}
            file_path = raw.get("file")
            line = raw.get("line")
            body = raw.get("body")
            if not file_path or not body or not isinstance(line, int) or line < 1:
                return {
                    "error": "inline comment requires non-empty `file`, `body`, and positive int `line`",
                    "offending": raw,
                }
            normalized_inline.append({
                "id": f"ic_{uuid.uuid4().hex[:10]}",
                "review_id": review_id,
                "file": file_path,
                "line": line,
                "body": body,
                "agent": reviewer,
                "created_at": now,
            })
        review = {
            "id": review_id,
            "pr_id": pr_id,
            "reviewer": reviewer,
            "state": state,
            "comments": comments or [],
            "inline_comments": normalized_inline,
            "considered_alternatives": [a for a in (considered_alternatives or [])
                                        if isinstance(a, str) and a.strip()],
            "submitted_at": now,
            "_updated_by": reviewer,
            "_updated_at": now,
        }
        self.stores.code_reviews.update(
            lambda m: m.set(review_id, review, reviewer),
            change_info={"agent": reviewer},
        )
        pr.setdefault("reviews", []).append(review_id)
        if state == "request_changes":
            pr["merge_state"] = "changes_requested"
        elif self._is_pr_approved(pr, extra_review=review):
            pr["merge_state"] = "ready"
        self.stores.pull_requests.update(
            lambda m: m.set(pr_id, pr, reviewer),
            change_info={"agent": reviewer},
        )
        self._emit("review_submitted", review, recipients=[pr.get("author")] if pr.get("author") else [])
        return review

    def list_inline_comments(self, pr_id: str, file: Optional[str] = None) -> List[dict]:
        """Return all inline comments on a PR, optionally filtered by file path."""
        out: List[dict] = []
        for review in self.stores.code_reviews.value().values():
            if review.get("pr_id") != pr_id:
                continue
            for ic in review.get("inline_comments") or []:
                if file is not None and ic.get("file") != file:
                    continue
                out.append(ic)
        out.sort(key=lambda c: (c.get("file", ""), c.get("line", 0), c.get("created_at", 0)))
        return out

    @staticmethod
    def _is_review_substantive(review: dict) -> bool:
        """Cutover 13: an approve-state review must have at least one inline comment AND
        at least one non-empty considered_alternatives entry to count as substantive."""
        if (review or {}).get("state") != "approve":
            return True  # only approve reviews need to be substantive
        if not (review.get("inline_comments") or []):
            return False
        alts = [a for a in (review.get("considered_alternatives") or [])
                if isinstance(a, str) and a.strip()]
        return bool(alts)

    def _is_pr_approved(self, pr: dict, extra_review: dict | None = None) -> bool:
        reviews = [r for r in self.stores.code_reviews.value().values()
                   if r.get("pr_id") == pr.get("id")]
        if extra_review:
            reviews.append(extra_review)
        approved = {r.get("reviewer") for r in reviews
                    if r.get("state") == "approve" and self._is_review_substantive(r)}
        required = set(pr.get("reviewers") or [])
        # Strict: ALL required reviewers must approve, not just one
        return required.issubset(approved)

    def record_check(self, pr_id: str, name: str, status: str, evidence: dict = None, agent: str = "verifier") -> dict:
        # Authorship gate: record_check admits only agents in the PR's
        # allowlist (orchestrator ∪ pr.checks_authorized ∪ pr.reviewers).
        # Empty actor falls through (back-compat for un-threaded
        # callsites). When the PR doesn't exist, record_check still runs
        # (orphan-check back-compat). PR-lifecycle family inline
        # dict-return shape (NOT a raise).
        normalized_actor = (agent or "").strip().lower()
        if normalized_actor:
            pr = self.stores.pull_requests.get(pr_id)
            if pr:
                allowed = (
                    {"orchestrator"}
                    | {a.strip().lower() for a in (pr.get("checks_authorized") or [])}
                    | {a.strip().lower() for a in (pr.get("reviewers") or [])}
                )
                if normalized_actor not in allowed:
                    return {
                        "error": "record_check_role_denied",
                        "method": "codehub.record_check",
                        "pr_id": pr_id,
                        "actor": agent,
                        "allowed": sorted(allowed),
                        "hint": (
                            f"caller {agent!r} is not in this PR's "
                            f"checks_authorized allowlist. Options: "
                            f"(a) add {agent!r} to checks_authorized at "
                            f"open_pull_request time, (b) add to the "
                            f"PR's reviewers, (c) call as orchestrator. "
                            f"Empty-actor calls (system/test paths) "
                            f"fall through via empty-actor convention."
                        ),
                    }
        now = time.time()
        check_id = f"check_{pr_id}_{name}"
        check = {"id": check_id, "pr_id": pr_id, "name": name, "status": status, "evidence": evidence or {}, "updated_at": now}
        self.stores.checks.update(
            lambda m: m.set(check_id, check, agent),
            change_info={"agent": agent},
        )
        pr = self.stores.pull_requests.get(pr_id)
        if pr:
            pr["checks"] = sorted(set([*pr.get("checks", []), check_id]))
            self.stores.pull_requests.update(
                lambda m: m.set(pr_id, pr, agent),
                change_info={"agent": agent},
            )
        return check

    def _run_premerge_verifier_gate(self, pr: dict) -> dict:
        """L2 merge-time verifier gate: contract tests + linked task completion.

        Bypassed when force_merged=True (orchestrator force-merge path).
        """
        if pr.get("force_merged"):
            return {"passed": True, "failed_checks": []}

        failed: list = []
        registryhub = getattr(self, "_registryhub", None)
        workhub = getattr(self, "_workhub", None)

        # Check 1: every linked_api must have a recent passing contract test
        if registryhub is not None:
            for endpoint_id in pr.get("linked_apis") or []:
                tests = registryhub.get_contract_test_results(endpoint_id)
                if not tests:
                    failed.append({"kind": "contract_test_missing",
                                   "endpoint": endpoint_id})
                    continue
                latest = max(tests, key=lambda t: t.get("created_at", 0))
                if not latest.get("result", {}).get("passed"):
                    failed.append({"kind": "contract_test_failed",
                                   "endpoint": endpoint_id,
                                   "evidence": latest.get("evidence")})

        # Check 2: every linked_task must be completed
        if workhub is not None:
            for task_id in pr.get("linked_tasks") or []:
                task = workhub.get_task(task_id)
                if not task:
                    failed.append({"kind": "linked_task_missing",
                                   "task_id": task_id})
                elif task.get("status") != "completed":
                    failed.append({"kind": "linked_task_incomplete",
                                   "task_id": task_id,
                                   "status": task.get("status")})

        return {"passed": not failed, "failed_checks": failed}

    def merge_pull_request(self, pr_id: str, strategy: str = "squash", agent: str = "codehub") -> dict:
        pr = self.stores.pull_requests.get(pr_id)
        if not pr:
            return {"error": f"PR not found: {pr_id}"}
        if pr.get("merge_state") != "ready":
            return {"error": "PR is not ready to merge", "merge_state": pr.get("merge_state")}

        # Role-gate (Phase 2 Fix C / Reviewer 2 HIGH). Mirrors
        # ``force_merge_pull_request`` and ``resolve_conflict``: the
        # orchestrator is always allowed; otherwise the caller must be the
        # PR's own author or assignee. Without this gate, the default
        # ``agent="codehub"`` and the runtime's ``agent=self._agent_id``
        # plumbing let any agent merge ANY PR — bypassing review /
        # ownership and short-circuiting the reason that
        # ``force_merge_pull_request`` is orchestrator-only in the first
        # place. ``merge_pull_request`` is the integration point; the L2
        # premerge verifier gate guards content, this gate guards *who*
        # may push the button.
        allowed = {"orchestrator"}
        pr_author = pr.get("author")
        pr_assignee = pr.get("assignee")
        if pr_author:
            allowed.add(pr_author)
        if pr_assignee:
            allowed.add(pr_assignee)
        if agent not in allowed:
            return {
                "error": "merge_pr_role_denied",
                "hint": (
                    "Only the orchestrator or the PR's author/assignee may "
                    "merge a pull request."
                ),
                "agent": agent,
                "allowed": sorted(allowed),
            }

        # L2 verifier gate
        gate = self._run_premerge_verifier_gate(pr)
        if not gate["passed"]:
            now = time.time()
            updated = dict(pr)
            updated["status"] = "premerge_failed"
            updated["premerge_failures"] = gate["failed_checks"]
            updated["_updated_by"] = agent
            updated["_updated_at"] = now
            self.stores.pull_requests.update(
                lambda m: m.set(pr_id, updated, agent),
                change_info={"agent": agent},
            )
            # Auto-create fix task in WorkHub for PR author
            workhub = getattr(self, "_workhub", None)
            if workhub is not None:
                try:
                    workhub.create_task(
                        title=f"Pre-merge verifier failed for PR {pr_id}",
                        description=f"Failures: {gate['failed_checks']}",
                        assignee=pr.get("author"),
                        agent=agent,
                        source="codehub_premerge_gate",
                        linked_pr=pr_id,
                        priority="P0",
                    )
                except Exception:
                    pass
            self._emit("premerge_failed",
                       {"pr_id": pr_id, "failed_checks": gate["failed_checks"]},
                       recipients=[pr.get("author")] if pr.get("author") else [],
                       priority="urgent")
            return {"error": "premerge_gate_failed",
                    "failed_checks": gate["failed_checks"]}

        git_dir = self.repo_root / ".git"
        if not git_dir.is_dir():
            # No real git repo — graceful metadata-only merge
            log.warning(
                "CodeHub.merge_pull_request: no .git dir at %s; falling back to metadata-only merge",
                self.repo_root,
            )
            now = time.time()
            pr["status"] = "merged"
            pr["merged_at"] = now
            pr["merged_by"] = agent
            pr["merge_strategy"] = strategy
            pr["merge_mode"] = "metadata_only"
            self.stores.pull_requests.update(
                lambda m: m.set(pr_id, pr, agent),
                change_info={"agent": agent},
            )
            repo = self.stores.repos.get(pr.get("repo_id", "main")) or {"id": pr.get("repo_id", "main"), "main_branch": "main"}
            repo["main_head"] = pr.get("head")
            repo["updated_at"] = now
            self.stores.repos.update(
                lambda m: m.set(repo["id"], repo, agent),
                change_info={"agent": agent},
            )
            self._emit("pull_request_merged", pr, recipients=[pr.get("author")] if pr.get("author") else [])
            return pr

        source = pr.get("source_branch", "")
        target = pr.get("target_branch", "main")

        # Checkout target branch in main worktree
        try:
            self.git.checkout(target)
        except Exception as exc:
            return {"error": f"Failed to checkout target branch '{target}': {exc}"}

        # Run the merge
        if strategy == "squash":
            merge_cmd = ["merge", "--squash", source]
            result = self.git._run(*merge_cmd, check=False)
            if result.returncode != 0:
                # Collect conflict files
                conflict_files: List[str] = []
                for line in result.stdout.splitlines():
                    if "CONFLICT" in line:
                        parts = line.split(":")
                        if len(parts) > 1:
                            conflict_files.append(parts[-1].strip())
                if not conflict_files:
                    # Try git status --porcelain to find conflicts
                    st = self.git._run("diff", "--name-only", "--diff-filter=U", check=False)
                    conflict_files = [f.strip() for f in st.stdout.splitlines() if f.strip()]
                return self._handle_merge_conflict(pr_id, pr, conflict_files, agent)
            # For squash: create a real commit
            merge_msg = f"Squash merge '{source}' into '{target}' [pr: {pr_id}]"
            try:
                self.git.commit(merge_msg)
            except Exception:
                # Nothing to commit (empty squash) is ok
                pass
        else:
            # no-ff merge
            merge_result = self.git.merge(source)
            if not merge_result.success:
                return self._handle_merge_conflict(pr_id, pr, merge_result.conflicts, agent)

        head = self.git.current_head()
        now = time.time()
        pr["status"] = "merged"
        pr["merged_at"] = now
        pr["merged_by"] = agent
        pr["merge_strategy"] = strategy
        pr["merge_mode"] = "real_git"
        pr["conflict_files"] = []
        self.stores.pull_requests.update(
            lambda m: m.set(pr_id, pr, agent),
            change_info={"agent": agent},
        )
        repo = self.stores.repos.get(pr.get("repo_id", "main")) or {"id": pr.get("repo_id", "main"), "main_branch": "main"}
        repo["main_head"] = head
        repo["updated_at"] = now
        self.stores.repos.update(
            lambda m: m.set(repo["id"], repo, agent),
            change_info={"agent": agent},
        )
        self._emit("pull_request_merged", pr, recipients=[pr.get("author")] if pr.get("author") else [])
        return pr

    def force_merge_pull_request(self, pr_id: str, reason: str, agent: str) -> dict:
        """Orchestrator-only bypass of the premerge verifier gate with audit trail."""
        if agent != "orchestrator":
            return {"error": "force_merge_orchestrator_only",
                    "hint": "Only orchestrator can bypass the verifier gate."}
        if not reason or len(reason) < 20:
            return {"error": "force_merge_reason_too_short",
                    "min_length": 20,
                    "hint": "Provide a substantive reason (>= 20 chars) for audit."}
        pr = self.stores.pull_requests.get(pr_id)
        if not pr:
            return {"error": f"PR not found: {pr_id}"}
        now = time.time()
        forced = dict(pr)
        forced["merge_state"] = "ready"
        forced["force_merged"] = True
        forced["force_reason"] = reason
        forced["force_by"] = agent
        forced["forced_at"] = now
        forced["_updated_by"] = agent
        forced["_updated_at"] = now
        self.stores.pull_requests.update(
            lambda m: m.set(pr_id, forced, agent),
            change_info={"agent": agent},
        )
        self._emit("pr_force_merged",
                   {"pr_id": pr_id, "reason": reason, "agent": agent},
                   recipients=["orchestrator"], priority="urgent")
        return self.merge_pull_request(pr_id, strategy="squash", agent=agent)

    def _handle_merge_conflict(self, pr_id: str, pr: dict, conflict_files: List[str], agent: str) -> dict:
        """Update PR to conflict state and auto-create a WorkHub resolution task."""
        # Abort / reset to leave the repo clean.
        # 'merge --abort' only works when MERGE_HEAD exists (i.e. non-squash).
        # 'reset --merge' works for squash conflicts too.
        self.git._run("merge", "--abort", check=False)
        self.git._run("reset", "--merge", check=False)
        self.git._run("checkout", pr.get("target_branch", "main"), check=False)

        now = time.time()
        pr["status"] = "conflict"
        pr["conflict_files"] = conflict_files
        pr["conflict_detected_at"] = now
        self.stores.pull_requests.update(
            lambda m: m.set(pr_id, pr, agent),
            change_info={"agent": agent},
        )

        self._emit(
            "pull_request_conflict",
            {"pr_id": pr_id, "conflict_files": conflict_files, "author": pr.get("author")},
            recipients=[pr.get("author")] if pr.get("author") else [],
            priority="urgent",
        )

        # Auto-create a WorkHub resolution task
        workhub = getattr(self, "_workhub", None)
        if workhub is not None:
            try:
                workhub.create_task(
                    title=f"Resolve merge conflict in PR {pr_id}",
                    description=(
                        f"PR '{pr.get('title', pr_id)}' has merge conflicts. "
                        f"Conflicting files: {conflict_files}. "
                        f"Source: {pr.get('source_branch')} → {pr.get('target_branch')}."
                    ),
                    assignee=pr.get("author"),
                    agent=agent or "codehub",
                    source="codehub_merge_conflict",
                    pr_id=pr_id,
                    conflict_files=conflict_files,
                    priority="P0",
                )
            except Exception:
                pass

        return pr

    def resolve_conflict(self, pr_id: str, resolution_files: Dict[str, str], agent: str = "codehub") -> dict:
        """
        Resolve a conflicted PR by writing *resolution_files* into the main worktree,
        staging, committing, and marking the PR as merged.

        *resolution_files* maps relative file paths to their resolved contents.

        Phase 0.2 attempt-3 Fix B closes a triple-bypass against the
        write-gate triad (role-gate / path containment / staging filter):

          1. Role-gate: only the orchestrator or the PR's own author /
             assignee may resolve a conflict. Without this, any agent
             (default ``"codehub"``) could ship arbitrary files into the
             target branch via a conflicted PR. Mirrors the gate on
             ``force_merge_pull_request``.
          2. Path containment: every supplied ``rel_path`` is resolved
             against ``repo_root`` and must land inside the repo. Absolute
             paths are rejected outright (defense in depth).
          3. Staging filter: paths are filtered through
             ``_filter_paths_for_staging`` so dotfile paths (e.g.
             ``.gates/...``) cannot be staged / committed via this
             primitive even if the file was written in-repo.
        """
        pr = self.stores.pull_requests.get(pr_id)
        if not pr:
            return {"error": f"PR not found: {pr_id}"}
        if pr.get("status") != "conflict":
            return {"error": "PR is not in conflict state", "status": pr.get("status")}

        # (1) Role-gate. Mirror force_merge_pull_request: orchestrator is
        # always allowed; otherwise the caller must be the PR's author or
        # assignee. Without this, the default ``agent="codehub"`` would
        # let any caller commit arbitrary files into the target branch.
        allowed = {"orchestrator"}
        pr_author = pr.get("author")
        pr_assignee = pr.get("assignee")
        if pr_author:
            allowed.add(pr_author)
        if pr_assignee:
            allowed.add(pr_assignee)
        if agent not in allowed:
            return {
                "error": "resolve_conflict_role_denied",
                "hint": (
                    "Only the orchestrator or the PR's author/assignee may "
                    "resolve a merge conflict."
                ),
                "agent": agent,
                "allowed": sorted(allowed),
            }

        git_dir = self.repo_root / ".git"
        if not git_dir.is_dir():
            return {"error": "No real git repository; cannot resolve conflict"}

        target = pr.get("target_branch", "main")
        try:
            self.git.checkout(target)
        except Exception as exc:
            return {"error": f"Failed to checkout target branch '{target}': {exc}"}

        # (2) Path containment + write. Resolve each path under
        # ``repo_root`` and reject anything that escapes the repo or is
        # supplied as an absolute path. We collect *kept_rel_paths* in
        # the same order the caller supplied so the staging step below
        # can re-filter through the dotfile gate without re-deriving
        # paths.
        repo_root_resolved = self.repo_root.resolve()
        kept_rel_paths: List[str] = []
        for rel_path, content in (resolution_files or {}).items():
            # Reject absolute paths outright (defense in depth — the
            # ``is_relative_to`` check below would also catch most cases,
            # but it would silently *allow* absolute paths that happen to
            # live under ``repo_root``).
            if Path(rel_path).is_absolute():
                return {
                    "error": (
                        "resolve_conflict: absolute paths not allowed "
                        "(got {!r})".format(rel_path)
                    )
                }
            abs_path = (self.repo_root / rel_path).resolve()
            if not abs_path.is_relative_to(repo_root_resolved):
                return {
                    "error": (
                        "resolve_conflict: path '{}' escapes repo_root".format(rel_path)
                    )
                }
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_text(content, encoding="utf-8")
            kept_rel_paths.append(rel_path)

        # (3) Staging filter. Even when a dotfile path is in-repo (e.g.
        # ``.gates/foo.yaml``), ``_filter_paths_for_staging`` will refuse
        # to stage it unless it's in ``ALLOWED_DOTFILES``. This prevents
        # a conflicted-PR squash-merge from shipping ``.gates/`` into the
        # target branch — the exploit Reviewer 2 demonstrated.
        if kept_rel_paths:
            from ....agents.runtime.auto_commit import _filter_paths_for_staging
            kept = _filter_paths_for_staging(list(kept_rel_paths), agent_id=agent)
            dropped = [k for k in kept_rel_paths if k not in kept]
            if dropped:
                log.warning(
                    "resolve_conflict refused dotfile paths for agent %r: %s",
                    agent, dropped,
                )
            if kept:
                self.git.add(*kept)
        else:
            self.git.add(".")

        commit_msg = (
            f"Resolve merge conflict in PR {pr_id} [resolved_by: {agent}]"
        )
        try:
            sha = self.git.commit(commit_msg)
        except Exception as exc:
            return {"error": f"Commit failed: {exc}"}

        now = time.time()
        pr["status"] = "merged"
        pr["merged_at"] = now
        pr["merged_by"] = agent
        pr["merge_mode"] = "conflict_resolved"
        pr["conflict_resolved_by"] = agent
        pr["conflict_resolved_at"] = now
        pr["conflict_files"] = []
        self.stores.pull_requests.update(
            lambda m: m.set(pr_id, pr, agent),
            change_info={"agent": agent},
        )
        self._emit("pull_request_merged", pr, recipients=[pr.get("author")] if pr.get("author") else [])
        return {**pr, "resolution_sha": sha}

    def list_conflicted_prs(self) -> List[dict]:
        """Return all PRs that are in 'conflict' status (need resolution)."""
        return [p for p in self.stores.pull_requests.value().values() if p.get("status") == "conflict"]

    def create_release(self, tag: str, source: str = "main", notes: str = "", agent: str = "codehub") -> dict:
        # Releases are an integrator-only action (the run-render/functional gate is
        # enforced at the tool layer, which can reach RunHub).
        if agent != "orchestrator":
            return {"error": "release_orchestrator_only",
                    "hint": "Only the orchestrator can cut a release."}
        now = time.time()
        # Cut an immutable release branch off *source* so the Preview page can
        # build from exactly this snapshot. Sanitize the tag for use as a ref.
        safe_tag = re.sub(r"[^A-Za-z0-9._-]+", "-", str(tag)).strip("-") or "untagged"
        branch = f"release-v{safe_tag}"
        branch_sha = None
        branch_error = None
        try:
            self.ensure_repo()
            branch_sha = self.git.create_branch_at(branch, start_point=source, force=True)
        except Exception as e:
            branch_error = str(e)
        release = {
            "id": tag,
            "tag": tag,
            "source": source,
            "notes": notes,
            "branch": branch,
            "branch_sha": branch_sha,
            "branch_error": branch_error,
            "created_at": now,
            "_updated_by": agent,
            "_updated_at": now,
        }
        self.stores.releases.update(
            lambda m: m.set(tag, release, agent),
            change_info={"agent": agent},
        )
        self._emit("release_created", release, recipients=[], priority="normal")
        return release

    def commit(self, agent_id: str, message: str, files: Optional[List[str]] = None) -> dict:
        """
        Run a real git add + commit in the agent's worktree.

        Auto-creates the worktree if it is not yet registered.
        Appends ``[agent: <agent_id>]`` trailer to *message*.
        Returns a dict with ``sha`` and the commit metadata.

        Phase 0.2 RE-FIX 5: all staged paths flow through the auto-stage
        path filter. When ``files`` is provided, each entry is checked
        against ``_should_stage_path``; rejected entries are dropped
        with a warning. When ``files`` is omitted (legacy ``git add .``
        callers), we enumerate worktree changes via
        ``git status --porcelain`` and stage the filtered subset
        explicitly — never letting a raw ``.`` reach ``git add``, which
        would silently include agent-authored dotfiles like
        ``.gates/allowed_code_checks.yaml``.
        """
        wt_path = self.repo_root / "worktrees" / agent_id
        if not wt_path.exists():
            wt_path = self.register_agent_worktree(agent_id)

        from .git_ops import GitOps
        from ....agents.runtime.auto_commit import (
            _filter_paths_for_staging,
            _should_stage_path,
        )
        wt_git = GitOps(wt_path)

        if files:
            kept = _filter_paths_for_staging(list(files), agent_id=agent_id)
            if kept:
                wt_git.add(*kept)
            dropped = [f for f in files if f not in kept]
            if dropped:
                log.warning(
                    "codehub.commit refused dotfile paths for agent %s: %s",
                    agent_id, dropped,
                )
        else:
            # Enumerate worktree changes and filter, rather than running
            # ``git add .`` which would happily stage agent-authored
            # dotfiles.
            try:
                status_res = wt_git._run("status", "--porcelain", "-z")
                status_out = status_res.stdout if status_res else ""
            except Exception:
                status_out = ""
            candidates: List[str] = []
            if status_out:
                # ``-z`` separates records with NUL; each record is
                # ``XY <path>``. Rename records encode two paths
                # (``XY <new>\0<old>``) — we only need to stage the
                # current path.
                tokens = status_out.split("\x00")
                i = 0
                while i < len(tokens):
                    rec = tokens[i]
                    i += 1
                    if not rec:
                        continue
                    # rec like "?? .gates/foo.yaml" or " M app/foo.py"
                    if len(rec) < 4:
                        continue
                    xy, path = rec[:2], rec[3:]
                    candidates.append(path)
                    # Skip the "old name" token on renames.
                    if xy[0] in ("R", "C"):
                        i += 1
            kept = _filter_paths_for_staging(candidates, agent_id=agent_id)
            dropped = [p for p in candidates if p not in kept]
            if dropped:
                log.warning(
                    "codehub.commit refused dotfile paths for agent %s: %s",
                    agent_id, dropped,
                )
            if kept:
                # ``-A`` so deletions get staged too; explicit paths
                # mean we never accidentally stage outside ``kept``.
                wt_git._run("add", "-A", "--", *kept)

        # Nothing-to-commit is NOT an error (smoke #6, 2026-06-06): the frontend's
        # files were already auto-committed/merged, so its post-impl codehub_commit
        # had an empty index — git commit raised, the tool reported failure, and
        # the LLM looped on codehub_commit forever. Treat an empty index as an
        # idempotent no-op success so the lane moves on instead of spinning.
        staged = wt_git._run("diff", "--cached", "--quiet", check=False)
        if staged is not None and getattr(staged, "returncode", 1) == 0:
            return {
                "sha": None,
                "committed": False,
                "note": "nothing to commit (work already committed)",
                "branch": f"agent/{agent_id}",
            }

        full_message = f"{message}\n\n[agent: {agent_id}]"
        sha = wt_git.commit(full_message)

        branch = f"agent/{agent_id}"
        meta = self.record_commit(agent_id, branch, files or [], message, commit_hash=sha)
        return {"sha": sha, **meta}

    def get_diff(self, pr_id: str, max_lines: int = 5000) -> dict:
        """
        Return the unified diff for a PR (head vs target branch).

        Truncates to *max_lines* lines with a marker when exceeded.
        """
        pr = self.stores.pull_requests.get(pr_id)
        if not pr:
            return {"error": f"PR not found: {pr_id}"}
        head = pr.get("head")
        if not head:
            return {"error": "PR has no head commit recorded"}
        target = pr.get("target_branch", "main")
        try:
            raw = self.git.diff(target, head)
        except Exception as exc:
            return {"error": str(exc)}
        lines = raw.splitlines()
        truncated = False
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            truncated = True
        result = {"diff": "\n".join(lines), "pr_id": pr_id, "head": head, "target": target}
        if truncated:
            result["truncated"] = True
            result["truncation_marker"] = f"[diff truncated at {max_lines} lines]"
        return result

    def get_blob(self, commit_hash: str, path: str) -> str:
        """Return file content at *commit_hash*."""
        return self.git.show(commit_hash, path)

    def get_file_content(self, pr_id: str, path: str) -> dict:
        """Return file content from the PR head commit."""
        pr = self.stores.pull_requests.get(pr_id)
        if not pr:
            return {"error": f"PR not found: {pr_id}"}
        head = pr.get("head")
        if not head:
            return {"error": "PR has no head commit recorded"}
        try:
            return {"content": self.git.show(head, path), "commit": head}
        except Exception as exc:
            return {"error": str(exc)}

    def list_prs(
        self,
        status: Optional[str] = None,
        author: Optional[str] = None,
        reviewer: Optional[str] = None,
    ) -> List[dict]:
        """Return PRs filtered by optional status, author, or reviewer."""
        prs = list(self.stores.pull_requests.value().values())
        if status is not None:
            prs = [p for p in prs if p.get("status") == status]
        if author is not None:
            prs = [p for p in prs if p.get("author") == author]
        if reviewer is not None:
            prs = [p for p in prs if reviewer in p.get("reviewers", [])]
        return prs

    def list_checks(self, pr_id: Optional[str] = None, name: Optional[str] = None) -> List[dict]:
        """Return checks filtered by optional pr_id or name."""
        checks = list(self.stores.checks.value().values())
        if pr_id is not None:
            checks = [c for c in checks if c.get("pr_id") == pr_id]
        if name is not None:
            checks = [c for c in checks if c.get("name") == name]
        return checks

    def get_check_summary(self, pr_id: str) -> dict:
        """Return counts of checks by status for *pr_id*."""
        checks = self.list_checks(pr_id=pr_id)
        summary: Dict[str, int] = {}
        for c in checks:
            s = c.get("status", "unknown")
            summary[s] = summary.get(s, 0) + 1
        return {"pr_id": pr_id, "total": len(checks), "by_status": summary}

    def get_versions(self) -> Dict[str, int]:
        return self.stores.versions()

    def suggest_reviewers(self, branch: str, linked_apis: list = None,
                          linked_tasks: list = None, author: str = "",
                          k: int = 3) -> list:
        """Weighted reviewer picker. Returns top-k {agent, score, reasons}."""
        candidates: dict = {}
        reasons_map: dict = {}

        def add(agent: str, weight: float, reason: str):
            if not agent or agent == author:
                return
            candidates[agent] = candidates.get(agent, 0.0) + weight
            reasons_map.setdefault(agent, []).append(reason)

        # Signal 1: API consumers (weight 3.0 each)
        if linked_apis and getattr(self, "_registryhub", None) is not None:
            for endpoint_id in linked_apis:
                for c in self._registryhub.get_consumers(endpoint_id):
                    add(c.get("agent"), 3.0, f"consumer of {endpoint_id}")

        # Signal 2: recent committer trailer (weight 1.0 each)
        try:
            entries = self.git.log_for_branch("main", max_count=20)
            for entry in entries:
                subj = entry.get("subject", "")
                # [agent: name] trailer convention
                if "[agent:" in subj:
                    start = subj.index("[agent:") + len("[agent:")
                    end = subj.index("]", start)
                    trailer = subj[start:end].strip()
                    add(trailer, 1.0, "recent committer on main")
        except Exception:
            pass

        # Signal 3: plan attendees (weight 0.5)
        if linked_tasks and getattr(self, "_workhub", None) is not None:
            for task_id in linked_tasks:
                task = self._workhub.get_task(task_id)
                if not task or not task.get("plan_id"):
                    continue
                for att in (self._workhub.snapshot().get("attendees", {}) or {}).values():
                    add(att.get("agent_id") or att.get("agent"), 0.5,
                        f"attendee of plan related to {task_id}")

        # Mandatory: orchestrator (unless author IS orchestrator)
        if author != "orchestrator":
            candidates["orchestrator"] = candidates.get("orchestrator", 0.0) + 100.0
            reasons_map.setdefault("orchestrator", []).append("mandatory lead reviewer")

        ranked = sorted(candidates.items(), key=lambda x: -x[1])
        return [{"agent": a, "score": s, "reasons": reasons_map.get(a, [])}
                for a, s in ranked[:k]]

    def get_branch_status(self, agent_id: str) -> dict:
        """Wraps git status + rev-list for the agent's worktree."""
        wt_path = self.repo_root / "worktrees" / agent_id
        if not wt_path.exists() or not (self.repo_root / ".git").exists():
            return {"clean": True, "dirty_files": [],
                    "commits_ahead_of_main": 0, "unpushed_commits": 0}
        try:
            status_proc = self.git._run("status", "--porcelain", cwd=wt_path)
            status_out = status_proc.stdout if hasattr(status_proc, "stdout") else str(status_proc)
            dirty_files = []
            for line in (status_out or "").splitlines():
                # Each line is "XY <path>"; we strip the 3-char prefix.
                if len(line) > 3:
                    dirty_files.append(line[3:].strip())
            # Try common default-branch names: main, then master.
            ahead = 0
            for base in ("main", "master"):
                ahead_proc = self.git._run(
                    "rev-list", "--count", f"{base}..HEAD", cwd=wt_path, check=False
                )
                ahead_str = (ahead_proc.stdout if hasattr(ahead_proc, "stdout") else str(ahead_proc)).strip()
                if ahead_str and ahead_proc.returncode == 0:
                    try:
                        ahead = int(ahead_str)
                    except ValueError:
                        ahead = 0
                    break
            return {
                "clean": not dirty_files,
                "dirty_files": dirty_files,
                "commits_ahead_of_main": ahead,
                "unpushed_commits": ahead,
            }
        except Exception:
            return {"clean": True, "dirty_files": [],
                    "commits_ahead_of_main": 0, "unpushed_commits": 0}

    def list_files_changed_on_branch(self, agent_id: str) -> list:
        """Return all files changed on the agent's branch since it
        diverged from main/master.

        Differs from ``get_branch_status().dirty_files`` (uncommitted
        only) — this gives the full picture including committed work.
        Used by hub_pulse's self_audit so it still detects
        "wrote-without-registering" after the agent commits.
        Empty list on any error (defensive).
        """
        wt_path = self.repo_root / "worktrees" / agent_id
        if not wt_path.exists() or not (self.repo_root / ".git").exists():
            return []
        try:
            for base in ("main", "master"):
                proc = self.git._run(
                    "diff", "--name-only", f"{base}...HEAD",
                    cwd=wt_path, check=False,
                )
                out = (proc.stdout if hasattr(proc, "stdout") else str(proc))
                if proc.returncode != 0:
                    continue
                return [ln.strip() for ln in (out or "").splitlines() if ln.strip()]
        except Exception:
            return []
        return []

    def list_prs_needing_review(self, reviewer: str) -> list:
        """PRs where `reviewer` is in pr.reviewers and has not yet submitted a decision."""
        out = []
        reviews = list(self.stores.code_reviews.value().values())
        for pr in self.stores.pull_requests.value().values():
            if pr.get("status") not in (None, "open"):
                continue
            if reviewer not in (pr.get("reviewers") or []):
                continue
            decided = any(
                r.get("reviewer") == reviewer and r.get("pr_id") == pr.get("id")
                for r in reviews
            )
            if decided:
                continue
            out.append(pr)
        return out

    def get_pending_reviews_for(self, agent_id: str, since_steps: int = 0) -> list:
        """Same as list_prs_needing_review but returns lightweight {pr_id, author, files_changed_count, step_age} entries."""
        prs = self.list_prs_needing_review(agent_id)
        result = []
        for pr in prs:
            result.append({
                "pr_id": pr.get("id"),
                "author": pr.get("author"),
                "files_changed_count": len((pr.get("files_changed") or [])),
                "step_age": since_steps,
            })
        return result

    def get_my_branch_loose_ends(self, agent_id: str) -> dict:
        """Compact dict for hub_commit_gate. {dirty, ahead, has_open_pr, conflict_prs}."""
        status = self.get_branch_status(agent_id)
        branch = f"agent/{agent_id}"
        my_open_prs = [
            pr for pr in self.stores.pull_requests.value().values()
            if pr.get("author") == agent_id
            and pr.get("status") in (None, "open")
            and pr.get("source_branch") == branch
        ]
        conflict_prs = [
            pr.get("id") for pr in self.stores.pull_requests.value().values()
            if pr.get("author") == agent_id and pr.get("status") == "conflict"
        ]
        return {
            "dirty": not status["clean"],
            "ahead": status["commits_ahead_of_main"],
            "has_open_pr": bool(my_open_prs),
            "conflict_prs": conflict_prs,
        }

    def snapshot(self) -> Dict[str, Any]:
        return self.stores.snapshot()
