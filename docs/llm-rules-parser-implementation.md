# LLM-Based Hospital Rules Parser Implementation Plan

## Overview

Implement an LLM-triggered parser that converts `hospital_rules.txt` into structured JSON, with schema validation and retry logic.

## Current State

- **Rules file**: `data/regulations/hospital_rules.txt` - plain text format
- **Loader**: `tools/data_loader.py` - `get_regulations()` returns raw text
- **Consumer**: `agents/compliance.py` - ComplianceOfficer agent reads raw text

## Implementation Steps

### 1. Create Pydantic Schema (`models/rules.py`)

```python
"""
Pydantic schemas for hospital rules validation.
"""
from typing import List, Optional
from pydantic import BaseModel, Field


class ShiftLimits(BaseModel):
    """Rules for shift limits and rest requirements."""
    max_consecutive_shifts: int = Field(..., description="Maximum consecutive shifts allowed")
    max_hours_per_week_fulltime: int = Field(..., description="Max hours/week for FullTime")
    max_hours_per_week_parttime: int = Field(..., description="Max hours/week for PartTime")
    max_hours_per_week_casual: int = Field(..., description="Max hours/week for Casual")
    min_rest_hours_between_shifts: int = Field(..., description="Min rest between shifts (hours)")


class CoverageRequirement(BaseModel):
    """A single coverage requirement."""
    description: str
    shift_type: Optional[str] = None  # 'ICU', 'Emergency', 'all'
    required_certifications: List[str] = Field(default_factory=list)
    requires_senior: bool = False


class FairnessRule(BaseModel):
    """Fair distribution rule."""
    rule_type: str  # 'weekend_distribution', 'night_rotation', 'preference_honoring'
    description: str
    priority: str = "normal"  # 'high', 'normal', 'low'


class SpecialConsideration(BaseModel):
    """Special scheduling consideration."""
    consideration_type: str  # 'availability', 'time_off', 'consent'
    description: str
    applies_to: Optional[str] = None  # 'Casual', 'all'
    priority: str = "normal"


class HospitalRules(BaseModel):
    """Complete hospital rules schema."""
    shift_limits: ShiftLimits
    coverage_requirements: List[CoverageRequirement]
    fairness_rules: List[FairnessRule]
    special_considerations: List[SpecialConsideration]


# Default rules - fallback when LLM parsing fails
DEFAULT_HOSPITAL_RULES = HospitalRules(
    shift_limits=ShiftLimits(
        max_consecutive_shifts=3,
        max_hours_per_week_fulltime=40,
        max_hours_per_week_parttime=30,
        max_hours_per_week_casual=20,
        min_rest_hours_between_shifts=10
    ),
    coverage_requirements=[
        CoverageRequirement(
            description="At least one Senior nurse must be on duty for every shift",
            shift_type="all",
            requires_senior=True
        ),
        CoverageRequirement(
            description="ICU shifts require ICU-certified nurses only",
            shift_type="ICU",
            required_certifications=["ICU"]
        ),
        CoverageRequirement(
            description="Emergency shifts require both ACLS and BLS certifications",
            shift_type="Emergency",
            required_certifications=["ACLS", "BLS"]
        )
    ],
    fairness_rules=[
        FairnessRule(rule_type="weekend_distribution", description="Weekend shifts distributed fairly"),
        FairnessRule(rule_type="night_rotation", description="Night shifts rotate among eligible nurses"),
        FairnessRule(rule_type="preference_honoring", description="Honor preferences when possible", priority="low")
    ],
    special_considerations=[
        SpecialConsideration(consideration_type="availability", description="Casual nurses have limited availability", applies_to="Casual"),
        SpecialConsideration(consideration_type="time_off", description="Adhoc time-off requests take priority", priority="high"),
        SpecialConsideration(consideration_type="consent", description="Consecutive weekend work requires nurse consent", priority="high")
    ]
)
```

### 2. Create LLM Rules Parser Tool (`tools/rules_parser.py`)

