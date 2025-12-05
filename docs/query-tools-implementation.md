# User Query Tools Implementation Plan

## Overview

Allow users to query nurse status, availability, shifts to fill, and other key information through the coordinator agent.

## Current State

### Existing Query Tools (in `tools/data_loader.py`)
- `get_available_nurses()` - Lists all nurses with certifications, preferences
- `get_shifts_to_fill()` - Lists shifts needing assignment
- `get_regulations()` - Returns hospital rules text

### Existing Query Tools (in `tools/history_tools.py`)
- `get_nurse_stats()` - 30-day rolling stats (fatigue, shifts, etc.)
- `get_shift_history()` - Historical roster logs
- `get_nurse_history(nurse_id)` - Individual nurse shift history
- `get_roster_by_id(roster_id)` - Specific roster details
- `list_pending_rosters()` - Drafts awaiting approval

### Gap Analysis
| Query Type | Tool Exists? | Exposed to Coordinator? |
|------------|--------------|-------------------------|
| List all nurses | ✅ `get_available_nurses` | ❌ |
| Nurse availability | ❌ | ❌ |
| Shifts to fill | ✅ `get_shifts_to_fill` | ❌ |
| Nurse stats/fatigue | ✅ `get_nurse_stats` | ❌ |
| Single nurse info | ❌ | ❌ |
| Nurse history | ✅ `get_nurse_history` | ❌ |

## Implementation

### 1. Create New Query Tools (`tools/query_tools.py`)

