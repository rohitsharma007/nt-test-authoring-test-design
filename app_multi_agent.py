"""
Multi-Agent Test Authoring Application

This Streamlit application orchestrates multiple agents:
- Agent-1: ADO Fetcher & Test Case Generator (Azure AI Agent)
- Agent-2: Test Case Validation & Automation Readiness (LangChain)

Future agents can be easily added to the workflow.
"""

import os
import re
import sys
import asyncio
from typing import Optional

import streamlit as st
from dotenv import load_dotenv

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.settings import get_settings
from workflows.orchestrator import TestAuthoringWorkflow
from utils.parsers import parse_markdown_table_tests

load_dotenv()

# -----------------------
# Page Configuration
# -----------------------
st.set_page_config(
    page_title="Multi-Agent Test Authoring",
    page_icon="🤖",
    layout="wide"
)

st.title("Multi-Agent Test Authoring POC")
st.caption(
    "This application uses multiple AI agents to fetch ADO work items, generate test cases, "
    "and prepare them for automation."
)

# -----------------------
# Sidebar Configuration
# -----------------------
with st.sidebar:
    st.subheader("🔧 Configuration")

    st.markdown("### Agent-1: Azure AI Agent")
    st.write("Fetches ADO work items and generates manual test cases.")
    st.code(
        '''
AZURE_AI_PROJECT_ENDPOINT=<endpoint>
AZURE_AI_AGENT_ID=<agent-id>
''',
        language="bash",
    )

    st.markdown("### Agent-2: LangChain Agent")
    st.write("Validates and prepares test cases for automation.")
    st.code(
        '''
LLM_PROVIDER=azure_openai
AZURE_OPENAI_ENDPOINT=<endpoint>
AZURE_OPENAI_API_KEY=<key>
AZURE_OPENAI_DEPLOYMENT=gpt-4o
''',
        language="bash",
    )

    st.markdown("---")
    st.markdown("### 📋 Workflow Steps")
    st.markdown("""
    1. **Agent-1**: Fetch ADO work items
    2. **Agent-1**: Generate manual test cases
    3. **Agent-2**: Validate test cases
    4. **Agent-2**: Normalize to atomic actions
    5. **Agent-2**: Analyze automation feasibility
    6. **Agent-2**: Detect duplicates
    7. **Agent-2**: Provide design recommendations
    """)

# -----------------------
# Validate Configuration
# -----------------------
settings = get_settings()
config_errors = settings.validate()

if config_errors:
    st.warning("⚠️ Configuration Issues Detected")
    for error in config_errors:
        st.error(f"• {error}")
    st.info("Please set the required environment variables to continue.")

# -----------------------
# Input Section
# -----------------------
st.subheader("📥 Input")

col1, col2 = st.columns([3, 1])

with col1:
    ado_url = st.text_input(
        "ADO Work Item URL",
        placeholder="https://dev.azure.com/<org>/<project>/_workitems/edit/24027",
        help="Enter the Azure DevOps work item URL to fetch and generate test cases"
    ).strip()

with col2:
    run_agent2 = st.checkbox(
        "Run Agent-2 (Validation)",
        value=True,
        help="Enable Agent-2 to validate and prepare test cases for automation"
    )

# Extract work item ID from URL
m = re.search(r"/_workitems/edit/(\d+)", ado_url or "")
work_item_id: Optional[str] = m.group(1) if m else None

if work_item_id:
    st.success(f"✓ Work Item ID: **{work_item_id}**")

# -----------------------
# Session State Defaults
# -----------------------
session_defaults = {
    'workflow_state': None,
    'workflow_running': False,
    'current_step': None,
}
for k, v in session_defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# -----------------------
# Run Workflow
# -----------------------
if st.button("🚀 Run Multi-Agent Workflow", type="primary", disabled=not work_item_id):
    if not work_item_id:
        st.error("Please provide a valid ADO Work Item URL")
    elif config_errors:
        st.error("Please fix configuration issues before running")
    else:
        st.session_state['workflow_running'] = True
        st.session_state['workflow_state'] = None

        # Create progress indicators
        progress_bar = st.progress(0)
        status_text = st.empty()

        try:
            # Agent-1 execution
            status_text.text("🔄 Agent-1: Fetching ADO work items...")
            progress_bar.progress(10)

            workflow = TestAuthoringWorkflow()

            # Run the workflow
            with st.spinner("Running multi-agent workflow..."):
                # Use async event loop
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                try:
                    final_state = loop.run_until_complete(
                        workflow.run(work_item_id, ado_url)
                    )
                finally:
                    loop.close()

            st.session_state['workflow_state'] = final_state
            progress_bar.progress(100)

            if final_state.get('status') == 'completed':
                status_text.text("✅ Workflow completed successfully!")
            elif final_state.get('status') == 'partial':
                status_text.text("⚠️ Workflow partially completed")
            else:
                status_text.text("❌ Workflow failed")

        except Exception as ex:
            st.exception(ex)
            status_text.text(f"❌ Error: {str(ex)}")

        finally:
            st.session_state['workflow_running'] = False

