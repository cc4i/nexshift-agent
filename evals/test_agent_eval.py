"""
NexShift Agent Evaluation Runner

This module provides pytest-based evaluation for all agents in the NexShift
nurse rostering system. It uses ADK-compatible evaluation patterns.

Usage:
    # Run all evaluations
    pytest evals/test_agent_eval.py -v

    # Run specific agent evaluations
    pytest evals/test_agent_eval.py -v -k "compliance"
    pytest evals/test_agent_eval.py -v -k "coordinator"

    # Run with detailed output
    pytest evals/test_agent_eval.py -v --tb=short

    # Run specific test case
    pytest evals/test_agent_eval.py -v -k "validate_roster_with_explicit_id"
"""

import json
import os
import sys
import asyncio
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass
import importlib
import re

try:
    import pytest
    PYTEST_AVAILABLE = True
except ImportError:
    PYTEST_AVAILABLE = False
    print("Warning: pytest not installed. Install with: pip install pytest pytest-asyncio")

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ADK imports
try:
    from google.adk.agents import LlmAgent
    from google.adk.sessions import InMemorySessionService
    from google.adk.runners import Runner
    from google.genai import types
    ADK_AVAILABLE = True
except ImportError:
    ADK_AVAILABLE = False
    print("Warning: ADK not available. Running in mock mode.")


@dataclass
class EvalTestCase:
    """Represents a single evaluation test case."""
    name: str
    description: str
    input: str
    expected_tool_trajectory: List[Dict[str, Any]]
    expected_response_contains: List[str]
    expected_response_not_contains: List[str]
    session_state: Dict[str, Any]
    conversation: Optional[List[Dict[str, str]]]
    mock_tool_response: Optional[Dict[str, Any]]


@dataclass
class EvalResult:
    """Result of running an evaluation test case."""
    test_name: str
    passed: bool
    tool_trajectory_score: float
    response_match_score: float
    actual_tools_called: List[str]
    actual_response: str
    errors: List[str]


class AgentEvaluator:
    """Evaluates agents against test cases."""

    def __init__(self, agent_factory_path: str, agent_factory_name: str):
        self.agent_factory_path = agent_factory_path
        self.agent_factory_name = agent_factory_name
        self._agent = None

    def _get_agent(self) -> LlmAgent:
        """Lazily load the agent."""
        if self._agent is None:
            module = importlib.import_module(self.agent_factory_path)
            factory = getattr(module, self.agent_factory_name)
            self._agent = factory()
        return self._agent

    async def run_test_case(self, test_case: EvalTestCase) -> EvalResult:
        """Run a single test case and return results."""
        errors = []
        actual_tools_called = []
        actual_response = ""

        if not ADK_AVAILABLE:
            # Mock mode for testing without ADK
            return EvalResult(
                test_name=test_case.name,
                passed=True,
                tool_trajectory_score=1.0,
                response_match_score=1.0,
                actual_tools_called=["mock_tool"],
                actual_response="Mock response for testing",
                errors=["ADK not available - running in mock mode"]
            )

        try:
            agent = self._get_agent()

            # Create session with initial state
            session_service = InMemorySessionService()
            session = await session_service.create_session(
                app_name="nexshift_eval",
                user_id="eval_user",
                session_id=f"eval_{test_case.name}"
            )

            # Set initial session state
            if test_case.session_state:
                for key, value in test_case.session_state.items():
                    session.state[key] = value

            # Run the agent
            runner = Runner(
                agent=agent,
                app_name="nexshift_eval",
                session_service=session_service
            )

            # Execute and collect results
            response_parts = []
            async for event in runner.run_async(
                user_id="eval_user",
                session_id=session.id,
                new_message=types.Content(
                    role="user",
                    parts=[types.Part(text=test_case.input)]
                )
            ):
                if hasattr(event, 'content') and event.content:
                    if hasattr(event.content, 'parts'):
                        for part in event.content.parts:
                            if hasattr(part, 'text') and part.text:
                                response_parts.append(part.text)
                            if hasattr(part, 'function_call') and part.function_call:
                                actual_tools_called.append(part.function_call.name)

            actual_response = "\n".join(response_parts)

        except Exception as e:
            errors.append(f"Execution error: {str(e)}")
            return EvalResult(
                test_name=test_case.name,
                passed=False,
                tool_trajectory_score=0.0,
                response_match_score=0.0,
                actual_tools_called=actual_tools_called,
                actual_response=actual_response,
                errors=errors
            )

        # Calculate scores
        tool_trajectory_score = self._calculate_tool_trajectory_score(
            test_case.expected_tool_trajectory,
            actual_tools_called
        )

        response_match_score = self._calculate_response_match_score(
            test_case.expected_response_contains,
            test_case.expected_response_not_contains,
            actual_response
        )

        # Determine pass/fail
        passed = tool_trajectory_score >= 0.8 and response_match_score >= 0.6

        return EvalResult(
            test_name=test_case.name,
            passed=passed,
            tool_trajectory_score=tool_trajectory_score,
            response_match_score=response_match_score,
            actual_tools_called=actual_tools_called,
            actual_response=actual_response,
            errors=errors
        )

    def _calculate_tool_trajectory_score(
        self,
        expected: List[Dict[str, Any]],
        actual: List[str]
    ) -> float:
        """Calculate tool trajectory matching score."""
        if not expected and not actual:
            return 1.0
        if not expected:
            return 0.5  # Tools called but none expected
        if not actual:
            return 0.0  # Expected tools but none called

        # Check if expected tools are in actual calls (order-independent)
        expected_names = [t.get("tool_name") for t in expected]
        matches = sum(1 for name in expected_names if name in actual)

        return matches / len(expected_names) if expected_names else 1.0

    def _calculate_response_match_score(
        self,
        expected_contains: List[str],
        expected_not_contains: List[str],
        actual: str
    ) -> float:
        """Calculate response content matching score."""
        if not expected_contains and not expected_not_contains:
            return 1.0

        actual_lower = actual.lower()

        # Check expected_contains
        contains_matches = 0
        if expected_contains:
            for term in expected_contains:
                if term.lower() in actual_lower:
                    contains_matches += 1
            contains_score = contains_matches / len(expected_contains)
        else:
            contains_score = 1.0

        # Check expected_not_contains
        not_contains_matches = 0
        if expected_not_contains:
            for term in expected_not_contains:
                if term.lower() not in actual_lower:
                    not_contains_matches += 1
            not_contains_score = not_contains_matches / len(expected_not_contains)
        else:
            not_contains_score = 1.0

        return (contains_score + not_contains_score) / 2


