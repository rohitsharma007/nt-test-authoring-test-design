"""State definitions for LangGraph workflows."""

from typing import Any, Dict, List, Optional, TypedDict, Annotated
from dataclasses import dataclass, field
from enum import Enum
import operator


class WorkflowStatus(Enum):
    """Overall workflow status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"  # Some steps completed, some failed


class WorkflowState(TypedDict, total=False):
    """Base workflow state for LangGraph."""
    status: str
    current_step: str
    error: Optional[str]
    messages: Annotated[List[str], operator.add]


class TestAuthoringState(TypedDict, total=False):
    """State for the test authoring workflow."""

    # Input
    work_item_id: str
    work_item_url: str

    # Workflow control
    status: str
    current_agent: str
    error: Optional[str]
    messages: Annotated[List[str], operator.add]

    # Agent-1 outputs
    agent1_status: str
    work_items: List[Dict[str, str]]
    work_items_raw: str
    test_cases: List[Dict[str, str]]
    test_cases_raw: str

    # Agent-2 outputs
    agent2_status: str
    validation_issues: List[Dict[str, Any]]
    normalized_test_cases: List[Dict[str, Any]]
    feasibility_results: List[Dict[str, Any]]
    duplicate_results: List[Dict[str, Any]]
    design_assessments: List[Dict[str, Any]]
    agent2_summary: Dict[str, Any]
    agent2_raw: str

    # Final outputs
    automation_ready_cases: List[Dict[str, Any]]
    manual_only_cases: List[Dict[str, Any]]
    recommendations: List[str]


@dataclass
class WorkflowContext:
    """Context object for workflow execution."""
    workflow_id: str
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "metadata": self.metadata,
        }
