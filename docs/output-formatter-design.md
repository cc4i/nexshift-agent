# Universal Output Formatter Design

## Problem

Tool outputs use `\n` for line breaks, but the chat UI collapses them into a single line, making data unreadable.

## Solution

Use ADK `after_agent_callback` on the **Coordinator agent only** to format the final response before it reaches the user. This is the simplest approach - one callback, one place.

## Architecture

```
User Request
     │
     ▼
┌─────────────────────────────────────────────────────────┐
│              RosteringCoordinator                       │
│                                                         │
│  1. Process request (tools, sub-agents, LLM)            │
│  2. Generate response                                   │
│                     │                                   │
│                     ▼                                   │
│  ┌───────────────────────────────────────────────────┐  │
│  │         after_agent_callback                      │  │
│  │  ┌─────────────────────────────────────────────┐  │  │
│  │  │         format_output()                     │  │  │
│  │  │  • Detect data type in response             │  │  │
│  │  │  • Convert to markdown (tables, lists...)   │  │  │
│  │  │  • Return formatted Content                 │  │  │
│  │  └─────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
     │
     ▼
Formatted Response to User
```

## Callback Implementation

### ADK Callback Signature

```python
# after_agent_callback signature
def after_agent_callback(
    callback_context: CallbackContext,
    content: types.Content
) -> Optional[types.Content]:
    """
    Called after agent generates response, before returning to user.

    Args:
        callback_context: Context with agent_name, session state, etc.
        content: The agent's response (role="model", parts=[...])

    Returns:
        None: Use original content
        types.Content: Replace with formatted content
    """
```

### Implementation

```python
# callbacks/format_output.py

from typing import Optional
from google.genai import types
from google.adk.agents.callback_context import CallbackContext
from utils.output_formatter import OutputFormatter


def format_agent_output(
    callback_context: CallbackContext,
    content: types.Content
) -> Optional[types.Content]:
    """
    Format the coordinator's final response for chat display.

    Detects data patterns in the response and applies appropriate
    markdown formatting (tables, sections, calendar views, etc.)
    """
    if not content or not content.parts:
        return None

    # Get the text content
    original_text = ""
    for part in content.parts:
        if hasattr(part, 'text') and part.text:
            original_text += part.text

    if not original_text:
        return None

    # Format the output
    formatter = OutputFormatter()
    formatted_text = formatter.format(original_text)

    # If no changes, return None to use original
    if formatted_text == original_text:
        return None

    # Return new Content with formatted text
    return types.Content(
        role="model",
        parts=[types.Part(text=formatted_text)]
    )
```

### Register Callback on Coordinator

```python
# agents/coordinator.py

from callbacks.format_output import format_agent_output

def create_coordinator_agent(model_name: str = "gemini-2.5-pro") -> LlmAgent:
    workflow = create_rostering_workflow()

    return LlmAgent(
        name="RosteringCoordinator",
        model=model_name,
        instruction=COORDINATOR_INSTRUCTION,
        tools=[...],
        sub_agents=[workflow],
        after_agent_callback=format_agent_output  # <-- Single callback here
    )
```

## Output Formatter Logic

The `OutputFormatter` class detects content type and applies formatting:

```python
# utils/output_formatter.py

import re
from typing import Optional
from datetime import datetime, timedelta


class OutputFormatter:
    """Converts agent output to well-formatted markdown."""

    def format(self, text: str) -> str:
        """
        Detect content type and apply appropriate formatting.
        """
        # Try each formatter in order
        if self._is_nurse_list(text):
            return self._format_nurse_list(text)
        elif self._is_roster(text):
            return self._format_roster(text)
        elif self._is_availability(text):
            return self._format_availability(text)
        elif self._is_nurse_profile(text):
            return self._format_nurse_profile(text)
        elif self._is_staffing_summary(text):
            return self._format_staffing_summary(text)
        elif self._is_shifts_list(text):
            return self._format_shifts_list(text)

        # No special formatting needed
        return text

    # Detection methods
    def _is_nurse_list(self, text: str) -> bool:
        return bool(re.search(r'\[OK\].*nurse_\d+|NURSES.*\n.*Senior|Junior|Mid', text, re.I))

    def _is_roster(self, text: str) -> bool:
        return bool(re.search(r'roster_\d+|ROSTER.*assignments|nurse_id.*shift_id', text, re.I))

    def _is_availability(self, text: str) -> bool:
        return bool(re.search(r'AVAILABILITY|AVAILABLE.*UNAVAILABLE|Limited Availability', text, re.I))

    def _is_nurse_profile(self, text: str) -> bool:
        return bool(re.search(r'NURSE PROFILE|Seniority:.*Contract:.*Certifications:', text, re.I))

    def _is_staffing_summary(self, text: str) -> bool:
        return bool(re.search(r'STAFFING SUMMARY|WORKFORCE.*FATIGUE STATUS', text, re.I))

    def _is_shifts_list(self, text: str) -> bool:
        return bool(re.search(r'SHIFTS TO BE FILLED|shift_\d+.*Ward', text, re.I))

    # Formatting methods (see detailed implementations below)
    def _format_nurse_list(self, text: str) -> str: ...
    def _format_roster(self, text: str) -> str: ...
    def _format_availability(self, text: str) -> str: ...
    def _format_nurse_profile(self, text: str) -> str: ...
    def _format_staffing_summary(self, text: str) -> str: ...
    def _format_shifts_list(self, text: str) -> str: ...
```

