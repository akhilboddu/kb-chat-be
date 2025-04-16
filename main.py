# main.py

import uuid
import time
import asyncio # <--- Import asyncio
import re  # For splitting sentences
import json # For formatting SSE data
from fastapi import FastAPI, HTTPException, UploadFile, File, Body, status, Query, Request, BackgroundTasks # Added Request and BackgroundTasks
from fastapi.responses import StreamingResponse # Added StreamingResponse
from pydantic import BaseModel, Field, HttpUrl
from typing import Dict, Any, List, Optional
from langchain_core.messages import HumanMessage, AIMessage # Import message types
from fastapi.middleware.cors import CORSMiddleware # Import CORS middleware
import datetime
import os
from chromadb.errors import NotFoundError # <--- Import NotFoundError
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import core components
import data_processor
from kb_manager import kb_manager # Singleton instance
import db_manager # Import the new DB manager
from agent_manager import create_agent_executor
from config import llm # Import the initialized LLM
from file_parser import parse_file, SUPPORTED_EXTENSIONS, get_file_extension # Import the file parser + get_file_extension
from langchain.memory import ConversationBufferMemory # Keep this one
from langchain_core.memory import BaseMemory # Correct import path for BaseMemory
from langchain_core.prompts import PromptTemplate # Add PromptTemplate import
from langchain_core.output_parsers import StrOutputParser # Add StrOutputParser import
from scraper import scrape_website # Import the scraper function
from data_processor import extract_text_from_json # Import JSON processor
from supabase_client import supabase # Import the supabase client

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
    kb_update_text: Optional[str] = None # Optional text specifically for KB update

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

# --- NEW: Model for Cleanup Response ---
class CleanupResponse(BaseModel):
    """Response model for the KB cleanup operation."""
    kb_id: str
    deleted_count: int
    message: str

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
    type: str # 'human' or 'ai' or 'human_agent'
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
    type: str = "answer"  # 'answer' or 'handoff'

# --- NEW: Models for Conversations Listing ---
class ConversationPreview(BaseModel):
    """Preview information for a single conversation."""
    last_message_timestamp: datetime.datetime
    last_message_preview: str
    message_count: int
    needs_human_attention: bool  # Flag indicating if conversation requires handoff
    
class KBConversationGroup(BaseModel):
    """Conversations for a single knowledge base."""
    kb_id: str
    name: Optional[str] = None
    conversation: ConversationPreview
    
class ListConversationsResponse(BaseModel):
    """Response model listing all conversations grouped by KB."""
    conversations: List[KBConversationGroup]

# --- NEW: Models for Human Chat and Knowledge Base Updates ---
class HumanChatRequest(BaseModel):
    """Request body for human agent chat response."""
    message: str = Field(..., description="The human agent's response message")

class HumanKnowledgeRequest(BaseModel):
    """Request body for adding human-verified knowledge to the KB."""
    knowledge_text: str = Field(..., description="The text to be added to the knowledge base")
    source_conversation_id: Optional[str] = Field(None, description="Optional: ID of the conversation this knowledge came from")

# --- NEW: Models for Agent Configuration ---
class AgentConfigResponse(BaseModel):
    """Response model for agent configuration."""
    system_prompt: str = Field(default=db_manager.DEFAULT_SYSTEM_PROMPT, description="The system prompt used by the agent.")
    max_iterations: int = Field(default=db_manager.DEFAULT_MAX_ITERATIONS, ge=1, description="Maximum iterations for the agent loop.")
    # Add other configurable fields here with defaults

class UpdateAgentConfigRequest(BaseModel):
    """Request model for updating agent configuration. All fields optional."""
    system_prompt: Optional[str] = Field(None, description="New system prompt for the agent.")
    max_iterations: Optional[int] = Field(None, ge=1, description="New maximum iterations for the agent loop.")
    # Add other configurable fields here as Optional

# --- NEW: Models for Scrape URL Endpoint ---
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

# --- FastAPI App Initialization ---
app = FastAPI(
    title="Multi-Tenant AI Sales Agent API",
    description="API for managing AI sales agents and WebSocket chat.",
    version="1.0.0"
)

