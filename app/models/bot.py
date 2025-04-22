from pydantic import BaseModel
import datetime
from typing import List, Optional
from uuid import UUID


class CreateBotConversationResponse(BaseModel):
    """Response model for creating a new conversation for a bot."""
    conversation_id: str
    created_at: datetime.datetime
    customer_email: str
    customer_name: str

class Conversation(BaseModel):
    """Model representing a conversation with a bot."""
    id: UUID
    bot_id: Optional[UUID] = None
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    customer_phone: Optional[str] = None
    customer_location: Optional[str] = None
    status: Optional[str] = "ai"
    read: Optional[bool] = False
    created_at: Optional[datetime.datetime] = None
    updated_at: Optional[datetime.datetime] = None
    last_message: Optional[str] = None
    last_message_time: Optional[datetime.datetime] = None

class PaginatedListBotConversationsResponse(BaseModel):
    """Response model for listing all conversations for a bot with pagination."""
    conversations: List[Conversation]
    total_count: int
    page: int
    page_size: int
    total_pages: int

class ListBotConversationsResponse(BaseModel):
    """Response model for listing all conversations for a bot."""
    conversations: List[Conversation]

class AddKnowledgeRequest(BaseModel):
    """Request model for adding verified knowledge to a bot's knowledge base."""
    knowledge_text: str
    source_conversation_id: Optional[str] = None