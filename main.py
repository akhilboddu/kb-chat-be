# main.py

import uuid
import time
import asyncio # <--- Import asyncio
import re  # For splitting sentences
import json # For formatting SSE data
from fastapi import FastAPI, HTTPException, UploadFile, File, Body, status, Query, Request # Added Request
from fastapi.responses import StreamingResponse # Added StreamingResponse
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
from langchain_core.messages import HumanMessage, AIMessage # Import message types
from fastapi.middleware.cors import CORSMiddleware # Import CORS middleware
import datetime
import os

# Import core components
import data_processor
from kb_manager import kb_manager # Singleton instance
import db_manager # Import the new DB manager
from agent_manager import create_agent_executor
from config import llm # Import the initialized LLM
from file_parser import parse_file, SUPPORTED_EXTENSIONS # Import the file parser
from langchain.memory import ConversationBufferMemory # Keep this one
from langchain_core.memory import BaseMemory # Correct import path for BaseMemory

# --- Initialize SQLite DB --- 
# Ensure the DB and tables are created when the app starts
db_manager.init_db()

# --- Conversation Memory Store (In-Memory - Not Persistent) ---
# Store memory objects keyed by kb_id
# conversation_memory_store: Dict[str, BaseMemory] = {} # REMOVED - Using DB now

# --- Pydantic Models ---

class CreateNamedAgentRequest(BaseModel):
    """Request body for creating a new agent, optionally with a name."""
    name: Optional[str] = Field(None, description="Optional human-readable name for the agent/KB", example="Sales Bot North America")

class CreateAgentRequest(BaseModel):
    """(Deprecated by CreateNamedAgentRequest)"""
    pass

class PopulateAgentJSONRequest(BaseModel):
    """Request body for populating an existing agent/KB with JSON data."""
    json_data: Dict[str, Any] = Field(
        ...,
        description="Arbitrary JSON data to populate the knowledge base.",
        example={
            "company_name": "Example Solutions Inc.",
            "product_details": {
                "name": "CogniChat Pro",
                "version": "3.0",
                "key_features": [
                    "Advanced NLU",
                    "Multi-lingual Support",
                    "Sentiment Analysis",
                    "API Integration"
                ],
                "description": "An enterprise-grade AI chatbot platform."
            },
            "sales_pitch_points": [
                "Boosts customer engagement by 30%.",
                "Reduces support ticket volume significantly.",
                "Integrates seamlessly with existing CRM."
            ],
            "contact": "sales@example.com"
        }
    )

class CreateAgentResponse(BaseModel):
    """Response body after successfully creating an agent/KB ID."""
    kb_id: str
    name: Optional[str] = None # Add optional name
    message: str

class HumanResponseRequest(BaseModel):
    """Request body for submitting human response and potentially updating KB."""
    human_response: str
    update_kb: bool = False # Flag to indicate if KB should be updated

class StatusResponse(BaseModel):
    """Generic status response."""
    status: str
    message: str

# --- Models for listing KBs ---
class KBInfo(BaseModel):
    """Information about a single Knowledge Base."""
    kb_id: str
    name: Optional[str] = None # Add optional name
    summary: str # Replaced document_count with summary
    
class ListKBsResponse(BaseModel):
    """Response containing a list of available KB information."""
    kbs: List[KBInfo]

class KBContentItem(BaseModel):
    """Represents a single item within the knowledge base content."""
    id: str
    document: str

class KBContentResponse(BaseModel):
    """Response model for listing the content of a Knowledge Base."""
    kb_id: str
    total_count: int
    limit: Optional[int] = None
    offset: Optional[int] = None
    content: List[KBContentItem]

# --- NEW: Models for listing uploaded files ---
class UploadedFileInfo(BaseModel):
    """Information about a single uploaded file."""
    filename: str
    file_size: Optional[int] = None
    content_type: Optional[str] = None
    upload_timestamp: datetime.datetime # Changed from str to datetime for better typing
    
class ListFilesResponse(BaseModel):
    """Response containing a list of uploaded file information."""
    kb_id: str
    files: List[UploadedFileInfo]

# --- NEW: Models for Conversation History Endpoint ---
class HistoryMessage(BaseModel):
    """Represents a single message in the conversation history."""
    type: str # 'human' or 'ai'
    content: str
    timestamp: Optional[datetime.datetime] = None # Include timestamp from DB

class ChatHistoryResponse(BaseModel):
    """Response model for retrieving conversation history."""
    kb_id: str
    history: List[HistoryMessage]

