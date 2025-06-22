from pydantic import BaseModel
from typing import List, Optional

class CRMEntry(BaseModel):
    id: str
    bot_id: str
    first_name: Optional[str]
    last_name: Optional[str]
    phone_number: Optional[str]
    email: Optional[str]
    lead_score: Optional[int]
    chat_summary: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]

class PaginatedCRMResponse(BaseModel):
    crms: List[CRMEntry]
    total_count: int
    page: int
    page_size: int
    total_pages: int 