# --- CORS Middleware Configuration ---
# Allow requests from all origins during development
# In production, replace "*" with the specific origin(s) of your frontend
origins = [
    "http://localhost:3002",
    "http://127.0.0.1:3002",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
] 

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

# --- Background Task Function --- 
async def run_scrape_and_populate(kb_id: str, url: str, max_pages: Optional[int]):
    """Runs the scraping and KB population process in the background."""
    logger.info(f"[Background Task] Starting scrape for KB '{kb_id}' from URL: {url} (max_pages: {max_pages or 'default'})" )
    current_status = "processing" # Keep track of the current status
    
    # Initialize scraping status
    db_manager.update_scrape_status(kb_id, {
        'status': current_status,
        'submitted_url': url,
        'pages_scraped': 0,
        'total_pages': max_pages if max_pages else config.get("MAX_INTERNAL_PAGES", 15),
        'progress': {'stage': 'starting', 'details': 'Initializing scraper'}
    })
    
    try:
        # 1. Run the scraper
        scrape_result = await scrape_website(url, max_pages=max_pages) # Pass max_pages override

        if not scrape_result or "error" in scrape_result:
            error_detail = scrape_result.get("error", "Unknown scraping error") if scrape_result else "Empty scrape result"
            logger.error(f"[Background Task] Scrape failed for KB '{kb_id}', URL '{url}'. Error: {error_detail}")
            current_status = "failed"
            # Update status to failed
            db_manager.update_scrape_status(kb_id, {
                'status': current_status,
                'submitted_url': url,
                'error': error_detail,
                'progress': {'stage': 'failed', 'details': f"Scraping failed: {error_detail}"}
            })
            return # Stop processing

        # Update pages scraped from metadata (merge with next status update if possible or ensure fields are present)
        pages_scraped_count = 0
        if "scrape_metadata" in scrape_result:
            pages_scraped_count = scrape_result["scrape_metadata"].get("pages_scraped", 0)
            # Update status including pages scraped
            db_manager.update_scrape_status(kb_id, {
                'status': current_status, # Still 'processing'
                'submitted_url': url,
                'pages_scraped': pages_scraped_count,
                'progress': {'stage': 'scraping_complete', 'details': f'Scraped {pages_scraped_count} pages'}
            })

        # 2. Extract the business profile
        business_profile = scrape_result.get("business_profile")
        if not business_profile or "error" in business_profile:
            error_detail = business_profile.get("error", "Unknown profile compilation error") if business_profile else "Missing business profile"
            logger.error(f"[Background Task] Profile compilation failed for KB '{kb_id}', URL '{url}'. Error: {error_detail}")
            current_status = "failed"
            db_manager.update_scrape_status(kb_id, {
                'status': current_status,
                'submitted_url': url,
                'error': error_detail,
                'progress': {'stage': 'failed', 'details': f"Profile compilation failed: {error_detail}"}
            })
            return # Stop processing
            
        logger.info(f"[Background Task] Scrape successful for KB '{kb_id}', URL '{url}'. Profile keys: {list(business_profile.keys())}")
        
        # Update status before processing
        db_manager.update_scrape_status(kb_id, {
            'status': current_status, # Still 'processing'
            'submitted_url': url,
            'pages_scraped': pages_scraped_count, # Include potentially updated count
            'progress': {'stage': 'processing_profile', 'details': 'Extracting text from profile'}
        })
        
        # 3. Process JSON profile to text
        text_to_add = extract_text_from_json(business_profile)
        if not text_to_add or not text_to_add.strip():
             logger.warning(f"[Background Task] No text extracted from scraped JSON profile for KB '{kb_id}', URL '{url}'. KB not populated.")
             current_status = "failed"
             db_manager.update_scrape_status(kb_id, {
                'status': current_status,
                'submitted_url': url,
                'error': 'No text content extracted from scraped profile',
                'progress': {'stage': 'failed', 'details': 'No text extracted from profile'}
             })
             return # Stop processing
             
        logger.info(f"[Background Task] Extracted {len(text_to_add)} characters from profile for KB '{kb_id}'.")

        # Update status before adding to KB
        db_manager.update_scrape_status(kb_id, {
            'status': current_status, # Still 'processing'
            'submitted_url': url,
            'progress': {'stage': 'populating_kb', 'details': 'Adding extracted text to knowledge base'}
        })

        # 4. Add text to Knowledge Base
        add_success = kb_manager.add_to_kb(kb_id, text_to_add)
        if add_success:
            logger.info(f"[Background Task] Successfully populated KB '{kb_id}' with scraped content from URL '{url}'.")
            current_status = "completed"
            db_manager.update_scrape_status(kb_id, {
                'status': current_status,
                'submitted_url': url,
                'pages_scraped': pages_scraped_count, # Final count
                'progress': {
                    'stage': 'completed',
                    'details': 'Successfully added content to knowledge base',
                    'chars_added': len(text_to_add),
                    'profile_keys': list(business_profile.keys())
                }
            })
        else:
             logger.error(f"[Background Task] Failed to add scraped content to KB '{kb_id}' from URL '{url}'.")
             current_status = "failed"
             db_manager.update_scrape_status(kb_id, {
                'status': current_status,
                'submitted_url': url,
                'error': 'Failed to add extracted content to knowledge base',
                'progress': {'stage': 'failed', 'details': 'Failed to add content to KB'}
             })
             
    except Exception as e:
        logger.exception(f"[Background Task] Unhandled exception during scrape/populate for KB '{kb_id}', URL '{url}': {e}")
        # Ensure status reflects failure
        current_status = "failed"
        db_manager.update_scrape_status(kb_id, {
            'status': current_status,
            'submitted_url': url,
            'error': f"Unhandled exception: {str(e)}",
            'progress': {'stage': 'failed', 'details': f'Unhandled exception: {str(e)}'}
        })

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

