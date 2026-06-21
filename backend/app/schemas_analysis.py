from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.constants import (
    CONFLICT_STATUS_CONFIRMED,
    CONFLICT_STATUS_IGNORED,
    CONFLICT_STATUS_UNREVIEWED,
)

EntityType = Literal["person", "organization", "location", "event", "object", "time", "quantity"]
ConflictType = Literal["time", "location", "quantity"]
ConflictStatus = Literal["unreviewed", "confirmed", "ignored"]


class AnalysisBaseModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Entity(AnalysisBaseModel):
    type: EntityType
    name: str = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        return value.strip()


class Quantity(AnalysisBaseModel):
    value: float
    unit: str = Field(min_length=1)

    @field_validator("unit")
    @classmethod
    def trim_unit(cls, value: str) -> str:
        return value.strip()


class Event(AnalysisBaseModel):
    event_id: str | None = None
    event_key: str = Field(min_length=1)
    title: str = Field(min_length=1)
    subject: str | None = None
    action: str | None = None
    object: str | None = None
    time_text: str | None = None
    time_normalized: str | None = None
    location: str | None = None
    quantity: Quantity | None = None
    evidence_ids: list[str] = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0, le=1)

    @field_validator(
        "event_key",
        "title",
        "subject",
        "action",
        "object",
        "time_text",
        "time_normalized",
        "location",
        mode="before",
    )
    @classmethod
    def trim_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class ExtractionResult(AnalysisBaseModel):
    entities: list[Entity] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)


class TimelineItem(AnalysisBaseModel):
    event_id: str
    event_key: str
    title: str
    time_text: str | None = None
    time_normalized: str | None = None
    time_group: str
    location: str | None = None
    evidence_ids: list[str] = Field(min_length=1)


class ConflictSide(AnalysisBaseModel):
    value: str
    event_id: str
    evidence_ids: list[str] = Field(min_length=1)


class Conflict(AnalysisBaseModel):
    conflict_id: str
    type: ConflictType
    event_key: str
    description: str
    left: ConflictSide
    right: ConflictSide
    status: ConflictStatus = CONFLICT_STATUS_UNREVIEWED


class CitationCheck(AnalysisBaseModel):
    used_citations: list[str] = Field(default_factory=list)
    invalid_citations: list[str] = Field(default_factory=list)
    valid_citation_count: int = 0
    invalid_citation_count: int = 0
    citation_coverage: float = Field(default=1.0, ge=0, le=1)
    conclusion_paragraph_count: int = 0
    cited_conclusion_paragraph_count: int = 0


class ConflictStatusUpdate(BaseModel):
    status: ConflictStatus

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        allowed = {
            CONFLICT_STATUS_UNREVIEWED,
            CONFLICT_STATUS_CONFIRMED,
            CONFLICT_STATUS_IGNORED,
        }
        if value not in allowed:
            raise ValueError("status must be unreviewed, confirmed, or ignored")
        return value
