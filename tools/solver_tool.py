from ortools.sat.python import cp_model
from models.domain import Nurse, Shift, Roster, Assignment, RosterMetadata, NursePreferences, NurseHistory
from datetime import datetime
import json


def generate_roster(start_date: str = "", num_days: int = 7, constraints_json: str = "{}") -> str:
    """
    Generates an optimal nurse roster using OR-Tools constraint solver.

    This function automatically loads nurse data from HRIS and generates shifts,
    so you don't need to pass large JSON strings.

    Args:
        start_date: Optional start date in YYYY-MM-DD format (defaults to next unscheduled date)
        num_days: Number of days to schedule (default: 7)
        constraints_json: Optional JSON string with additional constraints (default: "{}")

    Returns:
        JSON string containing the generated roster with assignments.
        If overlap detected, returns warning info instead.
    """
    # Import here to avoid circular imports
    from tools.data_loader import load_nurses, generate_shifts as gen_shifts
    from tools.history_tools import _load_json, NURSE_STATS_FILE, get_next_unscheduled_date, check_period_overlap
    from datetime import datetime as dt, timedelta

    # Load data automatically
    nurses_objs = load_nurses()

    # Parse start date - use next unscheduled date if not provided
    if start_date:
        try:
            parsed_date = dt.strptime(start_date, "%Y-%m-%d")
        except ValueError:
            return json.dumps({"error": f"Invalid date format '{start_date}'. Use YYYY-MM-DD."})
    else:
        next_date = get_next_unscheduled_date()
        parsed_date = dt.strptime(next_date, "%Y-%m-%d")

    # Check for overlap with existing rosters
    overlap_info = check_period_overlap(parsed_date.strftime("%Y-%m-%d"), num_days)

    if overlap_info["has_overlap"]:
        # Check if any overlapping roster is finalized
        finalized_overlaps = [r for r in overlap_info["overlapping_rosters"] if r["status"] == "finalized"]
        draft_overlaps = [r for r in overlap_info["overlapping_rosters"] if r["status"] == "draft"]

        warning = {
            "warning": "Period overlap detected",
            "requested_period": overlap_info["requested_period"],
            "overlapping_rosters": overlap_info["overlapping_rosters"],
            "suggested_start": overlap_info["suggested_start"]
        }

        if finalized_overlaps:
            warning["message"] = (
                f"Cannot generate roster: Period {overlap_info['requested_period']} "
                f"overlaps with finalized roster(s). "
                f"Suggested start date: {overlap_info['suggested_start']}"
            )
            warning["action_required"] = "Use suggested_start date or specify a different period"
            return json.dumps(warning)
        elif draft_overlaps:
            warning["message"] = (
                f"Period {overlap_info['requested_period']} overlaps with draft roster(s). "
                f"Delete the draft(s) first or use suggested start date: {overlap_info['suggested_start']}"
            )
            warning["action_required"] = "Delete draft roster(s) or use suggested_start date"
            return json.dumps(warning)

    # Generate shifts
    raw_shifts = gen_shifts(start_date=parsed_date, num_days=num_days)

    # Convert raw shifts to Shift objects
    shifts_objs = []
    for s in raw_shifts:
        date = dt.strptime(s["date"], "%Y-%m-%d")
        start_hour, start_min = map(int, s["start"].split(":"))
        end_hour, end_min = map(int, s["end"].split(":"))

        start_time = date.replace(hour=start_hour, minute=start_min)
        if end_hour < start_hour:
            end_time = (date + timedelta(days=1)).replace(hour=end_hour, minute=end_min)
        else:
            end_time = date.replace(hour=end_hour, minute=end_min)

        shifts_objs.append(Shift(
            id=s["id"],
            ward=s["ward"],
            start_time=start_time,
            end_time=end_time,
            required_certifications=s["required_certs"],
            min_level=s["min_level"]
        ))

    # Load nurse stats for fatigue-aware scheduling
    nurse_stats = _load_json(NURSE_STATS_FILE)

    # Run the solver
    return _solve_roster_internal(nurses_objs, shifts_objs, nurse_stats)


def _get_shift_duration_hours(shift) -> float:
    """Calculate shift duration in hours."""
    duration = shift.end_time - shift.start_time
    # Handle overnight shifts
    if duration.total_seconds() < 0:
        from datetime import timedelta
        duration = duration + timedelta(days=1)
    return duration.total_seconds() / 3600