def load_test_cases(test_file_path: str) -> List[EvalTestCase]:
    """Load test cases from a JSON file."""
    with open(test_file_path, 'r') as f:
        data = json.load(f)

    test_cases = []
    for tc in data.get("test_cases", []):
        test_cases.append(EvalTestCase(
            name=tc.get("name", "unnamed"),
            description=tc.get("description", ""),
            input=tc.get("input", ""),
            expected_tool_trajectory=tc.get("expected_tool_trajectory", []),
            expected_response_contains=tc.get("expected_response_contains", []),
            expected_response_not_contains=tc.get("expected_response_not_contains", []),
            session_state=tc.get("session_state", {}),
            conversation=tc.get("conversation"),
            mock_tool_response=tc.get("mock_tool_response")
        ))

    return test_cases


def load_evalset(evalset_path: str) -> Dict[str, Any]:
    """Load evaluation set configuration."""
    with open(evalset_path, 'r') as f:
        return json.load(f)


# ============================================================================
# Pytest Test Discovery and Execution
# ============================================================================

EVALS_DIR = Path(__file__).parent


def get_all_evalsets() -> List[Tuple[str, str, str]]:
    """Discover all evalset files and their test files."""
    evalsets = []

    for evalset_file in EVALS_DIR.rglob("*.evalset.json"):
        evalset = load_evalset(str(evalset_file))
        test_file = evalset_file.parent / evalset.get("test_file", "")

        if test_file.exists():
            evalsets.append((
                str(evalset_file),
                str(test_file),
                evalset.get("eval_set_id", evalset_file.stem)
            ))

    return evalsets


def generate_test_params():
    """Generate pytest parameters for all test cases."""
    params = []

    for evalset_path, test_file_path, eval_id in get_all_evalsets():
        evalset = load_evalset(evalset_path)
        test_cases = load_test_cases(test_file_path)

        for tc in test_cases:
            params.append(pytest.param(
                evalset,
                tc,
                id=f"{eval_id}::{tc.name}"
            ))

    return params


# Test data management
EVALS_TEST_DATA_DIR = Path(__file__).parent / "test_data"
PROJECT_DATA_DIR = Path(__file__).parent.parent / "data"

# Track rosters that exist before tests run (these should NOT be deleted)
_pre_existing_rosters: set = set()


def setup_test_data():
    """Copy test fixtures from evals/test_data to data/ for tests."""
    global _pre_existing_rosters

    dst_rosters = PROJECT_DATA_DIR / "rosters"

    # Record all rosters that exist BEFORE tests run
    if dst_rosters.exists():
        _pre_existing_rosters = {f.name for f in dst_rosters.glob("roster_*.json")}

    # Copy test rosters (files starting with roster_2025010608 are test fixtures)
    src_rosters = EVALS_TEST_DATA_DIR / "rosters"

    if src_rosters.exists():
        for roster_file in src_rosters.glob("roster_2025010608*.json"):
            shutil.copy(roster_file, dst_rosters / roster_file.name)


