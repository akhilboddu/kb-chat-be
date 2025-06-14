import time
from typing import Optional, Dict, Any
from app.core import supabase_metadata_manager as db_manager


class Progress:
    """
    Helper class for managing granular progress updates with throttling.
    Prevents excessive database writes while providing smooth progress tracking.
    """
    
    def __init__(self, kb_id: str, total_units: int, update_type: str = "scrape"):
        """
        Initialize progress tracker.
        
        Args:
            kb_id: Knowledge base ID
            total_units: Total number of units to process
            update_type: Type of update ("scrape" or "upload")
        """
        self.kb_id = kb_id
        self.total_units = total_units
        self.completed_units = 0
        self.update_type = update_type
        self.last_update_time = 0
        self.update_interval = 0.5  # Minimum seconds between updates
        self.last_stage = ""
        self.last_details = ""
        
    def step(self, details: str = "", units: int = 1, stage: Optional[str] = None, force: bool = False):
        """
        Update progress by incrementing completed units.
        
        Args:
            details: Human-readable progress details
            units: Number of units completed in this step
            stage: Optional stage name (e.g., "scraping", "parsing")
            force: Force update regardless of throttling
        """
        self.completed_units += units
        current_time = time.time()
        
        # Throttle updates unless forced or stage changed
        if not force and stage == self.last_stage:
            if current_time - self.last_update_time < self.update_interval:
                return
        
        # Calculate percentage
        percent = int((self.completed_units / self.total_units * 100)) if self.total_units > 0 else 0
        percent = min(percent, 100)  # Cap at 100%
        
        # Build progress update
        progress_data = {
            "completed_units": self.completed_units,
            "total_units": self.total_units,
            "progress": {
                "percent": percent,
                "details": details or self.last_details,
            }
        }
        
        if stage:
            progress_data["progress"]["stage"] = stage
            self.last_stage = stage
            
        if details:
            self.last_details = details
        
        # Send update based on type
        if self.update_type == "scrape":
            db_manager.update_scrape_status(self.kb_id, progress_data)
        elif self.update_type == "upload":
            db_manager.update_file_upload_status(self.kb_id, progress_data)
            
        self.last_update_time = current_time
        
    def complete(self, status: str = "completed", message: str = ""):
        """
        Mark the progress as complete.
        
        Args:
            status: Final status (e.g., "completed", "failed")
            message: Final message to display
        """
        progress_data = {
            "status": status,
            "completed_units": self.completed_units,
            "total_units": self.total_units,
            "progress": {
                "stage": status,
                "details": message,
                "percent": 100 if status == "completed" else 0
            }
        }
        
        if message:
            progress_data["message"] = message
            
        if self.update_type == "scrape":
            db_manager.update_scrape_status(self.kb_id, progress_data)
        elif self.update_type == "upload":
            db_manager.update_file_upload_status(self.kb_id, progress_data) 