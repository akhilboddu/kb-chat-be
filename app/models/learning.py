from pydantic import BaseModel, Field
import datetime
from typing import List, Optional, Dict, Any
from uuid import UUID


class Learning(BaseModel):
    """Model representing an AI-generated learning from conversations."""
    id: UUID
    bot_id: UUID
    title: str
    content: str
    source: Optional[str] = None
    confidence_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    status: str = Field(default="pending", pattern="^(pending|approved|rejected)$")
    conversation_id: Optional[str] = None
    gap_summary: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)
    created_at: Optional[datetime.datetime] = None
    updated_at: Optional[datetime.datetime] = None


class CreateLearningRequest(BaseModel):
    """Request model for creating a new learning entry."""
    bot_id: UUID
    title: str
    content: str
    source: Optional[str] = None
    confidence_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    conversation_id: Optional[str] = None
    gap_summary: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)


class UpdateLearningStatusRequest(BaseModel):
    """Request model for updating learning status."""
    status: str = Field(pattern="^(pending|approved|rejected)$")


class ListLearningsResponse(BaseModel):
    """Response model for listing learnings for a bot."""
    learnings: List[Learning]
    total_count: int
    pending_count: int
    approved_count: int
    rejected_count: int


class PaginatedListLearningsResponse(BaseModel):
    """Response model for listing learnings with pagination."""
    learnings: List[Learning]
    total_count: int
    pending_count: int
    approved_count: int
    rejected_count: int
    page: int
    page_size: int
    total_pages: int


class BulkUpdateLearningsRequest(BaseModel):
    """Request model for bulk updating learning statuses."""
    learning_ids: List[UUID]
    status: str = Field(pattern="^(pending|approved|rejected)$") 