## Output Types & Best Formats

| Data Type | Detection Pattern | Best Format |
|-----------|-------------------|-------------|
| Nurse list | `[OK]`, `nurse_xxx`, seniority levels | Markdown table |
| Nurse profile | `NURSE PROFILE`, key-value pairs | Sectioned key-value |
| Availability | `AVAILABLE`, `UNAVAILABLE` | Categorized sections |
| Roster | `roster_xxx`, assignments | **7-day calendar table** |
| Shifts list | `shift_xxx`, ward, time | Grouped table by date |
| Staffing summary | `WORKFORCE`, `FATIGUE` | Stats + alerts |
| Simple message | No pattern match | Pass through unchanged |

## Benefits of after_agent_callback Approach

1. **Single point of control** - One callback on coordinator only
2. **Clean tools** - Tools return raw data, no formatting logic
3. **Easy to modify** - Change formatting without touching tools
4. **Consistent output** - All responses go through same formatter
5. **Optional** - Returns `None` to skip formatting when not needed

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `callbacks/format_output.py` | CREATE | The after_agent_callback |
| `utils/output_formatter.py` | CREATE | Formatter with detection + formatting logic |
| `agents/coordinator.py` | UPDATE | Register the callback |

## Implementation Details

### 1. Create `utils/output_formatter.py`

