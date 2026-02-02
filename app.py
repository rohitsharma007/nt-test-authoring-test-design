import os
import re
import json
import html
from typing import List, Dict, Optional

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
st.caption(
    "Run 1: Fetch only the requested ADO item (ID-only) and its direct descendants (no siblings). "
    "Run 2: Generate manual test cases (Positive/Negative/Boundary/Functional)."
)

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
    "ADO Work Item URL (required; used to extract the ID)",
    placeholder="https://dev.azure.com/<org>/<project>/_workitems/edit/24027"
).strip()

# Extract numeric work item ID from URL if present (first match only)
m = re.search(r"/_workitems/edit/(\d+)", ado_url or "")
work_item_id: Optional[str] = m.group(1) if m else None

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


def _clean_block_text(s: Optional[str]) -> str:
    if not s:
        return ""
    t = s.replace("\r", "").strip()
    t = html.unescape(t)
    # Normalize spaces before line breaks
    t = re.sub(r"[ \t]+\n", "\n", t)
    return t


def _label_rx(label: str) -> re.Pattern:
    """
    Build a robust regex for single-line label extraction like:
    '- **Type:** value' OR 'Type: value' OR '*Type*: value'
    Accepts optional bullet '-' or '*' at start.
    """
    return re.compile(
        rf"(?im)^\s*(?:[-*]\s*)?\**\s*{re.escape(label)}\s*\**\s*:\s*(.*?)\s*$"
    )


def parse_plain_text_work_items(text: str) -> List[Dict[str, str]]:
    """
    Expected item block (markdown-tolerant):

    ### Fetched Work Item
    Type: Feature|User Story|Task
    Root ID: <id of the root that triggered this fetch>
    Parent ID: <parent id if any; blank for root>
    ID: <this item's id>
    Title: <title>
    State: <state>
    Area Path: <areaPath>

    Description (Plain Text):
    <multiline>

    Acceptance Criteria (Plain Text):
    <multiline-if-present>
    ---
    """
    if not text:
        return []

    # Split on a heading line that contains "Fetched Work Item", allowing #### or none
    splitter = re.compile(r"(?im)^\s*#{0,6}\s*Fetched Work Item\s*$")
    blocks = splitter.split(text)
    items: List[Dict[str, str]] = []

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        # Single-line labels (robust to bullets and bold)
        type_match = _label_rx("Type").search(block)
        root_match = _label_rx("Root ID").search(block)
        parent_match = _label_rx("Parent ID").search(block)
        id_match = _label_rx("ID").search(block)
        title_match = _label_rx("Title").search(block)
        state_match = _label_rx("State").search(block)
        area_match = _label_rx("Area Path").search(block)

        # Multi-line sections (robust to bullets and bold)
        desc_match = re.search(
            r"(?is)^\s*(?:[-*]\s*)?\**\s*Description\s*\(Plain\s*Text\)\s*\**\s*:\s*(.+?)"
            r"(?=^\s*(?:[-*]\s*)?\**\s*Acceptance\s*Criteria\b|^\s*-{3,}\s*$|\Z)",
            block,
            flags=re.MULTILINE,
        )
        acc_match = re.search(
            r"(?is)^\s*(?:[-*]\s*)?\**\s*Acceptance\s*Criteria(?:\s*\(Plain\s*Text\))?\s*\**\s*:\s*(.+?)"
            r"(?=^\s*-{3,}\s*$|\Z)",
            block,
            flags=re.MULTILINE,
        )

        item = {
            "type": _clean_block_text(type_match.group(1)) if type_match else "",
            "rootId": _clean_block_text(root_match.group(1)) if root_match else "",
            "parentId": _clean_block_text(parent_match.group(1)) if (parent_match and parent_match.group(1)) else "",
            "id": _clean_block_text(id_match.group(1)) if id_match else "",
            "title": _clean_block_text(title_match.group(1)) if title_match else "",
            "state": _clean_block_text(state_match.group(1)) if state_match else "",
            "areaPath": _clean_block_text(area_match.group(1)) if area_match else "",
            "description": _clean_block_text(desc_match.group(1)) if desc_match else "",
            "acceptanceCriteria": _clean_block_text(acc_match.group(1)) if acc_match else "",
        }

        if item["id"] or item["title"]:
            items.append(item)

    # De-duplicate by id while preserving order
    seen = set()
    deduped: List[Dict[str, str]] = []
    for it in items:
        iid = it.get("id") or ""
        if iid and iid in seen:
            continue
        if iid:
            seen.add(iid)
        deduped.append(it)

    return deduped


def _expected_child_type(root_type: str) -> Optional[str]:
    root_type = (root_type or "").strip().lower()
    if root_type == "feature":
        return "user story"
    if root_type == "user story":
        return "task"
    return None  # task => no children


