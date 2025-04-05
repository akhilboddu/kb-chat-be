# main.py

import uuid
import time
import asyncio # <--- Import asyncio
import re  # For splitting sentences
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File # Add UploadFile, File
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
from langchain_core.messages import HumanMessage, AIMessage # Import message types
from fastapi.middleware.cors import CORSMiddleware # Import CORS middleware

# Import core components
import data_processor
from kb_manager import kb_manager # Singleton instance
from agent_manager import create_agent_executor
from config import llm # Import the initialized LLM
from file_parser import parse_file, SUPPORTED_EXTENSIONS # Import the file parser

# --- Pydantic Models ---

class CreateAgentRequest(BaseModel):
    """Request body for creating a new agent/KB."""
    # Allows any valid JSON structure as input data
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
    """Response body after successfully creating an agent/KB."""
    kb_id: str
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
    summary: str # Replaced document_count with summary
    
class ListKBsResponse(BaseModel):
    """Response containing a list of available KB information."""
    kbs: List[KBInfo]

# --- Models for HTTP Chat Endpoint ---
class ChatRequest(BaseModel):
    """Request body for chat interactions via HTTP."""
    message: str = Field(..., description="User message to the agent")
    kb_id: str = Field(..., description="Knowledge base ID")
    
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
origins = ["*"] 

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True, # Allows cookies if needed (not used here, but often useful)
    allow_methods=["*"],    # Allows all methods (GET, POST, etc.)
    allow_headers=["*"],    # Allows all headers
)
# --- End CORS Configuration ---

print("FastAPI app initialized.")
if not llm:
    print("WARNING: LLM is not configured. Agent functionality will be limited.")


# --- Utility Functions ---
def chunk_response(text, max_chunk_size=1000):
    """
    Splits a long text response into smaller chunks, trying to break at sentence boundaries.
    Returns a list of chunks.
    """
    if len(text) <= max_chunk_size:
        return [text]  # Return as single chunk if already small enough
    
    # Split by sentences and build chunks that don't exceed max_chunk_size
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks = []
    current_chunk = ""
    
    for sentence in sentences:
        # If single sentence is longer than max size, force-split it
        if len(sentence) > max_chunk_size:
            # Add any existing content to chunks
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = ""
            
            # Split long sentence by size
            for i in range(0, len(sentence), max_chunk_size):
                chunks.append(sentence[i:i+max_chunk_size])
            continue
            
        # If adding this sentence would exceed max size, start a new chunk
        if len(current_chunk) + len(sentence) + 1 > max_chunk_size:
            chunks.append(current_chunk)
            current_chunk = sentence
        else:
            # Add to current chunk with space if not empty
            if current_chunk:
                current_chunk += " " + sentence
            else:
                current_chunk = sentence
    
    # Add the last chunk if it has content
    if current_chunk:
        chunks.append(current_chunk)
        
    return chunks

# --- HTTP Endpoints ---

@app.post("/agents", response_model=CreateAgentResponse, status_code=201)
async def create_agent(request: CreateAgentRequest):
    """
    Creates a new agent instance by processing input JSON data and
    populating a dedicated knowledge base.
    """
    print("Received request to create agent...")
    try:
        # 1. Generate a unique KB ID
        # Using timestamp and a short UUID part for uniqueness and readability
        timestamp = int(time.time())
        short_uuid = str(uuid.uuid4())[:8]
        kb_id = f"kb_{timestamp}_{short_uuid}"
        print(f"Generated KB ID: {kb_id}")

        # 2. Process JSON data
        print("Extracting text from JSON data...")
        extracted_text = data_processor.extract_text_from_json(request.json_data)
        if not extracted_text.strip():
            print("Warning: No text extracted from JSON data.")
            # Decide if this is an error or just an empty KB
            # For now, let's allow empty KBs but maybe log a warning
            # raise HTTPException(status_code=400, detail="No text content found in the provided JSON data.")

        print("Chunking extracted text...")
        text_chunks = data_processor.chunk_text(extracted_text)
        print(f"Generated {len(text_chunks)} chunks.")

        # 3. Create and populate KB
        print(f"Creating/getting KB collection: {kb_id}")
        kb_collection = kb_manager.create_or_get_kb(kb_id)

        if text_chunks:
            print(f"Populating KB: {kb_id}")
            kb_manager.populate_kb(kb_collection, text_chunks)
        else:
            print(f"KB {kb_id} created but is empty as no text chunks were generated.")

        print(f"Agent/KB {kb_id} created successfully.")
        return CreateAgentResponse(kb_id=kb_id, message="Agent knowledge base created successfully.")

    except Exception as e:
        print(f"Error creating agent: {e}")
        # Log the full error traceback here in a real application
        raise HTTPException(status_code=500, detail=f"Failed to create agent knowledge base: {str(e)}")

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

