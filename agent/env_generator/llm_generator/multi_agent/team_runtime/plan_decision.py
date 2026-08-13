"""Plan decision protocol extracted from team_protocols."""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from .models import Plan, PlanStatus

class PlanDecisionProtocol:
    """
    Plan decision protocol.

    Requires agents to submit plans before executing complex tasks, then lets
    the lead agent accept, reject, or request revisions.
    """
    
    def __init__(
        self,
        message_bus: Any,
        lead_agent_id: str = "orchestrator",
        max_revisions: int = 3,
        auto_approve_threshold: int = 3,  # Auto-approve if <= N steps
    ):
        self._message_bus = message_bus
        self._lead_id = lead_agent_id
        self._max_revisions = max_revisions
        self._auto_approve_threshold = auto_approve_threshold
        self._logger = logging.getLogger("PlanDecision")
        
        # Pending plans
        self._plans: Dict[str, Plan] = {}
        self._decision_events: Dict[str, asyncio.Event] = {}

        # Decision criteria (can be set by lead)
        self._criteria: List[str] = []

    def set_decision_criteria(self, criteria: List[str]) -> None:
        """Set criteria the lead uses when deciding plans."""
        self._criteria = criteria
        self._logger.info(f"Decision criteria set: {criteria}")
    
    async def submit_plan(
        self,
        agent_id: str,
        title: str,
        description: str,
        steps: List[Dict],
        require_approval: bool = True,
    ) -> Plan:
        """
        Submit a plan for decision.
        
        Args:
            agent_id: ID of agent submitting plan
            title: Plan title
            description: What the plan aims to achieve
            steps: List of planned steps
            require_approval: If False, auto-accept
            
        Returns:
            The Plan object (check status for final decision)
        """
        plan_id = f"plan_{uuid4().hex[:8]}"
        
        plan = Plan(
            id=plan_id,
            agent_id=agent_id,
            title=title,
            description=description,
            steps=steps,
            submitted_at=datetime.now(),
        )
        
        self._plans[plan_id] = plan
        self._decision_events[plan_id] = asyncio.Event()

        # Auto-accept simple plans
        if not require_approval or len(steps) <= self._auto_approve_threshold:
            plan.status = PlanStatus.APPROVED
            plan.decision_maker_id = "auto"
            plan.decided_at = datetime.now()
            self._decision_events[plan_id].set()
            self._logger.info(f"Plan {plan_id} auto-accepted ({len(steps)} steps)")
            return plan

        plan.status = PlanStatus.SUBMITTED
        self._logger.info(f"Plan {plan_id} submitted for decision: {title}")

        from utils.message import BaseMessage, MessageType, MessageHeader

        decision_request = BaseMessage(
            message_type=MessageType.TASK,
            header=MessageHeader(
                source_agent_id=agent_id,
                target_agent_id=self._lead_id,
            ),
            # #658: BaseMessage's field is `payload`; `content=` raised
            # `TypeError: BaseMessage.__init__() got an unexpected keyword argument 'content'`.
            # Gated behind the auto-approve branch above, so it only fired for plans with MORE
            # steps than `_auto_approve_threshold` (3) — every smaller plan short-circuits and
            # never builds a message, which is why an agent-callable tool could ship broken.
            payload={
                "type": "plan_decision_request",
                "plan": plan.to_dict(),
                "criteria": self._criteria,
            },
        )

        await self._message_bus.send(decision_request)

        return plan

    async def wait_for_decision(
        self,
        plan_id: str,
        timeout: float = 300.0,
    ) -> Plan:
        """
        Wait for a plan decision.
        
        Args:
            plan_id: ID of the plan
            timeout: Max wait time in seconds
            
        Returns:
            Updated Plan with approval status
        """
        if plan_id not in self._decision_events:
            raise ValueError(f"Plan {plan_id} not found")

        try:
            await asyncio.wait_for(
                self._decision_events[plan_id].wait(),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            self._logger.warning(f"Plan {plan_id} decision timed out")
            self._plans[plan_id].status = PlanStatus.REJECTED
            self._plans[plan_id].feedback = "Rejected: decision timeout"
            self._plans[plan_id].decided_at = datetime.now()

        return self._plans[plan_id]

    def accept_plan(
        self,
        plan_id: str,
        decision_maker_id: str,
        feedback: Optional[str] = None,
    ) -> bool:
        """
        Accept a plan (called by lead agent).
        
        Args:
            plan_id: ID of the plan
            decision_maker_id: ID of the agent making the decision
            feedback: Optional feedback
            
        Returns:
            True if accepted
        """
        if plan_id not in self._plans:
            self._logger.warning(f"Plan {plan_id} not found")
            return False
        
        plan = self._plans[plan_id]
        plan.status = PlanStatus.APPROVED
        plan.decision_maker_id = decision_maker_id
        plan.feedback = feedback
        plan.decided_at = datetime.now()

        if plan_id in self._decision_events:
            self._decision_events[plan_id].set()

        self._logger.info(f"Plan {plan_id} accepted by {decision_maker_id}")
        return True

    def request_plan_changes(
        self,
        plan_id: str,
        decision_maker_id: str,
        feedback: str,
        request_revision: bool = True,
    ) -> bool:
        """
        Reject a plan or request changes.
        
        Args:
            plan_id: ID of the plan
            decision_maker_id: ID of the agent making the decision
            feedback: Required feedback explaining the decision
            request_revision: If True, allow revision
            
        Returns:
            True if decision recorded
        """
        if plan_id not in self._plans:
            self._logger.warning(f"Plan {plan_id} not found")
            return False
        
        plan = self._plans[plan_id]
        plan.decision_maker_id = decision_maker_id
        plan.feedback = feedback
        plan.decided_at = datetime.now()
        
        if request_revision and plan.revision_count < self._max_revisions:
            plan.status = PlanStatus.REVISION_REQUESTED
            plan.revision_count += 1
            if plan_id in self._decision_events:
                self._decision_events[plan_id].set()
            self._logger.info(f"Plan {plan_id} revision requested (#{plan.revision_count})")
        else:
            plan.status = PlanStatus.REJECTED
            if plan_id in self._decision_events:
                self._decision_events[plan_id].set()
            self._logger.info(f"Plan {plan_id} rejected by {decision_maker_id}")
        
        return True
    
    async def revise_and_resubmit(
        self,
        plan_id: str,
        new_steps: List[Dict],
        revision_notes: Optional[str] = None,
    ) -> Plan:
        """
        Revise a plan and resubmit.
        
        Args:
            plan_id: ID of the plan
            new_steps: Updated steps
            revision_notes: Notes on what changed
            
        Returns:
            Updated Plan
        """
        if plan_id not in self._plans:
            raise ValueError(f"Plan {plan_id} not found")
        
        plan = self._plans[plan_id]
        
        if plan.status != PlanStatus.REVISION_REQUESTED:
            raise ValueError(f"Plan {plan_id} is not awaiting revision")
        
        plan.steps = new_steps
        plan.status = PlanStatus.SUBMITTED
        plan.submitted_at = datetime.now()
        
        # Reset event for a new decision cycle
        self._decision_events[plan_id] = asyncio.Event()
        
        self._logger.info(f"Plan {plan_id} revised and resubmitted")
        
        # Notify lead
        from utils.message import BaseMessage, MessageType, MessageHeader
        
        revision_msg = BaseMessage(
            message_type=MessageType.TASK,
            header=MessageHeader(
                source_agent_id=plan.agent_id,
                target_agent_id=self._lead_id,
            ),
            payload={                      # #658: `content` is not a BaseMessage field
                "type": "plan_revision",
                "plan": plan.to_dict(),
                "revision_notes": revision_notes,
            },
        )
        
        await self._message_bus.send(revision_msg)
        
        return plan
    
    def get_pending_plan_decisions(self) -> List[Plan]:
        """Get all plans waiting for a decision."""
        return [
            p for p in self._plans.values()
            if p.status in (PlanStatus.SUBMITTED, PlanStatus.REVISION_REQUESTED)
        ]
