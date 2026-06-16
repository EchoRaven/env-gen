"""Parallel file-claim and concurrency coordination helpers."""

import asyncio
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple


class ParallelCoordinationSupport:
    @staticmethod
    def _normalize_declared_file_path(raw: Any) -> Optional[str]:
        if not isinstance(raw, str):
            return None
        value = raw.strip().replace("\\", "/")
        if not value:
            return None
        while value.startswith("./"):
            value = value[2:]
        value = re.sub(r"/+", "/", value)
        return value.lower()

    def _extract_declared_files(self, subtask: Dict[str, Any]) -> List[str]:
        files = subtask.get("files") if isinstance(subtask, dict) else None
        if not isinstance(files, list):
            return []
        out: List[str] = []
        seen: Set[str] = set()
        for item in files:
            normalized = self._normalize_declared_file_path(item)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            out.append(normalized)
        return out

    async def _acquire_file_claims(
        self,
        *,
        claim_owner: str,
        files: List[str],
    ) -> Tuple[bool, List[Dict[str, Any]]]:
        if not files:
            return True, []
        now = time.time()
        conflicts: List[Dict[str, Any]] = []
        async with self._file_claim_lock:
            self._active_file_claims = {
                p: meta
                for p, meta in self._active_file_claims.items()
                if (now - float(meta.get("claimed_at", now))) <= self._file_claim_ttl_seconds
            }
            for path in files:
                existing = self._active_file_claims.get(path)
                if existing and existing.get("owner") != claim_owner:
                    conflicts.append(
                        {
                            "file": path,
                            "owner": existing.get("owner"),
                        }
                    )
            if conflicts:
                return False, conflicts
            for path in files:
                self._active_file_claims[path] = {
                    "owner": claim_owner,
                    "claimed_at": now,
                }
        return True, []

    async def _release_file_claims(self, *, claim_owner: str, files: List[str]) -> None:
        if not files:
            return
        async with self._file_claim_lock:
            for path in files:
                existing = self._active_file_claims.get(path)
                if existing and existing.get("owner") == claim_owner:
                    self._active_file_claims.pop(path, None)

    def _preplan_subtask_file_claims(
        self,
        executable_subtasks: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], Dict[int, Dict[str, Any]]]:
        owner_by_file: Dict[str, int] = {}
        blocked_by_index: Dict[int, Dict[str, Any]] = {}
        allowed: List[Dict[str, Any]] = []
        for item in executable_subtasks:
            idx = int(item.get("index"))
            subtask = item.get("subtask") or {}
            files = self._extract_declared_files(subtask)
            conflicts: List[Dict[str, Any]] = []
            for path in files:
                owner_idx = owner_by_file.get(path)
                if owner_idx is not None and owner_idx != idx:
                    conflicts.append({"file": path, "owned_by_subtask_index": owner_idx})
            if conflicts:
                blocked_by_index[idx] = {
                    "reason": "duplicate file ownership in same batch",
                    "conflicts": conflicts,
                }
                continue
            for path in files:
                owner_by_file[path] = idx
            allowed.append(item)
        return allowed, blocked_by_index

    def _estimate_write_conflict_risk(self, subtasks: List[Dict[str, Any]]) -> float:
        if not subtasks:
            return 0.0

        declared = 0
        unknown = 0
        claims: Dict[str, int] = {}
        for st in subtasks:
            files = self._extract_declared_files(st if isinstance(st, dict) else {})
            if not files:
                unknown += 1
                continue
            declared += 1
            for f in files:
                claims[f] = claims.get(f, 0) + 1

        overlap = sum(1 for c in claims.values() if c > 1)
        overlap_ratio = overlap / max(1, len(claims))
        unknown_ratio = unknown / max(1, len(subtasks))
        return min(1.0, overlap_ratio + (0.5 * unknown_ratio))

    @staticmethod
    def _is_read_mostly_workload_type(workload_type: Optional[str]) -> bool:
        normalized = str(workload_type or "").strip().lower()
        if not normalized:
            return False
        read_mostly_tokens = (
            "review",
            "investig",
            "analysis",
            "research",
            "audit",
            "inspect",
            "diagnos",
            "debug",
        )
        return any(token in normalized for token in read_mostly_tokens)

    def _resolve_adaptive_concurrency(
        self,
        subtasks: List[Dict[str, Any]],
        requested_max: int,
        workload_type: Optional[str],
    ) -> int:
        total = max(1, len(subtasks))
        requested = max(1, int(requested_max))
        base = min(requested, total)

        if self._is_read_mostly_workload_type(workload_type):
            return min(base, self._read_mostly_max_parallel)

        risk = self._estimate_write_conflict_risk(subtasks)
        if risk >= 0.6:
            base = min(base, self._write_high_risk_max_parallel)
        if risk >= 0.3:
            base = min(base, self._write_medium_risk_max_parallel)

        failure_rate = self._recent_failure_rate()
        if failure_rate >= self._failure_rate_high_threshold:
            base = min(base, self._failure_rate_high_cap)
        elif failure_rate >= self._failure_rate_medium_threshold:
            base = min(base, self._failure_rate_medium_cap)

        return min(base, self._write_low_risk_max_parallel)
