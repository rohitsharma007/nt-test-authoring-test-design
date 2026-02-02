import os
import re
import json
import html
from typing import List, Dict

import streamlit as st
from dotenv import load_dotenv

from azure.identity import AzureCliCredential, InteractiveBrowserCredential, ChainedTokenCredential
from azure.ai.agents import AgentsClient
from azure.ai.agents.models import ListSortOrder

load_dotenv()

# -----------------------
# Credentials
# -----------------------
try:
    cli_cred = AzureCliCredential()
    credential = ChainedTokenCredential(cli_cred, InteractiveBrowserCredential())
except Exception:
    credential = InteractiveBrowserCredential()

# -----------------------
# Environment Variables
# -----------------------
PROJECT_ENDPOINT = os.environ.get("AZURE_AI_PROJECT_ENDPOINT")
AGENT_ID = os.environ.get("AZURE_AI_AGENT_ID")

# -----------------------
# UI Setup
# -----------------------
st.set_page_config(page_title="ADO Stories via Agent", page_icon="✅", layout="centered")
st.title("UI Intelligence POC")
st.caption("First run fetches ADO items in simple text; second run generates manual test cases from the fetched items.")

with st.sidebar:
    st.subheader("Configuration")
    st.write("Set these environment variables before starting:")
    st.code(
        '''
export AZURE_AI_PROJECT_ENDPOINT="https://<id>.services.ai.azure.com/api/projects/<project>"
export AZURE_AI_AGENT_ID="<your-agent-id>"
''',
        language="bash",
    )

# -----------------------
# Inputs
# -----------------------
ado_url = st.text_input(
    "ADO Work Item URL",
    placeholder="https://dev.azure.com/<org>/<project>/_workitems/edit/24003"
)
col1, col2 = st.columns(2)
with col1:
    area_path = st.text_input("Area Path", value="WorkTop - Demo\\BFSI\\NT")
with col2:
    work_item_type = st.selectbox(
        "Work Item Type",
        ["User Story", "Task", "Feature", "Epic"],
        index=0
    )
state = st.text_input("State (optional)", value="Active")

# Extract numeric work item ID from URL if present
m = re.search(r"/_workitems/edit/(\d+)", ado_url or "")
work_item_id = m.group(1) if m else None

# -----------------------
# Helpers
# -----------------------
def collect_assistant_text(message) -> str:
    """
    Safely collect the assistant-to-user text from message content parts.
    """
    parts = []
    try:
        for c in (message.content or []):
            if getattr(c, "text", None) and getattr(c.text, "value", None):
                parts.append(c.text.value)
    except Exception:
        pass
    return "\n".join(parts).strip()


def parse_plain_text_work_items(text: str):
    """
    Parses blocks like:

    Fetched Work Item
    ID: 24015
    Title: ...
    State: ...
    Area Path: ...

    Description (Plain Text):
    <multiline>
    ---

    Returns: list of dicts: { id, title, state, areaPath, description }
    """
    if not text:
        return []

    # Split by "Fetched Work Item"
    blocks = re.split(r"(?i)\n?\s*Fetched Work Item\s*\n", text)
    items = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue

        id_match = re.search(r"(?im)^ID:\s*(\d+)\s*$", block)
        title_match = re.search(r"(?im)^Title:\s*(.+)$", block)
        state_match = re.search(r"(?im)^State:\s*(.+)$", block)
        area_match = re.search(r"(?im)^Area Path:\s*(.+)$", block)

        desc_match = re.search(r"(?is)Description\s*\(Plain\s*Text\)\s*:\s*(.+?)(?:\n-{3,}|$)", block)

        item = {
            "id": id_match.group(1).strip() if id_match else None,
            "title": title_match.group(1).strip() if title_match else None,
            "state": state_match.group(1).strip() if state_match else None,
            "areaPath": area_match.group(1).strip() if area_match else None,
            "description": (desc_match.group(1).strip() if desc_match else "").strip(),
        }

        if item["id"] or item["title"]:
            items.append(item)

    return items


