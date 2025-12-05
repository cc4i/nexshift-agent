"""
HRIS Management Tools - Add, update, and manage nurse records.

These tools modify the mock_hris.json file to add new nurses,
promote existing nurses, and update certifications.
"""

import json
import os
from datetime import datetime
from typing import List, Optional

DATA_DIR = os.path.join(os.path.dirname(__file__), "../data")
HRIS_FILE = os.path.join(DATA_DIR, "mock_hris.json")
NURSE_STATS_FILE = os.path.join(DATA_DIR, "nurse_stats.json")


def _load_hris() -> list:
    """Load HRIS data."""
    try:
        with open(HRIS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_hris(data: list) -> None:
    """Save HRIS data."""
    with open(HRIS_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)


def _load_nurse_stats() -> dict:
    """Load nurse stats."""
    try:
        with open(NURSE_STATS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_nurse_stats(data: dict) -> None:
    """Save nurse stats."""
    with open(NURSE_STATS_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)


def _get_next_nurse_id(nurses: list) -> str:
    """Generate the next nurse ID."""
    max_num = 0
    for nurse in nurses:
        nurse_id = nurse.get("id", "")
        if nurse_id.startswith("nurse_"):
            try:
                num = int(nurse_id.split("_")[1])
                max_num = max(max_num, num)
            except (IndexError, ValueError):
                pass
    return f"nurse_{max_num + 1:03d}"


def add_nurse(
    name: str,
    seniority_level: str = "Junior",
    contract_type: str = "FullTime",
    certifications: str = "BLS",
    avoid_night_shifts: bool = False,
    preferred_days: str = ""
) -> str:
    """
    Adds a new nurse to the HRIS system.

    Args:
        name: The nurse's name (required)
        seniority_level: "Junior", "Mid", or "Senior" (default: Junior)
        contract_type: "FullTime", "PartTime", or "Casual" (default: FullTime)
        certifications: Comma-separated list of certifications (default: "BLS")
                       Options: BLS, ACLS, ICU
        avoid_night_shifts: Whether nurse prefers to avoid night shifts (default: False)
        preferred_days: Comma-separated list of preferred days (e.g., "Monday,Tuesday,Wednesday")

    Returns:
        Confirmation message with the new nurse's details.
    """
    # Validate seniority level
    valid_levels = ["Junior", "Mid", "Senior"]
    if seniority_level not in valid_levels:
        return f"Error: Invalid seniority level '{seniority_level}'. Must be one of: {', '.join(valid_levels)}"

    # Validate contract type
    valid_contracts = ["FullTime", "PartTime", "Casual"]
    if contract_type not in valid_contracts:
        return f"Error: Invalid contract type '{contract_type}'. Must be one of: {', '.join(valid_contracts)}"

    # Parse certifications
    cert_list = [c.strip().upper() for c in certifications.split(",") if c.strip()]
    valid_certs = ["BLS", "ACLS", "ICU"]
    for cert in cert_list:
        if cert not in valid_certs:
            return f"Error: Invalid certification '{cert}'. Valid options: {', '.join(valid_certs)}"

    if not cert_list:
        cert_list = ["BLS"]

    # Parse preferred days
    day_list = []
    if preferred_days:
        valid_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        for day in preferred_days.split(","):
            day = day.strip().capitalize()
            if day in valid_days:
                day_list.append(day)

    # Load existing data
    nurses = _load_hris()

    # Check for duplicate name
    for nurse in nurses:
        if nurse.get("name", "").lower() == name.lower():
            return f"Error: A nurse named '{name}' already exists (ID: {nurse['id']}). Use a different name."

    # Generate new ID
    new_id = _get_next_nurse_id(nurses)

    # Create new nurse record
    new_nurse = {
        "id": new_id,
        "name": name,
        "certifications": cert_list,
        "seniority_level": seniority_level,
        "contract_type": contract_type,
        "preferences": {
            "avoid_night_shifts": avoid_night_shifts,
            "preferred_days": day_list,
            "adhoc_requests": []
        },
        "history_summary": {
            "last_shift": None,
            "consecutive_shifts": 0,
            "weekend_shifts_last_month": 0
        }
    }

    # Add to HRIS
    nurses.append(new_nurse)
    _save_hris(nurses)

    # Initialize nurse stats (fresh nurse with 0 fatigue)
    stats = _load_nurse_stats()
    stats[new_id] = {
        "nurse_name": name,
        "total_shifts_30d": 0,
        "weekend_shifts_30d": 0,
        "night_shifts_30d": 0,
        "consecutive_shifts_current": 0,
        "last_shift_date": "",
        "preferences_honored_rate": 1.0,
        "fatigue_score": 0.0,
        "updated_at": datetime.now().isoformat()
    }
    _save_nurse_stats(stats)

    # Build response
    result = f"SUCCESS: New nurse added to the system.\n\n"
    result += f"NURSE DETAILS\n"
    result += f"{'='*40}\n"
    result += f"ID: {new_id}\n"
    result += f"Name: {name}\n"
    result += f"Seniority: {seniority_level}\n"
    result += f"Contract: {contract_type}\n"
    result += f"Certifications: {', '.join(cert_list)}\n"
    result += f"Avoid Night Shifts: {'Yes' if avoid_night_shifts else 'No'}\n"
    if day_list:
        result += f"Preferred Days: {', '.join(day_list)}\n"
    result += f"\nFatigue Score: 0.0 (Fresh)\n"
    result += f"\nThe nurse is now available for roster generation."

    return result


def promote_nurse(nurse_id: str, new_level: str) -> str:
    """
    Promotes an existing nurse to a higher seniority level.

    Args:
        nurse_id: The nurse's ID (e.g., "nurse_002") or name
        new_level: The new seniority level ("Mid" or "Senior")

    Returns:
        Confirmation message with the updated details.
    """
    valid_levels = ["Junior", "Mid", "Senior"]
    seniority_order = {"Junior": 1, "Mid": 2, "Senior": 3}

    if new_level not in valid_levels:
        return f"Error: Invalid level '{new_level}'. Must be one of: {', '.join(valid_levels)}"

    nurses = _load_hris()

    # Find nurse by ID or name
    found_nurse = None
    for nurse in nurses:
        if nurse.get("id") == nurse_id or nurse.get("name", "").lower() == nurse_id.lower():
            found_nurse = nurse
            break

    if not found_nurse:
        return f"Error: Nurse '{nurse_id}' not found."

    current_level = found_nurse.get("seniority_level", "Junior")
    current_order = seniority_order.get(current_level, 0)
    new_order = seniority_order.get(new_level, 0)

    if new_order <= current_order:
        return f"Error: Cannot promote {found_nurse['name']} from {current_level} to {new_level}. Must promote to a higher level."

    # Update the nurse's level
    old_level = found_nurse["seniority_level"]
    found_nurse["seniority_level"] = new_level
    _save_hris(nurses)

    result = f"SUCCESS: Nurse promoted.\n\n"
    result += f"PROMOTION DETAILS\n"
    result += f"{'='*40}\n"
    result += f"Nurse: {found_nurse['name']} ({found_nurse['id']})\n"
    result += f"Previous Level: {old_level}\n"
    result += f"New Level: {new_level}\n"
    result += f"\nThe nurse can now be assigned to {new_level}-level shifts."

    return result


def update_nurse_certifications(nurse_id: str, add_certifications: str = "", remove_certifications: str = "") -> str:
    """
    Updates a nurse's certifications.

    Args:
        nurse_id: The nurse's ID (e.g., "nurse_002") or name
        add_certifications: Comma-separated certifications to add (e.g., "ICU,ACLS")
        remove_certifications: Comma-separated certifications to remove (e.g., "BLS")

    Returns:
        Confirmation message with updated certifications.
    """
    valid_certs = ["BLS", "ACLS", "ICU"]

    nurses = _load_hris()

    # Find nurse by ID or name
    found_nurse = None
    for nurse in nurses:
        if nurse.get("id") == nurse_id or nurse.get("name", "").lower() == nurse_id.lower():
            found_nurse = nurse
            break

    if not found_nurse:
        return f"Error: Nurse '{nurse_id}' not found."

    current_certs = set(found_nurse.get("certifications", []))
    original_certs = current_certs.copy()

    # Add certifications
    added = []
    if add_certifications:
        for cert in add_certifications.split(","):
            cert = cert.strip().upper()
            if cert not in valid_certs:
                return f"Error: Invalid certification '{cert}'. Valid options: {', '.join(valid_certs)}"
            if cert not in current_certs:
                current_certs.add(cert)
                added.append(cert)

    # Remove certifications
    removed = []
    if remove_certifications:
        for cert in remove_certifications.split(","):
            cert = cert.strip().upper()
            if cert in current_certs:
                current_certs.remove(cert)
                removed.append(cert)

    if not added and not removed:
        return f"No changes made. {found_nurse['name']} currently has: {', '.join(original_certs)}"

    # Update and save
    found_nurse["certifications"] = list(current_certs)
    _save_hris(nurses)

    result = f"SUCCESS: Certifications updated.\n\n"
    result += f"CERTIFICATION UPDATE\n"
    result += f"{'='*40}\n"
    result += f"Nurse: {found_nurse['name']} ({found_nurse['id']})\n"
    result += f"Previous: {', '.join(sorted(original_certs))}\n"
    result += f"Current: {', '.join(sorted(current_certs))}\n"
    if added:
        result += f"Added: {', '.join(added)}\n"
    if removed:
        result += f"Removed: {', '.join(removed)}\n"

    # Ward eligibility
    result += f"\nWard Eligibility:\n"
    if "ICU" in current_certs:
        result += f"  - ICU: Yes\n"
    else:
        result += f"  - ICU: No (requires ICU certification)\n"

    if "ACLS" in current_certs and "BLS" in current_certs:
        result += f"  - Emergency: Yes\n"
    else:
        result += f"  - Emergency: No (requires ACLS + BLS)\n"

    result += f"  - General: {'Yes' if 'BLS' in current_certs else 'No (requires BLS)'}\n"

    return result


def update_nurse_preferences(
    nurse_id: str,
    avoid_night_shifts: Optional[bool] = None,
    preferred_days: str = ""
) -> str:
    """
    Updates a nurse's scheduling preferences.

    Args:
        nurse_id: The nurse's ID (e.g., "nurse_002") or name
        avoid_night_shifts: Set to True/False to update night shift preference
        preferred_days: Comma-separated list of preferred days (replaces existing)
                       Use empty string to keep current, use "clear" to remove all

    Returns:
        Confirmation message with updated preferences.
    """
    nurses = _load_hris()

    # Find nurse by ID or name
    found_nurse = None
    for nurse in nurses:
        if nurse.get("id") == nurse_id or nurse.get("name", "").lower() == nurse_id.lower():
            found_nurse = nurse
            break

    if not found_nurse:
        return f"Error: Nurse '{nurse_id}' not found."

    prefs = found_nurse.get("preferences", {})
    changes = []

    # Update night shift preference
    if avoid_night_shifts is not None:
        old_value = prefs.get("avoid_night_shifts", False)
        if old_value != avoid_night_shifts:
            prefs["avoid_night_shifts"] = avoid_night_shifts
            changes.append(f"Avoid Night Shifts: {old_value} → {avoid_night_shifts}")

    # Update preferred days
    if preferred_days:
        old_days = prefs.get("preferred_days", [])
        if preferred_days.lower() == "clear":
            new_days = []
        else:
            valid_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            new_days = []
            for day in preferred_days.split(","):
                day = day.strip().capitalize()
                if day in valid_days:
                    new_days.append(day)

        if old_days != new_days:
            prefs["preferred_days"] = new_days
            changes.append(f"Preferred Days: {old_days} → {new_days}")

    if not changes:
        return f"No changes made to {found_nurse['name']}'s preferences."

    found_nurse["preferences"] = prefs
    _save_hris(nurses)

    result = f"SUCCESS: Preferences updated.\n\n"
    result += f"PREFERENCE UPDATE\n"
    result += f"{'='*40}\n"
    result += f"Nurse: {found_nurse['name']} ({found_nurse['id']})\n\n"
    result += "Changes:\n"
    for change in changes:
        result += f"  - {change}\n"

    return result


def remove_nurse(nurse_id: str) -> str:
    """
    Removes a nurse from the HRIS system.

    Args:
        nurse_id: The nurse's ID (e.g., "nurse_002") or name

    Returns:
        Confirmation message.
    """
    nurses = _load_hris()

    # Find nurse by ID or name
    found_index = None
    found_nurse = None
    for i, nurse in enumerate(nurses):
        if nurse.get("id") == nurse_id or nurse.get("name", "").lower() == nurse_id.lower():
            found_index = i
            found_nurse = nurse
            break

    if found_nurse is None:
        return f"Error: Nurse '{nurse_id}' not found."

    # Remove from HRIS
    nurses.pop(found_index)
    _save_hris(nurses)

    # Remove from stats
    stats = _load_nurse_stats()
    if found_nurse["id"] in stats:
        del stats[found_nurse["id"]]
        _save_nurse_stats(stats)

    result = f"SUCCESS: Nurse removed from the system.\n\n"
    result += f"Removed: {found_nurse['name']} ({found_nurse['id']})\n"
    result += f"\nNote: Any pending rosters with this nurse should be regenerated."

    return result


def list_available_certifications() -> str:
    """
    Lists all available certifications and their requirements.

    Returns:
        Information about certifications.
    """
    result = "AVAILABLE CERTIFICATIONS\n"
    result += "=" * 40 + "\n\n"

    result += "BLS (Basic Life Support)\n"
    result += "  - Required for: General Ward\n"
    result += "  - Prerequisite for: ACLS\n\n"

    result += "ACLS (Advanced Cardiac Life Support)\n"
    result += "  - Required for: Emergency Ward (with BLS)\n"
    result += "  - Prerequisite: BLS\n\n"

    result += "ICU (Intensive Care Unit)\n"
    result += "  - Required for: ICU Ward\n"
    result += "  - Specialized critical care certification\n\n"

    result += "WARD REQUIREMENTS\n"
    result += "-" * 40 + "\n"
    result += "ICU Ward:       ICU certification required\n"
    result += "Emergency Ward: ACLS + BLS certifications required\n"
    result += "General Ward:   BLS certification required\n"

    return result
