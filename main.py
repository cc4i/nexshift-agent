import asyncio
import logging
import sys
import os

from google.adk.sessions import InMemorySessionService
from google.adk.runners import Runner
from google.genai import types

from agents.coordinator import RosteringCoordinator
from agents.solver_agent import create_solver_agent
from agents.compliance import create_compliance_agent
from agents.empathy import create_empathy_agent

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    # 1. Initialize Agents
    solver_agent = create_solver_agent()
    compliance_agent = create_compliance_agent()
    empathy_agent = create_empathy_agent()
    
    coordinator = RosteringCoordinator(
        name="RosteringCoordinator",
        solver_agent=solver_agent,
        compliance_agent=compliance_agent,
        empathy_agent=empathy_agent
    )

    # 2. Setup Session
    session_service = InMemorySessionService()
    app_name = "nurse_rostering_app"
    user_id = "admin"
    session_id = "session_001"
    
    await session_service.create_session(
        app_name=app_name, 
        user_id=user_id, 
        session_id=session_id, 
        state={}
    )

    # 3. Run Agent
    runner = Runner(
        agent=coordinator,
        app_name=app_name,
        session_service=session_service
    )
    
    user_input = "Generate a roster for next week. Nurse Alice needs Friday off for a recital."
    content = types.Content(role='user', parts=[types.Part(text=user_input)])
    
    logger.info(f"Sending request: {user_input}")
    
    async for event in runner.run_async(user_id=user_id, session_id=session_id, new_message=content):
        pass # Logging is handled inside the agents

if __name__ == "__main__":
    asyncio.run(main())