def teardown_test_data():
    """Remove test fixtures and any rosters generated during tests."""
    dst_rosters = PROJECT_DATA_DIR / "rosters"

    # Remove test fixtures (files starting with roster_2025010608)
    for roster_file in dst_rosters.glob("roster_2025010608*.json"):
        roster_file.unlink(missing_ok=True)

    # Remove any rosters created DURING tests (not in pre-existing set)
    for roster_file in dst_rosters.glob("roster_*.json"):
        if roster_file.name not in _pre_existing_rosters:
            roster_file.unlink(missing_ok=True)


# Skip all tests if pytest is not available
if PYTEST_AVAILABLE:
    # Session-scoped fixture for test data setup/teardown
    @pytest.fixture(scope="session", autouse=True)
    def manage_test_data():
        """Setup test data before all tests, teardown after."""
        setup_test_data()
        yield
        teardown_test_data()

    # Skip all tests if ADK is not available
    @pytest.mark.skipif(not ADK_AVAILABLE, reason="ADK not installed")
    class TestAgentEvaluations:
        """Test class for agent evaluations."""

        @pytest.fixture(autouse=True)
        def setup(self):
            """Setup for each test."""
            self.evaluators = {}

        def get_evaluator(self, evalset: Dict[str, Any]) -> AgentEvaluator:
            """Get or create an evaluator for the given evalset."""
            key = evalset.get("eval_set_id", "default")
            if key not in self.evaluators:
                self.evaluators[key] = AgentEvaluator(
                    agent_factory_path=evalset.get("agent_module", ""),
                    agent_factory_name=evalset.get("agent_factory", "")
                )
            return self.evaluators[key]

        @pytest.mark.parametrize("evalset,test_case", generate_test_params() if PYTEST_AVAILABLE else [])
        @pytest.mark.asyncio
        async def test_agent_behavior(
            self,
            evalset: Dict[str, Any],
            test_case: EvalTestCase
        ):
            """Test a single agent behavior."""
            evaluator = self.get_evaluator(evalset)
            result = await evaluator.run_test_case(test_case)

            # Print detailed results for debugging
            print(f"\n{'='*60}")
            print(f"Test: {result.test_name}")
            print(f"Tool Trajectory Score: {result.tool_trajectory_score:.2f}")
            print(f"Response Match Score: {result.response_match_score:.2f}")
            print(f"Tools Called: {result.actual_tools_called}")
            if result.errors:
                print(f"Errors: {result.errors}")
            print(f"{'='*60}")

            # Get thresholds from evalset
            metrics = evalset.get("metrics", [])
            tool_threshold = 0.8
            response_threshold = 0.5

            for metric in metrics:
                if metric.get("metric_name") == "tool_trajectory_avg_score":
                    tool_threshold = metric.get("threshold", 0.8)
                elif metric.get("metric_name") == "response_match_score":
                    response_threshold = metric.get("threshold", 0.5)

            # Assert thresholds
            assert result.tool_trajectory_score >= tool_threshold, \
                f"Tool trajectory score {result.tool_trajectory_score:.2f} below threshold {tool_threshold}"

            assert result.response_match_score >= response_threshold, \
                f"Response match score {result.response_match_score:.2f} below threshold {response_threshold}"


# ============================================================================
# CLI Entry Point
# ============================================================================

def run_evaluation_report():
    """Run all evaluations and generate a summary report."""
    print("\n" + "="*70)
    print("NexShift Agent Evaluation Report")
    print("="*70 + "\n")

    evalsets = get_all_evalsets()

    for evalset_path, test_file_path, eval_id in evalsets:
        evalset = load_evalset(evalset_path)
        test_cases = load_test_cases(test_file_path)

        print(f"\n{evalset.get('name', eval_id)}")
        print("-" * 50)
        print(f"Test cases: {len(test_cases)}")
        print(f"Categories: {list(evalset.get('categories', {}).keys())}")

        for category, cases in evalset.get("categories", {}).items():
            print(f"  - {category}: {len(cases)} tests")

    print("\n" + "="*70)
    print("Run 'pytest evals/test_agent_eval.py -v' to execute all tests")
    print("="*70 + "\n")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--report":
        run_evaluation_report()
    else:
        # Run pytest
        pytest.main([__file__, "-v", "--tb=short"] + sys.argv[1:])
