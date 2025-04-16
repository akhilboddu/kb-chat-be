from pydantic import BaseModel
from typing import List, Optional
import datetime

class UploadedFileInfo(BaseModel):
    """Information about a single uploaded file."""
    filename: str
    file_size: Optional[int] = None
    content_type: Optional[str] = None
    upload_timestamp: datetime.datetime
    
class ListFilesResponse(BaseModel):
    """Response containing a list of uploaded file information."""
    kb_id: str
    files: List[UploadedFileInfo] 