# --- Models for HTTP Chat Endpoint ---
class ChatRequest(BaseModel):
    """Request body for chat interactions via HTTP."""
    message: str = Field(..., description="User message to the agent")
    
class ChatResponse(BaseModel):
    """Response from the agent via HTTP."""
    content: str
    type: str = "answer"  # Default is regular answer
    confidence_score: Optional[float] = None # Lower is better (e.g., distance)

# --- FastAPI App Initialization ---
app = FastAPI(
    title="Multi-Tenant AI Sales Agent API",
    description="API for managing AI sales agents and WebSocket chat.",
    version="1.0.0"
)

# --- CORS Middleware Configuration ---
# Allow requests from all origins during development
# In production, replace "*" with the specific origin(s) of your frontend
origins = ["http://localhost:3002", "http://127.0.0.1:3002"] 

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True, # Allows cookies if needed (not used here, but often useful)
    allow_methods=["*"],    # Allows all methods (GET, POST, etc.)
    allow_headers=["*"],    # Allows all headers
    expose_headers=["content-type", "content-length"]
)
# --- End CORS Configuration ---

print("FastAPI app initialized.")
if not llm:
    print("WARNING: LLM is not configured. Agent functionality will be limited.")


# --- Utility Functions ---
def clean_agent_output(text: str) -> str:
    """Removes surrounding markdown code blocks (```) and single backticks."""
    original_text = text
    cleaned_text = text.strip()
    # print(f"clean_agent_output: Original='{original_text}' Stripped='{cleaned_text}'") # Optional: less verbose logging

    # Remove leading/trailing code blocks (``` optional_lang newline ... newline ```)
    cleaned_text = re.sub(r'^```(?:[a-zA-Z0-9_]+)?\s*?\n(.*?)\n```$\s*', r'\1', cleaned_text, flags=re.DOTALL | re.MULTILINE)
    # Remove leading/trailing code blocks (```...```) on a single line
    cleaned_text = re.sub(r'^```(.*?)```$\s*', r'\1', cleaned_text)
    # Remove leading/trailing single backticks
    cleaned_text = re.sub(r'^`(.*?)`$\s*', r'\1', cleaned_text)
    # Remove just trailing ``` that might be left over
    cleaned_text = re.sub(r'\n```$\s*', '', cleaned_text) 
    cleaned_text = re.sub(r'```$\s*', '', cleaned_text) 

    final_cleaned = cleaned_text.strip()
    if final_cleaned != original_text.strip():
        print(f"clean_agent_output: Cleaned from '{original_text.strip()}' to '{final_cleaned}'")
    # else:
        # print("clean_agent_output: No changes made.") # Optional: less verbose logging
    return final_cleaned

# Removed chunk_response function - no longer needed with SSE generator

# --- HTTP Endpoints ---

