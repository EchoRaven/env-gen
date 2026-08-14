"""Team practice storage extracted from team_protocols."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from uuid import uuid4

from .models import PracticeType, TeamPractice

class TeamPracticeStore:
    """
    Store and retrieve team practices.
    
    Enables learning from successful team collaborations:
    - Record what worked
    - Query similar practices for new problems
    - Suggest team compositions based on history
    """
    
    def __init__(self, storage_path: Optional[Path] = None):
        self._practices: Dict[str, TeamPractice] = {}
        self._storage_path = storage_path
        self._logger = logging.getLogger("TeamPracticeStore")
        
        # Index by category for fast lookup
        self._by_category: Dict[str, List[str]] = {}
        self._by_type: Dict[PracticeType, List[str]] = {t: [] for t in PracticeType}
        
        # Load existing practices
        if storage_path and storage_path.exists():
            self._load()
    
    def _load(self) -> None:
        """Load practices from storage."""
        if not self._storage_path or not self._storage_path.exists():
            return
        
        try:
            with open(self._storage_path, 'r') as f:
                data = json.load(f)
            
            for p_data in data.get("practices", []):
                practice = TeamPractice.from_dict(p_data)
                self._practices[practice.id] = practice
                self._index_practice(practice)
            
            self._logger.info(f"Loaded {len(self._practices)} team practices")
        except Exception as e:
            self._logger.error(f"Failed to load practices: {e}")
    
    def _save(self) -> None:
        """Save practices to storage."""
        if not self._storage_path:
            return
        
        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            
            data = {
                "practices": [p.to_dict() for p in self._practices.values()],
                "updated_at": datetime.now().isoformat(),
            }
            
            with open(self._storage_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            self._logger.error(f"Failed to save practices: {e}")
    
    def _index_practice(self, practice: TeamPractice) -> None:
        """Index practice for fast lookup."""
        # By category
        if practice.problem_category not in self._by_category:
            self._by_category[practice.problem_category] = []
        self._by_category[practice.problem_category].append(practice.id)
        
        # By type
        self._by_type[practice.practice_type].append(practice.id)
    
    def record_practice(
        self,
        practice_type: PracticeType,
        problem_category: str,
        description: str,
        agents_spawned: List[Dict],
        success: bool,
        outcome_summary: str,
        findings: Optional[List[Dict]] = None,
        context: Optional[Dict] = None,
        duration_seconds: float = 0.0,
        created_by: Optional[str] = None,
    ) -> TeamPractice:
        """
        Record a new team practice.
        
        Call this after a successful team collaboration.
        """
        practice = TeamPractice(
            id=f"practice_{uuid4().hex[:8]}",
            practice_type=practice_type,
            problem_category=problem_category,
            description=description,
            agents_spawned=agents_spawned,
            context=context or {},
            success=success,
            outcome_summary=outcome_summary,
            findings=findings or [],
            duration_seconds=duration_seconds,
            agent_count=len(agents_spawned),
            created_by=created_by,
        )
        
        self._practices[practice.id] = practice
        self._index_practice(practice)
        self._save()
        
        self._logger.info(
            f"Recorded practice {practice.id}: {practice_type.value} "
            f"for {problem_category} (success={success})"
        )
        
        return practice
    
    def get_similar_practices(
        self,
        problem_category: Optional[str] = None,
        practice_type: Optional[PracticeType] = None,
        successful_only: bool = True,
        limit: int = 5,
    ) -> List[TeamPractice]:
        """
        Get similar practices for reference.
        
        Args:
            problem_category: Filter by category (e.g., "api_bug")
            practice_type: Filter by type (e.g., INVESTIGATION)
            successful_only: Only return successful practices
            limit: Max results
            
        Returns:
            List of matching TeamPractice objects
        """
        results = []
        
        # Get candidate IDs
        candidate_ids = set()
        
        if problem_category and problem_category in self._by_category:
            candidate_ids.update(self._by_category[problem_category])
        elif practice_type:
            candidate_ids.update(self._by_type[practice_type])
        else:
            candidate_ids = set(self._practices.keys())
        
        # Filter and sort
        for pid in candidate_ids:
            practice = self._practices.get(pid)
            if not practice:
                continue
            
            if successful_only and not practice.success:
                continue
            
            if practice_type and practice.practice_type != practice_type:
                continue
            
            results.append(practice)
        
        # Sort by reuse count and success
        results.sort(key=lambda p: (p.success, p.reuse_count), reverse=True)
        
        return results[:limit]
    
    def suggest_team_composition(
        self,
        problem_category: str,
        problem_description: str = "",
    ) -> Optional[Dict]:
        """
        Suggest a team composition based on similar past practices.
        
        Returns:
            Dict with suggested agents to spawn, or None if no matches
        """
        # Find successful practices for this category
        practices = self.get_similar_practices(
            problem_category=problem_category,
            successful_only=True,
            limit=3,
        )
        
        if not practices:
            # Try broader search
            practices = self.get_similar_practices(
                successful_only=True,
                limit=5,
            )
        
        if not practices:
            return None
        
        # Use the most reused successful practice
        best = max(practices, key=lambda p: (p.success, p.reuse_count))
        
        # Mark as reused
        best.reuse_count += 1
        self._save()
        
        return {
            "based_on": best.id,
            "original_problem": best.description,
            "suggested_team": best.agents_spawned,
            "expected_outcome": best.outcome_summary,
            "success_rate": f"{sum(1 for p in practices if p.success)}/{len(practices)}",
        }
    
    def mark_practice_reused(self, practice_id: str) -> bool:
        """Mark a practice as reused."""
        if practice_id not in self._practices:
            return False
        
        self._practices[practice_id].reuse_count += 1
        self._save()
        return True
    
    def get_practice(self, practice_id: str) -> Optional[TeamPractice]:
        """Get a practice by ID."""
        return self._practices.get(practice_id)
    
    def list_categories(self) -> List[str]:
        """List all problem categories."""
        return list(self._by_category.keys())
    
    def get_statistics(self) -> Dict:
        """Get statistics about stored practices."""
        total = len(self._practices)
        successful = sum(1 for p in self._practices.values() if p.success)
        
        return {
            "total_practices": total,
            "successful": successful,
            "success_rate": successful / total if total > 0 else 0,
            "categories": list(self._by_category.keys()),
            "by_type": {
                t.value: len(ids) for t, ids in self._by_type.items()
            },
            "most_reused": sorted(
                [p.to_dict() for p in self._practices.values()],
                key=lambda x: x["reuse_count"],
                reverse=True,
            )[:5],
        }
    
    def export_for_knowledge(self) -> List[Dict]:
        """Export all successful practices in knowledge format."""
        return [
            p.to_knowledge_format()
            for p in self._practices.values()
            if p.success
        ]

