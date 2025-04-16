from pydantic import BaseModel, Field
from typing import Optional

class StatusResponse(BaseModel):
    """Generic status response."""
    status: str
    message: str 