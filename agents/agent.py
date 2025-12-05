"""
Agent entry point for the Nurse Rostering System.

This module provides two options for the root agent:

1. RosteringWorkflow (SequentialAgent) - Recommended for roster generation
   - Enforces strict workflow: Context → Solver → Validation → Presentation
   - Uses session state to pass data between steps
   - No LLM-based orchestration overhead

2. RosteringCoordinator (LlmAgent) - For flexible orchestration
   - Can handle varied requests
   - Delegates to RosteringWorkflow for generation tasks
   - Handles direct roster management (approve/reject)
"""
import logging
from agents.coordinator import create_rostering_workflow, create_coordinator_agent

# Configure logging
logging.basicConfig(level=logging.INFO)

# Option 1: Use SequentialAgent workflow directly (simpler, more deterministic)
# This is recommended when the primary use case is roster generation
# root_agent = create_rostering_workflow()

# Option 2: Use LlmAgent coordinator (more flexible)
# This allows handling various requests and delegates to workflow for generation
root_agent = create_coordinator_agent()