# --- NEW: Cleanup Endpoint ---
@app.post("/agents/{kb_id}/cleanup", response_model=CleanupResponse, status_code=status.HTTP_200_OK)
async def cleanup_kb_duplicates_endpoint(kb_id: str):
    """
    Removes duplicate documents (based on exact text content) from the specified knowledge base.
    """
    print(f"Received request to cleanup duplicates in KB: {kb_id}")
    try:
        # Run the potentially long-running cleanup task in a separate thread
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

# --- Human Response Endpoint ---
@app.post("/agents/{kb_id}/human_response", response_model=StatusResponse)
async def human_response_endpoint(kb_id: str, request: HumanResponseRequest):
    """
    Receives a human response after a handoff, adds it to the conversation history,
    and optionally updates the KB.
    """
    print(f"Received human response for kb_id: {kb_id}. Update KB: {request.update_kb}")
    
    # --- Add Human Agent response to conversation history FIRST --- 
    # We do this regardless of whether KB is updated, to keep the chat flow intact.
    if request.human_response and request.human_response.strip():
        print(f"Adding human agent response to history for KB {kb_id}...")
        history_save_success = db_manager.add_conversation_message(
            kb_id=kb_id, 
            message_type='human_agent', # Differentiate from end-user ('human')
            content=request.human_response
        )
        if not history_save_success:
            # Log a warning but don't necessarily fail the whole request
            print(f"Warning: Failed to save human agent response to conversation history for KB {kb_id}. Continuing...")
    else:
        print(f"No human agent response content provided to add to history for KB {kb_id}.")
        # Decide if this should be an error or just proceed.
        # For now, proceed, but the frontend should ideally validate this.
    
    # --- Handle KB Update (Optional) --- 
    kb_update_message = "Knowledge base not updated."
    if request.update_kb:
        print(f"Attempting to update KB {kb_id} with human-provided text...")
        try:
            # Determine which text to use for KB update
            text_for_kb = request.kb_update_text if request.kb_update_text else request.human_response
            
            if not text_for_kb or not text_for_kb.strip():
                print(f"No valid text provided for KB update. KB {kb_id} was not updated.")
                kb_update_message = "Knowledge base was not updated (no valid text provided)."
                # Note: We still return success below because the response *was* received and added to history.
            else:
                # Use the existing KBManager function to add the response, passing metadata
                success = kb_manager.add_to_kb(
                    kb_id=kb_id, 
                    text_to_add=text_for_kb, 
                    metadata={"source": "human_verified"}
                )
                if success:
                    print(f"Successfully updated KB {kb_id} with human response.")
                    kb_update_message = "Knowledge base updated."
                    # --- Log the update --- 
                    log_success = db_manager.log_kb_update(kb_id, text_for_kb)
                    if not log_success:
                        print(f"Warning: Failed to log KB update for {kb_id} after successful addition.")
                    # --- End Log ---
                else:
                    # add_to_kb might return False if text is empty after stripping
                    print(f"Failed to update KB {kb_id} (add_to_kb returned False). Response was not added.")
                    kb_update_message = "Knowledge base was not updated (failed to add)."

        except Exception as e:
            print(f"Error updating KB {kb_id} with human response: {e}")
            # Log traceback
            import traceback
            traceback.print_exc()
            # We don't raise HTTPException here anymore, as the primary goal (receiving response)
            # might have succeeded. We'll return a success status but report the KB issue in the message.
            kb_update_message = f"Failed to update knowledge base due to error: {str(e)}"
    else:
        # If update_kb is false
        print(f"Human response received for kb_id: {kb_id}. KB not updated (update_kb={request.update_kb}).")
        # kb_update_message remains "Knowledge base not updated."

    # Return overall success status for receiving the response
    final_message = f"Human response received and added to history. {kb_update_message}"
    return StatusResponse(status="success", message=final_message)


