"""Parsing utilities for work items and test cases."""

import re
import html
from typing import List, Dict, Optional


def clean_block_text(s: Optional[str]) -> str:
    """Clean and normalize text content."""
    if not s:
        return ""
    t = s.replace("\r", "").strip()
    t = html.unescape(t)
    t = re.sub(r"[ \t]+\n", "\n", t)
    return t


def _label_rx(label: str) -> re.Pattern:
    """Build a robust regex for single-line label extraction."""
    return re.compile(
        rf"(?im)^\s*(?:[-*]\s*)?\**\s*{re.escape(label)}\s*\**\s*:\s*(.*?)\s*$"
    )


def parse_plain_text_work_items(text: str) -> List[Dict[str, str]]:
    """
    Parse work items from plain text format.

    Expected item block (markdown-tolerant):
    ### Fetched Work Item
    Type: Feature|User Story|Task
    Root ID: <id>
    Parent ID: <parent id>
    ID: <id>
    Title: <title>
    State: <state>
    Area Path: <areaPath>

    Description (Plain Text):
    <multiline>

    Acceptance Criteria (Plain Text):
    <multiline>
    ---
    """
    if not text:
        return []

    splitter = re.compile(r"(?im)^\s*#{0,6}\s*Fetched Work Item\s*$")
    blocks = splitter.split(text)
    items: List[Dict[str, str]] = []

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        type_match = _label_rx("Type").search(block)
        root_match = _label_rx("Root ID").search(block)
        parent_match = _label_rx("Parent ID").search(block)
        id_match = _label_rx("ID").search(block)
        title_match = _label_rx("Title").search(block)
        state_match = _label_rx("State").search(block)
        area_match = _label_rx("Area Path").search(block)

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
            "type": clean_block_text(type_match.group(1)) if type_match else "",
            "rootId": clean_block_text(root_match.group(1)) if root_match else "",
            "parentId": clean_block_text(parent_match.group(1)) if (parent_match and parent_match.group(1)) else "",
            "id": clean_block_text(id_match.group(1)) if id_match else "",
            "title": clean_block_text(title_match.group(1)) if title_match else "",
            "state": clean_block_text(state_match.group(1)) if state_match else "",
            "areaPath": clean_block_text(area_match.group(1)) if area_match else "",
            "description": clean_block_text(desc_match.group(1)) if desc_match else "",
            "acceptanceCriteria": clean_block_text(acc_match.group(1)) if acc_match else "",
        }

        if item["id"] or item["title"]:
            items.append(item)

    # De-duplicate by id
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
    """Determine expected child type based on root type."""
    root_type = (root_type or "").strip().lower()
    if root_type == "feature":
        return "user story"
    if root_type == "user story":
        return "task"
    return None


def filter_items_root_and_children(items: List[Dict[str, str]], requested_id: str) -> List[Dict[str, str]]:
    """
    Filter items to root and direct children only.

    Keep:
    - Root item (id == requested_id)
    - Direct children: items where parentId == requested_id
    """
    if not items:
        return []

    root = next((it for it in items if it.get("id") == requested_id), None)
    results: List[Dict[str, str]] = []

    if root:
        results.append(root)
        expected_child = _expected_child_type(root.get("type", ""))

        for it in items:
            if it is root:
                continue
            if it.get("parentId") == requested_id:
                if expected_child and it.get("type", "").strip().lower() != expected_child:
                    continue
                results.append(it)

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
        results = [it for it in items if it.get("parentId") == requested_id]
        if not results:
            results = [it for it in items if it.get("rootId") == requested_id and it.get("id") != requested_id]

    # De-duplicate
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


def _clean_cell(text: str) -> str:
    """Clean table cell content."""
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
    """Parse a single markdown table row."""
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
    """Parse test cases from markdown table format."""
    if not md_text:
        return []

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


