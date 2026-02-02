"""LangGraph workflow orchestrator for the multi-agent test authoring system."""

import asyncio
from typing import Any, Dict, List, Optional, Literal
from dataclasses import dataclass
import uuid

from langgraph.graph import StateGraph, END

from .state import TestAuthoringState, WorkflowStatus
from agents import ADOFetcherAgent, TestCaseValidatorAgent
from agents.base import AgentStatus
from agents.agent1_ado_fetcher import ADOFetchInput
from agents.agent2_validator import Agent2Input


def create_test_authoring_graph() -> StateGraph:
    """
    Create the LangGraph workflow for test authoring.

    Workflow:
    1. START -> Agent-1 (ADO Fetch & Test Generation)
    2. Agent-1 -> Conditional:
       - If test cases generated -> Agent-2 (Validation & Automation Readiness)
       - If no test cases -> END
    3. Agent-2 -> END

    Future extensions can add more agents by modifying this graph.
    """

    # Create the state graph
    workflow = StateGraph(TestAuthoringState)

    # Add nodes
    workflow.add_node("agent1_fetch", agent1_node)
    workflow.add_node("agent2_validate", agent2_node)
    workflow.add_node("finalize", finalize_node)

    # Set entry point
    workflow.set_entry_point("agent1_fetch")

    # Add edges
    workflow.add_conditional_edges(
        "agent1_fetch",
        should_continue_to_agent2,
        {
            "continue": "agent2_validate",
            "end": "finalize"
        }
    )

    workflow.add_edge("agent2_validate", "finalize")
    workflow.add_edge("finalize", END)

    return workflow


async def agent1_node(state: TestAuthoringState) -> TestAuthoringState:
    """
    Agent-1 node: Fetch ADO work items and generate test cases.
    """
    state["current_agent"] = "agent1"
    state["messages"] = [f"Starting Agent-1: Fetching work item {state.get('work_item_id')}"]

    try:
        agent = ADOFetcherAgent()
        input_data = ADOFetchInput(work_item_id=state.get("work_item_id", ""))

        result = await agent.execute(input_data)

        if result.is_success and result.data:
            state["agent1_status"] = "completed"
            state["work_items"] = result.data.work_items
            state["work_items_raw"] = result.data.raw_work_items_text
            state["test_cases"] = result.data.test_cases
            state["test_cases_raw"] = result.data.raw_test_cases_text
            state["messages"] = [
                f"Agent-1 completed: Found {len(result.data.work_items)} work items, "
                f"generated {len(result.data.test_cases)} test cases"
            ]
        else:
            state["agent1_status"] = "failed"
            state["error"] = result.error or "Unknown error in Agent-1"
            state["messages"] = [f"Agent-1 failed: {result.error}"]
            state["work_items"] = []
            state["test_cases"] = []

    except Exception as e:
        state["agent1_status"] = "failed"
        state["error"] = str(e)
        state["messages"] = [f"Agent-1 error: {str(e)}"]
        state["work_items"] = []
        state["test_cases"] = []

    return state


def should_continue_to_agent2(state: TestAuthoringState) -> Literal["continue", "end"]:
    """Determine if we should continue to Agent-2."""
    # Continue if we have test cases to validate
    if state.get("test_cases") and len(state.get("test_cases", [])) > 0:
        return "continue"
    return "end"


async def agent2_node(state: TestAuthoringState) -> TestAuthoringState:
    """
    Agent-2 node: Validate and prepare test cases for automation.
    """
    state["current_agent"] = "agent2"
    state["messages"] = [f"Starting Agent-2: Validating {len(state.get('test_cases', []))} test cases"]

    try:
        agent = TestCaseValidatorAgent()
        input_data = Agent2Input(
            test_cases=state.get("test_cases", []),
            analysis_type="full"
        )

        result = await agent.execute(input_data)

        if result.is_success and result.data:
            data = result.data
            state["agent2_status"] = "completed"
            state["validation_issues"] = [
                {"test_case_id": vi.test_case_id, "step_number": vi.step_number,
                 "issue_type": vi.issue_type, "description": vi.description,
                 "suggested_fix": vi.suggested_fix}
                for vi in data.validation_issues
            ]
            state["normalized_test_cases"] = data.normalized_test_cases
            state["feasibility_results"] = [
                {"test_case_id": fr.test_case_id, "step_number": fr.step_number,
                 "classification": fr.classification, "reason": fr.reason,
                 "alternative_approach": fr.alternative_approach}
                for fr in data.feasibility_results
            ]
            state["duplicate_results"] = [
                {"test_case_id": dr.test_case_id, "duplicate_type": dr.duplicate_type,
                 "similar_to": dr.similar_to, "overlap_percentage": dr.overlap_percentage,
                 "recommendation": dr.recommendation}
                for dr in data.duplicate_results
            ]
            state["design_assessments"] = [
                {"test_case_id": da.test_case_id, "readiness_status": da.readiness_status,
                 "refinement_needed": da.refinement_needed, "page_objects": da.page_objects,
                 "reusable_flows": da.reusable_flows, "test_data_requirements": da.test_data_requirements,
                 "environment_dependencies": da.environment_dependencies}
                for da in data.design_assessments
            ]
            state["agent2_summary"] = data.summary
            state["agent2_raw"] = data.raw_output
            state["messages"] = [
                f"Agent-2 completed: Analyzed {len(state.get('test_cases', []))} test cases"
            ]
        else:
            state["agent2_status"] = "failed"
            state["error"] = result.error or "Unknown error in Agent-2"
            state["messages"] = [f"Agent-2 failed: {result.error}"]

    except Exception as e:
        state["agent2_status"] = "failed"
        state["error"] = str(e)
        state["messages"] = [f"Agent-2 error: {str(e)}"]

    return state


