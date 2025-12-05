# Roster History Feature Design

> **Status**: ✅ IMPLEMENTED
> **Created**: 2025-12-04
> **Completed**: 2025-12-04
> **Storage**: JSON file-based
> **History Depth**: 12 weeks rolling
> **Finalization**: Requires user approval

---

## Overview

Per `design.md`, the system needs **Historical Shift Logs** to:
1. Establish baseline for **fairness and fatigue**
2. Allow EmpathyAdvocate to check "too many bad shifts *over the last few months*"
3. Support the **refinement loop** with historical context

---

## Data Model Extensions

### 1. Historical Shift Log (New)

**File**: `data/shift_history.json`

```json
{
  "logs": [
    {
      "roster_id": "roster_2025_week_48",
      "period": {
        "start": "2025-12-01",
        "end": "2025-12-07"
      },
      "status": "finalized",
      "generated_at": "2025-12-01T10:00:00",
      "finalized_at": "2025-12-01T14:30:00",
      "assignments": [
        {
          "nurse_id": "nurse_001",
          "shift_id": "shift_001",
          "ward": "ICU",
          "date": "2025-12-01",
          "shift_type": "day"
        },
        {
          "nurse_id": "nurse_002",
          "shift_id": "shift_002",
          "ward": "General",
          "date": "2025-12-01",
          "shift_type": "night"
        }
      ],
      "metadata": {
        "compliance_status": "Pass",
        "empathy_score": 0.85,
        "iterations": 2,
        "feedback": ["Improved weekend distribution after iteration 1"]
      }
    }
  ]
}
```

**Status Values**:
- `draft` - Generated but not approved
- `finalized` - Approved by user, nurse stats updated
- `rejected` - User rejected, archived for reference
- `archived` - Older than 12 weeks, kept for reference

### 2. Nurse Cumulative Stats (New)

**File**: `data/nurse_stats.json`

```json
{
  "nurse_001": {
    "nurse_name": "Alice",
    "total_shifts_30d": 12,
    "weekend_shifts_30d": 3,
    "night_shifts_30d": 2,
    "consecutive_shifts_current": 2,
    "last_shift_date": "2025-12-03",
    "preferences_honored_rate": 0.85,
    "fatigue_score": 0.3,
    "updated_at": "2025-12-03T16:00:00"
  },
  "nurse_002": {
    "nurse_name": "Bob",
    "total_shifts_30d": 10,
    "weekend_shifts_30d": 1,
    "night_shifts_30d": 4,
    "consecutive_shifts_current": 0,
    "last_shift_date": "2025-12-02",
    "preferences_honored_rate": 0.90,
    "fatigue_score": 0.2,
    "updated_at": "2025-12-02T08:00:00"
  }
}
```

**Fatigue Score Calculation**:
- 0.0 = Fresh (few recent shifts, preferences honored)
- 0.5 = Moderate (average workload)
- 1.0 = Burnout risk (many consecutive shifts, weekends, preferences ignored)

---

## Updated Workflow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         ROSTERING WORKFLOW                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  1. USER REQUEST                                                         │
│     ↓                                                                    │
│  2. COORDINATOR: Gather Context                                          │
│     ├── get_available_nurses()     ← HRIS Database                      │
│     ├── get_shifts_to_fill()       ← Shift Requirements                 │
│     ├── get_shift_history()        ← Historical Logs (NEW)              │
│     └── get_nurse_stats()          ← Cumulative Stats (NEW)             │
│     ↓                                                                    │
│  3. SOLVER: Generate Draft Roster                                        │
│     └── Uses history to avoid unfair assignments                        │
│     ↓                                                                    │
│  4. COMPLIANCE: Validate                                                 │
│     ↓                                                                    │
│  5. EMPATHY: Review against history                                      │
│     ├── Check: "Alice worked 3 weekends → give her a break"             │
│     └── Check: "Bob has low fatigue score → can take more"              │
│     ↓                                                                    │
│  6. DECISION                                                             │
│     ├── Score OK → Save as DRAFT                                        │
│     └── Score Low → Iterate with feedback                               │
│     ↓                                                                    │
│  7. USER REVIEW (Required)                                               │
│     ├── Approve → finalize_roster() → Update nurse stats                │
│     ├── Modify → Update assignments → Re-validate                       │
│     └── Reject → Archive as rejected                                    │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## New Tools

### Data Retrieval Tools

| Tool | Signature | Purpose |
|------|-----------|---------|
| `get_shift_history` | `(weeks: int = 12) -> str` | Retrieve past rosters for context |
| `get_nurse_stats` | `() -> str` | Get cumulative stats for all nurses (human-readable) |
| `get_nurse_stats_json` | `() -> str` | Get nurse stats as JSON (for solver) |
| `get_roster_by_id` | `(roster_id: str) -> str` | Retrieve specific roster details |

### Roster Management Tools

| Tool | Signature | Purpose |
|------|-----------|---------|
| `save_draft_roster` | `(roster_json: str) -> str` | Save roster as draft |
| `finalize_roster` | `(roster_id: str) -> str` | Mark as final, update nurse stats |
| `reject_roster` | `(roster_id: str, reason: str) -> str` | Mark as rejected |
| `list_pending_rosters` | `() -> str` | Show all draft rosters awaiting approval |

### Analysis Tools

| Tool | Signature | Purpose |
|------|-----------|---------|
| `compare_rosters` | `(roster_id_1: str, roster_id_2: str) -> str` | Compare two rosters side-by-side |
| `get_nurse_history` | `(nurse_id: str, weeks: int = 12) -> str` | Get specific nurse's shift history |

---

## Storage Structure

