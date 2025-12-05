from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field

class NursePreferences(BaseModel):
    avoid_night_shifts: bool = False
    preferred_days: List[str] = Field(default_factory=list)
    adhoc_requests: List[str] = Field(default_factory=list)

class NurseHistory(BaseModel):
    last_shift: Optional[datetime] = None
    consecutive_shifts: int = 0
    weekend_shifts_last_month: int = 0

class Nurse(BaseModel):
    id: str
    name: str
    certifications: List[str] = Field(default_factory=list)
    seniority_level: str
    contract_type: str
    preferences: NursePreferences
    history_summary: NurseHistory

class Shift(BaseModel):
    id: str
    ward: str
    start_time: datetime
    end_time: datetime
    required_certifications: List[str] = Field(default_factory=list)
    min_level: str

class Assignment(BaseModel):
    nurse_id: str
    shift_id: str

class RosterMetadata(BaseModel):
    generated_at: datetime
    compliance_status: str
    empathy_score: float
    compliance_notes: Optional[str] = None
    empathy_notes: Optional[str] = None

class Roster(BaseModel):
    id: str
    assignments: List[Assignment] = Field(default_factory=list)
    metadata: RosterMetadata
