"""
Supabase Metadata Manager - Drop-in replacement for SQLite db_manager
Handles all metadata and operational data storage using Supabase PostgreSQL
"""

import json
from typing import List, Dict, Any, Optional
from functools import lru_cache
from datetime import datetime

from app.core.supabase_client import supabase
from pydantic import BaseModel
from app.core.prompts import DEFAULT_SYSTEM_PROMPT, DEFAULT_MAX_ITERATIONS


# === Constants from original db_manager ===
# Moved to prompts.py


# === PYDANTIC MODELS ===
class PushSub(BaseModel):
    anon_id: str
    user_id: str
    subscription: dict[str, Any]


# === JSON PAYLOAD FUNCTIONS ===
def add_json_payload(kb_id: str, payload: Dict[str, Any]) -> bool:
    """Stores the original JSON payload associated with a KB ID."""
    try:
        supabase.table('json_payloads').insert({
            'kb_id': kb_id,
            'payload': payload  # JSONB will handle dict directly
        }).execute()
        print(f"Stored JSON payload for KB: {kb_id}")
        return True
    except Exception as e:
        print(f"Error adding JSON payload for {kb_id}: {e}")
        return False


def get_json_payloads(kb_id: str) -> List[Dict[str, Any]]:
    """Retrieves all original JSON payloads associated with a KB ID."""
    try:
        result = (supabase.table('json_payloads')
                 .select('payload, upload_timestamp')
                 .eq('kb_id', kb_id)
                 .order('upload_timestamp', desc=True)
                 .execute())
        
        payloads = []
        for row in result.data:
            payloads.append({
                'data': row['payload'],
                'uploaded_at': row['upload_timestamp']
            })
        return payloads
    except Exception as e:
        print(f"Error retrieving JSON payloads for {kb_id}: {e}")
        return []


def delete_json_payloads(kb_id: str) -> bool:
    """Deletes all JSON payloads associated with a KB ID."""
    try:
        result = (supabase.table('json_payloads')
                 .delete()
                 .eq('kb_id', kb_id)
                 .execute())
        
        # Check if any rows were affected
        affected = len(result.data) if result.data else 0
        print(f"Deleted {affected} JSON payload records for KB: {kb_id}")
        return True
    except Exception as e:
        print(f"Error deleting JSON payloads for {kb_id}: {e}")
        return False


# === FILE UPLOAD FUNCTIONS ===
def add_uploaded_file_record(
    kb_id: str, filename: str, file_size: Optional[int], content_type: Optional[str]
) -> bool:
    """Stores metadata about an uploaded file associated with a KB ID."""
    try:
        supabase.table('uploaded_files').insert({
            'kb_id': kb_id,
            'filename': filename,
            'file_size': file_size,
            'content_type': content_type
        }).execute()
        print(f"Stored file record for KB '{kb_id}': {filename} ({content_type}, {file_size} bytes)")
        return True
    except Exception as e:
        print(f"Error adding file record for KB '{kb_id}', file '{filename}': {e}")
        return False


def get_uploaded_files(kb_id: str) -> List[Dict[str, Any]]:
    """Retrieves metadata for all files uploaded for a specific KB ID."""
    try:
        result = (supabase.table('uploaded_files')
                 .select('filename, file_size, content_type, upload_timestamp')
                 .eq('kb_id', kb_id)
                 .order('upload_timestamp', desc=True)
                 .execute())
        
        return result.data if result.data else []
    except Exception as e:
        print(f"Error retrieving file records for {kb_id}: {e}")
        return []


def delete_uploaded_files(kb_id: str) -> bool:
    """Deletes all uploaded file records associated with a KB ID."""
    try:
        result = (supabase.table('uploaded_files')
                 .delete()
                 .eq('kb_id', kb_id)
                 .execute())
        
        print(f"Attempted deletion of file records for KB: {kb_id}. Check logs for affected rows if needed.")
        return True
    except Exception as e:
        print(f"Error deleting file records for {kb_id}: {e}")
        return False


# === CONVERSATION HISTORY FUNCTIONS ===
def add_conversation_message(kb_id: str, message_type: str, content: str) -> bool:
    """Adds a message to the conversation history for a given kb_id."""
    if message_type not in ("human", "ai", "human_agent"):
        print(f"Error: Invalid message_type '{message_type}'. Must be 'human', 'ai', or 'human_agent'.")
        return False
    
    if not content or not content.strip():
        print(f"Error: Cannot add empty content to conversation history for {kb_id}.")
        return False

    try:
        supabase.table('conversation_history').insert({
            'kb_id': kb_id,
            'message_type': message_type,
            'content': content
        }).execute()
        return True
    except Exception as e:
        print(f"Error adding conversation message for {kb_id}: {e}")
        return False