@app.post("/agents", response_model=CreateAgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(request: CreateNamedAgentRequest = Body(None)): # Accept new request model, make body optional for backward compatibility maybe?
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

@app.post("/agents/{kb_id}/json", response_model=StatusResponse, status_code=status.HTTP_200_OK)
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


@app.delete("/agents/{kb_id}", response_model=StatusResponse, status_code=status.HTTP_200_OK)
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

@app.get("/agents/{kb_id}/json", response_model=List[Dict[str, Any]])
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

@app.get("/agents", response_model=ListKBsResponse)
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

@app.get("/agents/{kb_id}/content", response_model=KBContentResponse)
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

# --- Human Response Endpoint ---
@app.post("/agents/{kb_id}/human_response", response_model=StatusResponse)
async def human_response_endpoint(kb_id: str, request: HumanResponseRequest):
    """
    Receives a human response after a handoff and optionally updates the KB.
    """
    print(f"Received human response for kb_id: {kb_id}. Update KB: {request.update_kb}")
    
    if request.update_kb and request.human_response:
        print(f"Attempting to update KB {kb_id} with human response...")
        try:
            # Use the existing KBManager function to add the response, passing metadata
            success = kb_manager.add_to_kb(
                kb_id=kb_id, 
                text_to_add=request.human_response, 
                metadata={"source": "human_verified"}
            )
            if success:
                print(f"Successfully updated KB {kb_id} with human response.")
                # --- Log the update --- 
                log_success = db_manager.log_kb_update(kb_id, request.human_response)
                if not log_success:
                    # Log a warning if logging fails, but don't fail the main operation
                    print(f"Warning: Failed to log KB update for {kb_id} after successful addition.")
                # --- End Log --- 
                return StatusResponse(status="success", message="Human response received and knowledge base updated.")
            else:
                # add_to_kb might return False if text is empty after stripping
                print(f"Failed to update KB {kb_id} (possibly empty response provided). Response was not added.")
                # Still return success for receiving the response, but message indicates KB not updated
                return StatusResponse(status="success", message="Human response received, but knowledge base was not updated (response might be empty)." )
        except Exception as e:
            print(f"Error updating KB {kb_id} with human response: {e}")
            # Log the full traceback in a real application
            # Return an error status specific to the KB update failure
            # We might still consider the reception of the response a success at the endpoint level
            # depending on requirements, but indicate the KB update failed.
            # For simplicity, we'll raise an HTTP exception here.
            raise HTTPException(status_code=500, detail=f"Human response received, but failed to update knowledge base: {str(e)}")
    else:
        # If update_kb is false or response is empty
        print(f"Human response received for kb_id: {kb_id}. KB not updated (update_kb={request.update_kb}).")
        return StatusResponse(status="success", message="Human response received, knowledge base not updated.")


# --- File Upload Endpoint ---
@app.post("/agents/{kb_id}/upload", response_model=StatusResponse)
async def upload_to_kb(kb_id: str, file: UploadFile = File(...)):
    """
    Accepts a file upload, parses its content, stores file metadata,
    and adds the extracted text to the specified knowledge base.
    """
    print(f"Received file upload request for kb_id: {kb_id}. Filename: {file.filename}, Content-Type: {file.content_type}")

    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided with the upload.")

    # --- Store File Metadata ---
    # Get file size (requires reading the file or seeking)
    file.file.seek(0, os.SEEK_END)
    file_size = file.file.tell()
    file.file.seek(0) # Reset file pointer for parsing
    print(f"Storing file record for '{file.filename}' ({file_size} bytes)... ")
    record_success = db_manager.add_uploaded_file_record(
        kb_id=kb_id,
        filename=file.filename,
        file_size=file_size,
        content_type=file.content_type
    )
    if not record_success:
        # Log the error but proceed with parsing and adding to KB? 
        # Or raise an error here? Let's log and proceed for now.
        # print(f"Warning: Failed to store file metadata record for '{file.filename}' in KB {kb_id}. Continuing with KB update.")
        # --- MODIFIED: Raise error on failure --- 
        print(f"Error: Failed to store file metadata record for '{file.filename}' in KB {kb_id}. Aborting upload.")
        raise HTTPException(status_code=500, detail=f"Failed to store file metadata before processing knowledge base.")

    # --- Parse File Content ---
    try:
        extracted_text = await parse_file(file)
    except Exception as e:
        print(f"Internal server error during file parsing for {file.filename}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Server error processing file: {str(e)}")
    
    if extracted_text is None:
        raise HTTPException(
            status_code=400, 
            detail=f"Unsupported file type or failed to parse file: {file.filename}. Supported types: {', '.join(SUPPORTED_EXTENSIONS)}"
        )
    if not extracted_text.strip():
        print(f"File {file.filename} parsed successfully but contained no text content.")
        return StatusResponse(status="success", message="File processed, but no text content found to add.")
    
    print(f"Adding extracted text from {file.filename} to KB {kb_id}...")
    try:
        success = kb_manager.add_to_kb(kb_id, extracted_text)
        if success:
            print(f"Successfully added content from {file.filename} to KB {kb_id}.")
            return StatusResponse(status="success", message=f"File '{file.filename}' processed, metadata stored, and content added to knowledge base {kb_id}.")
        else:
            print(f"Failed to add content from {file.filename} to KB {kb_id} (add_to_kb returned False).")
            raise HTTPException(status_code=500, detail="Failed to add extracted content to the knowledge base after parsing.")
    except Exception as e:
        print(f"Error adding parsed content from {file.filename} to KB {kb_id}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to update knowledge base: {str(e)}")


# --- NEW: Endpoint to list uploaded files ---
@app.get("/agents/{kb_id}/files", response_model=ListFilesResponse)
async def list_uploaded_files_endpoint(kb_id: str):
    """
    Lists metadata for all files uploaded to a specific knowledge base.
    """
    print(f"Received request to list uploaded files for KB: {kb_id}")
    try:
        # Verify KB exists (optional but good practice)
        # _ = kb_manager.create_or_get_kb(kb_id) # This might raise NotFoundError if KB doesn't exist
        
        file_info_list = db_manager.get_uploaded_files(kb_id)
        
        # Map the list of dicts to a list of UploadedFileInfo models
        files_response = [UploadedFileInfo(**info) for info in file_info_list]
        
        return ListFilesResponse(kb_id=kb_id, files=files_response)
    # except NotFoundError:
    #     raise HTTPException(status_code=404, detail=f"Knowledge base {kb_id} not found.")
    except Exception as e:
        print(f"Error listing uploaded files for KB {kb_id}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to list uploaded files: {str(e)}")


# --- NEW: Endpoint to retrieve conversation history ---
@app.get("/agents/{kb_id}/history", response_model=ChatHistoryResponse)
async def get_chat_history_endpoint(kb_id: str):
    """
    Retrieves the conversation history for a specific agent/KB.
    History is returned ordered by timestamp (oldest first).
    """
    print(f"Received request to get conversation history for KB: {kb_id}")
    try:
        # Retrieve history from the database manager
        db_history_raw = db_manager.get_conversation_history(kb_id)
        
        # Convert raw DB results (list of dicts) into HistoryMessage objects
        history_messages = [
            HistoryMessage(
                type=msg.get('message_type', 'unknown'), 
                content=msg.get('content', ''),
                timestamp=msg.get('timestamp') # Pass timestamp along
            ) 
            for msg in db_history_raw
        ]
        
        print(f"Retrieved {len(history_messages)} messages for KB {kb_id} history.")
        
        return ChatHistoryResponse(kb_id=kb_id, history=history_messages)
        
    except Exception as e:
        print(f"Error retrieving conversation history for KB {kb_id}: {e}")
        import traceback
        traceback.print_exc()
        # Consider if a 404 is more appropriate if kb_id potentially doesn't exist
        # For now, assuming any error is a 500
        raise HTTPException(status_code=500, detail=f"Failed to retrieve conversation history: {str(e)}")


# --- NEW: Endpoint to DELETE conversation history ---
@app.delete("/agents/{kb_id}/history", response_model=StatusResponse, status_code=status.HTTP_200_OK)
async def delete_chat_history_endpoint(kb_id: str):
    """
    Deletes all stored conversation history for a specific agent/KB.
    """
    print(f"Received request to DELETE conversation history for KB: {kb_id}")
    try:
        # Call the database manager function to delete history
        success = db_manager.delete_conversation_history(kb_id)
        
        if success:
            # Return a success status
            return StatusResponse(status="success", message=f"Conversation history for KB {kb_id} deleted successfully.")
        else:
            # If the DB function returns False, it indicates an internal error
            raise HTTPException(status_code=500, detail=f"Failed to delete conversation history for KB {kb_id} due to an internal error.")
            
    except Exception as e:
        # Catch any other unexpected errors
        print(f"Unexpected error during history deletion for KB {kb_id}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to delete conversation history: {str(e)}")


# --- HTTP Chat Endpoint (Now with Memory) ---
@app.post("/agents/{kb_id}/chat", response_model=ChatResponse)
async def chat_endpoint(kb_id: str, request: ChatRequest):
    """
    HTTP endpoint for stateful, non-streaming chat interactions with an agent,
    maintaining conversation history using in-memory storage.
    """
    print(f"Received HTTP chat request for kb_id: {kb_id}")
    
    try:
        # --- Memory Management (Load from DB) ---
        print(f"Loading conversation history for kb_id: {kb_id} from DB...")
        db_history = db_manager.get_conversation_history(kb_id)
        
        # Create a new memory instance for this request
        memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)
        
        # Populate memory from DB history
        for msg in db_history:
            if msg.get('message_type') == 'human':
                memory.chat_memory.add_user_message(msg.get('content', ''))
            elif msg.get('message_type') == 'ai':
                 memory.chat_memory.add_ai_message(msg.get('content', ''))
        
        print(f"Populated memory for kb_id: {kb_id} with {len(db_history)} messages from DB.")
        # --- End Memory Management ---

        # Instantiate the agent executor for this KB, passing the populated memory
        print(f"Creating agent executor with memory for kb_id: {kb_id}")
        # Pass the specific memory object for this conversation
        # AgentExecutor doesn't take memory directly with from_template prompt
        agent_executor = create_agent_executor(kb_id=kb_id) # REMOVED memory argument
        print(f"Agent executor created successfully for kb_id: {kb_id}")
        
        # Prepare the user message (Memory interaction is handled by AgentExecutor)
        user_message = request.message

        # --- Format history string from memory for the prompt --- 
        # Load history variables from the memory object
        memory_variables = memory.load_memory_variables({})
        # Extract the history string (default key is usually 'history', but ours is 'chat_history')
        history_string = memory_variables.get('chat_history', '') 
        # Ensure it's a string, ConversationBufferMemory with return_messages=True
        # might return a list of BaseMessage objects. Format if needed.
        if not isinstance(history_string, str):
            # Simple formatting for list of messages
            formatted_history = []
            for msg in history_string:
                if isinstance(msg, HumanMessage):
                    formatted_history.append(f"Human: {msg.content}")
                elif isinstance(msg, AIMessage):
                    formatted_history.append(f"AI: {msg.content}")
            history_string = "\n".join(formatted_history)
        # --- End History Formatting --- 
                
        # Prepare input for the agent (AgentExecutor handles loading memory now)
        # The memory object automatically provides the "chat_history" variable
        # We now need to pass the formatted history string manually
        input_data = {
            "input": user_message,
            "chat_history": history_string # Pass the formatted string history
        }
        
        # Invoke the agent in a separate thread to prevent blocking
        print(f"Invoking agent ({kb_id}) for message: {user_message}")
        response = await asyncio.to_thread(agent_executor.invoke, input_data)
        agent_output = response.get("output", "")
        print(f"Agent ({kb_id}) raw output: {agent_output}")
        
        # Clean the output before returning
        cleaned_output = clean_agent_output(agent_output)
        print(f"Agent ({kb_id}) cleaned output: {cleaned_output}")

        # --- Save Interaction to DB ---
        # Only save if the agent generated some output
        if cleaned_output is not None:
            print(f"Saving interaction to conversation history for kb_id: {kb_id}...")
            # Save user message (which was in input_data['input'])
            save_user_success = db_manager.add_conversation_message(kb_id, 'human', user_message)
            # Save AI response (the final cleaned output)
            save_ai_success = db_manager.add_conversation_message(kb_id, 'ai', cleaned_output)
            if not save_user_success or not save_ai_success:
                # Log an error if saving failed, but don't fail the request
                print(f"Warning: Failed to save full interaction to DB for kb_id: {kb_id}")
        # --- End Save Interaction ---
        
        # Extract confidence score (min distance) if available from intermediate steps
        min_distance = None
        confidence_decimal = None # Initialize decimal score
        
        if response.get("intermediate_steps"):
            for step in response["intermediate_steps"]:
                action, observation = step
                # Check if the observation came from our knowledge_base_retriever tool
                if action.tool == "knowledge_base_retriever" and isinstance(observation, dict):
                    min_distance = observation.get("min_distance")
                    # Use the first one found (should correspond to the most relevant retrieval)
                    if min_distance is not None:
                        print(f"Extracted min_distance (cosine): {min_distance}")
                        # Convert cosine distance (0=best, ~1=worst) to decimal score (0.0=worst, 1.0=best)
                        # Clamp distance between 0 and 1 just in case
                        clamped_distance = max(0.0, min(1.0, min_distance))
                        confidence_decimal = 1.0 - clamped_distance
                        print(f"Calculated confidence score (decimal): {confidence_decimal:.4f}") # Format for readability
                        break 
        
        # Check for handoff using the cleaned output
        # Instead of exact match, check if the polite handoff marker is present
        handoff_marker = "(needs help)"
        final_content = cleaned_output
        response_type = "answer" # Default to answer

        if cleaned_output.endswith(handoff_marker):
            print(f"Handoff marker found in agent output for {kb_id}.")
            # Remove the marker from the content sent to the user
            final_content = cleaned_output[:-len(handoff_marker)].strip()
            response_type = "handoff" # Set type to handoff
            # Optionally, you could trigger other backend actions here (e.g., notify human agent)
        # if cleaned_output == "HANDOFF_REQUIRED": # OLD check
        #     return ChatResponse(
        #         content="This question requires human assistance.",
        #         type="handoff",
        #         confidence_score=confidence_decimal # Pass decimal score
        #     )
        
        # Return the agent's cleaned response
        return ChatResponse(
            content=final_content, # Return potentially stripped content
            type=response_type, # Return correct type ('answer' or 'handoff')
            confidence_score=confidence_decimal # Pass decimal score
        )
        
    except Exception as e:
        import traceback
        print(f"Error in HTTP chat endpoint for {kb_id}: {e}\\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error processing chat request: {str(e)}")


# --- Run Instruction (for local development) ---
if __name__ == "__main__":
    import uvicorn
    print("Starting Uvicorn server...")
    # Use reload=True for development to automatically reload on code changes
    # Exclude the chromadb data directory from the reloader to prevent restarts during KB operations
    uvicorn.run(
        "main:app", 
        host="0.0.0.0", 
        port=8000, 
        reload=True,
        reload_excludes=["./chromadb_data/*"]
    ) 