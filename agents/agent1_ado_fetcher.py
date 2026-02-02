"""Agent-1: ADO Work Item Fetcher and Test Case Generator.

This agent wraps the existing Azure AI Agent that connects to Azure Logic App
to fetch ADO work items and generate manual test cases.
"""

import json
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

from azure.ai.agents.models import ListSortOrder

from .base import BaseAgent, AgentResult, AgentStatus
from utils.azure_client import create_agents_client, collect_assistant_text
from utils.parsers import parse_plain_text_work_items, parse_markdown_table_tests, filter_items_root_and_children
from config.settings import get_settings


@dataclass
class ADOFetchInput:
    """Input for ADO Fetcher Agent."""
    work_item_id: str
    fetch_children: bool = True


@dataclass
class ADOFetchOutput:
    """Output from ADO Fetcher Agent."""
    work_items: List[Dict[str, str]]
    test_cases: List[Dict[str, str]]
    raw_work_items_text: str = ""
    raw_test_cases_text: str = ""
    run1_status: str = ""
    run2_status: str = ""


class ADOFetcherAgent(BaseAgent):
    """
    Agent-1: Fetches ADO work items and generates manual test cases.

    This agent wraps the Azure AI Agent that:
    1. Connects to Azure Logic App to fetch work items from ADO
    2. Generates manual test cases from the fetched work items
    """

    def __init__(self):
        super().__init__(
            name="ADO Fetcher & Test Generator",
            description="Fetches ADO work items and generates manual test cases using Azure AI Agent"
        )
        self.settings = get_settings()

    def validate_input(self, input_data: Any) -> List[str]:
        """Validate input data."""
        errors = []

        if not self.settings.azure.project_endpoint:
            errors.append("AZURE_AI_PROJECT_ENDPOINT is not configured")
        if not self.settings.azure.agent1_id:
            errors.append("AZURE_AI_AGENT_ID is not configured")

        if isinstance(input_data, ADOFetchInput):
            if not input_data.work_item_id:
                errors.append("work_item_id is required")
        elif isinstance(input_data, dict):
            if not input_data.get("work_item_id"):
                errors.append("work_item_id is required")
        else:
            errors.append("Invalid input type. Expected ADOFetchInput or dict")

        return errors

    async def execute(self, input_data: Any, **kwargs) -> AgentResult:
        """
        Execute ADO fetch and test case generation.

        Args:
            input_data: ADOFetchInput or dict with work_item_id

        Returns:
            AgentResult with ADOFetchOutput
        """
        self._status = AgentStatus.RUNNING

        # Validate input
        errors = self.validate_input(input_data)
        if errors:
            self._status = AgentStatus.FAILED
            return AgentResult(
                status=AgentStatus.FAILED,
                error="; ".join(errors)
            )

        # Extract work_item_id
        if isinstance(input_data, ADOFetchInput):
            work_item_id = input_data.work_item_id
        else:
            work_item_id = input_data.get("work_item_id")

        try:
            # Create Azure AI Agents client
            agents = create_agents_client()
            thread = agents.threads.create()

            # Run 1: Fetch ADO work items
            run1_result = await self._run_fetch_work_items(
                agents, thread.id, work_item_id
            )

            if run1_result["status"] != "completed":
                self._status = AgentStatus.FAILED
                return AgentResult(
                    status=AgentStatus.FAILED,
                    error="Failed to fetch work items from ADO",
                    raw_output=run1_result.get("raw_text", ""),
                    metadata={"run1_status": run1_result["status"]}
                )

            work_items = run1_result["items"]
            if not work_items:
                self._status = AgentStatus.COMPLETED
                return AgentResult(
                    status=AgentStatus.COMPLETED,
                    data=ADOFetchOutput(
                        work_items=[],
                        test_cases=[],
                        raw_work_items_text=run1_result.get("raw_text", ""),
                        run1_status=run1_result["status"],
                        run2_status="skipped"
                    ),
                    raw_output=run1_result.get("raw_text", ""),
                    metadata={"message": "No work items found"}
                )

            # Run 2: Generate test cases
            run2_result = await self._run_generate_test_cases(
                agents, thread.id, work_items
            )

            output = ADOFetchOutput(
                work_items=work_items,
                test_cases=run2_result.get("test_cases", []),
                raw_work_items_text=run1_result.get("raw_text", ""),
                raw_test_cases_text=run2_result.get("raw_text", ""),
                run1_status=run1_result["status"],
                run2_status=run2_result.get("status", "failed")
            )

            self._status = AgentStatus.COMPLETED
            return AgentResult(
                status=AgentStatus.COMPLETED,
                data=output,
                raw_output=run2_result.get("raw_text", ""),
                metadata={
                    "work_item_count": len(work_items),
                    "test_case_count": len(run2_result.get("test_cases", []))
                }
            )

        except Exception as e:
            self._status = AgentStatus.FAILED
            return AgentResult(
                status=AgentStatus.FAILED,
                error=str(e)
            )

    async def _run_fetch_work_items(
        self,
        agents,
        thread_id: str,
        work_item_id: str
    ) -> Dict[str, Any]:
        """Run 1: Fetch ADO work items."""
        tool_inputs = {"workItemId": work_item_id}

        user_msg = (
            "Use the Logic App action attached to this agent to fetch Azure DevOps work items.\n"
            "HARD REQUIREMENTS:\n"
            "- ID-ONLY LOOKUP: You MUST use the provided `workItemId` to fetch the item directly.\n"
            "- Do NOT query or filter by areaPath, iterationPath, tags, or any other scope.\n"
            "- Do NOT infer or inject defaults for areaPath.\n"
            "- If `workItemId` is missing, STOP and ask the user for the exact ID. Do not run any search.\n\n"
            "EXPANSION RULES (based on the fetched item's Type):\n"
            "- If Type = Feature: return ONLY the Feature AND its direct child User Stories.\n"
            "- If Type = User Story: return ONLY the User Story AND its direct child Tasks.\n"
            "- If Type = Task: return ONLY the Task (no expansion).\n"
            "NEVER include siblings or unrelated items.\n\n"
            "REQUIRED FIELDS FOR EVERY RETURNED ITEM (Feature, User Story, Task):\n"
            "- Root ID: the requested `workItemId`\n"
            "- Parent ID: the immediate parent id (blank for the root item). "
            "  If Parent ID cannot be determined for a non-root item, DO NOT include that item.\n"
            "- ID\n- Title\n- Description (Plain Text only; sanitize HTML)\n- State\n- Area Path\n"
            "Also include an 'Acceptance Criteria (Plain Text):' block for Features and User Stories. Tasks may omit it.\n\n"
            "OUTPUT FORMAT (repeat this block for EACH returned item; NOT JSON):\n\n"
            "### Fetched Work Item\n"
            "Type: <Feature|User Story|Task>\n"
            "Root ID: <root-id>\n"
            "Parent ID: <parent-id-or-blank>\n"
            "ID: <id>\n"
            "Title: <title>\n"
            "State: <state>\n"
            "Area Path: <areaPath>\n\n"
            "Description (Plain Text):\n"
            "<description>\n\n"
            "Acceptance Criteria (Plain Text):\n"
            "<acceptance-criteria-if-present>\n"
            "---\n\n"
            "Inputs: " + json.dumps(tool_inputs, ensure_ascii=False)
        )

        agents.messages.create(thread_id=thread_id, role="user", content=user_msg)
        run = agents.runs.create_and_process(
            thread_id=thread_id,
            agent_id=self.settings.azure.agent1_id
        )

        msgs_iter = agents.messages.list(
            thread_id=thread_id,
            order=ListSortOrder.DESCENDING,
            limit=1
        )
        last_msg = next(iter(msgs_iter), None)
        raw_text = collect_assistant_text(last_msg) if (last_msg and last_msg.role == "assistant") else ""

        # Parse and filter items
        all_items = parse_plain_text_work_items(raw_text)
        filtered_items = filter_items_root_and_children(all_items, work_item_id)

        return {
            "status": run.status,
            "items": filtered_items,
            "raw_text": raw_text,
            "total_parsed": len(all_items),
            "filtered_count": len(filtered_items)
        }

    async def _run_generate_test_cases(
        self,
        agents,
        thread_id: str,
        work_items: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """Run 2: Generate test cases from work items."""
        condensed = []
        for w in work_items:
            condensed.append({
                "id": w.get("id"),
                "type": w.get("type"),
                "title": w.get("title"),
                "description": w.get("description") or "",
                "acceptanceCriteria": w.get("acceptanceCriteria") or "",
                "state": w.get("state"),
                "areaPath": w.get("areaPath"),
                "rootId": w.get("rootId"),
                "parentId": w.get("parentId"),
            })

        user_msg = (
            "Using the following work items (title + description; acceptance criteria when present), "
            "generate detailed MANUAL TEST CASES for each item.\n\n"
            "REQUIREMENTS:\n"
            "- Provide clear, ordered steps and corresponding expected outcomes.\n"
            "- Cover the following scenario categories comprehensively: Positive, Negative, Boundary, Functional.\n"
            "- Return test cases as a Markdown table with EXACTLY these columns:\n"
            "| Test Case ID | Category | Test Case Name/Objectives | Preconditions | Steps | Expected Outcome |\n"
            "- Keep each test case compact but complete, suitable for Azure DevOps Test Plans import.\n\n"
            + json.dumps(condensed, ensure_ascii=False)
        )

        agents.messages.create(thread_id=thread_id, role="user", content=user_msg)
        run = agents.runs.create_and_process(
            thread_id=thread_id,
            agent_id=self.settings.azure.agent1_id
        )

        msgs_iter = agents.messages.list(
            thread_id=thread_id,
            order=ListSortOrder.DESCENDING,
            limit=1
        )
        last_msg = next(iter(msgs_iter), None)
        raw_text = collect_assistant_text(last_msg) if (last_msg and last_msg.role == "assistant") else ""

        test_cases = parse_markdown_table_tests(raw_text)

        return {
            "status": run.status,
            "test_cases": test_cases,
            "raw_text": raw_text
        }


# Synchronous wrapper for non-async contexts
def run_ado_fetcher_sync(work_item_id: str) -> AgentResult:
    """Synchronous wrapper for ADO Fetcher Agent."""
    import asyncio

    agent = ADOFetcherAgent()
    input_data = ADOFetchInput(work_item_id=work_item_id)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(agent.execute(input_data))
    finally:
        loop.close()

    return result