def get_conversation_history(kb_id: str) -> List[Dict[str, Any]]:
    """Retrieves conversation history for a given kb_id, ordered by timestamp."""
    try:
        result = (supabase.table('conversation_history')
                 .select('message_type, content, timestamp')
                 .eq('kb_id', kb_id)
                 .order('timestamp')  # ASC for chronological order
                 .execute())
        
        return result.data if result.data else []
    except Exception as e:
        print(f"Error retrieving conversation history for {kb_id}: {e}")
        return []


def delete_conversation_history(kb_id: str) -> bool:
    """Deletes all conversation history messages associated with a specific kb_id."""
    try:
        result = (supabase.table('conversation_history')
                 .delete()
                 .eq('kb_id', kb_id)
                 .execute())
        
        rows_deleted = len(result.data) if result.data else 0
        print(f"Deleted {rows_deleted} conversation history records for KB: {kb_id}")
        return True
    except Exception as e:
        print(f"Error deleting conversation history for {kb_id}: {e}")
        return False


# === KB UPDATE LOG FUNCTIONS ===
def log_kb_update(kb_id: str, added_content: str) -> bool:
    """Logs when content is added to the KB via human verification."""
    if not added_content or not added_content.strip():
        print(f"Error: Cannot log empty content addition for KB {kb_id}.")
        return False

    try:
        supabase.table('kb_update_log').insert({
            'kb_id': kb_id,
            'added_content': added_content
        }).execute()
        print(f"Logged KB update for KB: {kb_id}")
        return True
    except Exception as e:
        print(f"Error logging KB update for {kb_id}: {e}")
        return False


# === AGENT CONFIGURATION FUNCTIONS ===
# Cache for frequently accessed configs
@lru_cache(maxsize=2048)
def get_agent_config_cached(kb_id: str) -> Dict[str, Any]:
    """Cached version of get_agent_config."""
    return get_agent_config(kb_id)


def get_agent_config(kb_id: str) -> Dict[str, Any]:
    """Retrieves agent configuration or returns defaults if not found."""
    config = {
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
        "max_iterations": DEFAULT_MAX_ITERATIONS,
    }
    
    try:
        result = (supabase.table('agent_config')
                 .select('system_prompt, max_iterations')
                 .eq('kb_id', kb_id)
                 .execute())
        
        if result.data and len(result.data) > 0:
            row = result.data[0]
            # Update defaults with fetched values only if they are not NULL
            if row.get("system_prompt") is not None:
                config["system_prompt"] = row["system_prompt"]
            if row.get("max_iterations") is not None:
                config["max_iterations"] = row["max_iterations"]
            print(f"Loaded specific config for KB: {kb_id}")
        else:
            print(f"No specific config found for KB: {kb_id}. Using defaults.")
            
        return config
    except Exception as e:
        print(f"Error retrieving agent config for {kb_id}, using defaults: {e}")
        return config


def upsert_agent_config(kb_id: str, config_data: Dict[str, Any]) -> bool:
    """Updates or inserts agent configuration."""
    # Clear cache for this kb_id
    get_agent_config_cached.cache_clear()
    
    # Filter out keys with None values
    update_data = {
        k: v for k, v in config_data.items()
        if v is not None and k != "confidence_threshold"
    }

    if not update_data:
        print(f"No valid configuration data provided to update for KB: {kb_id}")
        return False

    try:
        # Always include kb_id
        update_data['kb_id'] = kb_id
        
        # Upsert using Supabase (will insert or update based on kb_id)
        supabase.table('agent_config').upsert(update_data).execute()
        
        print(f"Upserted agent config for KB: {kb_id}")
        return True
    except Exception as e:
        print(f"Error upserting agent config for {kb_id}: {e}")
        return False


# === SCRAPING STATUS FUNCTIONS ===
def update_scrape_status(kb_id: str, status_data: dict) -> bool:
    """Updates the scraping status for a KB."""
    try:
        # Convert progress dict to JSONB if present
        if "progress" in status_data:
            status_data["progress_data"] = status_data.pop("progress")
        
        # Always include kb_id
        status_data['kb_id'] = kb_id
        
        # Upsert the status
        supabase.table('scraping_status').upsert(status_data).execute()
        return True
    except Exception as e:
        print(f"Error updating scrape status for KB {kb_id}: {e}")
        return False


