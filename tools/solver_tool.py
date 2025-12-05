from ortools.sat.python import cp_model
from models.domain import Nurse, Shift, Roster, Assignment, RosterMetadata
from datetime import datetime
import json


def generate_roster(start_date: str = "", num_days: int = 7, constraints_json: str = "{}") -> str:
    """
    Generates an optimal nurse roster using OR-Tools constraint solver.

    This function automatically loads nurse data from HRIS and generates shifts,
    so you don't need to pass large JSON strings.

    Args:
        start_date: Optional start date in YYYY-MM-DD format (defaults to today if empty)
        num_days: Number of days to schedule (default: 7)
        constraints_json: Optional JSON string with additional constraints (default: "{}")

    Returns:
        JSON string containing the generated roster with assignments.
    """
    # Import here to avoid circular imports
    from tools.data_loader import load_nurses, generate_shifts as gen_shifts
    from tools.history_tools import _load_json, NURSE_STATS_FILE
    from datetime import datetime as dt, timedelta

    # Load data automatically
    nurses_objs = load_nurses()

    # Parse start date
    if start_date:
        try:
            parsed_date = dt.strptime(start_date, "%Y-%m-%d")
        except ValueError:
            return json.dumps({"error": f"Invalid date format '{start_date}'. Use YYYY-MM-DD."})
    else:
        parsed_date = dt.now().replace(hour=0, minute=0, second=0, microsecond=0)

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


def _shifts_overlap_or_too_close(shift1, shift2, min_rest_hours: int = 10) -> bool:
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
    MIN_REST_HOURS = 10

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

    # Hard Constraint 5: Minimum rest period between shifts (10 hours)
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

    # Hard Constraint 7: At least one Senior nurse must be on duty for every shift period
    # Interpretation: For any group of shifts starting at the same time, at least one must be a Senior.
    # This ensures coverage while allowing Juniors to work concurrent shifts.
    senior_nurses = [n for n in nurses_objs if n.seniority_level == "Senior"]
    seniority_order = {"Junior": 1, "Mid": 2, "Senior": 3}

    # Group shifts by start time
    shifts_by_start = {}
    for s in shifts_objs:
        if s.start_time not in shifts_by_start:
            shifts_by_start[s.start_time] = []
        shifts_by_start[s.start_time].append(s)

    for start_time, concurrent_shifts in shifts_by_start.items():
        senior_assignments = []
        for s in concurrent_shifts:
            for n in senior_nurses:
                # Check eligibility
                if s.required_certifications:
                    has_certs = all(cert in n.certifications for cert in s.required_certifications)
                    if not has_certs:
                        continue
                
                if seniority_order.get(n.seniority_level, 0) < seniority_order.get(s.min_level, 0):
                    continue
                    
                senior_assignments.append(assignments[(n.id, s.id)])

        if senior_assignments:
            model.Add(sum(senior_assignments) >= 1)

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
        return json.dumps({"error": "No feasible solution found."})


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