```python
"""
Universal output formatter for chat-friendly rendering.
Converts structured data to markdown that displays correctly in chat UI.
"""
from typing import List, Dict, Any, Optional
from enum import Enum


class OutputFormat(Enum):
    TABLE = "table"
    KEY_VALUE = "key_value"
    SECTIONED_LIST = "sectioned_list"
    SUMMARY = "summary"
    TEXT = "text"


def format_table(
    headers: List[str],
    rows: List[List[str]],
    title: Optional[str] = None
) -> str:
    """Format data as markdown table."""
    result = ""
    if title:
        result += f"## {title}\n\n"

    # Header row
    result += "| " + " | ".join(headers) + " |\n"
    # Separator
    result += "|" + "|".join(["---"] * len(headers)) + "|\n"
    # Data rows
    for row in rows:
        result += "| " + " | ".join(str(cell) for cell in row) + " |\n"

    return result


def format_key_value(
    data: Dict[str, Any],
    title: Optional[str] = None,
    sections: Optional[Dict[str, Dict[str, Any]]] = None
) -> str:
    """Format as key-value pairs with optional sections."""
    result = ""
    if title:
        result += f"## {title}\n\n"

    if sections:
        for section_name, section_data in sections.items():
            result += f"### {section_name}\n\n"
            for key, value in section_data.items():
                result += f"- **{key}**: {value}\n"
            result += "\n"
    else:
        for key, value in data.items():
            result += f"- **{key}**: {value}\n"

    return result


def format_sectioned_list(
    sections: Dict[str, List[str]],
    title: Optional[str] = None
) -> str:
    """Format as sections with bullet lists."""
    result = ""
    if title:
        result += f"## {title}\n\n"

    for section_name, items in sections.items():
        result += f"### {section_name}\n\n"
        for item in items:
            result += f"- {item}\n"
        result += "\n"

    return result


def format_summary(
    title: str,
    stats: Dict[str, Any],
    table_data: Optional[tuple] = None,  # (headers, rows)
    alerts: Optional[List[str]] = None
) -> str:
    """Format mixed summary with stats, optional table, and alerts."""
    result = f"## {title}\n\n"

    # Stats section
    for key, value in stats.items():
        result += f"- **{key}**: {value}\n"
    result += "\n"

    # Optional table
    if table_data:
        headers, rows = table_data
        result += format_table(headers, rows)
        result += "\n"

    # Alerts
    if alerts:
        result += "### Alerts\n\n"
        for alert in alerts:
            result += f"- {alert}\n"

    return result


# Convenience functions for common outputs

def format_nurses_list(nurses: List[Dict], title: str = "Nurses") -> str:
    """Format nurse list as table."""
    headers = ["Status", "Name", "ID", "Level", "Contract", "Certifications"]
    rows = []
    for n in nurses:
        fatigue = n.get("fatigue_score", 0)
        status = "🔴" if fatigue >= 0.7 else "🟡" if fatigue >= 0.4 else "🟢"
        rows.append([
            status,
            n["name"],
            n["id"],
            n["seniority_level"],
            n["contract_type"],
            ", ".join(n.get("certifications", []))
        ])
    return format_table(headers, rows, title)


def format_nurse_profile(nurse: Dict, stats: Dict) -> str:
    """Format single nurse profile."""
    fatigue = stats.get("fatigue_score", 0)
    fatigue_status = "🔴 High Risk" if fatigue >= 0.7 else "🟡 Moderate" if fatigue >= 0.4 else "🟢 Good"

    sections = {
        "Basic Info": {
            "ID": nurse["id"],
            "Seniority": nurse["seniority_level"],
            "Contract": nurse["contract_type"],
            "Certifications": ", ".join(nurse.get("certifications", []))
        },
        "Preferences": {
            "Avoid Night Shifts": "Yes" if nurse.get("preferences", {}).get("avoid_night_shifts") else "No",
            "Preferred Days": ", ".join(nurse.get("preferences", {}).get("preferred_days", [])) or "None"
        },
        "Current Status": {
            "Last Shift": stats.get("last_shift_date", "N/A"),
            "Consecutive Shifts": stats.get("consecutive_shifts_current", 0),
            "Shifts (30d)": stats.get("total_shifts_30d", 0),
            "Weekend Shifts": stats.get("weekend_shifts_30d", 0),
            "Fatigue": f"{fatigue:.2f} {fatigue_status}"
        }
    }
    return format_key_value({}, title=f"Nurse: {nurse['name']}", sections=sections)


def format_availability(date: str, available: List, limited: List, unavailable: List) -> str:
    """Format availability by category."""
    sections = {
        f"✅ Available ({len(available)})": [
            f"{n['name']} - {n['seniority_level']}, {', '.join(n.get('certifications', []))}"
            for n in available
        ],
        f"⚠️ Limited ({len(limited)})": [
            f"{n['name']} - {n['constraint']}"
            for n in limited
        ],
        f"❌ Unavailable ({len(unavailable)})": [
            f"{n['name']} - {n['constraint']}"
            for n in unavailable
        ]
    }
    return format_sectioned_list(sections, title=f"Availability: {date}")


def format_shifts_list(shifts: List[Dict], title: str = "Shifts") -> str:
    """Format shifts as table grouped by date."""
    headers = ["ID", "Ward", "Time", "Required Certs", "Min Level"]
    rows = []
    current_date = None

    for s in shifts:
        # Add date separator row
        if s.get("date") != current_date:
            current_date = s.get("date")
            rows.append([f"**{current_date}**", "", "", "", ""])

        rows.append([
            s["id"],
            s["ward"],
            f"{s.get('start', '')} - {s.get('end', '')}",
            ", ".join(s.get("required_certs", [])),
            s.get("min_level", "")
        ])

    return format_table(headers, rows, title)


def format_roster(roster: Dict, nurses: List[Dict], shifts: List[Dict]) -> str:
    """
    Format roster as 7-day calendar view.
    Splits into multiple tables if period > 7 days.

    Args:
        roster: Roster dict with assignments
        nurses: List of nurse dicts for name lookup
        shifts: List of shift dicts for ward/time lookup
    """
    metadata = roster.get("metadata", {})
    assignments = roster.get("assignments", [])
    period = roster.get("period", {})

    # Build lookup maps
    nurse_map = {n["id"]: n["name"] for n in nurses}
    shift_map = {s["id"]: s for s in shifts}

    # Parse period dates
    start_date = datetime.strptime(period.get("start", ""), "%Y-%m-%d")
    end_date = datetime.strptime(period.get("end", ""), "%Y-%m-%d")
    total_days = (end_date - start_date).days + 1

    # Header with stats
    result = f"## Roster: {roster.get('id', 'Unknown')}\n\n"
    result += f"**Period**: {period.get('start')} to {period.get('end')} | "
    result += f"**Status**: {roster.get('status', 'unknown').upper()} | "
    result += f"**Compliance**: {metadata.get('compliance_status', 'N/A')} | "
    result += f"**Empathy**: {metadata.get('empathy_score', 'N/A')}\n\n"

    # Build assignment lookup: {nurse_id: {date_str: shift_info}}
    assignment_map = {}
    for a in assignments:
        nurse_id = a.get("nurse_id")
        shift_id = a.get("shift_id")
        shift = shift_map.get(shift_id, {})

        # Extract date from shift
        shift_start = shift.get("start_time", "")
        if shift_start:
            date_str = shift_start[:10]  # "2025-12-04T08:00:00" -> "2025-12-04"
        else:
            date_str = a.get("date", "")

        if nurse_id not in assignment_map:
            assignment_map[nurse_id] = {}

        # Format: Ward-ShiftType (e.g., "ICU-D", "ER-N")
        ward = shift.get("ward", "?")[:3]  # Truncate ward name
        start_hour = int(shift.get("start", "00:00").split(":")[0]) if shift.get("start") else 0
        if start_hour >= 20 or start_hour < 6:
            shift_type = "N"  # Night
        elif start_hour >= 16:
            shift_type = "E"  # Evening
        else:
            shift_type = "D"  # Day

        assignment_map[nurse_id][date_str] = f"{ward}-{shift_type}"

    # Get all nurses in this roster
    roster_nurse_ids = sorted(assignment_map.keys())

    # Split into 7-day chunks
    chunk_size = 7
    num_chunks = (total_days + chunk_size - 1) // chunk_size

    for chunk_idx in range(num_chunks):
        chunk_start = start_date + timedelta(days=chunk_idx * chunk_size)
        chunk_end = min(chunk_start + timedelta(days=chunk_size - 1), end_date)
        chunk_days = (chunk_end - chunk_start).days + 1

        if num_chunks > 1:
            result += f"### Week {chunk_idx + 1}\n\n"

        # Build header row with day names and dates
        headers = ["Nurse"]
        dates_in_chunk = []
        for i in range(chunk_days):
            d = chunk_start + timedelta(days=i)
            dates_in_chunk.append(d.strftime("%Y-%m-%d"))
            day_abbr = d.strftime("%a")  # Mon, Tue, etc.
            day_num = d.strftime("%d")   # 04, 05, etc.
            headers.append(f"{day_abbr} {day_num}")
        headers.append("Total")

        # Build rows
        rows = []
        for nurse_id in roster_nurse_ids:
            nurse_name = nurse_map.get(nurse_id, nurse_id)
            row = [nurse_name]
            nurse_total = 0

            for date_str in dates_in_chunk:
                cell = assignment_map.get(nurse_id, {}).get(date_str, "-")
                row.append(cell)
                if cell != "-":
                    nurse_total += 1

            row.append(str(nurse_total))
            rows.append(row)

        result += format_table(headers, rows)
        result += "\n"

    # Legend
    result += "**Legend**: D=Day(08-16) | E=Evening(16-00) | N=Night(20-04) | "
    result += "ICU=ICU | Gen=General | Eme=Emergency\n"

    return result


def format_staffing_summary(
    workforce: Dict,
    fatigue: Dict,
    shifts: Dict,
    coverage: Dict,
    alerts: List[str]
) -> str:
    """Format staffing summary."""
    stats = {
        "Total Nurses": workforce.get("total", 0),
        "By Seniority": f"Senior: {workforce.get('senior', 0)}, Mid: {workforce.get('mid', 0)}, Junior: {workforce.get('junior', 0)}",
        "Fatigue Status": f"🟢 {fatigue.get('good', 0)} | 🟡 {fatigue.get('moderate', 0)} | 🔴 {fatigue.get('high', 0)}",
        "Upcoming Shifts": f"{shifts.get('total', 0)} (ICU: {shifts.get('icu', 0)}, Emergency: {shifts.get('emergency', 0)}, General: {shifts.get('general', 0)})",
        "ICU-Certified": coverage.get("icu_certified", 0),
        "Emergency-Certified": coverage.get("emergency_certified", 0)
    }

    return format_summary(
        title="Staffing Summary",
        stats=stats,
        alerts=alerts if alerts else None
    )
```

