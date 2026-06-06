from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class JobCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=10)
    threshold: int = Field(default=60, ge=0, le=100)


class JobResponse(BaseModel):
    id: int
    title: str
    description: str
    threshold: int
    created_at: datetime

    model_config = {"from_attributes": True}


class DimensionResult(BaseModel):
    name: str
    weight: int
    score: int
    evidence: str
    gap: str


class MatchResult(BaseModel):
    candidate_name: str
    overall_score: int
    passed: bool
    dimensions: list[DimensionResult]
    highlights: list[str]
    gaps: list[str]
    rejection_reasons: list[str]
    summary: str


class InterviewQuestion(BaseModel):
    question: str
    category: str
    difficulty: str
    purpose: str
    expected_points: list[str]


class InterviewQuestions(BaseModel):
    technical: list[InterviewQuestion]
    behavioral: list[InterviewQuestion]
    gap_probing: list[InterviewQuestion]


class InterviewResult(BaseModel):
    interview_questions: InterviewQuestions
    interview_focus: list[str]
    estimated_duration: str
    question_count: int


class CandidateResponse(BaseModel):
    id: int
    job_id: int
    name: str
    filename: str
    resume_file_path: Optional[str] = None
    overall_score: Optional[int] = None
    passed: Optional[bool] = None
    match_result: Optional[dict] = None
    interview_result: Optional[dict] = None
    credibility_result: Optional[dict] = None
    answers: Optional[dict] = None
    final_summary: Optional[dict] = None
    status: str
    error_message: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class MatchResponse(BaseModel):
    job_id: int
    job_title: str
    total_candidates: int
    passed_count: int
    rejected_count: int
    candidates: list[CandidateResponse]


class AnswerSaveRequest(BaseModel):
    answers: dict[str, str]


class ReplaceQuestionRequest(BaseModel):
    category: str  # technical / behavioral / gap_probing
    question_index: int


class GenerateQuestionsRequest(BaseModel):
    interview_focus: list[str] = []


class RegenerateFocusRequest(BaseModel):
    current_focus: list[str] = []


class SaveEvaluationRequest(BaseModel):
    """Save evaluation ratings for a single question."""
    question_key: str  # e.g. "technical_0"
    ratings: list[int] = []  # 1-5 rating per expected_point
    skipped: bool = False  # if True, this question is skipped/not interviewed