# --- File Upload Endpoint ---
@app.post("/agents/{kb_id}/upload", response_model=StatusResponse)
async def upload_to_kb(kb_id: str, files: List[UploadFile] = File(...)):
    """
    Accepts multiple file uploads, parses their content, stores file metadata,
    and adds the extracted text to the specified knowledge base.
    """
    if not files or len(files) == 0:
        raise HTTPException(status_code=400, detail="No files provided for upload.")
    
    processed_files = 0
    failed_files = 0
    no_content_files = 0
    
    for file in files:
        print(f"Processing file for kb_id: {kb_id}. Filename: {file.filename}, Content-Type: {file.content_type}")

        if not file.filename:
            print(f"Skipping file with no filename in request")
            failed_files += 1
            continue

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
            print(f"Error: Failed to store file metadata record for '{file.filename}' in KB {kb_id}. Skipping this file.")
            failed_files += 1
            continue

        # --- Parse File Content ---
        raw_extracted_text: Optional[str] = None
        try:
            raw_extracted_text = await parse_file(file)
        except Exception as e:
            print(f"Error during file parsing for {file.filename}: {e}")
            import traceback
            traceback.print_exc()
            failed_files += 1
            continue
        
        if raw_extracted_text is None:
            print(f"Unsupported file type or failed to parse file: {file.filename}")
            failed_files += 1
            continue
            
        if not raw_extracted_text.strip():
            print(f"File {file.filename} parsed successfully but contained no text content.")
            no_content_files += 1
            continue
        
        # PDF parsing now happens directly into Markdown via pymupdf4llm in file_parser.py
        text_to_add = raw_extracted_text 
        file_extension = get_file_extension(file.filename)
        
        # --- Add to Knowledge Base --- 
        print(f"Adding parsed text from {file.filename} to KB {kb_id}...") # Simplified log
        try:
            success = kb_manager.add_to_kb(kb_id, text_to_add)
            if success:
                # Simplified message, as structuring is now part of parsing for PDFs
                parsed_as = "Markdown" if file_extension == '.pdf' else "text"
                print(f"Successfully added content (parsed as {parsed_as}) from {file.filename} to KB {kb_id}.")
                processed_files += 1
            else:
                print(f"Failed to add content from {file.filename} to KB {kb_id} (add_to_kb returned False).")
                failed_files += 1
        except Exception as e:
            print(f"Error adding parsed content from {file.filename} to KB {kb_id}: {e}")
            failed_files += 1

    # Generate a summary message based on processing results
    message = f"Processed {processed_files} file(s) successfully"
    if no_content_files > 0:
        message += f", {no_content_files} file(s) had no text content"
    if failed_files > 0:
        message += f", {failed_files} file(s) failed to process"
    
    if processed_files == 0 and (failed_files > 0 or no_content_files > 0):
        # If we processed nothing but had failures, return a 207 (Multi-Status)
        # or could use 422 Unprocessable Entity or 500 Internal Server Error
        if failed_files > 0:
            raise HTTPException(status_code=422, detail=message)
        else:
            # All files were processed but had no content
            return StatusResponse(status="warning", message=message)
    
    return StatusResponse(status="success", message=message)


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