## Example Outputs

### 7-Day Roster Calendar View

```markdown
## Roster: roster_202512041530

**Period**: 2025-12-04 to 2025-12-10 | **Status**: DRAFT | **Compliance**: PASS | **Empathy**: 0.85

| Nurse | Wed 04 | Thu 05 | Fri 06 | Sat 07 | Sun 08 | Mon 09 | Tue 10 | Total |
|-------|--------|--------|--------|--------|--------|--------|--------|-------|
| Alice | ICU-D | - | Eme-N | - | - | ICU-D | - | 3 |
| Bob | - | Gen-D | - | ICU-E | - | - | Gen-D | 3 |
| Charlie | ICU-E | - | - | Eme-N | ICU-D | - | - | 3 |
| Diana | - | ICU-D | ICU-E | - | - | Eme-N | - | 3 |
| Edward | Gen-D | - | - | - | Gen-D | - | ICU-E | 3 |

**Legend**: D=Day(08-16) | E=Evening(16-00) | N=Night(20-04) | ICU=ICU | Gen=General | Eme=Emergency
```

### 14-Day Roster (Multiple Tables)

```markdown
## Roster: roster_202512041530

**Period**: 2025-12-04 to 2025-12-17 | **Status**: DRAFT | **Compliance**: PASS | **Empathy**: 0.82

### Week 1

| Nurse | Wed 04 | Thu 05 | Fri 06 | Sat 07 | Sun 08 | Mon 09 | Tue 10 | Total |
|-------|--------|--------|--------|--------|--------|--------|--------|-------|
| Alice | ICU-D | - | Eme-N | - | - | ICU-D | - | 3 |
| Bob | - | Gen-D | - | ICU-E | - | - | Gen-D | 3 |
| Charlie | ICU-E | - | - | Eme-N | ICU-D | - | - | 3 |

### Week 2

| Nurse | Wed 11 | Thu 12 | Fri 13 | Sat 14 | Sun 15 | Mon 16 | Tue 17 | Total |
|-------|--------|--------|--------|--------|--------|--------|--------|-------|
| Alice | - | ICU-D | - | - | Eme-N | - | ICU-D | 3 |
| Bob | Gen-D | - | ICU-E | - | - | Gen-D | - | 3 |
| Charlie | - | - | Eme-N | ICU-D | - | - | ICU-E | 3 |

**Legend**: D=Day(08-16) | E=Evening(16-00) | N=Night(20-04) | ICU=ICU | Gen=General | Eme=Emergency
```

