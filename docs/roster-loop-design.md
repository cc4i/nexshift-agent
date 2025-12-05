# Roster Generation Feedback Loop with LoopAgent

## Overview

Implement a self-correcting roster generation workflow that:
1. Generates a roster with the solver
2. Runs validation (Compliance + Empathy)
3. Parses validation results for FAIL/REJECTED status
4. If failed: adjusts penalty weights and regenerates (up to max iterations)
5. If passed or max iterations: present to user

## Current Architecture

```
RosteringWorkflow (SequentialAgent)
├── ContextGatherer
├── RosterSolver
├── ValidationPipeline (ParallelAgent)
│   ├── ComplianceOfficer → output_key="compliance_report"
│   └── EmpathyAdvocate → output_key="empathy_report"
└── RosterPresenter
```

## Proposed Architecture

```
RosteringWorkflow (SequentialAgent)
├── ContextGatherer
├── RosterLoop (LoopAgent, max_iterations=3)
│   ├── RosterSolver (with adjustable penalties)
│   ├── ValidationPipeline (ParallelAgent)
│   │   ├── ComplianceOfficer
│   │   └── EmpathyAdvocate
│   └── ValidationChecker (LlmAgent)
│       - Parses compliance_report and empathy_report
│       - If PASS/APPROVED: calls exit_loop()
│       - If FAIL: writes feedback to session state, continues loop
└── RosterPresenter
```

## Key Design Decisions

### 1. How LoopAgent Works (from ADK source)
- Runs sub-agents in sequence, repeatedly
- Stops when: `event.actions.escalate = True` OR `max_iterations` reached
- The `exit_loop` tool sets `escalate = True` to break the loop

### 2. Passing Feedback Between Iterations
- **ValidationChecker** writes `validation_feedback` to session state
- On next iteration, **RosterSolver** reads this feedback
- Solver adjusts penalty multipliers based on specific failures

### 3. Penalty Adjustment Strategy
```python
# Base penalties (current)
PENALTY_CONFIG = {
    "fatigue_high": -30,
    "fatigue_moderate": -12,
    "fatigue_weekend": -20,
    "fatigue_night": -20,
    "underutilization": -15,
    "overwork": -10,
    "weekend_excess": -15,
    "night_excess": -15,
}

# On failure, multiply specific penalties
# e.g., if "Ivan underutilized" → multiply underutilization penalty by 1.5
```

### 4. Feedback Format (in session state)
```json
{
  "iteration": 1,
  "status": "FAIL",
  "issues": [
    {"type": "underutilization", "nurse_id": "nurse_006", "detail": "Ivan got 0 shifts"},
    {"type": "fatigue_violation", "nurse_id": "nurse_004", "detail": "Diana assigned night despite high fatigue"},
    {"type": "night_concentration", "nurse_id": "nurse_003", "detail": "Charlie has too many night shifts"}
  ],
  "penalty_multipliers": {
    "underutilization": 1.5,
    "fatigue_night": 1.5,
    "night_excess": 1.5
  }
}
```

## Implementation Steps

### Step 1: Create ValidationChecker Agent
**File:** `agents/validation_checker.py`

```python
from google.adk.agents import LlmAgent
from google.adk.tools import exit_loop

CHECKER_INSTRUCTION = """
You check if the roster passed validation. Read compliance_report and empathy_report.

If BOTH pass (Compliance: PASS AND Empathy: APPROVED):
  - Call exit_loop() to stop the generation loop

If ANY fails:
  - Analyze specific failures
  - Write validation_feedback to guide next iteration
  - Do NOT call exit_loop (loop will continue)
"""

def create_validation_checker_agent():
    return LlmAgent(
        name="ValidationChecker",
        model="gemini-2.5-flash",
        instruction=CHECKER_INSTRUCTION,
        output_key="validation_feedback",
        tools=[exit_loop]
    )
```

### Step 2: Modify RosterSolver to Read Feedback
**File:** `agents/solver_agent.py`

Update instruction to read `validation_feedback` from session state and apply penalty multipliers.

### Step 3: Modify generate_roster Tool to Accept Penalty Overrides
**File:** `tools/solver_tool.py`

```python
def generate_roster(
    start_date: str = "",
    num_days: int = 7,
    penalty_overrides: str = "{}"  # JSON with penalty multipliers
) -> str:
```

### Step 4: Create RosterLoop with LoopAgent
**File:** `agents/coordinator.py`

```python
from google.adk.agents import LoopAgent

def create_roster_loop() -> LoopAgent:
    solver = create_solver_agent()
    validation = create_validation_pipeline()
    checker = create_validation_checker_agent()

    return LoopAgent(
        name="RosterLoop",
        max_iterations=3,
        sub_agents=[solver, validation, checker]
    )
```

### Step 5: Update RosteringWorkflow
**File:** `agents/coordinator.py`

```python
def create_rostering_workflow() -> SequentialAgent:
    context_gatherer = create_context_gatherer_agent()
    roster_loop = create_roster_loop()  # NEW: LoopAgent instead of flat sequence
    presenter = create_presenter_agent()

    return SequentialAgent(
        name="RosteringWorkflow",
        sub_agents=[context_gatherer, roster_loop, presenter]
    )
```

## Files to Modify

| File | Changes |
|------|---------|
| `agents/validation_checker.py` | NEW - Create ValidationChecker agent |
| `agents/solver_agent.py` | Read validation_feedback, pass penalty overrides |
| `tools/solver_tool.py` | Accept penalty_overrides parameter |
| `agents/coordinator.py` | Create RosterLoop with LoopAgent |

## Max Iterations Behavior

When max iterations (3) is reached but validation still fails:
- **Present anyway** with warnings about failed checks
- User can then decide to approve with known issues or reject
- Presenter will clearly highlight which checks failed

## Testing Considerations

1. Test that loop exits on first try when validation passes
2. Test that loop retries with adjusted penalties when validation fails
3. Test that loop stops at max_iterations even if still failing
4. Verify feedback is correctly parsed and penalties adjusted

## Alternative Considered: Custom Python Loop

Instead of ADK LoopAgent, could implement a custom callback-based loop. However:
- LoopAgent is the ADK-native solution
- Provides proper state management and event handling
- More maintainable and consistent with rest of codebase

**Decision:** Use LoopAgent for ADK-native integration.
