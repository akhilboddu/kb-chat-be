from pydantic import BaseModel
import datetime

class CreateBotConversationResponse(BaseModel):
    """Response model for creating a new conversation for a bot."""
    conversation_id: str
    created_at: datetime.datetime
    customer_email: str
    customer_name: str