# --- WebSocket Endpoint ---
@app.websocket("/ws/agents/{kb_id}/chat")
async def websocket_endpoint(websocket: WebSocket, kb_id: str):
    """Handles WebSocket connections for agent chat with history."""
    connection_active = False
    
    try:
        await websocket.accept()
        connection_active = True
        print(f"WebSocket connection accepted for kb_id: {kb_id}")
        
        # Initialize chat history for this connection
        chat_history = []
        agent_executor = None
        
        # Instantiate the agent executor for this specific KB
        print(f"Creating agent executor for kb_id: {kb_id}")
        agent_executor = create_agent_executor(kb_id=kb_id)
        print(f"Agent executor created successfully for kb_id: {kb_id}")

        # Main WebSocket loop
        while connection_active:
            try:
                # Receive message from client
                data = await websocket.receive_text()
                print(f"Received message from client ({kb_id}): {data}")
                
                if not agent_executor:
                    await websocket.send_json({"type": "error", "content": "Agent is not available."})
                    continue

                # Append user message to history before invoking
                chat_history.append(HumanMessage(content=data))

                # Invoke the agent with the current history
                input_data = {"input": data, "chat_history": chat_history[:-1]}

                # Send immediate "Processing" status
                try:
                    await websocket.send_json({"type": "status", "content": "Processing..."})
                    print(f"Server: Status update sent.")
                except Exception as status_send_error:
                    print(f"Warning: Failed to send status update ({kb_id}): {status_send_error}")
                    # Connection might be lost
                    connection_active = False
                    break

                # Invoke the agent and get response
                print(f"Invoking agent ({kb_id}) in thread with input: {data}")
                response = await asyncio.to_thread(agent_executor.invoke, input_data)
                agent_output = response.get("output", "")
                print(f"Agent ({kb_id}) raw output: {agent_output}")
                
                # Check for handoff signal
                if agent_output == "HANDOFF_REQUIRED":
                    print(f"Agent ({kb_id}) triggered handoff.")
                    try:
                        await websocket.send_json({"type": "handoff", "message": "Agent requires assistance."})
                        print(f"Server: Handoff message sent.")
                    except Exception as e:
                        print(f"Failed to send handoff message: {e}")
                        connection_active = False
                        break
                else:
                    # If not handoff, chunk the response and send in smaller pieces
                    print(f"Sending chunked answer from agent ({kb_id}). Total length: {len(agent_output)}")
                    
                    # Split into smaller chunks to avoid WebSocket frame size issues
                    response_chunks = chunk_response(agent_output)
                    print(f"Split into {len(response_chunks)} chunks")
                    
                    # Track if all chunks were successfully sent
                    all_chunks_sent = True
                    
                    # Send each chunk separately
                    for i, chunk in enumerate(response_chunks):
                        is_first = (i == 0)
                        is_last = (i == len(response_chunks) - 1)
                        
                        chunk_type = "answer_part"
                        if is_first and is_last:
                            chunk_type = "answer"  # Single chunk only
                        elif is_first:
                            chunk_type = "answer_start"  # First of multiple chunks
                        elif is_last:
                            chunk_type = "answer_end"  # Last of multiple chunks
                        
                        print(f"Server: Sending chunk {i+1}/{len(response_chunks)}. Type: {chunk_type}")
                        try:
                            await websocket.send_json({
                                "type": chunk_type,
                                "content": chunk,
                                "chunk_info": {
                                    "index": i,
                                    "total": len(response_chunks)
                                }
                            })
                            # Small delay between chunks to prevent overwhelming
                            if len(response_chunks) > 1 and not is_last:
                                await asyncio.sleep(0.1)
                                
                        except Exception as chunk_error:
                            print(f"Failed to send chunk {i+1}: {chunk_error}")
                            all_chunks_sent = False
                            connection_active = False
                            break
                    
                    if all_chunks_sent:
                        print(f"Server: All chunks sent successfully.")
                        # Append agent's response to history only if all chunks were sent
                        chat_history.append(AIMessage(content=agent_output))
                    else:
                        print(f"Server: Failed to send all chunks. Connection might be closed.")
            
            except WebSocketDisconnect:
                print(f"WebSocket connection closed by client for kb_id: {kb_id}")
                connection_active = False
                break
            except Exception as e:
                import traceback
                print(f"Error processing message: {e}\n{traceback.format_exc()}")
                try:
                    await websocket.send_json({"type": "error", "content": f"An error occurred processing your request."})
                except Exception:
                    # If we can't send the error, the connection is likely dead
                    connection_active = False
                    break
                
    except WebSocketDisconnect:
        print(f"WebSocket connection closed during handshake for kb_id: {kb_id}")
    except Exception as e:
        import traceback
        print(f"Unexpected error in WebSocket handler for {kb_id}: {e}\n{traceback.format_exc()}")
    finally:
        # Cleanup code
        print(f"Cleaning up WebSocket resources for kb_id: {kb_id} (History length: {len(chat_history) if 'chat_history' in locals() else 0})")
        try:
            # Only try to close if we think the connection might still be active
            if connection_active:
                await websocket.close(code=1011)
        except Exception:
            pass  # Connection might already be closed


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
            # Use the existing KBManager function to add the response
            success = kb_manager.add_to_kb(kb_id, request.human_response)
            if success:
                print(f"Successfully updated KB {kb_id}.")
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
    Accepts a file upload, parses its content based on extension,
    and adds the extracted text to the specified knowledge base.
    """
    print(f"Received file upload request for kb_id: {kb_id}. Filename: {file.filename}")

    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided with the upload.")

    # Parse the file content using the file_parser module
    try:
        extracted_text = await parse_file(file)
    except Exception as e:
        # Catch unexpected errors during parsing itself
        print(f"Internal server error during file parsing for {file.filename}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Server error processing file: {str(e)}")

    # Check if parsing was successful and returned text
    if extracted_text is None:
        # parse_file returns None for unsupported types or major parsing errors
        # It logs the specific reason internally
        raise HTTPException(
            status_code=400, 
            detail=f"Unsupported file type or failed to parse file: {file.filename}. Supported types: {', '.join(SUPPORTED_EXTENSIONS)}"
        )
    
    if not extracted_text.strip():
        # Handle cases where the file is valid but contains no text
        print(f"File {file.filename} parsed successfully but contained no text content.")
        return StatusResponse(status="success", message="File processed, but no text content found to add.")

    # Add the extracted text to the knowledge base
    # kb_manager.add_to_kb handles chunking internally
    print(f"Adding extracted text from {file.filename} to KB {kb_id}...")
    try:
        success = kb_manager.add_to_kb(kb_id, extracted_text)
        if success:
            print(f"Successfully added content from {file.filename} to KB {kb_id}.")
            return StatusResponse(status="success", message=f"File '{file.filename}' processed and added to knowledge base {kb_id}.")
        else:
            # This might happen if add_to_kb fails for some reason (e.g., post-processing resulted in empty content)
            print(f"Failed to add content from {file.filename} to KB {kb_id} (add_to_kb returned False).")
            # We might return a 500 or a more specific error depending on why add_to_kb might fail
            raise HTTPException(status_code=500, detail="Failed to add extracted content to the knowledge base after parsing.")
            
    except Exception as e:
        print(f"Error adding parsed content from {file.filename} to KB {kb_id}: {e}")
        import traceback
        traceback.print_exc()
        # This indicates an error interacting with the KB store (ChromaDB)
        raise HTTPException(status_code=500, detail=f"Failed to update knowledge base: {str(e)}")


# --- HTTP Chat Endpoint ---
@app.post("/agents/{kb_id}/chat", response_model=ChatResponse)
async def chat_endpoint(kb_id: str, request: ChatRequest):
    """
    HTTP endpoint for chat interactions with an agent.
    Provides a simpler alternative to WebSockets for basic chat functionality.
    """
    print(f"Received HTTP chat request for kb_id: {kb_id}")
    
    try:
        # Instantiate the agent executor for this KB
        print(f"Creating agent executor for kb_id: {kb_id}")
        agent_executor = create_agent_executor(kb_id=kb_id)
        print(f"Agent executor created successfully for kb_id: {kb_id}")
        
        # Use an empty chat history for now (stateless)
        # In a production app, you might want to implement session-based history
        chat_history = []
        
        # Prepare the user message
        user_message = request.message
        
        # Add the message to history (for this request only)
        chat_history.append(HumanMessage(content=user_message))
        
        # Prepare input for the agent
        input_data = {"input": user_message, "chat_history": chat_history[:-1]}
        
        # Invoke the agent in a separate thread to prevent blocking
        print(f"Invoking agent ({kb_id}) for message: {user_message}")
        response = await asyncio.to_thread(agent_executor.invoke, input_data)
        agent_output = response.get("output", "")
        print(f"Agent ({kb_id}) raw output: {agent_output}")
        
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
        
        # Check for handoff
        if agent_output == "HANDOFF_REQUIRED":
            return ChatResponse(
                content="This question requires human assistance.",
                type="handoff",
                confidence_score=confidence_decimal # Pass decimal score
            )
        
        # Return the agent's response
        return ChatResponse(
            content=agent_output,
            type="answer",
            confidence_score=confidence_decimal # Pass decimal score
        )
        
    except Exception as e:
        import traceback
        print(f"Error in HTTP chat endpoint for {kb_id}: {e}\n{traceback.format_exc()}")
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