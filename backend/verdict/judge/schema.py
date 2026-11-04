"""Structured output the AI judge MUST return (validated with Pydantic, Phase 3).
Note: there is deliberately NO amount field anywhere in this schema."""

from enum import StrEnum

from pydantic import BaseModel, Field


class Category(StrEnum):
    MEMORIZATION = "memorization"
    TEST_TAMPERING = "test_tampering"
    GRADER_MANIPULATION = "grader_manipulation"
    ENVIRONMENT_SNIFFING = "environment_sniffing"
    SPEC_VIOLATION = "spec_violation"
    OTHER = "other"


class ReviewFinding(BaseModel):
    file: str
    line: int = Field(ge=1)
    category: Category
    evidence: str = Field(max_length=500)


class Review(BaseModel):
    decision: str = Field(pattern="^(CLEAR|HUMAN_REVIEW|BLOCK_RECOMMENDED)$")
    findings: list[ReviewFinding] = []
    explanation: str = Field(max_length=2000)


class SpecCheckItem(BaseModel):
    test_id: str
    implied_by_spec: bool
    reason: str = Field(max_length=500)


class SpecCheck(BaseModel):
    items: list[SpecCheckItem]
