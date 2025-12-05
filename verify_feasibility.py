import json
from tools.solver_tool import generate_roster
from datetime import datetime

def verify_roster_feasibility():
    print("Generating roster...")
    # Generate a roster for 7 days
    roster_json = generate_roster(start_date="2025-12-08", num_days=7)
    
    if "error" in roster_json:
        print(f"❌ Error generating roster: {roster_json}")
        return

    roster_data = json.loads(roster_json)
    assignments = roster_data.get("assignments", [])
    print(f"✅ Success! Generated {len(assignments)} assignments.")
    
    # Check Fiona's assignments
    fiona_id = "nurse_006"
    fiona_shifts = [a for a in assignments if a["nurse_id"] == fiona_id]
    
    # Load shift details
    from tools.data_loader import generate_shifts
    start_date = datetime.strptime("2025-12-08", "%Y-%m-%d")
    shifts = generate_shifts(start_date=start_date, num_days=7)
    shifts_map = {s["id"]: s for s in shifts}
    
    print(f"\nFiona ({fiona_id}) Assignments:")
    for a in fiona_shifts:
        sid = a['shift_id']
        s = shifts_map.get(sid)
        if s:
            print(f"  - {sid}: {s['day']} {s['start']}-{s['end']} ({s['ward']})")
        else:
            print(f"  - {sid}: (Unknown)")
        
    if not fiona_shifts:
        print("  (No shifts assigned)")

if __name__ == "__main__":
    verify_roster_feasibility()