def render_fetched_items_as_text(items):
    """
    Render items in the desired plain-text style in the UI.
    """
    if not items:
        st.write("(no items fetched)")
        return

    for i, w in enumerate(items, start=1):
        st.markdown("**Fetched Work Item**")
        if w.get("id"):
            st.write(f"ID: {w.get('id')}")
        if w.get("title"):
            st.write(f"Title: {w.get('title')}")
        if w.get("state"):
            st.write(f"State: {w.get('state')}")
        if w.get("areaPath"):
            st.write(f"Area Path: {w.get('areaPath')}")
        st.write("")  # spacing
        st.markdown("**Description (Plain Text):**")
        st.write(w.get("description") or "(no description)")
        st.markdown("---")


def _clean_cell(text: str) -> str:
    # Normalize whitespace and strip stray bullets
    if text is None:
        return ""
    t = text.replace("\r", "").strip()
    t = html.unescape(t)
    t = re.sub(r"[ \t]+\n", "\n", t)
    return t


def _parse_markdown_table_row(row_line: str, idx_id, idx_name, idx_prec, idx_steps, idx_out):
    """
    Split a single markdown table row into cells and assemble a test case dict.
    Returns a list of 0 or 1 dict.
    """
    row_line = row_line.strip()
    if not row_line.startswith("|"):
        return []
    cells = [c.strip() for c in row_line.strip("|").split("|")]

    if len(cells) < 2:
        return []

    def safe(idx):
        if idx is None:
            return ""
        if 0 <= idx < len(cells):
            return cells[idx]
        return ""

    case_id = _clean_cell(safe(idx_id))
    name = _clean_cell(safe(idx_name))
    pre = _clean_cell(safe(idx_prec))
    steps = _clean_cell(safe(idx_steps))
    expected = _clean_cell(safe(idx_out))

    # Skip header-like or dashed rows
    if all(re.fullmatch(r"[-\s:]+", c or "") for c in cells):
        return []

    if not name and not steps and not expected:
        return []

    return [{
        "id": case_id,
        "name": name,
        "preconditions": pre,
        "steps": steps,
        "expected": expected
    }]


def parse_markdown_table_tests(md_text: str) -> List[Dict[str, str]]:
    """
    Parse a Markdown-style table of manual test cases like:

    | Test Case ID | Test Case Name/Objectives | Preconditions | Steps | Expected Outcome |
    |--------------|---------------------------|---------------|-------|------------------|
    | TC-24015-1   | Validate UI Component...  | ...           | ...   | ...              |

    Returns: list of dicts with keys: id, name, preconditions, steps, expected
    """
    if not md_text:
        return []

    # Collect contiguous blocks of lines starting with '|'
    table_blocks = []
    current = []
    for ln in md_text.splitlines():
        if ln.strip().startswith("|"):
            current.append(ln.rstrip())
        else:
            if current:
                table_blocks.append("\n".join(current))
                current = []
    if current:
        table_blocks.append("\n".join(current))

    if not table_blocks:
        return []

    # Pick the largest table (most lines)
    table_text = max(table_blocks, key=lambda t: t.count("\n"))

    table_lines = [ln for ln in table_text.splitlines() if ln.strip()]
    if len(table_lines) < 2:
        return []

    header = table_lines[0].strip()
    header_cols = [c.strip().lower() for c in header.strip("|").split("|")]

    def find_col(name_options):
        for i, col in enumerate(header_cols):
            for opt in name_options:
                if opt in col:
                    return i
        return None

    idx_id = find_col(["test case id", "id"])
    idx_name = find_col(["test case name", "name", "objective", "objectives"])
    idx_prec = find_col(["precondition", "preconditions"])
    idx_steps = find_col(["step", "steps"])
    idx_out = find_col(["expected outcome", "expected result", "result", "outcome"])

    # Need at least name + steps + expected
    if idx_name is None or idx_steps is None or idx_out is None:
        return []

    # Find separator (---) row; data begins after it
    start_idx = None
    for i in range(1, len(table_lines)):
        if re.match(r'^\|\s*:?-{3,}', table_lines[i].strip()):
            start_idx = i + 1
            break
    if start_idx is None:
        start_idx = 2  # best-effort fallback

    cases = []
    row_buf = []
    for ln in table_lines[start_idx:]:
        if ln.strip().startswith("|"):
            if row_buf:
                row = " ".join(row_buf)
                cases.extend(_parse_markdown_table_row(row, idx_id, idx_name, idx_prec, idx_steps, idx_out))
                row_buf = []
            row_buf.append(ln)
        else:
            row_buf.append(ln)

    if row_buf:
        row = " ".join(row_buf)
        cases.extend(_parse_markdown_table_row(row, idx_id, idx_name, idx_prec, idx_steps, idx_out))

    return cases


