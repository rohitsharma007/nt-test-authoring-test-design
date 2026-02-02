"""
Validation script for multi-agent test authoring system.

This script allows you to test each agent individually or the full workflow.
"""

import os
import sys
import asyncio
import json

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

def print_header(title: str):
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)

def print_section(title: str):
    print(f"\n--- {title} ---")

def check_configuration():
    """Check if all required configuration is present."""
    print_header("Configuration Check")

    from config.settings import get_settings
    settings = get_settings()

    # Agent-1 Config
    print_section("Agent-1 (Azure AI Agent)")
    agent1_ok = True

    if settings.azure.project_endpoint:
        print(f"  ✅ AZURE_AI_PROJECT_ENDPOINT: {settings.azure.project_endpoint[:50]}...")
    else:
        print("  ❌ AZURE_AI_PROJECT_ENDPOINT: Not set")
        agent1_ok = False

    if settings.azure.agent1_id:
        print(f"  ✅ AZURE_AI_AGENT_ID: {settings.azure.agent1_id}")
    else:
        print("  ❌ AZURE_AI_AGENT_ID: Not set")
        agent1_ok = False

    # Agent-2 Config
    print_section("Agent-2 (LangChain LLM)")
    agent2_ok = True

    print(f"  LLM Provider: {settings.llm.provider}")

    if settings.llm.provider == "azure_openai":
        if settings.llm.azure_openai_endpoint:
            print(f"  ✅ AZURE_OPENAI_ENDPOINT: {settings.llm.azure_openai_endpoint[:40]}...")
        else:
            print("  ❌ AZURE_OPENAI_ENDPOINT: Not set")
            agent2_ok = False

        if settings.llm.azure_openai_api_key:
            print(f"  ✅ AZURE_OPENAI_API_KEY: {'*' * 20}")
        else:
            print("  ❌ AZURE_OPENAI_API_KEY: Not set")
            agent2_ok = False

        print(f"  Deployment: {settings.llm.azure_openai_deployment}")
        print(f"  API Version: {settings.llm.azure_openai_api_version}")

    elif settings.llm.provider == "openai":
        if settings.llm.openai_api_key:
            print(f"  ✅ OPENAI_API_KEY: {'*' * 20}")
        else:
            print("  ❌ OPENAI_API_KEY: Not set")
            agent2_ok = False

        print(f"  Model: {settings.llm.openai_model}")

    print(f"\n  Temperature: {settings.llm.temperature}")
    print(f"  Max Tokens: {settings.llm.max_tokens}")

    return agent1_ok, agent2_ok