# --- NEW: Endpoint to list all conversations grouped by KB ---
@app.get("/conversations", response_model=ListConversationsResponse)
async def list_conversations_endpoint():
    """
    Lists all conversations grouped by knowledge base,
    with preview information and handoff status.
    Used by the human desk interface to show conversations requiring attention.
    """
    print("Received request to list all conversations with handoff status")
    try:
        # Get all available KBs
        kb_info_list = kb_manager.list_kbs()
        
        # Initialize response list
        conversations_list = []
        
        # For each KB, fetch the conversation history and determine handoff status
        for kb_info in kb_info_list:
            kb_id = kb_info.get('kb_id')
            kb_name = kb_info.get('name')
            
            # Get conversation history for this KB
            history = db_manager.get_conversation_history(kb_id)
            
            # Skip if no history exists
            if not history or len(history) == 0:
                continue
                
            # Count total messages
            message_count = len(history)
            
            # Get the last message for preview
            last_message = history[-1]
            last_message_timestamp = last_message.get('timestamp', datetime.datetime.now())
            last_message_content = last_message.get('content', '')
            
            # Create a short preview (first 50 chars)
            preview = last_message_content[:50] + "..." if len(last_message_content) > 50 else last_message_content
            
            # Determine if handoff is needed
            # Logic: If the last message is from the AI and contains handoff marker
            needs_attention = False
            if last_message.get('message_type') == 'ai':
                content = last_message.get('content', '')
                if "(needs help)" in content:
                    needs_attention = True
            
            # Create the conversation preview
            conversation_preview = ConversationPreview(
                last_message_timestamp=last_message_timestamp,
                last_message_preview=preview,
                message_count=message_count,
                needs_human_attention=needs_attention
            )
            
            # Add to the response list
            conversations_list.append(
                KBConversationGroup(
                    kb_id=kb_id,
                    name=kb_name,
                    conversation=conversation_preview
                )
            )
        
        return ListConversationsResponse(conversations=conversations_list)
        
    except Exception as e:
        print(f"Error listing conversations: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to list conversations: {str(e)}")


# --- NEW: Human Chat Endpoint ---
@app.post("/agents/{kb_id}/human-chat", response_model=StatusResponse)
async def human_chat_endpoint(kb_id: str, request: HumanChatRequest):
    """
    Endpoint for human agents to respond to conversations.
    This only adds the response to the chat history.
    """
    print(f"Received human chat response for kb_id: {kb_id}")
    
    if not request.message or not request.message.strip():
        raise HTTPException(
            status_code=400,
            detail="Message cannot be empty"
        )
    
    # Add message to conversation history
    history_save_success = db_manager.add_conversation_message(
        kb_id=kb_id,
        message_type='human_agent',
        content=request.message
    )
    
    if not history_save_success:
        raise HTTPException(
            status_code=500,
            detail="Failed to save message to conversation history"
        )
    
    return StatusResponse(
        status="success",
        message="Human agent response added to conversation history"
    )