def parse_agent2_validation_output(text: str) -> Dict:
    """
    Parse Agent-2's validation output into structured format.

    Returns a dictionary with:
    - validated_test_cases: List of validated/normalized test cases
    - automation_feasibility: Feasibility analysis per test case
    - duplicates: Detected duplicates
    - recommendations: Overall recommendations
    """
    result = {
        "validated_test_cases": [],
        "automation_feasibility": [],
        "duplicates": [],
        "recommendations": [],
        "raw_output": text
    }

    if not text:
        return result

    # Parse sections based on markdown headers
    sections = re.split(r'\n##\s+', text)

    for section in sections:
        section = section.strip()
        if not section:
            continue

        # Get section title (first line)
        lines = section.split('\n', 1)
        title = lines[0].strip().lower()
        content = lines[1] if len(lines) > 1 else ""

        if "validated" in title or "normalized" in title:
            # Parse validated test cases table
            result["validated_test_cases"] = _parse_validation_table(content)
        elif "feasibility" in title or "automatable" in title:
            result["automation_feasibility"] = _parse_feasibility_section(content)
        elif "duplicate" in title or "dedup" in title:
            result["duplicates"] = _parse_duplicates_section(content)
        elif "recommend" in title or "design" in title:
            result["recommendations"] = _parse_recommendations_section(content)

    return result


def _parse_validation_table(content: str) -> List[Dict]:
    """Parse validated test cases from content."""
    cases = []

    # Try to parse as markdown table first
    table_cases = parse_markdown_table_tests(content)
    if table_cases:
        return table_cases

    # Fallback: parse structured text blocks
    blocks = re.split(r'\n###\s+', content)
    for block in blocks:
        block = block.strip()
        if not block:
            continue

        case = {}
        # Extract fields
        id_match = re.search(r'(?:Test Case ID|ID):\s*(.+)', block, re.IGNORECASE)
        if id_match:
            case["id"] = id_match.group(1).strip()

        name_match = re.search(r'(?:Name|Title|Objective):\s*(.+)', block, re.IGNORECASE)
        if name_match:
            case["name"] = name_match.group(1).strip()

        status_match = re.search(r'(?:Status|Readiness):\s*(.+)', block, re.IGNORECASE)
        if status_match:
            case["automation_status"] = status_match.group(1).strip()

        steps_match = re.search(r'(?:Steps|Atomic Actions):\s*(.+?)(?=\n[A-Z]|\Z)', block, re.IGNORECASE | re.DOTALL)
        if steps_match:
            case["normalized_steps"] = steps_match.group(1).strip()

        if case:
            cases.append(case)

    return cases


def _parse_feasibility_section(content: str) -> List[Dict]:
    """Parse automation feasibility analysis."""
    feasibility = []

    # Parse table format
    if "|" in content:
        lines = [l for l in content.split('\n') if l.strip().startswith('|')]
        for line in lines[2:]:  # Skip header and separator
            cells = [c.strip() for c in line.strip('|').split('|')]
            if len(cells) >= 3:
                feasibility.append({
                    "test_case_id": cells[0] if len(cells) > 0 else "",
                    "step": cells[1] if len(cells) > 1 else "",
                    "classification": cells[2] if len(cells) > 2 else "",
                    "reason": cells[3] if len(cells) > 3 else ""
                })

    return feasibility


def _parse_duplicates_section(content: str) -> List[Dict]:
    """Parse duplicate detection results."""
    duplicates = []

    # Parse bullet points or numbered list
    items = re.findall(r'[-*\d.]\s+(.+)', content)
    for item in items:
        # Try to extract test case references
        match = re.search(r'(TC-[\w-]+).*(?:duplicate|overlap|similar).*?(TC-[\w-]+)?', item, re.IGNORECASE)
        if match:
            duplicates.append({
                "test_case": match.group(1),
                "duplicate_of": match.group(2) or "",
                "description": item.strip()
            })
        else:
            duplicates.append({"description": item.strip()})

    return duplicates


def _parse_recommendations_section(content: str) -> List[str]:
    """Parse recommendations."""
    recommendations = []

    # Parse bullet points
    items = re.findall(r'[-*]\s+(.+)', content)
    if items:
        recommendations.extend([i.strip() for i in items])
    else:
        # Split by newlines
        for line in content.split('\n'):
            line = line.strip()
            if line and not line.startswith('#'):
                recommendations.append(line)

    return recommendations