```
data/
├── mock_hris.json           # Nurse profiles (existing)
├── regulations/
│   └── hospital_rules.txt   # Regulations (existing)
├── shift_history.json       # Historical roster log (NEW)
├── nurse_stats.json         # Cumulative nurse stats (NEW)
└── rosters/                 # Individual roster files (NEW)
    ├── roster_2025_week_48.json
    ├── roster_2025_week_49.json
    └── ...
```

---

## Roster Lifecycle

```
                    ┌──────────────┐
                    │   GENERATE   │
                    └──────┬───────┘
                           ↓
                    ┌──────────────┐
              ┌─────│    DRAFT     │─────┐
              │     └──────┬───────┘     │
              │            │             │
         [Reject]     [Approve]     [Regenerate]
              │            │             │
              ↓            ↓             │
       ┌──────────┐ ┌──────────────┐     │
       │ REJECTED │ │  FINALIZED   │     │
       └──────────┘ └──────┬───────┘     │
                           │             │
                    [After 12 weeks]     │
                           ↓             │
                    ┌──────────────┐     │
                    │   ARCHIVED   │←────┘
                    └──────────────┘
```

### State Transitions

| From | To | Trigger | Side Effects |
|------|----|---------|--------------|
| - | draft | `save_draft_roster()` | Creates roster file |
| draft | finalized | `finalize_roster()` | Updates `nurse_stats.json`, adds to `shift_history.json` |
| draft | rejected | `reject_roster()` | Archives with rejection reason |
| draft | draft | Regenerate | Overwrites previous draft |
| finalized | archived | Auto (>12 weeks) | Moves to archive section |

---

## Nurse Stats Update Logic

When a roster is **finalized**, update each nurse's stats:

```python
def update_nurse_stats(roster, nurse_stats):
    for assignment in roster.assignments:
        nurse_id = assignment.nurse_id
        stats = nurse_stats[nurse_id]

        # Update shift counts
        stats.total_shifts_30d += 1

        if is_weekend(assignment.date):
            stats.weekend_shifts_30d += 1

        if is_night_shift(assignment.shift_type):
            stats.night_shifts_30d += 1

        # Update consecutive shifts
        if assignment.date == stats.last_shift_date + 1 day:
            stats.consecutive_shifts_current += 1
        else:
            stats.consecutive_shifts_current = 1

        stats.last_shift_date = assignment.date

        # Recalculate fatigue score
        stats.fatigue_score = calculate_fatigue(stats)
```

### Fatigue Score Formula

```python
def calculate_fatigue(stats):
    # Weighted factors (0-1 each)
    consecutive_factor = min(stats.consecutive_shifts_current / 3, 1.0) * 0.3
    weekend_factor = min(stats.weekend_shifts_30d / 4, 1.0) * 0.25
    night_factor = min(stats.night_shifts_30d / 8, 1.0) * 0.25
    preference_factor = (1 - stats.preferences_honored_rate) * 0.2

    return consecutive_factor + weekend_factor + night_factor + preference_factor
```

---

## 12-Week Rolling Window

### Automatic Cleanup

Run weekly or on each access:

```python
def cleanup_old_history():
    cutoff_date = datetime.now() - timedelta(weeks=12)

    for roster in shift_history.logs:
        if roster.finalized_at < cutoff_date:
            roster.status = "archived"

    # Recalculate nurse stats based on remaining 12 weeks
    recalculate_nurse_stats()
```

### Stats Recalculation

When old rosters are archived, recalculate `nurse_stats.json` based on remaining history:

- `total_shifts_30d` → Recalculate from last 30 days only
- `weekend_shifts_30d` → Recalculate from last 30 days only
- Keep `consecutive_shifts_current` and `last_shift_date` as-is

---

## Implementation Order

1. **Phase 1: Storage Setup** ✅
   - [x] Create `data/shift_history.json` with empty structure
   - [x] Create `data/nurse_stats.json` with initial stats from mock data
   - [x] Create `data/rosters/` directory

2. **Phase 2: Read Tools** ✅
   - [x] Implement `get_shift_history()`
   - [x] Implement `get_nurse_stats()`
   - [x] Implement `get_roster_by_id()`
   - [x] Implement `get_nurse_history()`

3. **Phase 3: Write Tools** ✅
   - [x] Implement `save_draft_roster()`
   - [x] Implement `finalize_roster()`
   - [x] Implement `reject_roster()`

4. **Phase 4: Integration** ✅
   - [x] Update Coordinator to use history tools (15 tools total)
   - [x] Update EmpathyAdvocate to read nurse stats
   - [x] Update Solver to consider fatigue scores (fatigue-aware optimization)

5. **Phase 5: Maintenance** ✅
   - [x] Implement 12-week cleanup (`cleanup_old_history()`)
   - [x] Implement `compare_rosters()`
   - [x] Add `list_pending_rosters()`
   - [x] Add `recalculate_nurse_stats()` for stats refresh

---

## Demo Scenarios Enabled

1. **"Show me last week's roster"**
   ```
   User: Show me the roster from last week
   Agent: [calls get_shift_history(weeks=2)] Here's the roster from week 48...
   ```

2. **"Alice has worked too many weekends"**
   ```
   Agent: [EmpathyAdvocate reads nurse_stats]
   "Alice has worked 3 weekends in the last 30 days (fatigue score: 0.7).
   Recommending she gets this weekend off."
   ```

3. **"Approve this roster"**
   ```
   User: Approve the current roster
   Agent: [calls finalize_roster()]
   "Roster roster_2025_week_49 has been finalized.
   Updated stats for 3 nurses."
   ```

4. **"Compare this to last week"**
   ```
   User: How does this compare to last week?
   Agent: [calls compare_rosters()]
   "This week: Alice has 2 fewer shifts, Bob has 1 more weekend shift..."
   ```