# --- NEW: Human Knowledge Addition Endpoint ---
@app.post("/agents/{kb_id}/human-knowledge", response_model=StatusResponse)
async def human_knowledge_endpoint(kb_id: str, request: HumanKnowledgeRequest):
    """
    Endpoint for human agents to add verified knowledge to the KB.
    This only updates the knowledge base, not the chat history.
    """
    print(f"Received human knowledge addition for kb_id: {kb_id}")
    
    if not request.knowledge_text or not request.knowledge_text.strip():
        raise HTTPException(
            status_code=400,
            detail="Knowledge text cannot be empty"
        )
    
    try:
        # Prepare metadata, only including conversation_id if it's not None
        metadata_dict = {"source": "human_verified"}
        if request.source_conversation_id:
            metadata_dict["conversation_id"] = request.source_conversation_id
            
        # Add to knowledge base with potentially filtered metadata
        success = kb_manager.add_to_kb(
            kb_id=kb_id,
            text_to_add=request.knowledge_text,
            metadata=metadata_dict # Pass the constructed dictionary
        )
        
        if not success:
            # Check kb_manager logs for specific reasons why add_to_kb might fail
            print(f"kb_manager.add_to_kb returned False for KB {kb_id}") 
            raise HTTPException(
                status_code=500,
                detail="Failed to add knowledge to the knowledge base (internal KB error)"
            )
        
        # Log the KB update
        log_success = db_manager.log_kb_update(kb_id, request.knowledge_text)
        if not log_success:
            # Log warning but don't fail the request
            print(f"Warning: Failed to log KB update for {kb_id}")
        
        return StatusResponse(
            status="success",
            message="Knowledge successfully added to the knowledge base"
        )
        
    except HTTPException as http_exc:
        # Re-raise known HTTP exceptions (like the 400 for empty text)
        raise http_exc
    except Exception as e:
        # Catch potential errors during metadata creation or kb_manager call
        print(f"Error adding knowledge to KB {kb_id}: {e}")
        import traceback
        traceback.print_exc()
        # Check if the error message indicates a metadata issue specifically
        if "Expected metadata value to be a str, int, float or bool" in str(e):
             raise HTTPException(
                status_code=500,
                detail=f"Failed to add knowledge to knowledge base: Metadata type error - {str(e)}"
            )
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to add knowledge to knowledge base: {str(e)}"
            )

# --- NEW: Agent Configuration Endpoints ---
@app.get("/agents/{kb_id}/config", response_model=AgentConfigResponse)
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

@app.put("/agents/{kb_id}/config", response_model=StatusResponse)
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