def _analyze_infeasibility(nurses_objs: list, shifts_objs: list, nurse_stats: dict) -> dict:
    """
    Analyzes why the roster cannot be generated and provides solutions.

    Returns a detailed report with:
    - Capacity analysis (total shifts vs available nurse-hours)
    - Certification gaps
    - Seniority gaps
    - Recommendations
    """
    from collections import defaultdict

    # Contract type weekly hour limits
    MAX_HOURS = {
        "FullTime": 40,
        "PartTime": 30,
        "Casual": 20
    }

    report = {
        "summary": "",
        "capacity_analysis": {},
        "certification_gaps": [],
        "seniority_gaps": [],
        "ward_gaps": [],
        "availability_issues": [],
        "recommendations": [],
        "constraint_types": {
            "HARD_CONSTRAINTS_CANNOT_RELAX": [
                "Certification requirements (ICU, ACLS, BLS)",
                "Seniority requirements (Senior nurse per shift)",
                "Maximum weekly hours per contract type",
                "Minimum 8-hour rest between shifts"
            ],
            "SOFT_CONSTRAINTS_CAN_ADJUST": [
                "Night shift preferences",
                "Preferred days preferences",
                "Weekend distribution fairness"
            ]
        }
    }

    # =========================================================================
    # 1. CAPACITY ANALYSIS
    # =========================================================================
    total_shifts = len(shifts_objs)
    total_shift_hours = sum(_get_shift_duration_hours(s) for s in shifts_objs)

    # Calculate available nurse capacity
    total_nurse_capacity_hours = 0
    nurse_capacity = {}
    for n in nurses_objs:
        max_hours = MAX_HOURS.get(n.contract_type, 40)
        fatigue = nurse_stats.get(n.id, {}).get("fatigue_score", 0)
        # Reduce capacity for fatigued nurses
        if fatigue >= 0.8:
            effective_hours = max_hours * 0.5
        elif fatigue >= 0.5:
            effective_hours = max_hours * 0.75
        else:
            effective_hours = max_hours
        nurse_capacity[n.id] = {
            "name": n.name,
            "max_hours": max_hours,
            "effective_hours": effective_hours,
            "fatigue": fatigue
        }
        total_nurse_capacity_hours += effective_hours

    capacity_ratio = total_nurse_capacity_hours / total_shift_hours if total_shift_hours > 0 else 0

    report["capacity_analysis"] = {
        "total_shifts": total_shifts,
        "total_shift_hours": round(total_shift_hours, 1),
        "total_nurse_capacity_hours": round(total_nurse_capacity_hours, 1),
        "capacity_ratio": round(capacity_ratio, 2),
        "is_understaffed": capacity_ratio < 1.0,
        "nurses_count": len(nurses_objs),
        "shortage_hours": round(total_shift_hours - total_nurse_capacity_hours, 1) if capacity_ratio < 1.0 else 0
    }

    if capacity_ratio < 1.0:
        shortage = total_shift_hours - total_nurse_capacity_hours
        additional_fte_needed = shortage / 40  # Assuming 40 hrs per FTE
        report["recommendations"].append({
            "issue": "UNDERSTAFFED",
            "severity": "CRITICAL",
            "message": f"Need {round(shortage, 1)} more hours of capacity. Consider hiring {round(additional_fte_needed, 1)} additional FTE nurses."
        })

    # =========================================================================
    # 2. CERTIFICATION GAP ANALYSIS
    # =========================================================================
    shifts_by_cert = defaultdict(list)
    for s in shifts_objs:
        for cert in s.required_certifications:
            shifts_by_cert[cert].append(s)

    nurses_by_cert = defaultdict(list)
    for n in nurses_objs:
        for cert in n.certifications:
            nurses_by_cert[cert].append(n)

    for cert, cert_shifts in shifts_by_cert.items():
        qualified_nurses = nurses_by_cert.get(cert, [])
        cert_shift_hours = sum(_get_shift_duration_hours(s) for s in cert_shifts)

        qualified_capacity = sum(nurse_capacity[n.id]["effective_hours"] for n in qualified_nurses)

        if qualified_capacity < cert_shift_hours:
            gap = {
                "certification": cert,
                "required_hours": round(cert_shift_hours, 1),
                "available_hours": round(qualified_capacity, 1),
                "qualified_nurses": [n.name for n in qualified_nurses],
                "shortage_hours": round(cert_shift_hours - qualified_capacity, 1)
            }
            report["certification_gaps"].append(gap)
            report["recommendations"].append({
                "issue": f"CERTIFICATION_GAP_{cert}",
                "severity": "HIGH",
                "message": f"Need {round(cert_shift_hours - qualified_capacity, 1)} more hours of {cert}-certified nurses. "
                          f"Qualified: {', '.join([n.name for n in qualified_nurses]) or 'None'}. "
                          f"Solution: Train existing staff or hire {cert}-certified nurses."
            })

    # =========================================================================
    # 3. SENIORITY GAP ANALYSIS
    # =========================================================================
    seniority_order = {"Junior": 1, "Mid": 2, "Senior": 3}

    shifts_by_level = defaultdict(list)
    for s in shifts_objs:
        shifts_by_level[s.min_level].append(s)

    for level in ["Senior", "Mid"]:
        level_shifts = shifts_by_level.get(level, [])
        if not level_shifts:
            continue

        level_shift_hours = sum(_get_shift_duration_hours(s) for s in level_shifts)

        # Find nurses who can cover this level
        eligible_nurses = [n for n in nurses_objs
                          if seniority_order.get(n.seniority_level, 0) >= seniority_order.get(level, 0)]

        eligible_capacity = sum(nurse_capacity[n.id]["effective_hours"] for n in eligible_nurses)

        if eligible_capacity < level_shift_hours:
            gap = {
                "required_level": level,
                "required_hours": round(level_shift_hours, 1),
                "available_hours": round(eligible_capacity, 1),
                "eligible_nurses": [n.name for n in eligible_nurses],
                "shortage_hours": round(level_shift_hours - eligible_capacity, 1)
            }
            report["seniority_gaps"].append(gap)
            report["recommendations"].append({
                "issue": f"SENIORITY_GAP_{level}",
                "severity": "HIGH",
                "message": f"Need {round(level_shift_hours - eligible_capacity, 1)} more hours of {level}+ nurses. "
                          f"Solution: Promote staff or hire experienced nurses."
            })

    # =========================================================================
    # 4. WARD-SPECIFIC ANALYSIS
    # =========================================================================
    shifts_by_ward = defaultdict(list)
    for s in shifts_objs:
        shifts_by_ward[s.ward].append(s)

    for ward, ward_shifts in shifts_by_ward.items():
        ward_hours = sum(_get_shift_duration_hours(s) for s in ward_shifts)

        # Find nurses qualified for this ward
        qualified = []
        for n in nurses_objs:
            can_work = True
            if ward == "ICU" and "ICU" not in n.certifications:
                can_work = False
            elif ward == "Emergency" and ("ACLS" not in n.certifications or "BLS" not in n.certifications):
                can_work = False
            if can_work:
                qualified.append(n)

        qualified_capacity = sum(nurse_capacity[n.id]["effective_hours"] for n in qualified)

        if qualified_capacity < ward_hours:
            gap = {
                "ward": ward,
                "required_hours": round(ward_hours, 1),
                "available_hours": round(qualified_capacity, 1),
                "qualified_nurses": [n.name for n in qualified],
                "shortage_hours": round(ward_hours - qualified_capacity, 1)
            }
            report["ward_gaps"].append(gap)
            report["recommendations"].append({
                "issue": f"WARD_SHORTAGE_{ward}",
                "severity": "HIGH",
                "message": f"{ward} ward needs {round(ward_hours, 1)} hrs but only {round(qualified_capacity, 1)} hrs available. "
                          f"Qualified: {', '.join([n.name for n in qualified]) or 'None'}."
            })

    # =========================================================================
    # 5. FATIGUED NURSES ANALYSIS
    # =========================================================================
    fatigued_nurses = []
    for n in nurses_objs:
        fatigue = nurse_stats.get(n.id, {}).get("fatigue_score", 0)
        if fatigue >= 0.5:
            fatigued_nurses.append({
                "nurse": n.name,
                "nurse_id": n.id,
                "fatigue_score": round(fatigue, 2),
                "status": "HIGH RISK" if fatigue >= 0.8 else "MODERATE",
                "capacity_reduction": "50%" if fatigue >= 0.8 else "25%"
            })

    if fatigued_nurses:
        report["availability_issues"] = fatigued_nurses
        high_fatigue_count = len([f for f in fatigued_nurses if f["status"] == "HIGH RISK"])
        report["recommendations"].append({
            "issue": "FATIGUE",
            "severity": "MEDIUM" if high_fatigue_count == 0 else "HIGH",
            "message": f"{len(fatigued_nurses)} nurses have elevated fatigue ({high_fatigue_count} high risk). "
                      f"This reduces scheduling capacity. Consider rest days or lighter duties."
        })

    # =========================================================================
    # 6. CONSTRAINT CONFLICT ANALYSIS
    # =========================================================================
    # If no capacity issues found, analyze potential constraint conflicts
    has_capacity_issues = (
        report["capacity_analysis"].get("is_understaffed", False) or
        len(report.get("certification_gaps", [])) > 0 or
        len(report.get("seniority_gaps", [])) > 0 or
        len(report.get("ward_gaps", [])) > 0
    )

    constraint_issues = []

    if not has_capacity_issues:
        # Analyze scheduling constraint conflicts

        # 6a. Check shifts per day vs nurses available per day
        from collections import defaultdict
        shifts_per_day = defaultdict(list)
        for s in shifts_objs:
            day_key = s.start_time.date()
            shifts_per_day[day_key].append(s)

        for day, day_shifts in shifts_per_day.items():
            day_name = day.strftime("%A")
            shift_count = len(day_shifts)

            # Each nurse can only work 1 shift per day
            # So we need at least shift_count nurses available that day
            if shift_count > len(nurses_objs):
                constraint_issues.append({
                    "type": "DAILY_COVERAGE",
                    "severity": "HIGH",
                    "day": str(day),
                    "message": f"{day_name} ({day}) has {shift_count} shifts but only {len(nurses_objs)} nurses. "
                              f"Each nurse can only work 1 shift per day.",
                    "solutions": [
                        f"Hire {shift_count - len(nurses_objs)} more nurses",
                        "Reduce the number of shifts on this day",
                        "Consider overlapping shift coverage"
                    ]
                })

        # 6b. Check consecutive days constraint
        # If a nurse works 3 days in a row, they can't work day 4
        # This can cause issues if we need all nurses every day
        sorted_dates = sorted(shifts_per_day.keys())
        if len(sorted_dates) > 3:
            avg_shifts_per_day = sum(len(shifts_per_day[d]) for d in sorted_dates) / len(sorted_dates)
            if avg_shifts_per_day > len(nurses_objs) * 0.75:  # More than 75% utilization
                constraint_issues.append({
                    "type": "CONSECUTIVE_SHIFT_LIMIT",
                    "severity": "MEDIUM",
                    "message": f"High daily shift demand ({avg_shifts_per_day:.1f} avg) with {len(nurses_objs)} nurses. "
                              f"The 3-consecutive-shift limit may prevent full coverage.",
                    "solutions": [
                        "Hire additional nurses to allow rotation",
                        "Reduce shifts on some days to allow rest days",
                        "Consider adjusting the consecutive shift limit policy"
                    ]
                })

        # 6c. Check rest period conflicts (8-hour minimum between shifts)
        # Night shift (ends 08:00) + Day shift (starts 08:00) = 0 hours rest = CONFLICT
        night_to_day_conflicts = []
        for s in shifts_objs:
            # Night shifts end in the morning
            if s.start_time.hour == 0 or s.start_time.hour >= 16:  # Evening/night shifts
                end_hour = s.end_time.hour
                end_date = s.end_time.date()

                # Check if there's a day shift starting within 8 hours
                for s2 in shifts_objs:
                    if s2.start_time.date() == end_date and s2.start_time.hour < 14:
                        gap_hours = (s2.start_time - s.end_time).total_seconds() / 3600
                        if 0 < gap_hours < 8:
                            night_to_day_conflicts.append({
                                "shift1": f"{s.ward} {s.start_time.strftime('%H:%M')}-{s.end_time.strftime('%H:%M')}",
                                "shift2": f"{s2.ward} {s2.start_time.strftime('%H:%M')}-{s2.end_time.strftime('%H:%M')}",
                                "gap_hours": round(gap_hours, 1)
                            })

        if night_to_day_conflicts:
            constraint_issues.append({
                "type": "REST_PERIOD_CONFLICT",
                "severity": "HIGH",
                "message": f"Found {len(night_to_day_conflicts)} shift pairs with less than 8-hour rest gap. "
                          f"A nurse cannot work both shifts.",
                "examples": night_to_day_conflicts[:3],  # Show first 3
                "solutions": [
                    "Ensure enough nurses so different people cover consecutive tight shifts",
                    "Adjust shift start/end times to allow 8-hour gaps",
                    "Hire additional nurses to avoid back-to-back scheduling"
                ]
            })

        # 6d. Check if certain wards have too many shifts relative to qualified nurses
        for ward, ward_shifts in shifts_by_ward.items():
            qualified_count = len([n for n in nurses_objs if _nurse_can_work_ward(n, ward)])
            shifts_per_week = len(ward_shifts)

            # Each qualified nurse can work ~5 shifts per week (with rest days)
            max_coverage = qualified_count * 5

            if shifts_per_week > max_coverage * 0.9:  # Over 90% of max capacity
                constraint_issues.append({
                    "type": "WARD_OVERLOAD",
                    "severity": "MEDIUM",
                    "ward": ward,
                    "message": f"{ward} has {shifts_per_week} shifts but only {qualified_count} qualified nurses. "
                              f"With rest requirements, max sustainable is ~{max_coverage} shifts/week.",
                    "solutions": [
                        f"Hire {max(1, (shifts_per_week - max_coverage) // 5 + 1)} more {ward}-qualified nurses",
                        f"Cross-train existing nurses for {ward}",
                        f"Reduce {ward} shift count if clinically safe"
                    ]
                })

        # 6e. Check preference conflicts
        nurses_avoiding_nights = [n for n in nurses_objs if n.preferences and n.preferences.avoid_night_shifts]
        night_shifts = [s for s in shifts_objs if s.start_time.hour >= 20 or s.start_time.hour < 6]

        if night_shifts:
            nurses_for_nights = len(nurses_objs) - len(nurses_avoiding_nights)
            if nurses_for_nights < len(night_shifts) / len(sorted_dates):
                constraint_issues.append({
                    "type": "NIGHT_SHIFT_PREFERENCE_CONFLICT",
                    "severity": "MEDIUM",
                    "message": f"{len(nurses_avoiding_nights)} nurses avoid night shifts, leaving {nurses_for_nights} for "
                              f"{len(night_shifts)} night shifts over {len(sorted_dates)} days.",
                    "solutions": [
                        "Hire nurses willing to work night shifts",
                        "Discuss night shift requirements with nurses who prefer to avoid them",
                        "Consider night shift incentives/differentials"
                    ]
                })

    report["constraint_conflicts"] = constraint_issues

    # Add constraint-specific recommendations
    for conflict in constraint_issues:
        report["recommendations"].append({
            "issue": conflict["type"],
            "severity": conflict["severity"],
            "message": conflict["message"],
            "solutions": conflict.get("solutions", [])
        })

    # =========================================================================
    # 7. GENERATE SUMMARY
    # =========================================================================
    issues = []
    if report["capacity_analysis"].get("is_understaffed"):
        issues.append("understaffing")
    if report["certification_gaps"]:
        certs = [g["certification"] for g in report["certification_gaps"]]
        issues.append(f"certification gaps ({', '.join(certs)})")
    if report["seniority_gaps"]:
        issues.append("seniority gaps")
    if report["ward_gaps"]:
        wards = [g["ward"] for g in report["ward_gaps"]]
        issues.append(f"ward coverage gaps ({', '.join(wards)})")
    if fatigued_nurses:
        issues.append(f"nurse fatigue ({len(fatigued_nurses)} affected)")
    if constraint_issues:
        conflict_types = list(set(c["type"] for c in constraint_issues))
        issues.append(f"constraint conflicts ({', '.join(conflict_types)})")

    if issues:
        report["summary"] = f"Roster generation failed due to: {'; '.join(issues)}."
    else:
        report["summary"] = "No obvious capacity issues found. The problem may be due to complex constraint interactions. Solutions: hire more nurses (especially Seniors with ICU/ACLS certs), or reduce scheduling period. NOTE: Seniority and certification requirements are HARD constraints and cannot be relaxed."

    return report


