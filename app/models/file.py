from pydantic import BaseModel
from typing import List, Optional, Dict, Any
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

class FileUploadStatusResponse(BaseModel):
    """Response containing the status of a file upload operation."""
    kb_id: str
    status: str  # processing | completed | completed_with_errors | failed | not_found
    message: Optional[str] = ""
    total_files: int = 0
    processed_files: int = 0
    failed_files: int = 0
    progress: Optional[Dict[str, Any]] = None 