# --- HTTP Chat Endpoint (Now with Memory) ---
@app.post("/agents/{kb_id}/chat", response_model=ChatResponse)
async def chat_endpoint(kb_id: str, request: ChatRequest):
    """
    HTTP endpoint for stateful, non-streaming chat interactions with an agent,
    maintaining conversation history using the database.
    """
    print(f"Received HTTP chat request for kb_id: {kb_id}")
    
    user_message = request.message
    handoff_marker = "(needs help)"
    
    # Define default error/handoff messages outside the try block
    generic_error_msg = "Sorry, I encountered an issue processing your request."
    iteration_limit_msg = f"Hmm, I seem to be having trouble finding that specific information right now. I'll ask a human colleague to take a look for you. {handoff_marker}"
    
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
        agent_executor = create_agent_executor(kb_id=kb_id, memory=memory) 
        print(f"Agent executor created successfully for kb_id: {kb_id}")
        
        # --- Format History for Prompt --- 
        memory_variables = memory.load_memory_variables({})
        history_string = memory_variables.get('chat_history', '') 
        if not isinstance(history_string, str):
            formatted_history = []
            for msg in history_string:
                if isinstance(msg, HumanMessage):
                    formatted_history.append(f"Human: {msg.content}")
                elif isinstance(msg, AIMessage):
                    formatted_history.append(f"AI: {msg.content}")
            history_string = "\n".join(formatted_history)
                
        # --- Prepare Agent Input --- 
        input_data = {
            "input": user_message,
            "chat_history": history_string
        }
        
        # --- Invoke Agent --- 
        print(f"Invoking agent ({kb_id}) for message: {user_message}")
        try:
            response = await asyncio.to_thread(agent_executor.invoke, input_data)
            # Agent executed successfully, proceed to process output
            agent_output = None
            cleaned_output = None
            try:
                agent_output = response.get("output")
                if agent_output:
                    cleaned_output = clean_agent_output(agent_output)
                    print(f"Agent ({kb_id}) raw output: {agent_output}")
                    print(f"Agent ({kb_id}) cleaned output: {cleaned_output}")
                else:
                    print(f"Agent ({kb_id}) returned no 'output'.")
                    # Treat as invalid output, fall through to error handling below
            except Exception as clean_err:
                 print(f"Error cleaning agent output for {kb_id}: {clean_err}")
                 # Keep cleaned_output as None, fall through to error handling below

            # --- Determine Final Response Content & Type (Success Path) ---
            if cleaned_output is not None and cleaned_output.strip():
                final_content = cleaned_output # Start with the agent's cleaned output
                response_type = "answer"
                
                if cleaned_output.endswith(handoff_marker):
                    print(f"Handoff triggered by agent marker for {kb_id}.")
                    final_content = cleaned_output[:-len(handoff_marker)].strip()
                    response_type = "handoff"
            else:
                # Agent finished but output was invalid/empty
                print(f"Agent output was invalid or empty for {kb_id}. Using generic error.")
                response_type = "error" 
                final_content = generic_error_msg # Use the generic error message
                # Setting cleaned_output to None ensures DB saving logic treats it as error
                cleaned_output = None 

        # --- Handle Specific Agent Execution Errors ---            
        except MaxIterationsError as e:
            print(f"Agent ({kb_id}) hit max iterations: {e}")
            response_type = "handoff" # Treat as handoff
            cleaned_output = iteration_limit_msg # Use the specific message WITH marker
            final_content = cleaned_output[:-len(handoff_marker)].strip() # Remove marker for response
        except Exception as agent_exec_err:
            # Catch other potential errors during agent execution itself
            print(f"Error during agent execution for {kb_id}: {agent_exec_err}")
            import traceback
            traceback.print_exc()
            response_type = "error" # Treat as general error
            final_content = generic_error_msg
            cleaned_output = None # Ensure it's treated as error for DB saving
            
        # --- Save Interaction to DB --- 
        print(f"DEBUG: Attempting to save interaction for {kb_id}...")
        # Always save user message
        save_user_success = db_manager.add_conversation_message(kb_id, 'human', user_message)
        if not save_user_success:
             print(f"Warning: Failed to save user message to DB for kb_id: {kb_id}")

        # Save AI message based on response_type and content
        if response_type != "error":
            # Determine content to save: use cleaned_output if it exists (it will contain the marker on handoff)
            # Otherwise, use final_content (which might be the generic error if cleaning failed)
            content_to_save = cleaned_output if cleaned_output is not None else final_content
            print(f"DEBUG: Saving AI message. Type='{response_type}', Saved Content='{content_to_save}'")
            save_ai_success = db_manager.add_conversation_message(
                kb_id,
                'ai',
                content_to_save 
            )
            if not save_ai_success:
                print(f"Warning: Failed to save AI message to DB for kb_id: {kb_id}")
        else: # If response_type IS error
            print(f"DEBUG: Skipping save for AI message due to response_type='{response_type}'.")
            # Optionally save an error placeholder? For now, just skipping.

        # --- Return Response --- 
        # Return the final_content (which has marker removed for handoffs)
        print(f"DEBUG: Returning ChatResponse. final_content='{final_content}', response_type='{response_type}'")
        return ChatResponse(
            content=final_content,
            type=response_type
        )
        
    # --- Catch Errors Outside Agent Execution (e.g., memory loading, setup) ---
    except Exception as e:
        import traceback
        print(f"Critical error in HTTP chat endpoint setup/outside agent execution for {kb_id}: {e}\n{traceback.format_exc()}")
        # Return a generic error via HTTPException, don't save anything
        raise HTTPException(status_code=500, detail=f"Error processing chat request: {str(e)}")


