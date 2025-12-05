"""
Rostering Coordinator - Orchestrates the roster generation workflow using SequentialAgent.

The workflow enforces a strict sequence:
1. ContextGatherer - Gathers nurse stats, shifts, regulations
2. RosterSolver - Generates optimal roster
3. ValidationPipeline (Parallel) - Compliance + Empathy checks run in parallel
4. RosterPresenter - Synthesizes and presents to user
"""
import logging
from google.adk.agents import LlmAgent, SequentialAgent, ParallelAgent

from agents.context_gatherer import create_context_gatherer_agent
from agents.solver_agent import create_solver_agent
from agents.compliance import create_compliance_agent
from agents.empathy import create_empathy_agent
from agents.presenter import create_presenter_agent

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

logger = logging.getLogger(__name__)


def create_validation_pipeline() -> ParallelAgent:
    """
    Creates a parallel validation pipeline that runs compliance and empathy checks concurrently.
    Both agents read from 'draft_roster' in session state.
    """
    compliance_agent = create_compliance_agent()
    empathy_agent = create_empathy_agent()

    return ParallelAgent(
        name="ValidationPipeline",
        sub_agents=[compliance_agent, empathy_agent]
    )


def create_rostering_workflow() -> SequentialAgent:
    """
    Creates the main rostering workflow as a SequentialAgent.

    This ensures the following steps happen in order:
    1. Context gathering (MUST happen first)
    2. Roster generation (uses gathered context)
    3. Validation (compliance + empathy in parallel)
    4. Presentation (synthesizes all results)

    Session State Flow:
    - ContextGatherer → writes 'gathered_context'
    - RosterSolver → reads context, writes 'draft_roster'
    - ComplianceOfficer → reads 'draft_roster', writes 'compliance_report'
    - EmpathyAdvocate → reads 'draft_roster', writes 'empathy_report'
    - RosterPresenter → reads all, presents to user
    """
    context_gatherer = create_context_gatherer_agent()
    solver = create_solver_agent()
    validation = create_validation_pipeline()
    presenter = create_presenter_agent()

    return SequentialAgent(
        name="RosteringWorkflow",
        sub_agents=[
            context_gatherer,  # Step 1: Gather context
            solver,            # Step 2: Generate roster
            validation,        # Step 3: Validate (parallel)
            presenter          # Step 4: Present to user
        ]
    )


# For backward compatibility, also provide the old coordinator pattern
# This can be used for more flexible, LLM-driven orchestration if needed

COORDINATOR_INSTRUCTION = """
You are the RosteringCoordinator, the main orchestrator for a nurse rostering system.

## Query Capabilities

You can answer questions about nurses, shifts, and staffing:

### Nurse Queries
- **list_nurses(filter_by)**: List nurses. Filters: "senior", "junior", "mid", "available", "fatigued", "fulltime", "parttime", "casual", "icu", "acls", "bls"
- **get_nurse_info(nurse_id)**: Get detailed info for a nurse by ID or name
- **get_nurse_availability(date)**: Check who can work on a date (YYYY-MM-DD)
- **get_nurse_stats()**: Get 30-day stats for all nurses (fatigue, shifts)
- **get_nurse_history(nurse_id, weeks)**: Get shift history for a specific nurse

### Shift & Staffing Queries
- **get_upcoming_shifts(days)**: Show shifts needing assignment (default: 7 days)
- **get_staffing_summary()**: High-level overview with alerts
- **get_shift_history(weeks)**: Historical roster logs

### Roster Management
- **list_pending_rosters()**: Show drafts awaiting approval
- **get_roster(roster_id)**: View a roster's full details and assignments
- **finalize_roster(roster_id)**: Approve a draft roster
- **reject_roster(roster_id, reason)**: Reject a draft roster
- **delete_pending_roster(roster_id)**: Permanently delete a draft/rejected roster

## Roster Generation

For roster generation requests, delegate to the RosteringWorkflow sub-agent which handles:
1. Context gathering
2. Roster generation
3. Compliance validation
4. Empathy review
5. Presentation

## Example Queries

- "Show me all senior nurses" → list_nurses(filter_by="senior")
- "Is Alice available tomorrow?" → get_nurse_info("Alice") or get_nurse_availability("2025-12-05")
- "What shifts need to be filled?" → get_upcoming_shifts()
- "Give me a staffing overview" → get_staffing_summary()
- "Who's fatigued?" → list_nurses(filter_by="fatigued")
- "Show ICU-certified nurses" → list_nurses(filter_by="icu")

## Response Style

- Be professional and concise
- Present information in a readable format
- Use the appropriate query tool based on user intent
"""

from tools.history_tools import list_pending_rosters, finalize_roster, reject_roster, delete_pending_roster, get_roster
from callbacks.format_output import format_model_output


def create_coordinator_agent(model_name: str = "gemini-2.5-pro") -> LlmAgent:
    """
    Creates a lightweight coordinator that delegates to the SequentialAgent workflow.

    This coordinator handles:
    - Initial user requests (delegates to RosteringWorkflow)
    - Direct roster management (approve/reject pending rosters)
    """
    workflow = create_rostering_workflow()

    return LlmAgent(
        name="RosteringCoordinator",
        model=model_name,
        instruction=COORDINATOR_INSTRUCTION,
        tools=[
            # Query tools - nurses
            list_nurses,
            get_nurse_info,
            get_nurse_availability,
            get_nurse_stats,
            get_nurse_history,
            # Query tools - shifts & staffing
            get_upcoming_shifts,
            get_staffing_summary,
            get_shift_history,
            # Roster management
            list_pending_rosters,
            get_roster,
            finalize_roster,
            reject_roster,
            delete_pending_roster
        ],
        sub_agents=[workflow],
        after_model_callback=format_model_output
    )
