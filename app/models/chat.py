from pydantic import BaseModel, Field
from typing import List, Optional
import datetime

class ChatRequest(BaseModel):
    """Request body for chat interactions via HTTP."""
    message: str = Field(..., description="User message to the agent")
    
class ChatResponse(BaseModel):
    """Response from the agent via HTTP."""
    content: str
    type: str = "answer"  # 'answer' or 'handoff'

class HumanResponseRequest(BaseModel):
    """Request body for submitting human response and potentially updating KB."""
    human_response: str
    update_kb: bool = False # Flag to indicate if KB should be updated
    kb_update_text: Optional[str] = None # Optional text specifically for KB update

class HumanChatRequest(BaseModel):
    """Request body for human agent chat response."""
    message: str = Field(..., description="The human agent's response message")

class HumanKnowledgeRequest(BaseModel):
    """Request body for adding human-verified knowledge to the KB."""
    knowledge_text: str = Field(..., description="The text to be added to the knowledge base")
    source_conversation_id: Optional[str] = Field(None, description="Optional: ID of the conversation this knowledge came from")

class HistoryMessage(BaseModel):
    """Represents a single message in the conversation history."""
    type: str # 'human' or 'ai' or 'human_agent'
    content: str
    timestamp: Optional[datetime.datetime] = None # Include timestamp from DB

class ChatHistoryResponse(BaseModel):
    """Response model for retrieving conversation history."""
    kb_id: str
    history: List[HistoryMessage]

class ConversationPreview(BaseModel):
    """Preview information for a single conversation."""
    last_message_timestamp: datetime.datetime
    last_message_preview: str
    message_count: int
    needs_human_attention: bool  # Flag indicating if conversation requires handoff
    
class KBConversationGroup(BaseModel):
    """Conversations for a single knowledge base."""
    kb_id: str
    name: Optional[str] = None
    conversation: ConversationPreview
    
class ListConversationsResponse(BaseModel):
    """Response model listing all conversations grouped by KB."""
    conversations: List[KBConversationGroup] 