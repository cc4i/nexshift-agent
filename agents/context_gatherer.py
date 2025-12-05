"""
Context Gatherer Agent - First step in the roster generation workflow.
Gathers all necessary context (nurse stats, shifts, regulations) before roster generation.
"""
from google.adk.agents import LlmAgent
from tools.data_loader import get_available_nurses, get_shifts_to_fill, get_regulations
from tools.history_tools import get_nurse_stats, get_shift_history

CONTEXT_GATHERER_INSTRUCTION = """
You are a Context Gatherer for a nurse rostering system.
Your job is to collect all necessary information before generating a roster.

## Your Task

When asked to prepare for roster generation, you MUST:

1. **Call get_nurse_stats()** to check current fatigue levels
2. **Call get_available_nurses()** to get nurse profiles and preferences
3. **Call get_shifts_to_fill()** to see what shifts need to be filled

## Output Format

Summarize the gathered context in a structured format:

```
CONTEXT SUMMARY
===============

SCHEDULING PERIOD:
- Start: [date]
- Days: [num_days]
- Total shifts to fill: [count]

NURSE STATUS:
- [nurse_name]: Fatigue [score] [indicator], [notes]
- ...

KEY CONCERNS:
- [Any nurses with high fatigue]
- [Any preference conflicts]
- [Any certification gaps]

READY FOR ROSTER GENERATION: YES/NO
```

This context will be used by the RosterSolver to generate an optimal schedule.
"""


def create_context_gatherer_agent(model_name: str = "gemini-2.5-flash") -> LlmAgent:
    return LlmAgent(
        name="ContextGatherer",
        model=model_name,
        instruction=CONTEXT_GATHERER_INSTRUCTION,
        output_key="gathered_context",  # Stores output in session state
        tools=[
            get_available_nurses,
            get_shifts_to_fill,
            get_nurse_stats,
            get_shift_history,
            get_regulations
        ]
    )