def filter_items_root_and_children(items: List[Dict[str, str]], requested_id: str) -> List[Dict[str, str]]:
    """
    Keep:
      - Root item (id == requested_id), if present.
      - Direct children: items where parentId == requested_id.
      - If Parent ID missing but rootId == requested_id, accept as children.
    Enforce child type only if the root is present and its type is known.
    """
    if not items:
        return []

    # Identify root item if present
    root = next((it for it in items if it.get("id") == requested_id), None)
    results: List[Dict[str, str]] = []

    if root:
        results.append(root)
        expected_child = _expected_child_type(root.get("type", ""))

        # Primary rule: direct children by parentId
        for it in items:
            if it is root:
                continue
            if it.get("parentId") == requested_id:
                if expected_child and it.get("type", "").strip().lower() != expected_child:
                    continue
                results.append(it)

        # If no children found via parentId, but agent provided rootId, use that as fallback
        if len(results) == 1:
            fallback_children = [
                it for it in items
                if it.get("id") != requested_id and it.get("rootId") == requested_id
            ]
            if expected_child:
                fallback_children = [
                    it for it in fallback_children
                    if it.get("type", "").strip().lower() == expected_child
                ]
            results.extend(fallback_children)
    else:
        # Root not present: accept children that point to requested_id
        results = [it for it in items if it.get("parentId") == requested_id]

        # If still empty, accept items with rootId == requested_id (safe when root is Feature)
        if not results:
            results = [it for it in items if it.get("rootId") == requested_id and it.get("id") != requested_id]

    # De-duplicate by id
    seen = set()
    filtered: List[Dict[str, str]] = []
    for it in results:
        iid = it.get("id") or ""
        if iid and iid in seen:
            continue
        if iid:
            seen.add(iid)
        filtered.append(it)

    return filtered


def render_fetched_items_as_text(items: List[Dict[str, str]]) -> None:
    """
    Render items in the desired plain-text style in the UI.
    """
    if not items:
        st.write("(no items fetched)")
        return

    for _, w in enumerate(items, start=1):
        st.markdown("**Fetched Work Item**")
        if w.get("type"):
            st.write(f"Type: {w.get('type')}")
        if w.get("rootId"):
            st.write(f"Root ID: {w.get('rootId')}")
        if w.get("parentId"):
            st.write(f"Parent ID: {w.get('parentId')}")
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

        ac = w.get("acceptanceCriteria")
        if ac:
            st.markdown("**Acceptance Criteria (Plain Text):**")
            st.write(ac)

        st.markdown("---")


def _clean_cell(text: str) -> str:
    # Normalize whitespace and strip stray bullets
    if text is None:
        return ""
    t = text.replace("\r", "").strip()
    t = html.unescape(t)
    t = re.sub(r"[ \t]+\n", "\n", t)
    return t


def _parse_markdown_table_row(
    row_line: str,
    idx_id: Optional[int],
    idx_cat: Optional[int],
    idx_name: Optional[int],
    idx_prec: Optional[int],
    idx_steps: Optional[int],
    idx_out: Optional[int],
) -> List[Dict[str, str]]:
    row_line = row_line.strip()
    if not row_line.startswith("|"):
        return []
    cells = [c.strip() for c in row_line.strip("|").split("|")]
    if len(cells) < 2:
        return []

    def safe(idx: Optional[int]) -> str:
        if idx is None:
            return ""
        if 0 <= idx < len(cells):
            return cells[idx]
        return ""

    case_id = _clean_cell(safe(idx_id))
    category = _clean_cell(safe(idx_cat))
    name = _clean_cell(safe(idx_name))
    pre = _clean_cell(safe(idx_prec))
    steps = _clean_cell(safe(idx_steps))
    expected = _clean_cell(safe(idx_out))

    if all(re.fullmatch(r"[-\s:]+", c or "") for c in cells):
        return []
    if not (name or steps or expected or category):
        return []

    return [{
        "id": case_id,
        "category": category,
        "name": name,
        "preconditions": pre,
        "steps": steps,
        "expected": expected
    }]


def parse_markdown_table_tests(md_text: str) -> List[Dict[str, str]]:
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
    idx_cat = find_col(["category", "scenario type", "type"])
    idx_name = find_col(["test case name", "name", "objective", "objectives"])
    idx_prec = find_col(["precondition", "preconditions"])
    idx_steps = find_col(["step", "steps"])
    idx_out = find_col(["expected outcome", "expected result", "result", "outcome"])

    if idx_name is None or idx_steps is None or idx_out is None:
        return []

    # Find separator (---) row; data begins after it
    start_idx = None
    for i in range(1, len(table_lines)):
        if re.match(r'^\|\s*:?-{3,}', table_lines[i].strip()):
            start_idx = i + 1
            break
    if start_idx is None:
        start_idx = 2

    cases = []
    row_buf = []
    for ln in table_lines[start_idx:]:
        if ln.strip().startswith("|"):
            if row_buf:
                row = " ".join(row_buf)
                cases.extend(_parse_markdown_table_row(row, idx_id, idx_cat, idx_name, idx_prec, idx_steps, idx_out))
                row_buf = []
            row_buf.append(ln)
        else:
            row_buf.append(ln)

    if row_buf:
        row = " ".join(row_buf)
        cases.extend(_parse_markdown_table_row(row, idx_id, idx_cat, idx_name, idx_prec, idx_steps, idx_out))

    return cases