async def finalize_node(state: TestAuthoringState) -> TestAuthoringState:
    """
    Finalize node: Compile final outputs and recommendations.
    """
    state["current_agent"] = "finalizer"

    # Determine overall status
    agent1_ok = state.get("agent1_status") == "completed"
    agent2_ok = state.get("agent2_status") == "completed"

    if agent1_ok and agent2_ok:
        state["status"] = "completed"
    elif agent1_ok:
        state["status"] = "partial"
    else:
        state["status"] = "failed"

    # Compile automation-ready vs manual-only cases
    automation_ready = []
    manual_only = []

    design_assessments = state.get("design_assessments", [])
    test_cases = state.get("test_cases", [])

    # Create a map of test case IDs to assessment status
    assessment_map = {da.get("test_case_id"): da for da in design_assessments}

    for tc in test_cases:
        tc_id = tc.get("id", "")
        assessment = assessment_map.get(tc_id, {})

        if assessment.get("readiness_status") == "READY":
            automation_ready.append({**tc, "assessment": assessment})
        elif assessment.get("readiness_status") == "NOT_SUITABLE":
            manual_only.append({**tc, "assessment": assessment})
        else:
            # NEEDS_REFINEMENT - can be automation-ready with changes
            automation_ready.append({**tc, "assessment": assessment})

    state["automation_ready_cases"] = automation_ready
    state["manual_only_cases"] = manual_only

    # Compile recommendations
    recommendations = []
    summary = state.get("agent2_summary", {})

    if summary.get("total_validation_issues", 0) > 0:
        recommendations.append(
            f"Review {summary['total_validation_issues']} validation issues before automation"
        )

    if summary.get("requires_mock_count", 0) > 0:
        recommendations.append(
            f"Set up mock services for {summary['requires_mock_count']} steps that require mocking"
        )

    if summary.get("manual_only_count", 0) > 0:
        recommendations.append(
            f"Keep {summary['manual_only_count']} steps as manual verification"
        )

    if summary.get("duplicates_found", 0) > 0:
        recommendations.append(
            f"Review {summary['duplicates_found']} potential duplicates to avoid redundant tests"
        )

    state["recommendations"] = recommendations
    state["messages"] = [
        f"Workflow completed. Ready for automation: {len(automation_ready)}, Manual only: {len(manual_only)}"
    ]

    return state


class TestAuthoringWorkflow:
    """
    High-level workflow class for test authoring.

    This provides a simple interface to run the multi-agent workflow.
    """

    def __init__(self):
        self.graph = create_test_authoring_graph()
        self.compiled_graph = self.graph.compile()

    async def run(
        self,
        work_item_id: str,
        work_item_url: str = ""
    ) -> TestAuthoringState:
        """
        Run the test authoring workflow.

        Args:
            work_item_id: Azure DevOps work item ID
            work_item_url: Optional URL of the work item

        Returns:
            Final workflow state
        """
        initial_state: TestAuthoringState = {
            "work_item_id": work_item_id,
            "work_item_url": work_item_url,
            "status": "running",
            "current_agent": "",
            "messages": [f"Starting workflow for work item {work_item_id}"],
        }

        # Run the graph
        final_state = await self.compiled_graph.ainvoke(initial_state)

        return final_state

    def run_sync(
        self,
        work_item_id: str,
        work_item_url: str = ""
    ) -> TestAuthoringState:
        """Synchronous wrapper for run()."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(self.run(work_item_id, work_item_url))
        finally:
            loop.close()
        return result


# Factory function for creating workflows
def create_workflow() -> TestAuthoringWorkflow:
    """Create a new test authoring workflow instance."""
    return TestAuthoringWorkflow()
