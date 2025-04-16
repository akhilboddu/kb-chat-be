from pydantic import BaseModel, Field, HttpUrl
from typing import Dict, Any, List, Optional
import datetime

from app.models.base import StatusResponse

class CreateNamedAgentRequest(BaseModel):
    """Request body for creating a new agent, optionally with a name."""
    name: Optional[str] = Field(None, description="Optional human-readable name for the agent/KB", example="Sales Bot North America")

class CreateAgentRequest(BaseModel):
    """(Deprecated by CreateNamedAgentRequest)"""
    pass

class PopulateAgentJSONRequest(BaseModel):
    """Request body for populating an existing agent/KB with JSON data."""
    json_data: Dict[str, Any] = Field(
        ...,
        description="Arbitrary JSON data to populate the knowledge base.",
        example={
            "company_name": "Example Solutions Inc.",
            "product_details": {
                "name": "CogniChat Pro",
                "version": "3.0",
                "key_features": [
                    "Advanced NLU",
                    "Multi-lingual Support",
                    "Sentiment Analysis",
                    "API Integration"
                ],
                "description": "An enterprise-grade AI chatbot platform."
            },
            "sales_pitch_points": [
                "Boosts customer engagement by 30%.",
                "Reduces support ticket volume significantly.",
                "Integrates seamlessly with existing CRM."
            ],
            "contact": "sales@example.com"
        }
    )

class CreateAgentResponse(BaseModel):
    """Response body after successfully creating an agent/KB ID."""
    kb_id: str
    name: Optional[str] = None # Add optional name
    message: str

class KBInfo(BaseModel):
    """Information about a single Knowledge Base."""
    kb_id: str
    name: Optional[str] = None
    summary: str

class ListKBsResponse(BaseModel):
    """Response containing a list of available KB information."""
    kbs: List[KBInfo]

class KBContentItem(BaseModel):
    """Represents a single item within the knowledge base content."""
    id: str
    document: str

class KBContentResponse(BaseModel):
    """Response model for listing the content of a Knowledge Base."""
    kb_id: str
    total_count: int
    limit: Optional[int] = None
    offset: Optional[int] = None
    content: List[KBContentItem]

class CleanupResponse(BaseModel):
    """Response model for the KB cleanup operation."""
    kb_id: str
    deleted_count: int
    message: str

class AgentConfigResponse(BaseModel):
    """Response model for agent configuration."""
    system_prompt: str = Field(None, description="The system prompt used by the agent.")
    max_iterations: int = Field(None, ge=1, description="Maximum iterations for the agent loop.")

class UpdateAgentConfigRequest(BaseModel):
    """Request model for updating agent configuration. All fields optional."""
    system_prompt: Optional[str] = Field(None, description="New system prompt for the agent.")
    max_iterations: Optional[int] = Field(None, ge=1, description="New maximum iterations for the agent loop.") 