# -----------------------
# Session defaults
# -----------------------
defaults = {
    'approved_idx': None,
    'test_cases_text': None,
    'run1_status': None,
    'run2_status': None,
    'fetched_items': None,        # parsed list of dicts from plain text (filtered)
    'fetched_plain_text': None,   # raw text for reference
    'filter_debug': None,         # counts and reason summary
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
    elif not work_item_id:
        st.error(
            "Please provide a specific ADO Work Item URL with an ID "
            "(e.g., https://dev.azure.com/<org>/<project>/_workitems/edit/24027). "
            "This tool only supports ID-only lookup and will not query by area path."
        )
    else:
        try:
            # Reset states on each fetch
            st.session_state['run1_status'] = None
            st.session_state['run2_status'] = None
            st.session_state['fetched_items'] = None
            st.session_state['fetched_plain_text'] = None
            st.session_state['test_cases_text'] = None
            st.session_state['approved_idx'] = None
            st.session_state['filter_debug'] = None

            agents = AgentsClient(endpoint=PROJECT_ENDPOINT, credential=credential)
            thread = agents.threads.create()

            # ID-only input
            tool_inputs = {"workItemId": work_item_id}

            # ---- Run 1: ID-only fetch, forbid areaPath fallback and sibling expansion
            user_msg_run1 = (
                "Use the Logic App action attached to this agent to fetch Azure DevOps work items.\n"
                "HARD REQUIREMENTS:\n"
                "- ID-ONLY LOOKUP: You MUST use the provided `workItemId` to fetch the item directly.\n"
                "- Do NOT query or filter by areaPath, iterationPath, tags, or any other scope.\n"
                "- Do NOT infer or inject defaults for areaPath.\n"
                "- If `workItemId` is missing, STOP and ask the user for the exact ID. Do not run any search.\n\n"
                "EXPANSION RULES (based on the fetched item's Type):\n"
                "• If Type = Feature: return ONLY the Feature AND its direct child User Stories.\n"
                "• If Type = User Story: return ONLY the User Story AND its direct child Tasks.\n"
                "• If Type = Task: return ONLY the Task (no expansion).\n"
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

                # Parse and then FILTER strictly to root + direct children, even if root block is missing
                all_items = parse_plain_text_work_items(text1)
                filtered_items = filter_items_root_and_children(all_items, work_item_id)

                # For debug display
                root_item = next((it for it in filtered_items if it.get("id") == work_item_id), None)
                st.session_state['fetched_items'] = filtered_items
                st.session_state['filter_debug'] = {
                    "total_from_agent": len(all_items),
                    "kept_after_filter": len(filtered_items),
                    "discarded": max(0, len(all_items) - len(filtered_items)),
                    "requested_id": work_item_id,
                    "root_type": (root_item or {}).get("type", ""),
                    "root_present": bool(root_item),
                }

            # ---- Run 2: Generate Manual Test Cases (Markdown table format)
            if st.session_state['run1_status'] != "completed":
                st.warning("Run 1 did not complete. Check Agent/Logic App configuration.")
            elif not st.session_state['fetched_items']:
                st.session_state['test_cases_text'] = "(no test cases returned)"
                st.session_state['run2_status'] = "skipped (no work items found)"
            else:
                condensed = []
                for w in st.session_state['fetched_items']:
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

                user_msg_run2 = (
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

# Debug summary (what we filtered)
# dbg = st.session_state.get('filter_debug') or {}
# if dbg:
#     st.info(
#         f"Requested ID: {dbg.get('requested_id')}  •  Root present: {dbg.get('root_present')}  "
#         f"•  Root Type: {dbg.get('root_type') or '(unknown)'}  •  From agent: {dbg.get('total_from_agent')}  "
#         f"•  Kept: {dbg.get('kept_after_filter')}  •  Discarded: {dbg.get('discarded')}"
#     )

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
        # 1) Try Markdown table format first
        parsed_cases = parse_markdown_table_tests(test_cases_text)

        if parsed_cases:
            for idx, case in enumerate(parsed_cases):
                with st.container():
                    # Heading
                    title_line = case.get("name") or f"Test Case {idx+1}"
                    case_id = case.get("id")
                    heading = f"{case_id} — {title_line}" if case_id else title_line
                    st.markdown(f"### {heading}")

                    # Category (if present)
                    if case.get("category"):
                        st.markdown(f"**Category:** {case['category']}")

                    # Body
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