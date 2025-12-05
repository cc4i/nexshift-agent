# Nurse Rostering Agent - Demo Guide

This guide provides sample conversations to demonstrate the agent's capabilities.

## Starting the Agent

```bash
# From the project root directory
adk web .
```

Then open http://localhost:8000 in your browser and select "agents" from the dropdown.

---

## Demo Flow (Recommended Order)

### Step 1: Check Current State
```
Show me the current nurse stats and any pending rosters.
```

### Step 2: Generate a Roster
```
Generate an optimal roster for this week, considering nurse fatigue scores.
```

### Step 3: Review the Draft
```
Show me the details of the draft roster.
```

### Step 4: Approve or Reject
```
Approve this roster.
```
or
```
Reject this roster - Alice has too many weekend shifts.
```

### Step 5: Check Updated Stats
```
Show me the updated nurse stats after finalizing the roster.
```

---

## Demo Scenarios

### Scenario 1: Basic Roster Generation

**User Prompt:**
```
I need to create a roster for this week. Can you show me who's available and what shifts need to be filled?
```

**Expected Behavior:**
- Agent uses `get_available_nurses` tool to fetch nurse data
- Agent uses `get_shifts_to_fill` tool to fetch shift requirements
- Agent uses `get_nurse_stats` to check fatigue levels
- Agent presents a summary with any concerns highlighted

---

### Scenario 2: Full Roster with History Check

**User Prompt:**
```
Please generate an optimal roster for the upcoming shifts. Check the history to make sure we're distributing shifts fairly.
```

**Expected Behavior:**
1. Agent checks `get_nurse_stats` for current fatigue scores
2. Agent checks `get_shift_history` for recent patterns
3. Agent gathers shift requirements
4. Agent generates roster via RosterSolver
5. Agent validates with ComplianceOfficer and EmpathyAdvocate
6. Agent saves as draft using `save_draft_roster`
7. Agent presents roster and awaits approval

---

### Scenario 3: Approve a Roster

**User Prompt:**
```
Approve the current draft roster.
```

**Expected Behavior:**
- Agent calls `finalize_roster` with the roster ID
- Nurse stats are updated (shift counts, fatigue scores)
- Confirmation message shown

---

### Scenario 4: Reject and Regenerate

**User Prompt:**
```
Reject this roster - Alice already has a high fatigue score. Regenerate with Bob taking more shifts.
```

**Expected Behavior:**
- Agent calls `reject_roster` with reason
- Agent regenerates with new constraints
- Agent saves new draft

---

### Scenario 5: View Nurse History

**User Prompt:**
```
Show me Alice's shift history for the past month.
```

**Expected Behavior:**
- Agent calls `get_nurse_history("nurse_001", weeks=4)`
- Shows all shifts Alice has worked
- Highlights weekend and night shifts

---

### Scenario 6: Compare Rosters

**User Prompt:**
```
Compare this week's roster with last week's.
```

**Expected Behavior:**
- Agent calls `compare_rosters` with two roster IDs
- Shows side-by-side comparison of assignments
- Highlights differences in shift distribution

---

### Scenario 7: Check Pending Rosters

**User Prompt:**
```
Are there any pending rosters awaiting my approval?
```

**Expected Behavior:**
- Agent calls `list_pending_rosters`
- Shows all draft rosters with their scores

---

### Scenario 8: Fatigue-Aware Scheduling

**User Prompt:**
```
Which nurses have high fatigue scores? Make sure they get fewer shifts this week.
```

**Expected Behavior:**
- Agent calls `get_nurse_stats`
- Identifies nurses with fatigue score > 0.4
- Generates roster giving them lighter workload
- Explains the trade-offs made

---

## Mock Data Reference

### Nurses (from mock_hris.json)

| Name    | Seniority | Contract | Certifications | Preferences         |
|---------|-----------|----------|----------------|---------------------|
| Alice   | Senior    | FullTime | ACLS, BLS, ICU | Avoids night shifts |
| Bob     | Junior    | FullTime | BLS            | Prefers Wed/Thu     |
| Charlie | Mid       | Casual   | ACLS, ICU      | Prefers Fri/Sat/Sun |

### Current Nurse Stats (from nurse_stats.json)

| Nurse   | Shifts (30d) | Weekends | Nights | Fatigue Score |
|---------|--------------|----------|--------|---------------|
| Alice   | 14           | 4        | 1      | 0.41 🟡       |
| Bob     | 11           | 1        | 4      | 0.31 🟢       |
| Charlie | 7            | 2        | 3      | 0.33 🟢       |

### Shifts (7 days, ~26 total)

| Ward      | Time        | Required Certs | Min Level |
|-----------|-------------|----------------|-----------|
| ICU       | 08:00-16:00 | ICU            | Senior    |
| ICU       | 16:00-00:00 | ICU            | Junior    |
| General   | 08:00-16:00 | BLS            | Junior    |
| Emergency | 20:00-04:00 | ACLS, BLS      | Mid       |

*Note: General ward shifts are skipped on weekends*

---

## Roster Lifecycle

```
    ┌──────────────┐
    │   GENERATE   │  ← RosterSolver creates
    └──────┬───────┘
           ↓
    ┌──────────────┐
    │    DRAFT     │  ← Awaiting user approval
    └──────┬───────┘
           │
     ┌─────┴─────┐
     ↓           ↓
┌─────────┐ ┌──────────┐
│ APPROVE │ │  REJECT  │
└────┬────┘ └────┬─────┘
     ↓           ↓
┌──────────┐ ┌──────────┐
│FINALIZED │ │ ARCHIVED │
└──────────┘ └──────────┘
     │
     └── Updates nurse_stats.json
```

---

## Architecture Overview

```
User Request
     ↓
RosteringCoordinator (gemini-2.5-pro)
     │
     ├── Data Tools
     │   ├── get_available_nurses
     │   ├── get_shifts_to_fill
     │   └── get_regulations
     │
     ├── History Tools
     │   ├── get_nurse_stats
     │   ├── get_shift_history
     │   ├── get_nurse_history
     │   └── compare_rosters
     │
     ├── Roster Management
     │   ├── save_draft_roster
     │   ├── finalize_roster
     │   ├── reject_roster
     │   └── list_pending_rosters
     │
     └── Sub-Agents
         ├── RosterSolver (gemini-2.5-flash)
         │   └── solve_roster_cp_model (OR-Tools)
         ├── ComplianceOfficer (gemini-2.5-flash)
         └── EmpathyAdvocate (gemini-2.5-pro)
                ↓
          Draft Roster
                ↓
          User Approval
                ↓
          Finalized Roster
```

---

## Troubleshooting

### "No root_agent found" Error
```bash
cd /path/to/nexshift-agent
adk web .
```

### Model API Errors
```bash
gcloud auth application-default login
```

### Check Agent Setup
```bash
python -c "from agents.agent import root_agent; print(f'Tools: {len(root_agent.tools)}')"
```
Should output: `Tools: 14`

---

## Tips for Demo

1. **Start with stats**: Show `get_nurse_stats` to establish context
2. **Generate a roster**: Show the full workflow from request to draft
3. **Show history**: Demonstrate how past rosters inform current decisions
4. **Approve/Reject**: Show the finalization flow and stats update
5. **Compare rosters**: If you have multiple rosters, show comparison
6. **Highlight fatigue**: Point out how high fatigue affects scheduling

---

## Files Modified by the Agent

| File | Purpose |
|------|---------|
| `data/nurse_stats.json` | Updated when roster is finalized |
| `data/shift_history.json` | Roster log (12 weeks rolling) |
| `data/rosters/*.json` | Individual roster files |
