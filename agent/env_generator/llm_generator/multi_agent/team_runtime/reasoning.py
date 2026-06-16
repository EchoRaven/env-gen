from __future__ import annotations

"""Parallel reasoning protocol extracted from team_protocols."""

import asyncio
import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import uuid4

from .models import CandidateStatus, ParallelReasoningResult, PracticeType, ReasoningCandidate

if TYPE_CHECKING:
    from .manager import DynamicAgentManager
    from .practices import TeamPracticeStore

class ParallelReasoningProtocol:
    """
    Generic parallel reasoning protocol.

    Multiple spawned workers can analyze different candidate explanations in
    parallel, exchange challenge rounds, and converge on the strongest answer.
    """
    
    def __init__(
        self,
        agent_manager: DynamicAgentManager,
        message_bus: Any,
        max_challenge_rounds: int = 3,
        min_confidence_threshold: float = 0.7,
        practice_store: Optional["TeamPracticeStore"] = None,
    ):
        self._agent_manager = agent_manager
        self._message_bus = message_bus
        self._max_challenge_rounds = max_challenge_rounds
        self._min_confidence = min_confidence_threshold
        self._practice_store = practice_store  # For recording successful practices
        self._logger = logging.getLogger("ParallelReasoning")

        # Active reasoning sessions
        self._sessions: Dict[str, Dict] = {}

    async def run_parallel_reasoning(
        self,
        problem: str,
        candidates: List[str],
        requester_id: str,
        context: Optional[Dict] = None,
    ) -> ParallelReasoningResult:
        """
        Start a parallel reasoning session.
        
        Args:
            problem: The problem description
            candidates: List of candidate explanations to analyze
            requester_id: ID of agent requesting the reasoning session
            context: Additional context (files, error logs, etc.)
            
        Returns:
            ParallelReasoningResult with the strongest candidate
        """
        start_time = datetime.now()
        session_id = f"reason_{uuid4().hex[:8]}"

        self._logger.info(f"Starting parallel reasoning {session_id}: {problem[:50]}...")
        self._logger.info(f"Candidates: {candidates}")

        candidate_objects = [
            ReasoningCandidate(
                id=f"h_{i}",
                description=h,
                proposed_by=requester_id,
            )
            for i, h in enumerate(candidates)
        ]

        # Store session state
        self._sessions[session_id] = {
            "problem": problem,
            "candidates": candidate_objects,
            "context": context or {},
            "workers": [],
        }

        try:
            # Phase 1: Spawn worker lanes for each candidate
            workers = await self._spawn_candidate_workers(
                session_id, problem, candidate_objects, context
            )

            # Phase 2: Initial evidence gathering
            await self._run_evidence_phase(session_id, workers)

            # Phase 3: Challenge rounds
            challenge_rounds = 0
            consensus = False

            for round_num in range(self._max_challenge_rounds):
                challenge_rounds = round_num + 1
                self._logger.info(f"Challenge round {challenge_rounds}")

                await self._run_challenge_round(session_id, workers, round_num)

                # Check for consensus
                consensus = self._check_consensus(candidate_objects)
                if consensus:
                    self._logger.info(f"Consensus reached after {challenge_rounds} rounds")
                    break

            # Phase 4: Determine strongest candidate
            winning = self._determine_winner(candidate_objects)

            for worker_id in workers:
                await self._agent_manager.terminate_runtime_agent(worker_id, wait=False)

            duration = (datetime.now() - start_time).total_seconds()

            result = ParallelReasoningResult(
                problem=problem,
                winning_candidate=winning,
                all_candidates=candidate_objects,
                challenge_rounds=challenge_rounds,
                consensus_reached=consensus,
                summary=self._generate_summary(problem, winning, candidate_objects, consensus),
                duration=duration,
            )

            self._logger.info(f"Parallel reasoning complete: {result.summary}")

            # Record successful practice for future reference
            if self._practice_store and winning:
                try:
                    # Categorize problem (simple heuristic)
                    problem_lower = problem.lower()
                    if "bug" in problem_lower or "error" in problem_lower:
                        category = "debugging"
                    elif "api" in problem_lower:
                        category = "api_issue"
                    elif "performance" in problem_lower or "slow" in problem_lower:
                        category = "performance"
                    elif "security" in problem_lower:
                        category = "security"
                    else:
                        category = "general"
                    
                    self._practice_store.record_practice(
                        practice_type=PracticeType.PARALLEL_REASONING,
                        problem_category=category,
                        description=problem,
                        agents_spawned=[
                            {
                                "type": "analysis_worker",
                                "role": f"candidate_{i}",
                                "task": h.description[:100],
                            }
                            for i, h in enumerate(candidate_objects)
                        ],
                        success=consensus,
                        outcome_summary=result.summary,
                        findings=[
                            {"hypothesis": h.description, "confidence": h.confidence}
                            for h in candidate_objects
                        ],
                        context=context or {},
                        duration_seconds=duration,
                        created_by=requester_id,
                    )
                    self._logger.info("Recorded parallel reasoning practice for future reference")
                except Exception as record_err:
                    self._logger.warning(f"Failed to record practice: {record_err}")

            return result

        except Exception as e:
            self._logger.error(f"Parallel reasoning failed: {e}")
            import traceback
            self._logger.error(traceback.format_exc())

            # Cleanup on error
            for worker_id in self._sessions.get(session_id, {}).get("workers", []):
                await self._agent_manager.terminate_runtime_agent(worker_id, wait=False)

            return ParallelReasoningResult(
                problem=problem,
                all_candidates=candidate_objects,
                summary=f"Parallel reasoning failed: {e}",
                duration=(datetime.now() - start_time).total_seconds(),
            )
        finally:
            self._sessions.pop(session_id, None)

    async def _spawn_candidate_workers(
        self,
        session_id: str,
        problem: str,
        candidates: List[ReasoningCandidate],
        context: Optional[Dict],
    ) -> List[str]:
        """Spawn one reasoning worker for each candidate explanation."""
        workers = []

        for candidate in candidates:
            prompt = f"""You are analyzing one candidate explanation for: {problem}

YOUR CANDIDATE: {candidate.description}

Your job is to:
1. Gather evidence that SUPPORTS or REFUTES this candidate
2. Be objective - look for both supporting and contradicting evidence
3. Rate your confidence (0-1) after analysis
4. Be prepared to defend your findings and challenge competing candidates

Context: {json.dumps(context or {}, indent=2)}

Start analyzing. Use available tools to examine code, logs, and state.
Report your findings with evidence.
"""

            agent_id = await self._agent_manager.spawn_worker(
                worker_type="analysis_worker",
                task=prompt,
                parent_id=session_id,
                role=f"candidate_worker_{candidate.id}",
            )

            candidate.worker_id = agent_id
            candidate.status = CandidateStatus.ANALYZING
            workers.append(agent_id)

        self._sessions[session_id]["workers"] = workers
        return workers

    async def _run_evidence_phase(
        self,
        session_id: str,
        workers: List[str],
    ) -> None:
        """Wait for initial evidence gathering to complete."""
        events = {}
        for worker_id in workers:
            events[worker_id] = asyncio.Event()

        from utils.message import MessageType

        def on_findings(message):
            source_id = getattr(getattr(message, "header", None), "source_agent_id", "")
            if source_id not in events:
                return
            result_data = getattr(message, "result_data", None)
            payload = getattr(message, "payload", None)
            content = result_data if result_data is not None else payload
            candidate_objects = self._sessions[session_id]["candidates"]
            for candidate in candidate_objects:
                if candidate.worker_id == source_id:
                    candidate.evidence.append({
                        "type": "initial_finding",
                        "content": content,
                        "timestamp": datetime.now().isoformat(),
                    })
                    if isinstance(content, dict) and "confidence" in content:
                        candidate.confidence = content.get("confidence", 0.5)
                    break
            events[source_id].set()

        sub_id = None
        try:
            sub_id = self._message_bus.subscribe(
                subscriber_id=f"parallel_reasoning_{session_id}",
                message_types=[MessageType.RESULT, MessageType.ERROR],
                callback=on_findings,
            )
        except Exception as e:
            self._logger.warning(f"Failed to subscribe reasoning listener: {e}")

        try:
            await asyncio.wait_for(
                asyncio.gather(*[e.wait() for e in events.values()]),
                timeout=300.0  # 5 minutes
            )
        except asyncio.TimeoutError:
            self._logger.warning("Parallel evidence phase timed out")
        finally:
            if sub_id:
                self._message_bus.unsubscribe(sub_id)

    async def _run_challenge_round(
        self,
        session_id: str,
        workers: List[str],
        round_num: int,
    ) -> None:
        """Run one challenge round where workers critique competing candidates."""
        candidate_objects = self._sessions[session_id]["candidates"]

        for candidate in candidate_objects:
            if not candidate.worker_id:
                continue

            other_findings = []
            for other in candidate_objects:
                if other.id != candidate.id:
                    other_findings.append({
                        "candidate": other.description,
                        "evidence": other.evidence,
                        "confidence": other.confidence,
                    })

            challenge_prompt = f"""CHALLENGE ROUND {round_num + 1}

Other parallel workers have found:
{json.dumps(other_findings, indent=2)}

Your task:
1. Challenge their findings - find holes in their evidence
2. Defend your candidate against potential challenges
3. Update your confidence based on what you've learned
4. If another candidate seems stronger, acknowledge it

Report your challenges and updated confidence.
"""

            agent = self._agent_manager._orchestrator._agents.get(candidate.worker_id)
            if agent:
                await agent.send_task({
                    "task": challenge_prompt,
                    "type": "challenge_round",
                    "round": round_num,
                })

        await asyncio.sleep(30)

    def _check_consensus(self, candidates: List[ReasoningCandidate]) -> bool:
        """Check whether one candidate clearly dominates the others."""
        confidences = [h.confidence for h in candidates]
        if not confidences:
            return False

        max_conf = max(confidences)
        second_max = sorted(confidences)[-2] if len(confidences) > 1 else 0

        return max_conf >= self._min_confidence and (max_conf - second_max) >= 0.3

    def _determine_winner(self, candidates: List[ReasoningCandidate]) -> Optional[ReasoningCandidate]:
        """Determine the strongest candidate explanation."""
        if not candidates:
            return None

        sorted_candidates = sorted(candidates, key=lambda h: h.confidence, reverse=True)
        winner = sorted_candidates[0]

        if winner.confidence >= self._min_confidence:
            winner.status = CandidateStatus.CONSENSUS
            return winner

        return None

    def _generate_summary(
        self,
        problem: str,
        winner: Optional[ReasoningCandidate],
        all_candidates: List[ReasoningCandidate],
        consensus: bool,
    ) -> str:
        """Generate parallel reasoning summary."""
        if winner:
            summary = f"Parallel reasoning concluded: '{winner.description}' "
            summary += f"(confidence: {winner.confidence:.1%})"
            if consensus:
                summary += " - Consensus reached"
        else:
            summary = "No clear conclusion - candidates remained inconclusive. "
            summary += f"Best: {max(all_candidates, key=lambda h: h.confidence).description}"

        return summary