```python
"""
LLM-based parser for hospital rules with schema validation and retry.
"""
import json
import logging
from typing import Optional
from pydantic import ValidationError
from google.adk.agents import LlmAgent
from models.rules import HospitalRules, DEFAULT_HOSPITAL_RULES
from tools.data_loader import load_regulations

logger = logging.getLogger(__name__)

MAX_RETRIES = 3

PARSER_INSTRUCTION = """
You are a rules parser. Convert the hospital regulations text into a structured JSON format.

You MUST output ONLY valid JSON matching this exact schema - no markdown, no explanation:

{
  "shift_limits": {
    "max_consecutive_shifts": <int>,
    "max_hours_per_week_fulltime": <int>,
    "max_hours_per_week_parttime": <int>,
    "max_hours_per_week_casual": <int>,
    "min_rest_hours_between_shifts": <int>
  },
  "coverage_requirements": [
    {
      "description": "<string>",
      "shift_type": "<string or null>",
      "required_certifications": ["<string>", ...],
      "requires_senior": <bool>
    }
  ],
  "fairness_rules": [
    {
      "rule_type": "<string>",
      "description": "<string>",
      "priority": "<high|normal|low>"
    }
  ],
  "special_considerations": [
    {
      "consideration_type": "<string>",
      "description": "<string>",
      "applies_to": "<string or null>",
      "priority": "<high|normal|low>"
    }
  ]
}

Extract ALL rules from the provided text. Output ONLY the JSON object.
"""


async def parse_rules_with_llm(rules_text: str, model_name: str = "gemini-2.5-flash") -> HospitalRules:
    """
    Parse hospital rules text using LLM with schema validation and retry.

    Args:
        rules_text: Raw text from hospital_rules.txt
        model_name: LLM model to use

    Returns:
        Validated HospitalRules object

    Raises:
        ValueError: If all retries fail (caller should use DEFAULT_HOSPITAL_RULES)
    """
    from google import genai

    client = genai.Client()

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # Build prompt with error feedback if retrying
            prompt = f"Parse these hospital regulations:\n\n{rules_text}"
            if last_error and attempt > 1:
                prompt += f"\n\nYour previous output failed validation with error:\n{last_error}\n\nPlease fix and try again. Output ONLY valid JSON."

            # Call LLM
            response = await client.aio.models.generate_content(
                model=model_name,
                contents=prompt,
                config={
                    "system_instruction": PARSER_INSTRUCTION,
                    "temperature": 0.1  # Low temperature for structured output
                }
            )

            # Extract JSON from response
            response_text = response.text.strip()

            # Handle potential markdown code blocks
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                response_text = "\n".join(lines[1:-1])

            # Parse JSON
            parsed_data = json.loads(response_text)

            # Validate against Pydantic schema
            validated_rules = HospitalRules(**parsed_data)

            logger.info(f"Successfully parsed hospital rules on attempt {attempt}")
            return validated_rules

        except json.JSONDecodeError as e:
            last_error = f"Invalid JSON: {e}"
            logger.warning(f"Attempt {attempt}/{MAX_RETRIES} failed - {last_error}")

        except ValidationError as e:
            last_error = f"Schema validation failed: {e}"
            logger.warning(f"Attempt {attempt}/{MAX_RETRIES} failed - {last_error}")

        except Exception as e:
            last_error = f"Unexpected error: {e}"
            logger.warning(f"Attempt {attempt}/{MAX_RETRIES} failed - {last_error}")

    # All retries exhausted
    raise ValueError(f"Failed to parse rules after {MAX_RETRIES} attempts. Last error: {last_error}")


def get_hospital_rules_sync() -> HospitalRules:
    """
    Synchronous wrapper that returns DEFAULT_HOSPITAL_RULES.
    Use parse_rules_with_llm() for async LLM-based parsing.
    """
    return DEFAULT_HOSPITAL_RULES


async def get_parsed_hospital_rules(force_refresh: bool = False) -> HospitalRules:
    """
    Get parsed hospital rules, using LLM parsing with fallback to defaults.

    Args:
        force_refresh: If True, re-parse even if cached

    Returns:
        Validated HospitalRules object
    """
    # TODO: Add caching layer if needed

    try:
        rules_text = load_regulations()
        return await parse_rules_with_llm(rules_text)
    except ValueError as e:
        logger.error(f"LLM parsing failed, using defaults: {e}")
        return DEFAULT_HOSPITAL_RULES


# ADK Tool function for agents
def get_structured_regulations() -> str:
    """
    Returns hospital regulations as structured JSON.
    Uses default rules (synchronous). For LLM-parsed rules, use async version.
    """
    return DEFAULT_HOSPITAL_RULES.model_dump_json(indent=2)
```