```python
"""
Query tools for user-facing information retrieval.
"""
import json
from datetime import datetime, timedelta
from typing import Optional
from tools.data_loader import load_nurses, generate_shifts
from tools.history_tools import _load_json, NURSE_STATS_FILE


def get_nurse_info(nurse_id: str) -> str:
    """
    Get detailed information about a specific nurse.

    Args:
        nurse_id: Nurse ID (e.g., "nurse_001") or name (e.g., "Alice")

    Returns:
        Formatted nurse profile with certifications, preferences, and current stats.
    """
    nurses = load_nurses()
    stats = _load_json(NURSE_STATS_FILE)

    # Find nurse by ID or name
    nurse = None
    for n in nurses:
        if n.id == nurse_id or n.name.lower() == nurse_id.lower():
            nurse = n
            break

    if not nurse:
        return f"Nurse '{nurse_id}' not found. Use list_nurses() to see all nurses."

    nurse_stats = stats.get(nurse.id, {})
    fatigue = nurse_stats.get("fatigue_score", 0)

    # Fatigue indicator
    if fatigue >= 0.7:
        fatigue_indicator = "🔴 HIGH RISK - Reduce shifts"
    elif fatigue >= 0.4:
        fatigue_indicator = "🟡 Moderate - Monitor closely"
    else:
        fatigue_indicator = "🟢 Good"

    result = f"NURSE PROFILE: {nurse.name}\n" + "=" * 50 + "\n\n"
    result += f"ID: {nurse.id}\n"
    result += f"Seniority: {nurse.seniority_level}\n"
    result += f"Contract: {nurse.contract_type}\n"
    result += f"Certifications: {', '.join(nurse.certifications)}\n\n"

    result += "PREFERENCES:\n"
    result += f"  Avoid night shifts: {'Yes' if nurse.preferences.avoid_night_shifts else 'No'}\n"
    result += f"  Preferred days: {', '.join(nurse.preferences.preferred_days) or 'None specified'}\n"
    if nurse.preferences.adhoc_requests:
        result += f"  Active requests: {', '.join(nurse.preferences.adhoc_requests)}\n"

    result += "\nCURRENT STATUS:\n"
    result += f"  Last shift: {nurse_stats.get('last_shift_date', 'N/A')}\n"
    result += f"  Consecutive shifts: {nurse_stats.get('consecutive_shifts_current', 0)}\n"
    result += f"  Shifts (30d): {nurse_stats.get('total_shifts_30d', 0)}\n"
    result += f"  Weekend shifts (30d): {nurse_stats.get('weekend_shifts_30d', 0)}\n"
    result += f"  Night shifts (30d): {nurse_stats.get('night_shifts_30d', 0)}\n"
    result += f"  Fatigue: {fatigue:.2f} {fatigue_indicator}\n"

    return result


def list_nurses(filter_by: str = "") -> str:
    """
    List all nurses with optional filtering.

    Args:
        filter_by: Optional filter - "senior", "available", "fatigued", "icu", etc.

    Returns:
        Formatted list of nurses matching the filter.
    """
    nurses = load_nurses()
    stats = _load_json(NURSE_STATS_FILE)

    # Apply filters
    filtered = nurses
    filter_desc = "All Nurses"

    if filter_by:
        filter_lower = filter_by.lower()
        if filter_lower == "senior":
            filtered = [n for n in nurses if n.seniority_level == "Senior"]
            filter_desc = "Senior Nurses"
        elif filter_lower == "junior":
            filtered = [n for n in nurses if n.seniority_level == "Junior"]
            filter_desc = "Junior Nurses"
        elif filter_lower == "available" or filter_lower == "fresh":
            # Fatigue < 0.4
            filtered = [n for n in nurses if stats.get(n.id, {}).get("fatigue_score", 0) < 0.4]
            filter_desc = "Available Nurses (Low Fatigue)"
        elif filter_lower == "fatigued" or filter_lower == "tired":
            filtered = [n for n in nurses if stats.get(n.id, {}).get("fatigue_score", 0) >= 0.4]
            filter_desc = "Fatigued Nurses"
        elif filter_lower == "fulltime":
            filtered = [n for n in nurses if n.contract_type == "FullTime"]
            filter_desc = "FullTime Nurses"
        elif filter_lower == "parttime":
            filtered = [n for n in nurses if n.contract_type == "PartTime"]
            filter_desc = "PartTime Nurses"
        elif filter_lower == "casual":
            filtered = [n for n in nurses if n.contract_type == "Casual"]
            filter_desc = "Casual Nurses"
        elif filter_lower in ["icu", "acls", "bls"]:
            cert = filter_lower.upper()
            filtered = [n for n in nurses if cert in n.certifications]
            filter_desc = f"Nurses with {cert} Certification"

    if not filtered:
        return f"No nurses found matching filter: {filter_by}"

    result = f"{filter_desc.upper()}\n" + "=" * 50 + "\n\n"

    for n in filtered:
        nurse_stats = stats.get(n.id, {})
        fatigue = nurse_stats.get("fatigue_score", 0)

        if fatigue >= 0.7:
            status = "🔴"
        elif fatigue >= 0.4:
            status = "🟡"
        else:
            status = "🟢"

        result += f"{status} {n.name} ({n.id})\n"
        result += f"   {n.seniority_level} | {n.contract_type} | {', '.join(n.certifications)}\n"

    result += f"\nTotal: {len(filtered)} nurses\n"
    return result


def get_nurse_availability(date: str = "") -> str:
    """
    Get nurse availability for a specific date or upcoming week.

    Args:
        date: Date in YYYY-MM-DD format (defaults to today)

    Returns:
        Availability summary showing who can work and any constraints.
    """
    nurses = load_nurses()
    stats = _load_json(NURSE_STATS_FILE)

    # Parse date
    if date:
        try:
            check_date = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            return f"Invalid date format: {date}. Use YYYY-MM-DD."
    else:
        check_date = datetime.now()

    day_name = check_date.strftime("%A")
    is_weekend = check_date.weekday() >= 5

    result = f"NURSE AVAILABILITY: {check_date.strftime('%Y-%m-%d')} ({day_name})\n"
    result += "=" * 50 + "\n\n"

    available = []
    limited = []
    unavailable = []

    for n in nurses:
        nurse_stats = stats.get(n.id, {})
        fatigue = nurse_stats.get("fatigue_score", 0)
        consecutive = nurse_stats.get("consecutive_shifts_current", 0)

        constraints = []

        # Check consecutive shift limit
        if consecutive >= 3:
            constraints.append("Max consecutive shifts reached")

        # Check fatigue
        if fatigue >= 0.7:
            constraints.append("High fatigue risk")

        # Check adhoc time-off requests
        if n.preferences.adhoc_requests:
            for req in n.preferences.adhoc_requests:
                if req.startswith("Off_"):
                    off_date = req.split("_")[1] if len(req.split("_")) > 1 else ""
                    if off_date == check_date.strftime("%Y-%m-%d"):
                        constraints.append("Time-off requested")

        # Check preferences
        if n.preferences.preferred_days and day_name not in n.preferences.preferred_days:
            constraints.append(f"Prefers: {', '.join(n.preferences.preferred_days)}")

        # Categorize
        if "Max consecutive shifts reached" in constraints or "Time-off requested" in constraints:
            unavailable.append((n, constraints))
        elif constraints:
            limited.append((n, constraints))
        else:
            available.append(n)

    # Format output
    result += f"✅ AVAILABLE ({len(available)}):\n"
    for n in available:
        result += f"   {n.name} - {n.seniority_level}, {', '.join(n.certifications)}\n"

    result += f"\n⚠️ LIMITED AVAILABILITY ({len(limited)}):\n"
    for n, cons in limited:
        result += f"   {n.name} - {'; '.join(cons)}\n"

    result += f"\n❌ UNAVAILABLE ({len(unavailable)}):\n"
    for n, cons in unavailable:
        result += f"   {n.name} - {'; '.join(cons)}\n"

    if is_weekend:
        result += "\n📅 Note: This is a weekend - fair distribution rules apply.\n"

    return result


def get_upcoming_shifts(days: int = 7) -> str:
    """
    Get shifts that need to be filled for the upcoming period.

    Args:
        days: Number of days to look ahead (default: 7)

    Returns:
        Formatted list of upcoming shifts with requirements.
    """
    from tools.data_loader import get_shifts_to_fill
    return get_shifts_to_fill(num_days=days)


def get_staffing_summary() -> str:
    """
    Get a high-level staffing summary including coverage gaps and alerts.

    Returns:
        Summary of current staffing status, fatigue levels, and potential issues.
    """
    nurses = load_nurses()
    stats = _load_json(NURSE_STATS_FILE)
    shifts = generate_shifts(num_days=7)

    result = "STAFFING SUMMARY\n" + "=" * 50 + "\n\n"

    # Nurse counts by type
    by_seniority = {"Senior": 0, "Mid": 0, "Junior": 0}
    by_contract = {"FullTime": 0, "PartTime": 0, "Casual": 0}
    by_fatigue = {"good": 0, "moderate": 0, "high": 0}

    for n in nurses:
        by_seniority[n.seniority_level] = by_seniority.get(n.seniority_level, 0) + 1
        by_contract[n.contract_type] = by_contract.get(n.contract_type, 0) + 1

        fatigue = stats.get(n.id, {}).get("fatigue_score", 0)
        if fatigue >= 0.7:
            by_fatigue["high"] += 1
        elif fatigue >= 0.4:
            by_fatigue["moderate"] += 1
        else:
            by_fatigue["good"] += 1

    result += "WORKFORCE:\n"
    result += f"  Total nurses: {len(nurses)}\n"
    result += f"  By seniority: Senior={by_seniority['Senior']}, Mid={by_seniority['Mid']}, Junior={by_seniority['Junior']}\n"
    result += f"  By contract: FullTime={by_contract['FullTime']}, PartTime={by_contract['PartTime']}, Casual={by_contract['Casual']}\n"

    result += "\nFATIGUE STATUS:\n"
    result += f"  🟢 Good: {by_fatigue['good']} nurses\n"
    result += f"  🟡 Moderate: {by_fatigue['moderate']} nurses\n"
    result += f"  🔴 High Risk: {by_fatigue['high']} nurses\n"

    # Shift requirements
    icu_shifts = len([s for s in shifts if s["ward"] == "ICU"])
    emergency_shifts = len([s for s in shifts if s["ward"] == "Emergency"])
    general_shifts = len([s for s in shifts if s["ward"] == "General"])

    result += "\nUPCOMING SHIFTS (7 days):\n"
    result += f"  Total: {len(shifts)} shifts\n"
    result += f"  ICU: {icu_shifts} | Emergency: {emergency_shifts} | General: {general_shifts}\n"

    # Coverage check
    icu_certified = len([n for n in nurses if "ICU" in n.certifications])
    emergency_certified = len([n for n in nurses if "ACLS" in n.certifications and "BLS" in n.certifications])
    senior_count = by_seniority["Senior"]

    result += "\nCOVERAGE CHECK:\n"
    result += f"  ICU-certified nurses: {icu_certified}\n"
    result += f"  Emergency-certified (ACLS+BLS): {emergency_certified}\n"
    result += f"  Senior nurses (required each shift): {senior_count}\n"

    # Alerts
    alerts = []
    if by_fatigue["high"] > 0:
        high_fatigue_names = [n.name for n in nurses if stats.get(n.id, {}).get("fatigue_score", 0) >= 0.7]
        alerts.append(f"🔴 {by_fatigue['high']} nurse(s) at high fatigue: {', '.join(high_fatigue_names)}")

    if senior_count < 2:
        alerts.append("⚠️ Low senior nurse coverage - may impact shift requirements")

    if alerts:
        result += "\n⚠️ ALERTS:\n"
        for alert in alerts:
            result += f"  {alert}\n"
    else:
        result += "\n✅ No staffing alerts.\n"

    return result
```