def get_scrape_status(kb_id: str) -> Optional[dict]:
    """Retrieves the current scraping status for a KB."""
    try:
        result = (supabase.table('scraping_status')
                 .select('*')
                 .eq('kb_id', kb_id)
                 .execute())
        
        if not result.data:
            return None
        
        status = result.data[0]
        
        # Convert progress_data back to progress
        if status.get("progress_data"):
            status["progress"] = status.pop("progress_data")
            
        return status
    except Exception as e:
        print(f"Error retrieving scrape status for KB {kb_id}: {e}")
        return None


# === FILE UPLOAD STATUS FUNCTIONS ===
def update_file_upload_status(kb_id: str, status_data: dict) -> bool:
    """Updates the file upload status for a KB."""
    try:
        # Convert progress dict to JSONB if present
        if "progress" in status_data:
            status_data["progress_data"] = status_data.pop("progress")
        
        # Always include kb_id
        status_data['kb_id'] = kb_id
        
        print(f"Updating file upload status for KB {kb_id}: {status_data.get('status', 'unknown')} - {status_data.get('message', '')}")
        
        # Upsert the status and ensure it completes
        result = supabase.table('file_upload_status').upsert(status_data).execute()
        
        # Verify the operation succeeded
        if result and result.data:
            print(f"Successfully updated file upload status for KB {kb_id}")
            return True
        else:
            print(f"Warning: No data returned from upsert for KB {kb_id}")
            return False
            
    except Exception as e:
        print(f"Error updating file upload status for KB {kb_id}: {e}")
        import traceback
        traceback.print_exc()
        return False


def get_file_upload_status(kb_id: str) -> Optional[dict]:
    """Retrieves the current file upload status for a KB."""
    try:
        result = (supabase.table('file_upload_status')
                 .select('*')
                 .eq('kb_id', kb_id)
                 .execute())
        
        if not result.data:
            return None
        
        status = result.data[0]
        
        # Convert progress_data back to progress
        if status.get("progress_data"):
            status["progress"] = status.pop("progress_data")
            
        return status
    except Exception as e:
        print(f"Error retrieving file upload status for KB {kb_id}: {e}")
        return None


# === POSTGRES FUNCTIONS (for compatibility) ===
def get_postgres_db():
    """For compatibility - returns Supabase connection info."""
    # This should use the Supabase PostgreSQL connection string
    # For now, just raise NotImplementedError as these functions
    # should be migrated to use Supabase client directly
    raise NotImplementedError("Use Supabase client directly instead of raw PostgreSQL connection")


def get_conversation_count(user_id: str):
    """Gets conversation count for a user - needs to be migrated to Supabase."""
    try:
        # Use Supabase client instead of raw PostgreSQL
        result = supabase.rpc('get_user_conversation_count', {
            'user_id_param': user_id
        }).execute()
        
        return result.data if result.data else 0
    except Exception as e:
        print(f"Error retrieving conversation count: {e}")
        # Fallback to direct query
        try:
            from datetime import datetime
            current_month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            
            result = (supabase.table('conversations')
                     .select('id', count='exact')
                     .eq('bot_id', user_id)  # This might need adjustment based on schema
                     .gte('created_at', current_month_start.isoformat())
                     .execute())
            
            return result.count if hasattr(result, 'count') else 0
        except Exception as e2:
            print(f"Fallback error retrieving conversation count: {e2}")
            return None


def get_message_count(user_id: str):
    """Gets message count for a user - needs to be migrated to Supabase."""
    try:
        # Use Supabase client instead of raw PostgreSQL
        result = supabase.rpc('get_user_message_count', {
            'user_id_param': user_id
        }).execute()
        
        return result.data if result.data else 0
    except Exception as e:
        print(f"Error retrieving message count: {e}")
        # For now, return None as this requires complex joins
        # This should be implemented as a Supabase RPC function
        return None


# === UTILITY FUNCTIONS ===
def get_db():
    """Legacy function - no longer needed with Supabase."""
    # This function was used to get SQLite connection
    # Now everything goes through Supabase client
    raise DeprecationWarning("get_db() is deprecated. Use Supabase client directly.")


def init_db():
    """Legacy function - no longer needed as tables are created via Supabase migrations."""
    print("init_db() called but not needed - Supabase tables should be created via migrations")
    pass 