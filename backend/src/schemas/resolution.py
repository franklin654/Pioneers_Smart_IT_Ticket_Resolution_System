"""Resolution-related request/response schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from src.db.models import FeedbackAction, ResolutionStep


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: FeedbackAction
    modified_resolution: list[ResolutionStep] | None = None

    @model_validator(mode="after")
    def _validate_modified_required(self) -> "FeedbackRequest":
        if self.action == FeedbackAction.MODIFIED:
            if not self.modified_resolution:
                raise ValueError("modified_resolution is required when action is 'modified'.")
        return self
