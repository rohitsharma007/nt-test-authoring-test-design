"""Agent-2: Manual Test Case Validation & Automation Readiness Agent.

This agent evaluates, refines, and prepares manual test cases for automation.
It uses LangChain for LLM interactions.
"""

import json
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

from .base import BaseAgent, AgentResult, AgentStatus
from .prompts.agent2_prompts import (
    AGENT2_SYSTEM_PROMPT,
    AGENT2_VALIDATION_PROMPT,
    AGENT2_NORMALIZATION_PROMPT,
    AGENT2_FEASIBILITY_PROMPT,
    AGENT2_DEDUPLICATION_PROMPT,
    AGENT2_DESIGN_PROMPT,
    get_agent2_full_analysis_prompt,
)
from config.settings import get_settings


@dataclass
class ValidationIssue:
    """A validation issue found in a test case."""
    test_case_id: str
    step_number: Optional[int]
    issue_type: str  # "vague", "incomplete", "non_deterministic", "missing_assertion"
    description: str
    suggested_fix: str = ""


@dataclass
class NormalizedStep:
    """A normalized atomic action step."""
    step_number: int
    original_step: str
    action_type: str  # OPEN_URL, CLICK, INPUT, SELECT, VERIFY, WAIT, HOVER, SCROLL
    target_element: str
    value_or_expected: str


@dataclass
class FeasibilityResult:
    """Automation feasibility result for a step."""
    test_case_id: str
    step_number: int
    classification: str  # AUTOMATABLE, REQUIRES_MOCK, MANUAL_ONLY
    reason: str
    alternative_approach: str = ""


@dataclass
class DuplicateResult:
    """Duplicate detection result."""
    test_case_id: str
    duplicate_type: str  # FULL_DUPLICATE, PARTIAL_OVERLAP, SIMILAR_FLOW
    similar_to: str
    overlap_percentage: int
    recommendation: str  # SKIP, EXTEND, KEEP


@dataclass
class DesignAssessment:
    """Automation design assessment for a test case."""
    test_case_id: str
    readiness_status: str  # READY, NEEDS_REFINEMENT, NOT_SUITABLE
    refinement_needed: str = ""
    page_objects: List[str] = field(default_factory=list)
    reusable_flows: List[str] = field(default_factory=list)
    test_data_requirements: List[str] = field(default_factory=list)
    environment_dependencies: List[str] = field(default_factory=list)


@dataclass
class Agent2Input:
    """Input for Agent-2."""
    test_cases: List[Dict[str, str]]
    existing_tests: Optional[List[Dict[str, str]]] = None
    analysis_type: str = "full"  # "full", "validation", "normalization", "feasibility", "deduplication", "design"


@dataclass
class Agent2Output:
    """Output from Agent-2."""
    validation_issues: List[ValidationIssue] = field(default_factory=list)
    normalized_test_cases: List[Dict[str, Any]] = field(default_factory=list)
    feasibility_results: List[FeasibilityResult] = field(default_factory=list)
    duplicate_results: List[DuplicateResult] = field(default_factory=list)
    design_assessments: List[DesignAssessment] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)
    raw_output: str = ""


