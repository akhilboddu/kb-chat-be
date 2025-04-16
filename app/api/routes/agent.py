import time
import uuid
from fastapi import APIRouter, Body, HTTPException, Query, status
from typing import Dict, Any, List, Optional
from chromadb.errors import NotFoundError

import db_manager
from kb_manager import kb_manager
import data_processor
from app.models.agent import (
    CreateNamedAgentRequest, CreateAgentResponse, PopulateAgentJSONRequest,
    StatusResponse, ListKBsResponse, KBInfo, KBContentResponse, KBContentItem,
    CleanupResponse, AgentConfigResponse, UpdateAgentConfigRequest
)

router = APIRouter(prefix="/agents", tags=["agents"])

@router.post("", response_model=CreateAgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(request: CreateNamedAgentRequest = Body(None)):
    """
    Creates a new empty agent instance (knowledge base collection),
    optionally assigning it a name, and returns its unique ID.
    If no request body is provided or name is null, creates an unnamed agent.
    """
    agent_name = request.name if request else None
    if agent_name:
        print(f"Received request to create a new empty agent with name: '{agent_name}'...")
    else:
        print("Received request to create a new unnamed empty agent...")

    try:
        # 1. Generate a unique KB ID
        timestamp = int(time.time())
        short_uuid = str(uuid.uuid4())[:8]
        kb_id = f"kb_{timestamp}_{short_uuid}"
        print(f"Generated KB ID: {kb_id}")

        # 2. Create the empty KB collection using kb_manager, passing the name
        print(f"Creating empty KB collection: {kb_id}...")
        _ = kb_manager.create_or_get_kb(kb_id, name=agent_name)
        print(f"Empty KB collection {kb_id} created successfully.")

        return CreateAgentResponse(
            kb_id=kb_id, 
            name=agent_name, 
            message="Agent created successfully with an empty knowledge base."
        )

    except Exception as e:
        print(f"Error creating agent KB: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to create agent knowledge base: {str(e)}")


@router.post("/{kb_id}/json", response_model=StatusResponse, status_code=status.HTTP_200_OK)
async def populate_agent_from_json(kb_id: str, request: PopulateAgentJSONRequest):
    """
    Populates an existing agent's knowledge base using provided JSON data.
    """
    print(f"Received request to populate KB {kb_id} from JSON...")
    try:
        # 1. Verify KB exists (create_or_get_kb will retrieve it)
        try:
            kb_collection = kb_manager.create_or_get_kb(kb_id)
            print(f"Verified KB collection exists: {kb_id}")
        except Exception as get_err: # More specific error handling might be needed
             print(f"Error accessing KB {kb_id} before population: {get_err}")
             # If create_or_get_kb fails unexpectedly, it might indicate a deeper issue
             raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Knowledge base {kb_id} not found or inaccessible.")

        # 2. Store the original JSON payload in SQLite
        print(f"Storing original JSON payload for KB {kb_id} in metadata DB...")
        store_success = db_manager.add_json_payload(kb_id, request.json_data)
        if not store_success:
            # Log the error, but maybe don't fail the whole operation?
            # Decide if this is critical. For now, we'll log and continue.
            print(f"Warning: Failed to store original JSON payload for KB {kb_id} in metadata DB. Proceeding with KB population.")
            # Alternatively, raise HTTPException(500, "Failed to store JSON metadata")

        # 3. Process JSON data for ChromaDB
        print("Extracting text from JSON data...")
        extracted_text = data_processor.extract_text_from_json(request.json_data)
        if not extracted_text or not extracted_text.strip():
            print(f"Warning: No text extracted from JSON data for KB {kb_id}.")
            return StatusResponse(status="success", message="KB exists, but no text content found in JSON to add.")

        # 4. Add extracted text to the KB (ChromaDB)
        print(f"Adding extracted text to KB {kb_id}...")
        success = kb_manager.add_to_kb(kb_id, extracted_text)

        if success:
            print(f"Successfully populated KB {kb_id} from JSON.")
            return StatusResponse(status="success", message=f"Knowledge base {kb_id} populated successfully from JSON data.")
        else:
            print(f"Failed to add content from JSON to KB {kb_id} (add_to_kb returned False).")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to add extracted JSON content to the knowledge base.")

    except HTTPException as http_exc:
        # Re-raise known HTTP exceptions
        raise http_exc
    except Exception as e:
        print(f"Error populating KB {kb_id} from JSON: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to populate knowledge base from JSON: {str(e)}")


@router.delete("/{kb_id}", response_model=StatusResponse, status_code=status.HTTP_200_OK)
async def delete_agent(kb_id: str):
    """
    Deletes an agent instance, its associated knowledge base (ChromaDB),
    stored original JSON payloads (SQLite), and uploaded file records (SQLite).
    """
    print(f"Received request to delete agent KB and associated data: {kb_id}")
    
    # --- Delete File Records (SQLite) ---
    file_records_deleted = False
    try:
        file_records_deleted = db_manager.delete_uploaded_files(kb_id)
        if file_records_deleted:
            print(f"SQLite file record deletion process completed for KB {kb_id}.")
        else:
            print(f"SQLite file record deletion failed internally for KB {kb_id}.")
    except Exception as e:
        print(f"Unexpected error during SQLite file record deletion for KB {kb_id}: {e}")
        # Log traceback

    # --- Delete JSON Payloads (SQLite) ---
    payload_delete_success = False
    try:
        payload_delete_success = db_manager.delete_json_payloads(kb_id)
        if payload_delete_success:
             print(f"SQLite JSON payload deletion process completed for KB {kb_id}.")
        else:
            print(f"SQLite JSON payload deletion failed internally for KB {kb_id}.")
    except Exception as e:
        print(f"Unexpected error during SQLite JSON payload deletion for KB {kb_id}: {e}")
        # Log traceback

    # --- Delete Knowledge Base (ChromaDB) ---
    kb_delete_success = False
    try:
        kb_delete_success = kb_manager.delete_kb(kb_id)
        if kb_delete_success:
            print(f"ChromaDB deletion process completed for KB {kb_id}.")
        else:
            print(f"ChromaDB deletion process failed internally for KB {kb_id}.")
    except Exception as e:
        print(f"Unexpected error during ChromaDB deletion of KB {kb_id}: {e}")
        # Log traceback

    # Determine overall status
    all_deleted = kb_delete_success and payload_delete_success and file_records_deleted
    any_deleted = kb_delete_success or payload_delete_success or file_records_deleted

    if all_deleted:
         return StatusResponse(status="success", message=f"Agent {kb_id} and all associated data deleted successfully (or did not exist).")
    elif any_deleted:
        # Construct a more informative warning message
        deleted_parts = []
        failed_parts = []
        if kb_delete_success: deleted_parts.append("KB")
        else: failed_parts.append("KB")
        if payload_delete_success: deleted_parts.append("JSON metadata")
        else: failed_parts.append("JSON metadata")
        if file_records_deleted: deleted_parts.append("File records")
        else: failed_parts.append("File records")
        
        message = f"Partial deletion for Agent {kb_id}. Successfully deleted: {', '.join(deleted_parts)}. Failed to delete: {', '.join(failed_parts)}."
        return StatusResponse(status="warning", message=message)
    else: # Nothing was deleted successfully
         raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to delete knowledge base {kb_id} and all associated metadata due to internal errors.")


@router.get("/{kb_id}/json", response_model=List[Dict[str, Any]])
async def get_agent_json_payloads(kb_id: str):
    """
    Retrieves all original JSON payloads that were uploaded
    to populate this agent's knowledge base.
    Returns an empty list if no JSON payloads are found or if the KB ID doesn't exist.
    """
    print(f"Received request to get stored JSON payloads for KB: {kb_id}")
    try:
        payloads = db_manager.get_json_payloads(kb_id)
        # The function returns an empty list if not found or on DB error, which is acceptable here.
        return payloads
    except Exception as e:
        # Catch unexpected errors during retrieval
        print(f"Unexpected error retrieving JSON payloads for KB {kb_id}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to retrieve JSON payloads for knowledge base {kb_id}: {str(e)}")


@router.get("", response_model=ListKBsResponse)
async def list_kbs_endpoint():
    """
    Lists all available Knowledge Bases with a brief summary derived from their content.
    """
    print("Received request to list KBs...")
    try:
        kb_info_list = kb_manager.list_kbs()
        # Map the list of dicts to a list of KBInfo models
        kbs_response = [KBInfo(**info) for info in kb_info_list]
        return ListKBsResponse(kbs=kbs_response)
    except Exception as e:
        print(f"Error listing KBs: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list knowledge bases: {str(e)}")


@router.get("/{kb_id}/content", response_model=KBContentResponse)
async def get_kb_content_endpoint(
    kb_id: str, 
    limit: Optional[int] = Query(None, ge=1, description="Maximum number of documents to return"), 
    offset: Optional[int] = Query(None, ge=0, description="Number of documents to skip")
):
    """
    Retrieves the documents stored within a specific knowledge base, with pagination.
    """
    print(f"Received request to get content for KB: {kb_id}, Limit: {limit}, Offset: {offset}")
    try:
        result = kb_manager.get_kb_content(kb_id, limit=limit, offset=offset)
        
        # Combine IDs and documents into KBContentItem objects
        content_items = [
            KBContentItem(id=doc_id, document=doc) 
            for doc_id, doc in zip(result.get('ids', []), result.get('documents', []))
        ]
        
        return KBContentResponse(
            kb_id=kb_id,
            total_count=result['total_count'],
            limit=result['limit'],
            offset=result['offset'],
            content=content_items
        )
        
    except Exception as e:
        # Handle errors raised from kb_manager (e.g., unexpected errors)
        print(f"Error getting content for KB {kb_id}: {e}")
        import traceback
        traceback.print_exc()
        # Distinguish between 'not found' (handled by kb_manager returning count 0) and other errors
        # If get_kb_content raised something other than NotFoundError, it's likely a 500
        raise HTTPException(status_code=500, detail=f"Failed to retrieve content for knowledge base {kb_id}: {str(e)}")


@router.post("/{kb_id}/cleanup", response_model=CleanupResponse, status_code=status.HTTP_200_OK)
async def cleanup_kb_duplicates_endpoint(kb_id: str):
    """
    Removes duplicate documents (based on exact text content) from the specified knowledge base.
    """
    print(f"Received request to cleanup duplicates in KB: {kb_id}")
    try:
        # Run the potentially long-running cleanup task in a separate thread
        import asyncio
        deleted_count = await asyncio.to_thread(kb_manager.cleanup_duplicates, kb_id)

        message = f"Successfully removed {deleted_count} duplicate documents from KB {kb_id}."
        if deleted_count == 0:
            message = f"No duplicate documents found in KB {kb_id}."

        return CleanupResponse(
            kb_id=kb_id,
            deleted_count=deleted_count,
            message=message
        )

    except NotFoundError:
        # Catch the specific error raised by kb_manager if collection not found
        print(f"Cleanup failed: Knowledge base {kb_id} not found.")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Knowledge base {kb_id} not found.")
    except Exception as e:
        # Catch any other exceptions raised during the cleanup process
        print(f"Error during duplicate cleanup for KB {kb_id}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to cleanup duplicates in knowledge base {kb_id}: {str(e)}")


@router.get("/{kb_id}/config", response_model=AgentConfigResponse)
async def get_agent_config_endpoint(kb_id: str):
    """Retrieves the current configuration for a specific agent."""
    print(f"Received request to get agent config for KB: {kb_id}")
    try:
        config_data = db_manager.get_agent_config(kb_id)
        # Pydantic will use defaults if a key is missing from config_data
        return AgentConfigResponse(**config_data)
    except Exception as e:
        print(f"Error getting agent config for {kb_id}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to retrieve agent configuration: {str(e)}")


@router.put("/{kb_id}/config", response_model=StatusResponse)
async def update_agent_config_endpoint(kb_id: str, request: UpdateAgentConfigRequest):
    """Updates the configuration for a specific agent."""
    print(f"Received request to update agent config for KB: {kb_id}")
    # Convert Pydantic model to dict, excluding unset fields
    update_data = request.model_dump(exclude_unset=True)
    
    if not update_data:
        # No fields were provided in the request body
        raise HTTPException(status_code=400, detail="No configuration parameters provided for update.")
        
    try:
        success = db_manager.upsert_agent_config(kb_id, update_data)
        if success:
            return StatusResponse(status="success", message="Agent configuration updated successfully.")
        else:
            # Check logs for specific upsert error
            raise HTTPException(status_code=500, detail="Failed to update agent configuration due to an internal database error.")
    except HTTPException as http_exc:
        raise http_exc # Re-raise specific HTTP exceptions
    except Exception as e:
        print(f"Error updating agent config for {kb_id}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to update agent configuration: {str(e)}") 