# -----------------------
# Results Display
# -----------------------
st.markdown("---")
st.subheader("📊 Results")

workflow_state = st.session_state.get('workflow_state')

if workflow_state:
    # Create tabs for different result sections
    tabs = st.tabs([
        "📋 Work Items",
        "🧪 Generated Test Cases",
        "✅ Validation Results",
        "🤖 Automation Readiness",
        "📝 Recommendations",
        "🔍 Raw Output"
    ])

    # Tab 1: Work Items
    with tabs[0]:
        st.markdown("### Fetched Work Items")
        agent1_status = workflow_state.get('agent1_status', 'not_run')
        st.write(f"**Agent-1 Status:** {agent1_status}")

        work_items = workflow_state.get('work_items', [])
        if work_items:
            for wi in work_items:
                with st.expander(f"📄 {wi.get('type', 'Item')}: {wi.get('title', 'Untitled')} (ID: {wi.get('id', 'N/A')})"):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write(f"**Type:** {wi.get('type', 'N/A')}")
                        st.write(f"**State:** {wi.get('state', 'N/A')}")
                        st.write(f"**Area Path:** {wi.get('areaPath', 'N/A')}")
                    with col2:
                        st.write(f"**Root ID:** {wi.get('rootId', 'N/A')}")
                        st.write(f"**Parent ID:** {wi.get('parentId', 'N/A')}")

                    st.markdown("**Description:**")
                    st.write(wi.get('description', '(no description)'))

                    if wi.get('acceptanceCriteria'):
                        st.markdown("**Acceptance Criteria:**")
                        st.write(wi.get('acceptanceCriteria'))
        else:
            st.info("No work items fetched")

    # Tab 2: Generated Test Cases
    with tabs[1]:
        st.markdown("### Generated Test Cases")

        test_cases = workflow_state.get('test_cases', [])
        if test_cases:
            st.write(f"**Total Test Cases:** {len(test_cases)}")

            for idx, tc in enumerate(test_cases):
                with st.expander(f"🧪 {tc.get('id', f'TC-{idx+1}')}: {tc.get('name', 'Unnamed Test Case')}"):
                    st.write(f"**Category:** {tc.get('category', 'N/A')}")
                    st.write(f"**Preconditions:** {tc.get('preconditions', 'None')}")

                    st.markdown("**Steps:**")
                    st.write(tc.get('steps', 'No steps defined'))

                    st.markdown("**Expected Outcome:**")
                    st.write(tc.get('expected', 'Not specified'))
        else:
            st.info("No test cases generated")

    # Tab 3: Validation Results
    with tabs[2]:
        st.markdown("### Test Case Validation")
        agent2_status = workflow_state.get('agent2_status', 'not_run')
        st.write(f"**Agent-2 Status:** {agent2_status}")

        validation_issues = workflow_state.get('validation_issues', [])
        if validation_issues:
            st.warning(f"Found {len(validation_issues)} validation issues")

            for issue in validation_issues:
                with st.container():
                    col1, col2 = st.columns([1, 3])
                    with col1:
                        st.write(f"**{issue.get('test_case_id', 'N/A')}**")
                        if issue.get('step_number'):
                            st.write(f"Step: {issue['step_number']}")
                    with col2:
                        st.write(f"**Issue:** {issue.get('issue_type', 'Unknown')}")
                        st.write(issue.get('description', ''))
                        if issue.get('suggested_fix'):
                            st.success(f"💡 Fix: {issue['suggested_fix']}")
                    st.markdown("---")
        else:
            if agent2_status == 'completed':
                st.success("✅ No validation issues found!")
            else:
                st.info("Validation not run or no results available")

        # Normalized Test Cases
        st.markdown("### Normalized Test Cases (Atomic Actions)")
        normalized = workflow_state.get('normalized_test_cases', [])
        if normalized:
            for ntc in normalized:
                with st.expander(f"📋 {ntc.get('id', 'Unknown')}: {ntc.get('name', 'Unnamed')}"):
                    steps = ntc.get('normalized_steps', [])
                    if steps:
                        st.table(steps)
                    else:
                        st.write("No normalized steps")

    # Tab 4: Automation Readiness
    with tabs[3]:
        st.markdown("### Automation Feasibility Analysis")

        feasibility = workflow_state.get('feasibility_results', [])
        if feasibility:
            # Summary counts
            automatable = len([f for f in feasibility if f.get('classification') == 'AUTOMATABLE'])
            requires_mock = len([f for f in feasibility if f.get('classification') == 'REQUIRES_MOCK'])
            manual_only = len([f for f in feasibility if f.get('classification') == 'MANUAL_ONLY'])

            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Automatable", automatable, delta=None)
            with col2:
                st.metric("Requires Mock", requires_mock, delta=None)
            with col3:
                st.metric("Manual Only", manual_only, delta=None)

            st.markdown("#### Detailed Analysis")
            for fr in feasibility:
                status_icon = "✅" if fr.get('classification') == 'AUTOMATABLE' else "⚠️" if fr.get('classification') == 'REQUIRES_MOCK' else "❌"
                st.write(f"{status_icon} **{fr.get('test_case_id', 'N/A')}** - Step {fr.get('step_number', 'N/A')}: {fr.get('classification', 'Unknown')}")
                if fr.get('reason'):
                    st.caption(f"Reason: {fr['reason']}")
                if fr.get('alternative_approach'):
                    st.caption(f"Alternative: {fr['alternative_approach']}")

        # Design Assessments
        st.markdown("### Automation Design Assessment")
        assessments = workflow_state.get('design_assessments', [])
        if assessments:
            for da in assessments:
                status_color = "🟢" if da.get('readiness_status') == 'READY' else "🟡" if da.get('readiness_status') == 'NEEDS_REFINEMENT' else "🔴"
                with st.expander(f"{status_color} {da.get('test_case_id', 'Unknown')}: {da.get('readiness_status', 'Unknown')}"):
                    if da.get('refinement_needed'):
                        st.warning(f"Refinement needed: {da['refinement_needed']}")

                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown("**Page Objects:**")
                        for po in da.get('page_objects', []):
                            st.write(f"• {po}")

                        st.markdown("**Reusable Flows:**")
                        for rf in da.get('reusable_flows', []):
                            st.write(f"• {rf}")

                    with col2:
                        st.markdown("**Test Data Requirements:**")
                        for td in da.get('test_data_requirements', []):
                            st.write(f"• {td}")

                        st.markdown("**Environment Dependencies:**")
                        for ed in da.get('environment_dependencies', []):
                            st.write(f"• {ed}")

        # Duplicates
        st.markdown("### Duplicate Detection")
        duplicates = workflow_state.get('duplicate_results', [])
        if duplicates:
            st.warning(f"Found {len(duplicates)} potential duplicates")
            for dup in duplicates:
                st.write(f"• **{dup.get('test_case_id', 'N/A')}** - {dup.get('duplicate_type', 'Unknown')} "
                        f"(Similar to: {dup.get('similar_to', 'N/A')}, Overlap: {dup.get('overlap_percentage', 0)}%)")
                st.caption(f"Recommendation: {dup.get('recommendation', 'N/A')}")
        else:
            st.success("✅ No duplicates detected")

    # Tab 5: Recommendations
    with tabs[4]:
        st.markdown("### Summary & Recommendations")

        summary = workflow_state.get('agent2_summary', {})
        if summary:
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Ready for Automation", summary.get('ready_for_automation', 0))
            with col2:
                st.metric("Needs Refinement", summary.get('needs_refinement', 0))
            with col3:
                st.metric("Not Suitable", summary.get('not_suitable', 0))
            with col4:
                st.metric("Validation Issues", summary.get('total_validation_issues', 0))

        recommendations = workflow_state.get('recommendations', [])
        if recommendations:
            st.markdown("### 📋 Action Items")
            for idx, rec in enumerate(recommendations, 1):
                st.write(f"{idx}. {rec}")
        else:
            st.info("No specific recommendations")

        # Final Categorization
        st.markdown("### Final Test Case Categorization")

        automation_ready = workflow_state.get('automation_ready_cases', [])
        manual_only_cases = workflow_state.get('manual_only_cases', [])

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("#### ✅ Automation Ready")
            if automation_ready:
                for tc in automation_ready:
                    st.write(f"• {tc.get('id', 'N/A')}: {tc.get('name', 'Unnamed')}")
            else:
                st.info("None")

        with col2:
            st.markdown("#### 🔧 Manual Only")
            if manual_only_cases:
                for tc in manual_only_cases:
                    st.write(f"• {tc.get('id', 'N/A')}: {tc.get('name', 'Unnamed')}")
            else:
                st.info("None")

    # Tab 6: Raw Output
    with tabs[5]:
        st.markdown("### Raw Agent Outputs")

        st.markdown("#### Agent-1: Work Items (Raw)")
        work_items_raw = workflow_state.get('work_items_raw', '')
        if work_items_raw:
            with st.expander("Show raw work items output"):
                st.code(work_items_raw)

        st.markdown("#### Agent-1: Test Cases (Raw)")
        test_cases_raw = workflow_state.get('test_cases_raw', '')
        if test_cases_raw:
            with st.expander("Show raw test cases output"):
                st.code(test_cases_raw)

        st.markdown("#### Agent-2: Validation Analysis (Raw)")
        agent2_raw = workflow_state.get('agent2_raw', '')
        if agent2_raw:
            with st.expander("Show raw Agent-2 output"):
                st.markdown(agent2_raw)

        st.markdown("#### Full Workflow State (Debug)")
        with st.expander("Show full workflow state"):
            st.json({k: v for k, v in workflow_state.items() if not k.endswith('_raw')})

else:
    st.info("👆 Enter an ADO Work Item URL and click 'Run Multi-Agent Workflow' to get started.")

# -----------------------
# Footer
# -----------------------
st.markdown("---")
st.caption(
    "Multi-Agent Test Authoring POC | "
    "Agent-1: Azure AI Agent (ADO + Logic App) | "
    "Agent-2: LangChain (Validation & Automation Readiness)"
)