def _nurse_can_work_ward(nurse, ward: str) -> bool:
    """Check if a nurse is qualified to work in a ward."""
    if ward == "ICU":
        return "ICU" in nurse.certifications
    elif ward == "Emergency":
        return "ACLS" in nurse.certifications and "BLS" in nurse.certifications
    else:  # General
        return "BLS" in nurse.certifications


def simulate_staffing_change(
    action: str = "hire",
    nurse_id: str = "",
    new_level: str = "",
    start_date: str = "",
    num_days: int = 7
) -> str:
    """
    Simulates staffing changes (hiring or promotion) to check if roster generation would succeed.

    For 'hire' action: Automatically determines what nurses to hire based on gap analysis.
    For 'promote' action: Simulates promoting an existing nurse to a higher level.

    Args:
        action: "hire" (auto-fill gaps) or "promote" (upgrade existing nurse)
        nurse_id: For promote - the nurse ID to promote (e.g., "nurse_002")
        new_level: For promote - target seniority level ("Mid" or "Senior")
        start_date: Start date for simulation (YYYY-MM-DD), defaults to next unscheduled
        num_days: Number of days to simulate (default: 7)

    Returns:
        Simulation report showing if the changes would resolve staffing issues.
    """
    from tools.data_loader import load_nurses, generate_shifts as gen_shifts
    from tools.history_tools import _load_json, NURSE_STATS_FILE, get_next_unscheduled_date
    from datetime import datetime as dt, timedelta
    from copy import deepcopy

    # Load current data
    nurses_objs = load_nurses()
    nurse_stats = _load_json(NURSE_STATS_FILE)

    # Determine start date
    if start_date:
        try:
            parsed_date = dt.strptime(start_date, "%Y-%m-%d")
        except ValueError:
            return json.dumps({"error": f"Invalid date format '{start_date}'. Use YYYY-MM-DD."})
    else:
        next_date = get_next_unscheduled_date()
        parsed_date = dt.strptime(next_date, "%Y-%m-%d")

    # Generate shifts
    raw_shifts = gen_shifts(start_date=parsed_date, num_days=num_days)
    shifts_objs = []
    for s in raw_shifts:
        date = dt.strptime(s["date"], "%Y-%m-%d")
        start_hour, start_min = map(int, s["start"].split(":"))
        end_hour, end_min = map(int, s["end"].split(":"))
        start_time = date.replace(hour=start_hour, minute=start_min)
        if end_hour < start_hour:
            end_time = (date + timedelta(days=1)).replace(hour=end_hour, minute=end_min)
        else:
            end_time = date.replace(hour=end_hour, minute=end_min)
        shifts_objs.append(Shift(
            id=s["id"],
            ward=s["ward"],
            start_time=start_time,
            end_time=end_time,
            required_certifications=s["required_certs"],
            min_level=s["min_level"]
        ))

    # Get current analysis (before changes)
    before_analysis = _analyze_infeasibility(nurses_objs, shifts_objs, nurse_stats)

    result = {
        "action": action,
        "period": f"{parsed_date.strftime('%Y-%m-%d')} to {(parsed_date + timedelta(days=num_days-1)).strftime('%Y-%m-%d')}",
        "before": before_analysis,
        "simulated_changes": [],
        "after": None,
        "success": False,
        "recommendations": []
    }

    # Create a copy of nurses for simulation
    simulated_nurses = deepcopy(nurses_objs)
    simulated_stats = deepcopy(nurse_stats)

    if action == "promote":
        # Promote an existing nurse
        if not nurse_id or not new_level:
            return json.dumps({
                "error": "For 'promote' action, nurse_id and new_level are required.",
                "example": "simulate_staffing_change(action='promote', nurse_id='nurse_002', new_level='Mid')"
            })

        seniority_order = {"Junior": 1, "Mid": 2, "Senior": 3}
        target_level_num = seniority_order.get(new_level, 0)

        promoted = False
        for n in simulated_nurses:
            if n.id == nurse_id:
                current_level_num = seniority_order.get(n.seniority_level, 0)
                if target_level_num <= current_level_num:
                    return json.dumps({
                        "error": f"{n.name} is already {n.seniority_level}. Cannot promote to {new_level}."
                    })
                result["simulated_changes"].append({
                    "type": "promote",
                    "nurse": n.name,
                    "nurse_id": n.id,
                    "from_level": n.seniority_level,
                    "to_level": new_level
                })
                n.seniority_level = new_level
                promoted = True
                break

        if not promoted:
            return json.dumps({"error": f"Nurse '{nurse_id}' not found."})

    elif action == "hire":
        # Auto-determine what to hire based on gaps
        gaps_to_fill = []

        # Check ward gaps first (most specific)
        for gap in before_analysis.get("ward_gaps", []):
            ward = gap["ward"]
            shortage_hours = gap["shortage_hours"]

            # Determine requirements for this ward
            if ward == "ICU":
                certs = ["ICU", "BLS"]
                min_level = "Mid"
            elif ward == "Emergency":
                certs = ["ACLS", "BLS"]
                min_level = "Mid"
            else:
                certs = ["BLS"]
                min_level = "Junior"

            # How many nurses needed? (assume 40 hrs per FTE)
            nurses_needed = max(1, int((shortage_hours + 39) // 40))

            gaps_to_fill.append({
                "ward": ward,
                "shortage_hours": shortage_hours,
                "certifications": certs,
                "min_level": min_level,
                "nurses_needed": nurses_needed
            })

        # Check seniority gaps
        for gap in before_analysis.get("seniority_gaps", []):
            level = gap["required_level"]
            shortage = gap["shortage_hours"]
            nurses_needed = max(1, int((shortage + 39) // 40))

            # Check if already covered by ward-specific hires
            existing_coverage = sum(
                g["nurses_needed"] * 40
                for g in gaps_to_fill
                if seniority_order.get(g["min_level"], 0) >= seniority_order.get(level, 0)
            )

            if existing_coverage < shortage:
                remaining = shortage - existing_coverage
                gaps_to_fill.append({
                    "ward": "General",
                    "shortage_hours": remaining,
                    "certifications": ["BLS"],
                    "min_level": level,
                    "nurses_needed": max(1, int((remaining + 39) // 40))
                })

        # Check general capacity gap
        if before_analysis["capacity_analysis"].get("is_understaffed"):
            general_shortage = before_analysis["capacity_analysis"]["shortage_hours"]
            # Subtract what we're already hiring
            already_hiring_hours = sum(g["nurses_needed"] * 40 for g in gaps_to_fill)
            remaining_shortage = general_shortage - already_hiring_hours

            if remaining_shortage > 0:
                gaps_to_fill.append({
                    "ward": "General",
                    "shortage_hours": remaining_shortage,
                    "certifications": ["BLS"],
                    "min_level": "Junior",
                    "nurses_needed": max(1, int((remaining_shortage + 39) // 40))
                })

        if not gaps_to_fill:
            result["recommendations"].append("No obvious hiring needs detected. Issue may be constraint-related.")
        else:
            # Create simulated nurses for each gap
            seniority_order = {"Junior": 1, "Mid": 2, "Senior": 3}
            hire_counter = 1

            for gap in gaps_to_fill:
                for i in range(gap["nurses_needed"]):
                    new_nurse_id = f"sim_nurse_{hire_counter:03d}"
                    new_nurse = Nurse(
                        id=new_nurse_id,
                        name=f"New Hire {hire_counter} ({gap['ward']})",
                        seniority_level=gap["min_level"],
                        certifications=gap["certifications"],
                        contract_type="FullTime",
                        preferences=NursePreferences(),  # Default preferences
                        history_summary=NurseHistory()   # Fresh history (no previous shifts)
                    )
                    simulated_nurses.append(new_nurse)
                    simulated_stats[new_nurse_id] = {"fatigue_score": 0.0}  # Fresh nurse

                    result["simulated_changes"].append({
                        "type": "hire",
                        "nurse": new_nurse.name,
                        "nurse_id": new_nurse_id,
                        "seniority": gap["min_level"],
                        "certifications": gap["certifications"],
                        "contract": "FullTime",
                        "target_ward": gap["ward"]
                    })
                    hire_counter += 1

    else:
        return json.dumps({"error": f"Unknown action '{action}'. Use 'hire' or 'promote'."})

    # Re-analyze with simulated changes
    after_analysis = _analyze_infeasibility(simulated_nurses, shifts_objs, simulated_stats)
    result["after"] = after_analysis

    # Determine if simulation would succeed
    has_remaining_gaps = (
        after_analysis["capacity_analysis"].get("is_understaffed", False) or
        len(after_analysis.get("ward_gaps", [])) > 0 or
        len(after_analysis.get("certification_gaps", [])) > 0 or
        len(after_analysis.get("seniority_gaps", [])) > 0
    )

    result["success"] = not has_remaining_gaps

    # Generate human-readable summary
    if result["success"]:
        result["summary"] = "SUCCESS: The simulated changes would allow roster generation."
    else:
        result["summary"] = "PARTIAL: The simulated changes help but don't fully resolve all gaps."
        result["remaining_issues"] = after_analysis.get("recommendations", [])

    # Generate job posting recommendations for hires
    if action == "hire" and result["simulated_changes"]:
        job_postings = []
        for change in result["simulated_changes"]:
            if change["type"] == "hire":
                posting = {
                    "title": f"{change['seniority']} Nurse - {change['target_ward']}",
                    "type": change["contract"],
                    "required_certifications": change["certifications"],
                    "seniority_level": change["seniority"]
                }
                # Avoid duplicates
                if posting not in job_postings:
                    job_postings.append(posting)
        result["recommended_job_postings"] = job_postings

    return json.dumps(result, default=str, indent=2)


def _shifts_overlap_or_too_close(shift1, shift2, min_rest_hours: int = 8) -> bool:
    """Check if two shifts are too close (less than min_rest_hours apart)."""
    from datetime import timedelta
    min_rest = timedelta(hours=min_rest_hours)

    # Get end of first shift and start of second
    if shift1.end_time <= shift2.start_time:
        gap = shift2.start_time - shift1.end_time
        return gap < min_rest
    elif shift2.end_time <= shift1.start_time:
        gap = shift1.start_time - shift2.end_time
        return gap < min_rest
    else:
        # Shifts overlap
        return True


def _solve_roster_internal(nurses_objs: list, shifts_objs: list, nurse_stats: dict) -> str:
    """Internal solver logic with compliance constraints."""
    model = cp_model.CpModel()

    # Contract type weekly hour limits
    MAX_HOURS = {
        "FullTime": 40,
        "PartTime": 30,
        "Casual": 20
    }
    MAX_CONSECUTIVE_SHIFTS = 3
    MIN_REST_HOURS = 8

    # Variables: assignments[(n, s)] is 1 if nurse n works shift s, 0 otherwise
    assignments = {}
    for n in nurses_objs:
        for s in shifts_objs:
            assignments[(n.id, s.id)] = model.NewBoolVar(f'shift_n{n.id}_s{s.id}')

    # Hard Constraint 1: Each shift must be assigned to exactly one nurse
    for s in shifts_objs:
        model.Add(sum(assignments[(n.id, s.id)] for n in nurses_objs) == 1)

    # Hard Constraint 2: Certification requirements
    for s in shifts_objs:
        for n in nurses_objs:
            if s.required_certifications:
                has_all_certs = all(cert in n.certifications for cert in s.required_certifications)
                if not has_all_certs:
                    model.Add(assignments[(n.id, s.id)] == 0)

    # Hard Constraint 3: Seniority level requirements
    seniority_order = {"Junior": 1, "Mid": 2, "Senior": 3}
    for s in shifts_objs:
        for n in nurses_objs:
            nurse_level = seniority_order.get(n.seniority_level, 0)
            required_level = seniority_order.get(s.min_level, 0)
            if nurse_level < required_level:
                model.Add(assignments[(n.id, s.id)] == 0)

    # Hard Constraint 4: Maximum weekly hours per contract type
    for n in nurses_objs:
        max_hours = MAX_HOURS.get(n.contract_type, 40)
        # Calculate total hours for this nurse
        # Each shift duration in hours, multiplied by assignment variable
        total_hours_terms = []
        for s in shifts_objs:
            shift_hours = int(_get_shift_duration_hours(s))
            total_hours_terms.append(shift_hours * assignments[(n.id, s.id)])
        model.Add(sum(total_hours_terms) <= max_hours)

    # Hard Constraint: Fair distribution (Min/Max shifts per nurse)
    # OR-Tools best practice: Ensure every nurse gets a fair share of shifts
    # NOTE: Relaxed to allow for Senior coverage requirements (Seniors may need to work more)
    num_shifts = len(shifts_objs)
    num_nurses = len(nurses_objs)
    if num_nurses > 0:
        avg_shifts = num_shifts / num_nurses
        # Allow a wider window. Min is average - 2 (can be 0), Max is handled by MAX_HOURS
        # We allow 0 because strict senior coverage might require Seniors to take most shifts
        min_shifts_per_nurse = max(0, int(avg_shifts) - 2)
        
        for n in nurses_objs:
            shifts_worked = []
            for s in shifts_objs:
                shifts_worked.append(assignments[(n.id, s.id)])
            
            model.Add(sum(shifts_worked) >= min_shifts_per_nurse)
            # Upper bound is already handled by MAX_HOURS (Constraint 4)

    # Hard Constraint 5: Minimum rest period between shifts (8 hours)
    # For each nurse, if two shifts are too close, they can't both be assigned
    for n in nurses_objs:
        for i, s1 in enumerate(shifts_objs):
            for s2 in shifts_objs[i+1:]:
                if _shifts_overlap_or_too_close(s1, s2, MIN_REST_HOURS):
                    # Can't have both shifts
                    model.AddAtMostOne([assignments[(n.id, s1.id)], assignments[(n.id, s2.id)]])

    # Hard Constraint 6: Maximum consecutive shifts (3)
    # Group shifts by date to check consecutive working days/shifts
    shifts_by_date = {}
    for s in shifts_objs:
        date_key = s.start_time.date()
        if date_key not in shifts_by_date:
            shifts_by_date[date_key] = []
        shifts_by_date[date_key].append(s)

    sorted_dates = sorted(shifts_by_date.keys())

    # For any window of MAX_CONSECUTIVE_SHIFTS + 1 consecutive dates,
    # nurse can work at most MAX_CONSECUTIVE_SHIFTS
    # This covers both "4 days in a row" and "4 shifts in 2 days" violations
    for n in nurses_objs:
        for i in range(len(sorted_dates) - MAX_CONSECUTIVE_SHIFTS):
            window_dates = sorted_dates[i : i + MAX_CONSECUTIVE_SHIFTS + 1]
            
            # Check if these are actually consecutive dates
            is_consecutive_days = True
            for j in range(len(window_dates) - 1):
                if (window_dates[j+1] - window_dates[j]).days > 1:
                    is_consecutive_days = False
                    break
            
            if is_consecutive_days:
                # Sum of shifts worked in this window must be <= MAX_CONSECUTIVE_SHIFTS
                window_assignments = []
                for date in window_dates:
                    for s in shifts_by_date[date]:
                        window_assignments.append(assignments[(n.id, s.id)])
                
                if window_assignments:
                    model.Add(sum(window_assignments) <= MAX_CONSECUTIVE_SHIFTS)

    # Hard Constraint 7: At least one Senior nurse must be on duty for EVERY shift
    # Rule: "At least one Senior nurse must be on duty for every shift"
    # This means EACH individual shift must have a Senior nurse assigned to it.
    senior_nurses = [n for n in nurses_objs if n.seniority_level == "Senior"]

    for s in shifts_objs:
        # Find all Senior nurses who are eligible for this shift
        eligible_senior_assignments = []
        for n in senior_nurses:
            # Check certification eligibility
            if s.required_certifications:
                has_certs = all(cert in n.certifications for cert in s.required_certifications)
                if not has_certs:
                    continue

            # Check seniority level eligibility (Senior >= any min_level)
            nurse_level = seniority_order.get(n.seniority_level, 0)
            required_level = seniority_order.get(s.min_level, 0)
            if nurse_level < required_level:
                continue

            eligible_senior_assignments.append(assignments[(n.id, s.id)])

        # Each shift must have at least one Senior nurse
        if eligible_senior_assignments:
            model.Add(sum(eligible_senior_assignments) >= 1)

    # Hard Constraint 8: Honor adhoc time-off requests (high priority)
    from datetime import timedelta as td
    for n in nurses_objs:
        if n.preferences and n.preferences.adhoc_requests:
            for request in n.preferences.adhoc_requests:
                # Parse adhoc request format: "Off_YYYY-MM-DD_Reason_XXX"
                if request.startswith("Off_"):
                    parts = request.split("_")
                    if len(parts) >= 2:
                        try:
                            off_date_str = parts[1]
                            off_date = datetime.strptime(off_date_str, "%Y-%m-%d").date()
                            # Block all shifts on this date for this nurse
                            for s in shifts_objs:
                                if s.start_time.date() == off_date:
                                    model.Add(assignments[(n.id, s.id)] == 0)
                        except ValueError:
                            pass  # Invalid date format, skip

    # Soft Constraints (Preferences) - build objective function
    objective_terms = []

    # Soft Constraint: Prefer Senior nurses on shifts (for coverage)
    for s in shifts_objs:
        for n in nurses_objs:
            if n.seniority_level == "Senior":
                # Bonus for having a Senior nurse on shift
                objective_terms.append(3 * assignments[(n.id, s.id)])

    for n in nurses_objs:
        stats = nurse_stats.get(n.id, {})
        fatigue_score = stats.get("fatigue_score", 0.0)

        for s in shifts_objs:
            # Fatigue-aware scheduling - STRONGER penalties
            # Fatigue levels: 0.0-0.4 (Good), 0.5-0.7 (Moderate), 0.8-1.0 (High Risk)
            if fatigue_score >= 0.8:
                # High fatigue - strong penalty, especially for difficult shifts
                objective_terms.append(-50 * assignments[(n.id, s.id)])
            elif fatigue_score >= 0.5:
                objective_terms.append(-25 * assignments[(n.id, s.id)])

            # Extra penalty for weekend/night shifts for fatigued nurses
            if fatigue_score >= 0.5:
                if s.start_time.weekday() >= 5:
                    objective_terms.append(-30 * assignments[(n.id, s.id)])
                if s.start_time.hour >= 20 or s.start_time.hour < 6:
                    objective_terms.append(-30 * assignments[(n.id, s.id)])

            # Preference: Avoid night shifts - MUCH stronger penalty
            if n.preferences and n.preferences.avoid_night_shifts:
                if s.start_time.hour >= 20 or s.start_time.hour < 6:
                    objective_terms.append(-50 * assignments[(n.id, s.id)])

            # Preference: Preferred days bonus
            if n.preferences and n.preferences.preferred_days:
                day_name = s.start_time.strftime("%A")
                if day_name in n.preferences.preferred_days:
                    objective_terms.append(5 * assignments[(n.id, s.id)])

    # Fairness: Even distribution of shifts - STRONGER penalties
    for n in nurses_objs:
        nurse_total = sum(assignments[(n.id, s.id)] for s in shifts_objs)
        fair_share = len(shifts_objs) // len(nurses_objs)

        # Penalize both over-assignment AND under-assignment
        excess = model.NewIntVar(0, len(shifts_objs), f'excess_{n.id}')
        deficit = model.NewIntVar(0, len(shifts_objs), f'deficit_{n.id}')
        model.Add(excess >= nurse_total - fair_share)
        model.Add(deficit >= fair_share - nurse_total)  # Corrected deficit calculation
        objective_terms.append(-10 * excess)   # Stronger penalty for overwork
        objective_terms.append(-15 * deficit)  # Even stronger penalty for underutilization

    # Fairness: Distribute weekend shifts fairly - MUCH stronger penalty
    weekend_shifts = [s for s in shifts_objs if s.start_time.weekday() >= 5]
    if weekend_shifts:
        fair_weekend_share = max(1, len(weekend_shifts) // len(nurses_objs))
        for n in nurses_objs:
            weekend_total = sum(assignments[(n.id, s.id)] for s in weekend_shifts)
            weekend_excess = model.NewIntVar(0, len(weekend_shifts), f'weekend_excess_{n.id}')
            model.Add(weekend_excess >= weekend_total - fair_weekend_share)
            objective_terms.append(-30 * weekend_excess)  # Much stronger penalty

    # Fairness: Distribute night shifts fairly among eligible nurses - MUCH stronger penalty
    night_shifts = [s for s in shifts_objs if s.start_time.hour >= 20 or s.start_time.hour < 6]
    if night_shifts:
        # Only count nurses who don't avoid night shifts
        eligible_for_nights = [n for n in nurses_objs
                               if not (n.preferences and n.preferences.avoid_night_shifts)]
        if eligible_for_nights:
            fair_night_share = max(1, len(night_shifts) // len(eligible_for_nights))
            for n in eligible_for_nights:
                night_total = sum(assignments[(n.id, s.id)] for s in night_shifts)
                night_excess = model.NewIntVar(0, len(night_shifts), f'night_excess_{n.id}')
                model.Add(night_excess >= night_total - fair_night_share)
                objective_terms.append(-30 * night_excess)  # Much stronger penalty

    if objective_terms:
        model.Maximize(sum(objective_terms))

    solver = cp_model.CpSolver()
    # Add solver parameters for better performance
    solver.parameters.max_time_in_seconds = 30.0
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)

    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        roster_assignments = []
        for n in nurses_objs:
            for s in shifts_objs:
                if solver.Value(assignments[(n.id, s.id)]) == 1:
                    roster_assignments.append(Assignment(nurse_id=n.id, shift_id=s.id))

        roster = Roster(
            id=f"roster_{datetime.now().strftime('%Y%m%d%H%M')}",
            assignments=roster_assignments,
            metadata=RosterMetadata(
                generated_at=datetime.now(),
                compliance_status="Pending",
                empathy_score=0.0
            )
        )
        return json.dumps(roster.model_dump(), default=str)
    else:
        # Analyze why the solver failed and provide recommendations
        analysis = _analyze_infeasibility(nurses_objs, shifts_objs, nurse_stats)
        return json.dumps({
            "error": "No feasible solution found",
            "analysis": analysis
        }, default=str)


def solve_roster_cp_model(nurses_json: str, shifts_json: str, constraints_json: str, nurse_stats_json: str = "{}") -> str:
    """
    Solves the nurse rostering problem using Google OR-Tools.

    Args:
        nurses_json: JSON string containing list of nurse objects.
        shifts_json: JSON string containing list of shift objects.
        constraints_json: JSON string containing list of constraint objects.
        nurse_stats_json: Optional JSON string containing nurse fatigue stats from nurse_stats.json.
                         Used to reduce shifts for fatigued nurses.

    Returns:
        JSON string containing the generated roster.
    """
    # Parse JSON inputs
    nurses = json.loads(nurses_json)
    shifts = json.loads(shifts_json)
    _ = json.loads(constraints_json)  # constraints parsed for future use
    nurse_stats = json.loads(nurse_stats_json) if nurse_stats_json else {}

    # Reconstruct models from dicts for internal logic
    nurses_objs = [Nurse(**n) for n in nurses]
    shifts_objs = [Shift(**s) for s in shifts]

    model = cp_model.CpModel()

    # Variables: assignments[(n, s)] is 1 if nurse n works shift s, 0 otherwise
    assignments = {}
    for n in nurses_objs:
        for s in shifts_objs:
            assignments[(n.id, s.id)] = model.NewBoolVar(f'shift_n{n.id}_s{s.id}')

    # Hard Constraint 1: Each shift must be assigned to exactly one nurse
    for s in shifts_objs:
        model.AddExactlyOne(assignments[(n.id, s.id)] for n in nurses_objs)

    # Hard Constraint 2: Certification requirements
    for s in shifts_objs:
        for n in nurses_objs:
            # If shift requires certifications the nurse doesn't have, prevent assignment
            if s.required_certifications:
                has_all_certs = all(cert in n.certifications for cert in s.required_certifications)
                if not has_all_certs:
                    model.Add(assignments[(n.id, s.id)] == 0)

    # Hard Constraint 3: Seniority level requirements
    seniority_order = {"Junior": 1, "Mid": 2, "Senior": 3}
    for s in shifts_objs:
        for n in nurses_objs:
            nurse_level = seniority_order.get(n.seniority_level, 0)
            required_level = seniority_order.get(s.min_level, 0)
            if nurse_level < required_level:
                model.Add(assignments[(n.id, s.id)] == 0)

    # Soft Constraints (Preferences) - build objective function
    objective_terms = []

    for n in nurses_objs:
        # Get fatigue score for this nurse (default to 0 if not found)
        stats = nurse_stats.get(n.id, {})
        fatigue_score = stats.get("fatigue_score", 0.0)

        for s in shifts_objs:
            # Fatigue-aware scheduling: Penalize assigning shifts to fatigued nurses
            # Fatigue levels: 0.0-0.4 (Good), 0.5-0.7 (Moderate), 0.8-1.0 (High Risk)
            if fatigue_score >= 0.8:
                # High risk - strong penalty to reduce shifts
                objective_terms.append(-20 * assignments[(n.id, s.id)])
            elif fatigue_score >= 0.5:
                # Moderate - medium penalty
                objective_terms.append(-8 * assignments[(n.id, s.id)])
            # Good fatigue (< 0.5) - no penalty

            # Extra penalty for assigning weekend/night shifts to fatigued nurses
            if fatigue_score >= 0.5:
                # Check if shift is on weekend (Saturday=5, Sunday=6)
                if s.start_time.weekday() >= 5:
                    objective_terms.append(-5 * assignments[(n.id, s.id)])
                # Check if night shift
                if s.start_time.hour >= 20 or s.start_time.hour < 6:
                    objective_terms.append(-5 * assignments[(n.id, s.id)])

            # Preference: Avoid night shifts (shifts starting at 20:00 or later)
            if n.preferences and n.preferences.avoid_night_shifts and s.start_time.hour >= 20:
                objective_terms.append(-10 * assignments[(n.id, s.id)])

            # Preference: Preferred days bonus
            if n.preferences and n.preferences.preferred_days:
                day_name = s.start_time.strftime("%A")
                if day_name in n.preferences.preferred_days:
                    objective_terms.append(5 * assignments[(n.id, s.id)])

    # Fairness: Encourage even distribution of shifts
    # Add a small penalty for each shift a nurse takes to spread shifts around
    for n in nurses_objs:
        nurse_total = sum(assignments[(n.id, s.id)] for s in shifts_objs)
        # Penalize having more than fair share of shifts
        fair_share = len(shifts_objs) // len(nurses_objs)
        excess = model.NewIntVar(0, len(shifts_objs), f'excess_{n.id}')
        model.Add(excess >= nurse_total - fair_share)
        objective_terms.append(-3 * excess)  # Penalty for excess shifts

    if objective_terms:
        model.Maximize(sum(objective_terms))

    # Solve
    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        roster_assignments = []
        for n in nurses_objs:
            for s in shifts_objs:
                if solver.Value(assignments[(n.id, s.id)]) == 1:
                    roster_assignments.append(Assignment(nurse_id=n.id, shift_id=s.id))

        roster = Roster(
            id=f"roster_{datetime.now().strftime('%Y%m%d%H%M')}",
            assignments=roster_assignments,
            metadata=RosterMetadata(
                generated_at=datetime.now(),
                compliance_status="Pending",
                empathy_score=0.0
            )
        )
        return json.dumps(roster.model_dump(), default=str)
    else:
        return json.dumps({"error": "No feasible solution found."})