### Nurse List Table

```markdown
## Available Nurses (Low Fatigue)

| Status | Name | ID | Level | Contract | Certifications |
|--------|------|----|-------|----------|----------------|
| 🟢 | Alice | nurse_001 | Senior | FullTime | ACLS, BLS, ICU |
| 🟢 | Bob | nurse_002 | Junior | FullTime | BLS, ACLS |
| 🟢 | Charlie | nurse_003 | Mid | FullTime | ACLS, BLS, ICU |
| 🟢 | Edward | nurse_005 | Mid | FullTime | BLS, ACLS |

**Total: 4 nurses**
```

### Nurse Profile

```markdown
## Nurse: Alice

### Basic Info

- **ID**: nurse_001
- **Seniority**: Senior
- **Contract**: FullTime
- **Certifications**: ACLS, BLS, ICU

### Preferences

- **Avoid Night Shifts**: Yes
- **Preferred Days**: Monday, Tuesday, Wednesday

### Current Status

- **Last Shift**: 2025-12-03
- **Consecutive Shifts**: 2
- **Shifts (30d)**: 12
- **Weekend Shifts**: 3
- **Fatigue**: 0.35 🟢 Good
```

### Availability View

```markdown
## Availability: 2025-12-05 (Thursday)

### ✅ Available (6)

- Alice - Senior, ACLS, BLS, ICU
- Bob - Junior, BLS, ACLS
- Charlie - Mid, ACLS, BLS, ICU
- Edward - Mid, BLS, ACLS
- Hannah - Mid, ACLS, BLS, ICU
- Julia - Senior, ACLS, BLS, ICU

### ⚠️ Limited (2)

- Diana - High fatigue risk
- George - Prefers: Monday, Tuesday

### ❌ Unavailable (2)

- Fiona - Max consecutive shifts reached
- Ivan - Time-off requested
```

### Staffing Summary

```markdown
## Staffing Summary

- **Total Nurses**: 10
- **By Seniority**: Senior: 4, Mid: 3, Junior: 3
- **Fatigue Status**: 🟢 8 | 🟡 1 | 🔴 1
- **Upcoming Shifts**: 28 (ICU: 14, Emergency: 7, General: 7)
- **ICU-Certified**: 6
- **Emergency-Certified**: 8

### Alerts

- 🔴 1 nurse at high fatigue: Diana
```

## Benefits

1. **Consistent formatting** - All outputs use same markdown patterns
2. **Readable in chat** - Tables and sections render properly
3. **Centralized logic** - Format changes in one place
4. **Type-aware** - Chooses best format per data type
5. **Extensible** - Easy to add new formats
6. **Calendar view** - Roster displayed as intuitive 7-day grid
7. **Multi-week support** - Long rosters split into weekly tables
