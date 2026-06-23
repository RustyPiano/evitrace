from typing import Any, Protocol

from pydantic import BaseModel, Field


class RunCancelled(Exception):
    pass


class ExtractionPersistence(Protocol):
    def load_done(self) -> dict[int, tuple[str, dict]]:
        ...

    def record_batch(
        self,
        batch_index: int,
        input_hash: str,
        status: str,
        result: dict | None,
        error_code: str | None,
        error_message: str | None,
    ) -> None:
        ...

    def set_plan(self, total_batches: int, estimated_input_tokens: int) -> None:
        ...


class SkillManifest(BaseModel):
    id: str
    name: str
    version: str
    description: str
    enabled_by_default: bool
    required: bool
    input_types: list[str]
    output_type: str


class SkillContext(BaseModel):
    task_id: str
    run_id: str | None = None
    data_root: str


class SkillResult(BaseModel):
    success: bool
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    data: dict | list | None = None
    metrics: dict = Field(default_factory=dict)


class Skill(Protocol):
    manifest: SkillManifest

    def run(self, context: SkillContext, payload: Any) -> SkillResult:
        ...