# -----------------------
# Session defaults
# -----------------------
defaults = {
    'approved_idx': None,
    'test_cases_text': None,
    'run1_status': None,
    'run2_status': None,
    'fetched_items': None,        # parsed list of dicts from plain text
    'fetched_plain_text': None,   # raw text for reference
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# -----------------------
# Fetch from Agent (Run 1 + Run 2)
# -----------------------
if st.button("Fetch from Agent"):
    if not PROJECT_ENDPOINT or not AGENT_ID:
        st.error("Missing AZURE_AI_PROJECT_ENDPOINT or AZURE_AI_AGENT_ID.")
    else:
        try:
            # Reset states on each fetch
            st.session_state['run1_status'] = None
            st.session_state['run2_status'] = None
            st.session_state['fetched_items'] = None
            st.session_state['fetched_plain_text'] = None
            st.session_state['test_cases_text'] = None
            st.session_state['approved_idx'] = None

            agents = AgentsClient(endpoint=PROJECT_ENDPOINT, credential=credential)
            thread = agents.threads.create()

            # Build tool inputs
            tool_inputs = {"areaPath": area_path, "workItemType": work_item_type}
            if state:
                tool_inputs["state"] = state
            if work_item_id:
                tool_inputs["workItemId"] = work_item_id

            # ---- Run 1: Ask the Logic App tool to return PLAIN TEXT (not JSON)
            user_msg_run1 = (
                "Use the Logic App action attached to this agent to fetch ADO work items. "
                "Always include areaPath (default: \"WorkTop - Demo\\BFSI\\NT\"). "
                "If workItemType is missing, default to \"User Story\". "
                "Return the results ONLY in this simple text format (DO NOT return JSON):\n\n"
                "Fetched Work Item\n"
                "ID: <id>\n"
                "Title: <title>\n"
                "State: <state>\n"
                "Area Path: <areaPath>\n\n"
                "Description (Plain Text):\n"
                "<description>\n"
                "---\n\n"
                "Inputs: " + json.dumps(tool_inputs, ensure_ascii=False)
            )

            with st.spinner("Fetching from ADO…"):
                agents.messages.create(thread_id=thread.id, role="user", content=user_msg_run1)
                run1 = agents.runs.create_and_process(thread_id=thread.id, agent_id=AGENT_ID)
                st.session_state['run1_status'] = run1.status

                msgs_iter1 = agents.messages.list(
                    thread_id=thread.id, order=ListSortOrder.DESCENDING, limit=1
                )
                last_msg1 = next(iter(msgs_iter1), None)
                text1 = collect_assistant_text(last_msg1) if (last_msg1 and last_msg1.role == "assistant") else ""
                st.session_state['fetched_plain_text'] = text1 or ""

                # Parse the plain text into structured items for downstream use
                items = parse_plain_text_work_items(text1)
                st.session_state['fetched_items'] = items

            # ---- Run 2: Generate Manual Test Cases (request Markdown table format)
            if st.session_state['run1_status'] != "completed":
                st.warning("Run 1 did not complete. Check Agent/Logic App configuration.")
            elif not st.session_state['fetched_items']:
                st.session_state['test_cases_text'] = "(no test cases returned)"
                st.session_state['run2_status'] = "skipped (no work items found)"
            else:
                condensed = []
                for w in st.session_state['fetched_items']:
                    desc = w.get("description") or ""
                    condensed.append({
                        "id": w.get("id"),
                        "title": w.get("title"),
                        "text": desc
                    })

                user_msg_run2 = (
                    "Using the following items (title + text), generate detailed MANUAL TEST CASES for each item. "
                    "Prefer 'text' as the main narrative (it may be derived from Description or Acceptance Criteria). "
                    "Return the test cases as a Markdown table with these columns:\n"
                    "| Test Case ID | Test Case Name/Objectives | Preconditions | Steps | Expected Outcome |\n"
                    "Ensure steps are clear and ordered; keep each test case compact but complete.\n\n"
                    + json.dumps(condensed, ensure_ascii=False)
                )

                with st.spinner("Generating manual test cases…"):
                    agents.messages.create(thread_id=thread.id, role="user", content=user_msg_run2)
                    run2 = agents.runs.create_and_process(thread_id=thread.id, agent_id=AGENT_ID)

                    st.session_state['run2_status'] = run2.status
                    msgs_iter2 = agents.messages.list(
                        thread_id=thread.id, order=ListSortOrder.DESCENDING, limit=1
                    )
                    last_msg2 = next(iter(msgs_iter2), None)
                    test_cases_text = collect_assistant_text(last_msg2) if (last_msg2 and last_msg2.role == "assistant") else ""
                    st.session_state['test_cases_text'] = test_cases_text or "(no test cases returned)"

        except Exception as ex:
            st.exception(ex)

# -----------------------
# Results
# -----------------------
st.subheader("Results")

tab1, tab2 = st.tabs(["Fetched Items (Plain Text)", "Manual Test Cases"])

with tab1:
    if st.session_state.get('run1_status'):
        st.write(f"**Run 1 status:** {st.session_state['run1_status']}")
    else:
        st.write("_Run 1 has not been executed yet._")

    items = st.session_state.get('fetched_items') or []
    if items:
        render_fetched_items_as_text(items)
    else:
        raw_text = st.session_state.get('fetched_plain_text')
        if raw_text:
            st.markdown("**Raw Agent Response (plain text):**")
            st.code(raw_text)
        else:
            st.write("(no items fetched)")

with tab2:
    if st.session_state.get('run2_status'):
        st.write(f"**Run 2 status:** {st.session_state['run2_status']}")
    else:
        st.write("_Run 2 has not been executed yet._")

    st.subheader("Manual Test Cases")
    test_cases_text = st.session_state.get('test_cases_text', "") or ""

    if not test_cases_text.strip() or test_cases_text.strip() == "(no test cases returned)":
        st.write("(no test cases returned)")
    else:
        # 1) Try Markdown table format first (as per your screenshot)
        parsed_cases = parse_markdown_table_tests(test_cases_text)

        if parsed_cases:
            for idx, case in enumerate(parsed_cases):
                with st.container():
                    title_line = case.get("name") or f"Test Case {idx+1}"
                    case_id = case.get("id")
                    heading = f"{case_id} — {title_line}" if case_id else title_line
                    st.markdown(f"### {heading}")

                    if case.get("preconditions"):
                        st.markdown("**Preconditions:**")
                        st.markdown(case["preconditions"])
                    if case.get("steps"):
                        st.markdown("**Steps:**")
                        st.markdown(case["steps"])
                    if case.get("expected"):
                        st.markdown("**Expected Outcome:**")
                        st.markdown(case["expected"])

                    colA, _ = st.columns(2)
                    approve_key = f"approve_{idx}"
                    if colA.button("Approve for Script Generation", key=approve_key):
                        st.session_state['approved_idx'] = idx

                    if st.session_state.get('approved_idx') == idx:
                        st.info("Generating test script...")

                st.markdown("---")

        else:
            # 2) Fallback to heading-based cases: "Test Case N: <title>"
            test_case_blocks = re.split(r'(Test Case \d+:\s*[^\n]+)', test_cases_text, flags=re.IGNORECASE)

            if len(test_case_blocks) < 3:
                # 3) If neither format, just render raw
                st.write(test_cases_text)
            else:
                test_cases = []
                i = 1
                while i < len(test_case_blocks):
                    heading = test_case_blocks[i].strip()
                    content = test_case_blocks[i + 1].strip() if (i + 1) < len(test_case_blocks) else ''
                    test_cases.append((heading, content))
                    i += 2

                for idx, (heading, content) in enumerate(test_cases):
                    with st.container():
                        st.markdown(f"### {heading}")
                        st.markdown(content)
                        colA, _ = st.columns(2)
                        approve_key = f"approve_{idx}"
                        if colA.button("Approve for Script Generation", key=approve_key):
                            st.session_state['approved_idx'] = idx

                        if st.session_state.get('approved_idx') == idx:
                            st.info("Generating test script...")

                    st.markdown("---")