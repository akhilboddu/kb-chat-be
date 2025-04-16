from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, Dict
import datetime

class ScrapeURLRequest(BaseModel):
    """Request body for initiating a website scrape."""
    url: HttpUrl = Field(..., description="The URL of the website to scrape.")
    max_pages: Optional[int] = Field(None, ge=1, description="Optional override for the maximum number of pages to scrape.")

class ScrapeInitiatedResponse(BaseModel):
    """Response confirming that scraping has started."""
    kb_id: str
    status: str = "processing"
    message: str
    submitted_url: str

class ScrapeStatusResponse(BaseModel):
    """Response containing the current status of a scraping operation."""
    kb_id: str
    status: str  # "processing", "completed", "failed"
    progress: Optional[dict] = None  # Optional progress details
    error: Optional[str] = None  # Error message if status is "failed"
    submitted_url: str
    pages_scraped: Optional[int] = None
    total_pages: Optional[int] = None
    last_update: Optional[datetime.datetime] = None 