class TestCaseValidatorAgent(BaseAgent):
    """
    Agent-2: Manual Test Case Validation & Automation Readiness Agent.

    This agent takes test cases from Agent-1 and:
    1. Validates test case quality
    2. Normalizes steps to atomic actions
    3. Analyzes automation feasibility
    4. Detects duplicates
    5. Provides automation design recommendations
    """

    def __init__(self, llm=None):
        super().__init__(
            name="Test Case Validator",
            description="Validates and prepares manual test cases for automation"
        )
        self.settings = get_settings()
        self._llm = llm

    def _get_llm(self):
        """Get or create LLM instance."""
        if self._llm is not None:
            return self._llm

        settings = self.settings.llm

        if settings.provider == "azure_openai":
            from langchain_openai import AzureChatOpenAI
            self._llm = AzureChatOpenAI(
                azure_endpoint=settings.azure_openai_endpoint,
                api_key=settings.azure_openai_api_key,
                api_version=settings.azure_openai_api_version,
                deployment_name=settings.azure_openai_deployment,
                temperature=settings.temperature,
                max_tokens=settings.max_tokens,
            )
        elif settings.provider == "openai":
            from langchain_openai import ChatOpenAI
            self._llm = ChatOpenAI(
                api_key=settings.openai_api_key,
                model=settings.openai_model,
                temperature=settings.temperature,
                max_tokens=settings.max_tokens,
            )
        else:
            raise ValueError(f"Unsupported LLM provider: {settings.provider}")

        return self._llm

    def validate_input(self, input_data: Any) -> List[str]:
        """Validate input data."""
        errors = []

        if isinstance(input_data, Agent2Input):
            if not input_data.test_cases:
                errors.append("test_cases cannot be empty")
        elif isinstance(input_data, dict):
            if not input_data.get("test_cases"):
                errors.append("test_cases cannot be empty")
        elif isinstance(input_data, list):
            if not input_data:
                errors.append("test_cases list cannot be empty")
        else:
            errors.append("Invalid input type")

        return errors

    async def execute(self, input_data: Any, **kwargs) -> AgentResult:
        """
        Execute test case validation and automation readiness analysis.

        Args:
            input_data: Agent2Input, dict with test_cases, or list of test cases

        Returns:
            AgentResult with Agent2Output
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

        # Extract test cases and options
        if isinstance(input_data, Agent2Input):
            test_cases = input_data.test_cases
            existing_tests = input_data.existing_tests
            analysis_type = input_data.analysis_type
        elif isinstance(input_data, dict):
            test_cases = input_data.get("test_cases", [])
            existing_tests = input_data.get("existing_tests")
            analysis_type = input_data.get("analysis_type", "full")
        else:
            test_cases = input_data
            existing_tests = None
            analysis_type = "full"

        try:
            # Format test cases for the prompt
            test_cases_text = self._format_test_cases(test_cases)
            existing_tests_text = self._format_test_cases(existing_tests) if existing_tests else ""

            # Get LLM
            llm = self._get_llm()

            # Execute analysis based on type
            if analysis_type == "full":
                result = await self._run_full_analysis(llm, test_cases_text, existing_tests_text)
            elif analysis_type == "validation":
                result = await self._run_validation(llm, test_cases_text)
            elif analysis_type == "normalization":
                result = await self._run_normalization(llm, test_cases_text)
            elif analysis_type == "feasibility":
                result = await self._run_feasibility(llm, test_cases_text)
            elif analysis_type == "deduplication":
                result = await self._run_deduplication(llm, test_cases_text, existing_tests_text)
            elif analysis_type == "design":
                result = await self._run_design_assessment(llm, test_cases_text)
            else:
                raise ValueError(f"Unknown analysis type: {analysis_type}")

            self._status = AgentStatus.COMPLETED
            return AgentResult(
                status=AgentStatus.COMPLETED,
                data=result,
                raw_output=result.raw_output,
                metadata={
                    "analysis_type": analysis_type,
                    "test_case_count": len(test_cases)
                }
            )

        except Exception as e:
            self._status = AgentStatus.FAILED
            return AgentResult(
                status=AgentStatus.FAILED,
                error=str(e)
            )

    def _format_test_cases(self, test_cases: List[Dict[str, str]]) -> str:
        """Format test cases for prompt inclusion."""
        if not test_cases:
            return ""

        formatted = []
        for i, tc in enumerate(test_cases, 1):
            tc_text = f"### Test Case {i}\n"
            tc_text += f"- **ID**: {tc.get('id', f'TC-{i}')}\n"
            tc_text += f"- **Name**: {tc.get('name', 'Unnamed')}\n"
            tc_text += f"- **Category**: {tc.get('category', 'N/A')}\n"
            tc_text += f"- **Preconditions**: {tc.get('preconditions', 'None')}\n"
            tc_text += f"- **Steps**: {tc.get('steps', 'No steps')}\n"
            tc_text += f"- **Expected Outcome**: {tc.get('expected', 'Not specified')}\n"
            formatted.append(tc_text)

        return "\n".join(formatted)

    async def _run_full_analysis(self, llm, test_cases_text: str, existing_tests_text: str) -> Agent2Output:
        """Run comprehensive analysis."""
        from langchain_core.messages import SystemMessage, HumanMessage

        prompt = get_agent2_full_analysis_prompt(test_cases_text, existing_tests_text)

        messages = [
            SystemMessage(content=AGENT2_SYSTEM_PROMPT),
            HumanMessage(content=prompt)
        ]

        response = await llm.ainvoke(messages)
        raw_output = response.content

        # Parse the response into structured output
        output = self._parse_full_analysis_response(raw_output)
        output.raw_output = raw_output

        return output

    async def _run_validation(self, llm, test_cases_text: str) -> Agent2Output:
        """Run validation analysis only."""
        from langchain_core.messages import SystemMessage, HumanMessage

        prompt = AGENT2_VALIDATION_PROMPT.format(test_cases=test_cases_text)

        messages = [
            SystemMessage(content=AGENT2_SYSTEM_PROMPT),
            HumanMessage(content=prompt)
        ]

        response = await llm.ainvoke(messages)
        raw_output = response.content

        output = Agent2Output()
        output.validation_issues = self._parse_validation_issues(raw_output)
        output.raw_output = raw_output

        return output

    async def _run_normalization(self, llm, test_cases_text: str) -> Agent2Output:
        """Run normalization analysis only."""
        from langchain_core.messages import SystemMessage, HumanMessage

        prompt = AGENT2_NORMALIZATION_PROMPT.format(test_cases=test_cases_text)

        messages = [
            SystemMessage(content=AGENT2_SYSTEM_PROMPT),
            HumanMessage(content=prompt)
        ]

        response = await llm.ainvoke(messages)
        raw_output = response.content

        output = Agent2Output()
        output.normalized_test_cases = self._parse_normalized_cases(raw_output)
        output.raw_output = raw_output

        return output

    async def _run_feasibility(self, llm, test_cases_text: str) -> Agent2Output:
        """Run feasibility analysis only."""
        from langchain_core.messages import SystemMessage, HumanMessage

        prompt = AGENT2_FEASIBILITY_PROMPT.format(test_cases=test_cases_text)

        messages = [
            SystemMessage(content=AGENT2_SYSTEM_PROMPT),
            HumanMessage(content=prompt)
        ]

        response = await llm.ainvoke(messages)
        raw_output = response.content

        output = Agent2Output()
        output.feasibility_results = self._parse_feasibility_results(raw_output)
        output.raw_output = raw_output

        return output

    async def _run_deduplication(self, llm, test_cases_text: str, existing_tests_text: str) -> Agent2Output:
        """Run deduplication analysis only."""
        from langchain_core.messages import SystemMessage, HumanMessage

        prompt = AGENT2_DEDUPLICATION_PROMPT.format(
            test_cases=test_cases_text,
            existing_tests=existing_tests_text or "None provided"
        )

        messages = [
            SystemMessage(content=AGENT2_SYSTEM_PROMPT),
            HumanMessage(content=prompt)
        ]

        response = await llm.ainvoke(messages)
        raw_output = response.content

        output = Agent2Output()
        output.duplicate_results = self._parse_duplicate_results(raw_output)
        output.raw_output = raw_output

        return output

    async def _run_design_assessment(self, llm, test_cases_text: str) -> Agent2Output:
        """Run design assessment only."""
        from langchain_core.messages import SystemMessage, HumanMessage

        prompt = AGENT2_DESIGN_PROMPT.format(test_cases=test_cases_text)

        messages = [
            SystemMessage(content=AGENT2_SYSTEM_PROMPT),
            HumanMessage(content=prompt)
        ]

        response = await llm.ainvoke(messages)
        raw_output = response.content

        output = Agent2Output()
        output.design_assessments = self._parse_design_assessments(raw_output)
        output.raw_output = raw_output

        return output

    def _parse_full_analysis_response(self, text: str) -> Agent2Output:
        """Parse full analysis response into structured output."""
        output = Agent2Output()

        # Parse each section
        output.validation_issues = self._parse_validation_issues(text)
        output.normalized_test_cases = self._parse_normalized_cases(text)
        output.feasibility_results = self._parse_feasibility_results(text)
        output.duplicate_results = self._parse_duplicate_results(text)
        output.design_assessments = self._parse_design_assessments(text)

        # Generate summary
        output.summary = {
            "total_validation_issues": len(output.validation_issues),
            "total_normalized_cases": len(output.normalized_test_cases),
            "automatable_count": len([f for f in output.feasibility_results if f.classification == "AUTOMATABLE"]),
            "requires_mock_count": len([f for f in output.feasibility_results if f.classification == "REQUIRES_MOCK"]),
            "manual_only_count": len([f for f in output.feasibility_results if f.classification == "MANUAL_ONLY"]),
            "duplicates_found": len(output.duplicate_results),
            "ready_for_automation": len([d for d in output.design_assessments if d.readiness_status == "READY"]),
            "needs_refinement": len([d for d in output.design_assessments if d.readiness_status == "NEEDS_REFINEMENT"]),
            "not_suitable": len([d for d in output.design_assessments if d.readiness_status == "NOT_SUITABLE"]),
        }

        return output

    def _parse_validation_issues(self, text: str) -> List[ValidationIssue]:
        """Parse validation issues from response."""
        import re
        issues = []

        # Look for table rows with validation issues
        pattern = r'\|\s*(TC-[\w-]+)\s*\|\s*(\d+)?\s*\|\s*(\w+[\w\s]*)\s*\|\s*([^|]+)\s*\|\s*([^|]*)\s*\|'
        matches = re.findall(pattern, text, re.IGNORECASE)

        for match in matches:
            tc_id, step_num, issue_type, description, suggested_fix = match
            issues.append(ValidationIssue(
                test_case_id=tc_id.strip(),
                step_number=int(step_num) if step_num.strip() else None,
                issue_type=issue_type.strip().lower().replace(" ", "_"),
                description=description.strip(),
                suggested_fix=suggested_fix.strip()
            ))

        return issues

    def _parse_normalized_cases(self, text: str) -> List[Dict[str, Any]]:
        """Parse normalized test cases from response."""
        import re
        cases = []

        # Split by test case headers
        tc_pattern = r'###\s*(TC-[\w-]+)[:\s]*([^\n]*)'
        sections = re.split(tc_pattern, text)

        i = 1
        while i < len(sections):
            tc_id = sections[i].strip()
            tc_name = sections[i+1].strip() if i+1 < len(sections) else ""
            content = sections[i+2] if i+2 < len(sections) else ""

            # Parse steps table
            step_pattern = r'\|\s*(\d+)\s*\|\s*([^|]*)\s*\|\s*(\w+)\s*\|\s*([^|]*)\s*\|\s*([^|]*)\s*\|'
            step_matches = re.findall(step_pattern, content, re.IGNORECASE)

            steps = []
            for match in step_matches:
                step_num, original, action, target, value = match
                steps.append({
                    "step_number": int(step_num),
                    "original_step": original.strip(),
                    "action_type": action.strip().upper(),
                    "target_element": target.strip(),
                    "value_or_expected": value.strip()
                })

            if tc_id or steps:
                cases.append({
                    "id": tc_id,
                    "name": tc_name,
                    "normalized_steps": steps
                })

            i += 3

        return cases

    def _parse_feasibility_results(self, text: str) -> List[FeasibilityResult]:
        """Parse feasibility results from response."""
        import re
        results = []

        pattern = r'\|\s*(TC-[\w-]+)\s*\|\s*(\d+)?\s*\|\s*(AUTOMATABLE|REQUIRES_MOCK|MANUAL_ONLY)\s*\|\s*([^|]+)\s*\|\s*([^|]*)\s*\|'
        matches = re.findall(pattern, text, re.IGNORECASE)

        for match in matches:
            tc_id, step_num, classification, reason, alternative = match
            results.append(FeasibilityResult(
                test_case_id=tc_id.strip(),
                step_number=int(step_num) if step_num.strip() else 0,
                classification=classification.strip().upper(),
                reason=reason.strip(),
                alternative_approach=alternative.strip()
            ))

        return results

    def _parse_duplicate_results(self, text: str) -> List[DuplicateResult]:
        """Parse duplicate detection results from response."""
        import re
        results = []

        pattern = r'\|\s*(TC-[\w-]+)\s*\|\s*(FULL_DUPLICATE|PARTIAL_OVERLAP|SIMILAR_FLOW)\s*\|\s*(TC-[\w-]+)?\s*\|\s*(\d+)%?\s*\|\s*(\w+)\s*[^|]*\|'
        matches = re.findall(pattern, text, re.IGNORECASE)

        for match in matches:
            tc_id, dup_type, similar_to, overlap, recommendation = match
            results.append(DuplicateResult(
                test_case_id=tc_id.strip(),
                duplicate_type=dup_type.strip().upper(),
                similar_to=similar_to.strip() if similar_to else "",
                overlap_percentage=int(overlap) if overlap else 0,
                recommendation=recommendation.strip().upper()
            ))

        return results

    def _parse_design_assessments(self, text: str) -> List[DesignAssessment]:
        """Parse design assessments from response."""
        import re
        assessments = []

        # Split by test case sections
        tc_pattern = r'###\s*(TC-[\w-]+)[:\s]*([^\n]*)'
        sections = re.split(tc_pattern, text)

        i = 1
        while i < len(sections):
            tc_id = sections[i].strip()
            tc_name = sections[i+1].strip() if i+1 < len(sections) else ""
            content = sections[i+2] if i+2 < len(sections) else ""

            # Extract fields
            status_match = re.search(r'\*\*Readiness Status\*\*:\s*(READY|NEEDS_REFINEMENT|NOT_SUITABLE)', content, re.IGNORECASE)
            refinement_match = re.search(r'\*\*Refinement Needed\*\*:\s*([^\n]+)', content, re.IGNORECASE)

            # Extract lists
            page_objects = re.findall(r'Page Objects\*\*:[^\n]*\n((?:\s*[-*]\s*[^\n]+\n?)*)', content, re.IGNORECASE)
            reusable_flows = re.findall(r'Reusable Flows\*\*:[^\n]*\n((?:\s*[-*]\s*[^\n]+\n?)*)', content, re.IGNORECASE)
            test_data = re.findall(r'Test Data Requirements\*\*:[^\n]*\n((?:\s*[-*]\s*[^\n]+\n?)*)', content, re.IGNORECASE)
            env_deps = re.findall(r'Environment Dependencies\*\*:[^\n]*\n((?:\s*[-*]\s*[^\n]+\n?)*)', content, re.IGNORECASE)

            def parse_list(list_text):
                if not list_text:
                    return []
                items = re.findall(r'[-*]\s*([^\n]+)', list_text[0] if list_text else "")
                return [item.strip() for item in items]

            if tc_id:
                assessments.append(DesignAssessment(
                    test_case_id=tc_id,
                    readiness_status=status_match.group(1).upper() if status_match else "NEEDS_REFINEMENT",
                    refinement_needed=refinement_match.group(1).strip() if refinement_match else "",
                    page_objects=parse_list(page_objects),
                    reusable_flows=parse_list(reusable_flows),
                    test_data_requirements=parse_list(test_data),
                    environment_dependencies=parse_list(env_deps)
                ))

            i += 3

        return assessments


# Synchronous wrapper for non-async contexts
def run_validator_sync(test_cases: List[Dict[str, str]], analysis_type: str = "full") -> AgentResult:
    """Synchronous wrapper for Test Case Validator Agent."""
    import asyncio

    agent = TestCaseValidatorAgent()
    input_data = Agent2Input(test_cases=test_cases, analysis_type=analysis_type)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(agent.execute(input_data))
    finally:
        loop.close()

    return result