def test_agent2_standalone():
    """Test Agent-2 with sample test cases (no Agent-1 required)."""
    print_header("Testing Agent-2 Standalone")

    # Sample test cases (simulating Agent-1 output)
    sample_test_cases = [
        {
            "id": "TC-001",
            "name": "Verify user login with valid credentials",
            "category": "Positive",
            "preconditions": "User account exists in the system",
            "steps": "1. Navigate to login page\n2. Enter valid username\n3. Enter valid password\n4. Click Login button",
            "expected": "User is logged in and redirected to dashboard"
        },
        {
            "id": "TC-002",
            "name": "Verify error on invalid password",
            "category": "Negative",
            "preconditions": "User account exists",
            "steps": "1. Go to login\n2. Enter valid username\n3. Enter wrong password\n4. Click Login",
            "expected": "Error message displayed"
        },
        {
            "id": "TC-003",
            "name": "Verify OTP verification",
            "category": "Functional",
            "preconditions": "User has 2FA enabled",
            "steps": "1. Login with credentials\n2. Wait for OTP\n3. Enter OTP\n4. Verify login",
            "expected": "User logged in after OTP verification"
        }
    ]

    print("\nSample Test Cases:")
    for tc in sample_test_cases:
        print(f"  • {tc['id']}: {tc['name']}")

    print("\nRunning Agent-2 validation analysis...")

    try:
        from agents.agent2_validator import TestCaseValidatorAgent, Agent2Input

        agent = TestCaseValidatorAgent()
        input_data = Agent2Input(
            test_cases=sample_test_cases,
            analysis_type="full"
        )

        # Run async
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(agent.execute(input_data))
        finally:
            loop.close()

        if result.is_success:
            print("\n✅ Agent-2 executed successfully!")

            data = result.data
            print_section("Results Summary")

            if data.summary:
                print(f"  Validation Issues: {data.summary.get('total_validation_issues', 0)}")
                print(f"  Automatable Steps: {data.summary.get('automatable_count', 0)}")
                print(f"  Requires Mock: {data.summary.get('requires_mock_count', 0)}")
                print(f"  Manual Only: {data.summary.get('manual_only_count', 0)}")
                print(f"  Ready for Automation: {data.summary.get('ready_for_automation', 0)}")
                print(f"  Needs Refinement: {data.summary.get('needs_refinement', 0)}")

            print_section("Validation Issues Found")
            if data.validation_issues:
                for issue in data.validation_issues:
                    print(f"  • {issue.test_case_id}: {issue.issue_type} - {issue.description}")
            else:
                print("  No issues found (or parsing needed)")

            print_section("Feasibility Results")
            if data.feasibility_results:
                for fr in data.feasibility_results:
                    print(f"  • {fr.test_case_id} Step {fr.step_number}: {fr.classification}")
            else:
                print("  Check raw output for details")

            print_section("Design Assessments")
            if data.design_assessments:
                for da in data.design_assessments:
                    print(f"  • {da.test_case_id}: {da.readiness_status}")
            else:
                print("  Check raw output for details")

            print_section("Raw Output Preview (first 1000 chars)")
            print(data.raw_output[:1000] if data.raw_output else "No raw output")

            return True
        else:
            print(f"\n❌ Agent-2 failed: {result.error}")
            return False

    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_full_workflow(work_item_id: str):
    """Test the full workflow with a real ADO work item."""
    print_header(f"Testing Full Workflow (Work Item: {work_item_id})")

    try:
        from workflows.orchestrator import TestAuthoringWorkflow

        workflow = TestAuthoringWorkflow()

        print("\nRunning workflow...")
        print("  Step 1: Agent-1 fetching ADO work items...")
        print("  Step 2: Agent-1 generating test cases...")
        print("  Step 3: Agent-2 validating test cases...")

        # Run async
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(workflow.run(work_item_id))
        finally:
            loop.close()

        print_section("Workflow Results")
        print(f"  Status: {result.get('status', 'unknown')}")
        print(f"  Agent-1 Status: {result.get('agent1_status', 'not_run')}")
        print(f"  Agent-2 Status: {result.get('agent2_status', 'not_run')}")

        work_items = result.get('work_items', [])
        print(f"  Work Items Found: {len(work_items)}")
        for wi in work_items:
            print(f"    • {wi.get('type', 'N/A')}: {wi.get('title', 'Untitled')} (ID: {wi.get('id', 'N/A')})")

        test_cases = result.get('test_cases', [])
        print(f"  Test Cases Generated: {len(test_cases)}")
        for tc in test_cases:
            print(f"    • {tc.get('id', 'N/A')}: {tc.get('name', 'Unnamed')}")

        if result.get('error'):
            print(f"\n⚠️ Error: {result['error']}")

        recommendations = result.get('recommendations', [])
        if recommendations:
            print_section("Recommendations")
            for rec in recommendations:
                print(f"  • {rec}")

        return result.get('status') == 'completed'

    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print_header("Multi-Agent Test Authoring Validation")
    print("This script validates the multi-agent system components.\n")

    # Step 1: Check configuration
    agent1_ok, agent2_ok = check_configuration()

    print_section("Configuration Summary")
    print(f"  Agent-1 (Azure AI): {'✅ Ready' if agent1_ok else '❌ Not configured'}")
    print(f"  Agent-2 (LangChain): {'✅ Ready' if agent2_ok else '❌ Not configured'}")

    # Menu
    print_header("Validation Options")
    print("1. Test Agent-2 standalone (with sample test cases)")
    print("2. Test full workflow (requires ADO work item ID)")
    print("3. Exit")

    choice = input("\nSelect option (1-3): ").strip()

    if choice == "1":
        if not agent2_ok:
            print("\n⚠️ Agent-2 is not configured. Please set LLM credentials in .env file.")
            print("\nRequired for Azure OpenAI:")
            print("  AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/")
            print("  AZURE_OPENAI_API_KEY=<your-api-key>")
            print("  AZURE_OPENAI_DEPLOYMENT=gpt-4o")
            print("\nOR for OpenAI:")
            print("  LLM_PROVIDER=openai")
            print("  OPENAI_API_KEY=<your-api-key>")
            return

        test_agent2_standalone()

    elif choice == "2":
        if not agent1_ok:
            print("\n⚠️ Agent-1 is not configured. Cannot run full workflow.")
            return

        work_item_id = input("\nEnter ADO Work Item ID: ").strip()
        if work_item_id:
            test_full_workflow(work_item_id)
        else:
            print("No work item ID provided.")

    elif choice == "3":
        print("\nExiting...")
    else:
        print("\nInvalid option.")


if __name__ == "__main__":
    main()