### 2. Update Coordinator Agent (`agents/coordinator.py`)

Add query tools to the coordinator:

```python
# Add imports
from tools.query_tools import (
    get_nurse_info,
    list_nurses,
    get_nurse_availability,
    get_upcoming_shifts,
    get_staffing_summary
)
from tools.history_tools import (
    get_nurse_stats,
    get_shift_history,
    get_nurse_history
)

COORDINATOR_INSTRUCTION = """
You are the RosteringCoordinator for a nurse rostering system.

## Query Capabilities

You can answer questions about:
- **Nurses**: list_nurses(), get_nurse_info(nurse_id), get_nurse_availability(date)
- **Stats**: get_nurse_stats(), get_staffing_summary()
- **Shifts**: get_upcoming_shifts(days), get_shift_history(weeks)
- **History**: get_nurse_history(nurse_id, weeks)
- **Rosters**: list_pending_rosters()

## Roster Management

For roster generation, delegate to RosteringWorkflow sub-agent.
For approvals: finalize_roster(roster_id), reject_roster(roster_id, reason)

## Example Queries

User: "Show me all senior nurses"
→ list_nurses(filter_by="senior")

User: "Is Alice available tomorrow?"
→ get_nurse_availability(date="2025-12-05") or get_nurse_info("Alice")

User: "What shifts need to be filled?"
→ get_upcoming_shifts()

User: "Give me a staffing overview"
→ get_staffing_summary()
"""

def create_coordinator_agent(model_name: str = "gemini-2.5-pro") -> LlmAgent:
    workflow = create_rostering_workflow()

    return LlmAgent(
        name="RosteringCoordinator",
        model=model_name,
        instruction=COORDINATOR_INSTRUCTION,
        tools=[
            # Query tools
            list_nurses,
            get_nurse_info,
            get_nurse_availability,
            get_upcoming_shifts,
            get_staffing_summary,
            get_nurse_stats,
            get_shift_history,
            get_nurse_history,
            # Management tools
            list_pending_rosters,
            finalize_roster,
            reject_roster
        ],
        sub_agents=[workflow]
    )
```