# --- NEW: Scrape URL Endpoint ---
@app.post("/agents/{kb_id}/scrape-url", response_model=ScrapeInitiatedResponse, status_code=status.HTTP_202_ACCEPTED)
async def scrape_url_and_populate_kb(
    kb_id: str, 
    request: ScrapeURLRequest, 
    background_tasks: BackgroundTasks
):
    """
    Initiate scraping of a URL to populate a knowledge base.
    The scraping happens in the background.
    """
    try:
        # Initialize scraping status
        initial_status = {
            "status": "processing",
            "submitted_url": str(request.url),
            "pages_scraped": 0,
            "total_pages": request.max_pages if request.max_pages else config.get("MAX_INTERNAL_PAGES", 15),
            "progress": {
                "stage": "initialized",
                "details": "Starting scrape process"
            }
        }
        
        # Update initial status
        if not db_manager.update_scrape_status(kb_id, initial_status):
            raise HTTPException(
                status_code=500,
                detail="Failed to initialize scraping status"
            )
        
        # Add the background task
        background_tasks.add_task(
            run_scrape_and_populate,
            kb_id=kb_id,
            url=str(request.url),
            max_pages=request.max_pages
        )
        
        return ScrapeInitiatedResponse(
            kb_id=kb_id,
            status="processing",
            message="Scraping initiated in background",
            submitted_url=str(request.url)
        )
        
    except Exception as e:
        logger.error(f"Error initiating scrape for KB {kb_id}: {e}")
        # Update status to failed if initialization fails
        db_manager.update_scrape_status(kb_id, {
            "status": "failed",
            "submitted_url": str(request.url),
            "error": str(e),
            "progress": {
                "stage": "failed",
                "details": f"Failed to initialize scrape: {str(e)}"
            }
        })
        raise HTTPException(
            status_code=500,
            detail=f"Failed to initiate scraping: {str(e)}"
        )

@app.get("/agents/{kb_id}/scrape-status", response_model=ScrapeStatusResponse)
async def get_scrape_status(kb_id: str):
    """
    Get the current status of a scraping operation for a specific KB.
    """
    try:
        status = db_manager.get_scrape_status(kb_id)
        if not status:
            raise HTTPException(
                status_code=404,
                detail=f"No scraping operation found for KB {kb_id}"
            )
        return ScrapeStatusResponse(**status)
    except Exception as e:
        logger.error(f"Error retrieving scrape status for KB {kb_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve scraping status: {str(e)}"
        )


# --- BOT: Endpoints ---
@app.post("/bots/{bot_id}/chat", response_model=ChatResponse)
async def bot_chat_endpoint(bot_id: str, request: ChatRequest):
    """
    HTTP endpoint for stateful, non-streaming chat interactions with a bot,
    maintaining conversation history using the database.
    """
    print(f"Received HTTP chat request for bot_id: {bot_id}")

    response = supabase.table("bots").select("*").eq("id", bot_id).execute()
    kb_id = response.data[0]["kb_id"]

    # now use all logic from /agents/{kb_id}/chat endpoint
    return await chat_endpoint(kb_id, request)

@app.post("/bots/{bot_id}/upload", response_model=StatusResponse)
async def bot_upload_endpoint(bot_id: str, files: List[UploadFile] = File(...)):
    """
    Upload files to a bot's knowledge base.
    """
    print(f"Received upload request for bot_id: {bot_id}")
    print(f"Files: {files}")
    # also add to knowledge_sources table under supabase
    for file in files:
        fileContent = ""
        fileExtension = file.filename.split(".")[-1]

        # Read file size
        file.file.seek(0, os.SEEK_END)
        file_size = file.file.tell()
        file.file.seek(0)  # Reset file pointer
        
        # Format with Python's f-string formatting for floating point (:.1f for 1 decimal place)
        fileContent = f"File: {file.filename} ({file.content_type or f'{fileExtension} file'}) - Size: {file_size / 1024:.1f} KB"

        sourceData = {
            "bot_id": bot_id,
            "source_type": "file",
            "content": fileContent
        }
        response = supabase.table("knowledge_sources").insert(sourceData).execute()
        print(f"Knowledge source added: {response}")

    response = supabase.table("bots").select("*").eq("id", bot_id).execute()
    print(f"Bot response: {response}")

    kb_id = response.data[0]["kb_id"]

    # now use all logic from /agents/{kb_id}/upload endpoint
    return await upload_to_kb(kb_id, files)

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