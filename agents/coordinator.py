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
    list_nurse_preferences,
    get_nurse_availability,
    get_upcoming_shifts,
    get_staffing_summary
)
from tools.history_tools import (
    get_nurse_stats,
    get_shift_history,
    get_nurse_history
)
from tools.data_loader import get_regulations

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

## IMPORTANT: Preserving Formatted Output

Many tools return pre-formatted text with calendar views, tables, and structured layouts.
When a tool returns formatted output (with newlines, separators like "===", tables, etc.):
- Output the tool result EXACTLY as returned
- Do NOT summarize, condense, or reformat it
- Do NOT put it all on one line
- Just present the formatted output directly to the user

## Query Capabilities

You can answer questions about nurses, shifts, and staffing:

### Nurse Queries
- **list_nurses(filter_by)**: List nurses. Filters: "senior", "junior", "mid", "available", "fatigued", "fulltime", "parttime", "casual", "icu", "acls", "bls"
- **list_nurse_preferences()**: List all nurses' scheduling preferences (night shift avoidance, preferred days, time-off requests)
- **get_nurse_info(nurse_id)**: Get detailed info for a nurse by ID or name
- **get_nurse_availability(date)**: Check who can work on a date (YYYY-MM-DD)
- **get_nurse_stats()**: Get 30-day stats for all nurses (fatigue, shifts)
- **get_nurse_history(nurse_id, weeks)**: Get shift history for a specific nurse

### Shift & Staffing Queries
- **get_upcoming_shifts(days)**: Show shifts needing assignment (default: 7 days)
- **get_staffing_summary()**: High-level overview with alerts
- **get_shift_history(weeks)**: Historical roster logs
- **get_regulations()**: Display hospital regulations and labor laws for nurse scheduling

### Roster Management
- **list_pending_rosters()**: Show drafts awaiting approval
- **list_all_rosters()**: Show ALL rosters (drafts, finalized, rejected) with status
- **get_roster(roster_id)**: View a single roster's calendar details
- **get_rosters_by_date_range(start_date, end_date)**: View schedule across a date range (may combine multiple rosters)
  Use this when user asks for a date range like "show me 2025-12-05 to 2025-12-15"
  IMPORTANT: This tool returns a pre-formatted calendar view with newlines.
  You MUST output the tool's result EXACTLY as returned - do NOT summarize,
  condense, or reformat it. Just output the entire tool result verbatim.
- **finalize_roster(roster_id)**: Approve a draft roster
- **reject_roster(roster_id, reason)**: Reject a draft roster
- **delete_roster(roster_id)**: Permanently delete a draft/rejected roster

### Direct Validation (without full workflow)
Use these to validate a specific roster without running the full generation workflow:
- **validate_roster_compliance(roster_id)**: Check certification, seniority, and senior coverage compliance
- **validate_weekly_hours(roster_id)**: Check weekly hour limits per contract type
- **analyze_roster_fairness(roster_id)**: Check empathy score, preference violations, burnout risks

### HRIS Management (Hiring, Promotions, Certifications)
- **add_nurse(name, seniority_level, contract_type, certifications, ...)**: Add a new nurse to the system
- **promote_nurse(nurse_id, new_level)**: Promote a nurse to a higher seniority level
- **update_nurse_certifications(nurse_id, add_certifications, remove_certifications)**: Update nurse certifications
- **update_nurse_preferences(nurse_id, avoid_night_shifts, preferred_days)**: Update nurse scheduling preferences
- **remove_nurse(nurse_id)**: Remove a nurse from the system
- **list_available_certifications()**: Show available certifications and ward requirements

## Roster Generation

For roster generation requests, delegate to the RosteringWorkflow sub-agent which handles:
1. Context gathering
2. Roster generation
3. Compliance validation
4. Empathy review
5. Presentation

## Example Queries

- "Show me all senior nurses" → list_nurses(filter_by="senior")
- "Show nurse preferences" → list_nurse_preferences()
- "Is Alice available tomorrow?" → get_nurse_info("Alice") or get_nurse_availability("2025-12-05")
- "What shifts need to be filled?" → get_upcoming_shifts()
- "Give me a staffing overview" → get_staffing_summary()
- "Who's fatigued?" → list_nurses(filter_by="fatigued")
- "Show ICU-certified nurses" → list_nurses(filter_by="icu")

## HRIS Examples

- "Hire a new ICU nurse named John" → add_nurse(name="John", seniority_level="Mid", certifications="ICU,BLS")
- "Promote Bob to Mid level" → promote_nurse(nurse_id="nurse_002", new_level="Mid")
- "Add ICU certification to Charlie" → update_nurse_certifications(nurse_id="nurse_003", add_certifications="ICU")
- "What certifications are available?" → list_available_certifications()

## Response Style

- Be professional
- For formatted tool output (calendars, tables, reports), present it EXACTLY as returned
- For simple queries or your own responses, be concise
- Use the appropriate query tool based on user intent
"""

from tools.history_tools import (
    list_pending_rosters,
    list_all_rosters,
    finalize_roster,
    reject_roster,
    delete_roster,
    delete_pending_roster,
    get_roster,
    get_rosters_by_date_range
)
from tools.hris_tools import (
    add_nurse,
    promote_nurse,
    update_nurse_certifications,
    update_nurse_preferences,
    remove_nurse,
    list_available_certifications
)
from tools.compliance_tools import (
    validate_roster_compliance,
    validate_weekly_hours
)
from tools.empathy_tools import (
    analyze_roster_fairness
)
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
            list_nurse_preferences,
            get_nurse_info,
            get_nurse_availability,
            get_nurse_stats,
            get_nurse_history,
            # Query tools - shifts & staffing
            get_upcoming_shifts,
            get_staffing_summary,
            get_shift_history,
            get_regulations,
            # Roster management
            list_pending_rosters,
            list_all_rosters,
            get_roster,
            get_rosters_by_date_range,
            finalize_roster,
            reject_roster,
            delete_roster,
            delete_pending_roster,
            # HRIS management - hiring, promotions, certifications
            add_nurse,
            promote_nurse,
            update_nurse_certifications,
            update_nurse_preferences,
            remove_nurse,
            list_available_certifications,
            # Direct validation tools
            validate_roster_compliance,
            validate_weekly_hours,
            analyze_roster_fairness
        ],
        sub_agents=[workflow],
        after_model_callback=format_model_output
    )