### 3. File Changes Summary

| File | Action | Description |
|------|--------|-------------|
| `tools/query_tools.py` | CREATE | New query tools module |
| `agents/coordinator.py` | UPDATE | Add query tools to coordinator |

### 4. Query Tool Reference

| Tool | Purpose | Example Query |
|------|---------|---------------|
| `list_nurses(filter_by)` | List nurses with optional filter | "Show ICU nurses", "Who's fatigued?" |
| `get_nurse_info(nurse_id)` | Detailed nurse profile | "Tell me about Alice" |
| `get_nurse_availability(date)` | Who can work on a date | "Who's available Friday?" |
| `get_upcoming_shifts(days)` | Shifts needing assignment | "What shifts need filling?" |
| `get_staffing_summary()` | High-level overview | "Staffing status", "Coverage gaps" |
| `get_nurse_stats()` | All nurse statistics | "Fatigue levels", "30-day stats" |
| `get_nurse_history(nurse_id)` | Individual shift history | "Alice's recent shifts" |
| `get_shift_history(weeks)` | Roster history logs | "Past rosters" |

### 5. Filter Options for `list_nurses()`

| Filter | Description |
|--------|-------------|
| `"senior"` | Senior seniority level |
| `"junior"` | Junior seniority level |
| `"available"` / `"fresh"` | Fatigue < 0.4 |
| `"fatigued"` / `"tired"` | Fatigue >= 0.4 |
| `"fulltime"` | FullTime contract |
| `"parttime"` | PartTime contract |
| `"casual"` | Casual contract |
| `"icu"` | ICU certified |
| `"acls"` | ACLS certified |
| `"bls"` | BLS certified |