### 3. Update Compliance Agent (`agents/compliance.py`)

```python
"""
Compliance Officer Agent - Validates rosters against regulations.
"""
from google.adk.agents import LlmAgent
from tools.rules_parser import get_structured_regulations

COMPLIANCE_INSTRUCTION = """
You are a Compliance Officer for a hospital nurse rostering system.

## Input
- Draft roster from session state key 'draft_roster'
- Structured regulations from get_structured_regulations() tool

## Regulations Schema
The regulations JSON contains:
- shift_limits: max consecutive shifts, weekly hours by contract type, min rest hours
- coverage_requirements: certifications and seniority requirements per shift type
- fairness_rules: weekend/night distribution rules
- special_considerations: time-off, consent requirements

## Validation Process
1. Call get_structured_regulations() to get rules JSON
2. Check each rule category against the roster:
   - Shift limits: consecutive shifts, weekly hours, rest periods
   - Coverage: certifications, senior presence
   - Fairness: distribution checks
   - Special: time-off honored, consent obtained

## Output Format
```
COMPLIANCE REPORT
=================
Status: PASS / FAIL

Rules Checked:
- [Rule]: PASS/FAIL - [details]
...

Violations Found: [count]
[List violations]

Summary: [Brief status]
```
"""


def create_compliance_agent(model_name: str = "gemini-2.5-flash") -> LlmAgent:
    return LlmAgent(
        name="ComplianceOfficer",
        model=model_name,
        instruction=COMPLIANCE_INSTRUCTION,
        output_key="compliance_report",
        tools=[get_structured_regulations]  # Changed from get_regulations
    )
```

### 4. Integration with Solver (`tools/solver_tool.py`)

Update the solver to use structured rules:

```python
from models.rules import HospitalRules, DEFAULT_HOSPITAL_RULES

def _solve_roster_internal(nurses_objs: list, shifts_objs: list, nurse_stats: dict,
                           rules: HospitalRules = None) -> str:
    """Internal solver with structured rules."""
    if rules is None:
        rules = DEFAULT_HOSPITAL_RULES

    # Use rules.shift_limits.max_consecutive_shifts instead of hardcoded 3
    MAX_CONSECUTIVE_SHIFTS = rules.shift_limits.max_consecutive_shifts
    MIN_REST_HOURS = rules.shift_limits.min_rest_hours_between_shifts

    MAX_HOURS = {
        "FullTime": rules.shift_limits.max_hours_per_week_fulltime,
        "PartTime": rules.shift_limits.max_hours_per_week_parttime,
        "Casual": rules.shift_limits.max_hours_per_week_casual
    }

    # ... rest of solver logic using structured rules
```

## File Changes Summary

| File | Action | Description |
|------|--------|-------------|
| `models/rules.py` | CREATE | Pydantic schemas + DEFAULT_HOSPITAL_RULES |
| `tools/rules_parser.py` | CREATE | LLM parser with retry + validation |
| `agents/compliance.py` | UPDATE | Use structured regulations tool |
| `tools/solver_tool.py` | UPDATE | Accept HospitalRules parameter |

## Key Features

1. **Schema Validation**: Pydantic enforces exact structure
2. **Retry Logic**: Up to 3 attempts with error feedback to LLM
3. **No Fallback Needed**: Default JSON derived from hospital_rules.txt always available
4. **Rejection on Mismatch**: ValidationError raised if LLM output doesn't match schema

## Testing

```python
# Test schema validation
from models.rules import HospitalRules

# Should pass
valid = {"shift_limits": {...}, "coverage_requirements": [...], ...}
HospitalRules(**valid)

# Should raise ValidationError
invalid = {"shift_limits": {"max_consecutive_shifts": "three"}}  # wrong type
HospitalRules(**invalid)  # Raises ValidationError

# Test LLM parsing
import asyncio
from tools.rules_parser import parse_rules_with_llm

async def test():
    rules_text = open("data/regulations/hospital_rules.txt").read()
    try:
        result = await parse_rules_with_llm(rules_text)
        print("Parsed successfully:", result)
    except ValueError as e:
        print("Failed, using defaults:", e)

asyncio.run(test())
```
