import asyncio
import json
import logging
from fastapi import APIRouter, HTTPException, status, Body, Query, Depends, WebSocket, WebSocketDisconnect, Path
from langchain.memory import ConversationBufferMemory
from langchain_core.messages import HumanMessage, AIMessage
import math
from typing import Dict, Set, Optional, Any

from datetime import datetime
from app.config.redisconnection import redisConnection
from app.config.settings import EXPIRY_STATUS_TIME, ONLINE
from app.core.supabase_client import supabase
from app.database.operations import post_message
from app.utils.cache_utils import get_cached_response, set_cached_response
from app.models.chat import (
    ChatRequest,
    ChatResponse,
    HumanResponseRequest,
    HumanChatRequest,
    HumanKnowledgeRequest,
    ChatHistoryResponse,
    HistoryMessage,
    ListConversationsResponse,
    KBConversationGroup,
    ConversationPreview,
    PaginatedListMessagesResponse,
    DemoChatRequest,
)
from app.models.bot import (
    CreateBotConversationResponse,
    PaginatedListBotConversationsResponse,
)
from app.models.base import StatusResponse

from app.core import supabase_metadata_manager as db_manager, kb_manager, agent_manager
from app.services.push_notifications import send_push_notification
from app.services.send_email import notify_admin_on_user_message, notify_client_message
from app.utils.text_processing import clean_agent_output, auto_add_handoff_if_needed
from app.utils.verification import get_current_user
from app.utils.crm_utils import ensure_crm_entry
from app.utils.subscription_limits import enforce_subscription_limits

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

# Store active websocket connections
active_connections: Dict[str, Set[WebSocket]] = {}

async def broadcast_to_all_connections(conversation_id: str, message_data: dict):
    """Broadcast message to all WebSocket connections for this conversation"""
    logger.info(f"Attempting to broadcast to conversation {conversation_id}, active_connections has: {list(active_connections.keys())}")
    if conversation_id not in active_connections:
        logger.warning(f"No active connections found for conversation {conversation_id}")
        return
    
    connection_count = len(active_connections[conversation_id])
    logger.info(f"Broadcasting to {connection_count} connections for conversation {conversation_id}")
    
    dead_connections = []
    sent_count = 0
    for ws in list(active_connections[conversation_id]):
        try:
            await ws.send_json(message_data)
            sent_count += 1
            logger.debug(f"Successfully sent message to WebSocket connection")
        except Exception as e:
            logger.error(f"Failed to send message to WebSocket: {e}")
            dead_connections.append(ws)
    
    logger.info(f"Successfully sent to {sent_count}/{connection_count} connections")
    
    # Clean up dead connections
    for ws in dead_connections:
        active_connections[conversation_id].discard(ws)
    
    if not active_connections[conversation_id]:
        del active_connections[conversation_id]
        logger.info(f"Removed conversation {conversation_id} from active_connections (no remaining connections)")

async def handle_handoff_triggered(conversation_id: str):
    """Handle all handoff-related updates when handoff is triggered"""
    # Update conversation status to human
    supabase.table("conversations").update({
        "status": "human"
    }).eq("id", conversation_id).execute()
    
    # Increment handoff_requests counter
    resp = supabase.table("conversations").select("handoff_requests").eq("id", conversation_id).single().execute()
    current = resp.data.get("handoff_requests", 0) if resp.data else 0
    supabase.table("conversations").update({
        "handoff_requests": current + 1
    }).eq("id", conversation_id).execute()

# Add a new WebSocket endpoint for agents/operators
agent_active_connections = {}

@router.post("/send-mail")
async def send_mail(request: ChatRequest):
    client = redisConnection.client
    if not client:
        return {"message": "Redis client not available"}
    #
    if client.get(request.conversation_id):
        return {"message": "user is online"}

    response = (
        supabase.table("conversations")
        .select("*")
        .eq("id", request.conversation_id)
        .execute()
    )  # ensures you get one row or error
    print(response.data[0])

    botId = response.data[0]["bot_id"]
    client_email = response.data[0]["customer_email"]
    botData = supabase.table("bots").select("company","user_id").eq("id", botId).execute()
    company_name = botData.data[0]["company"]

    userId = botData.data[0]["user_id"] 
    userData = supabase.auth.admin.get_user_by_id(userId)
    company_email = userData.user.email
    

    #get user email from conversation_id in supabase
    

    data = (
        response.data[0]
        if hasattr(response, "data") and len(response.data) > 0
        else None
    )

    if data:
        notify_client_message(
            company_name,
            company_email,
            request.message,
            request.conversation_id,  
            client_email,
            botId  # Pass the bot_id that we already fetched
        )
        return {"message": "mail has been sent"}

    return {"message": "conversation not found"}


@router.get("/{conversation_id}/chat-history")
async def get_chat_history(conversation_id: str):
    try:
        conversation_response = (
            supabase.table("messages")
            .select("*")
            .eq("conversation_id", conversation_id)
            .order("created_at", desc=False)
            .execute()
        )
        data = conversation_response.data
        response = []
        for dat in data:
            response.append({
                "id": dat["id"], 
                "role": dat["role"], 
                "message": dat["content"], 
                "reply_to_message_id": dat["reply_to_message_id"], 
                "timestamp": dat["created_at"],  # Use timestamp instead of created_at for consistency
                "status": dat.get("status")  # Include status field for handoff indicators
            })
          
        return response
    except Exception as e:
        print(e)
        return []


@router.post("/agents/{kb_id}/chat", response_model=ChatResponse)
async def chat_endpoint(
    kb_id: str,
    request: ChatRequest,
    store_history: bool = Query(True, description="When false, skip persisting messages"),
    customer_context: Optional[Dict[str, Any]] = None,
):
    """
    HTTP endpoint for stateful, non-streaming chat interactions with an agent,
    maintaining conversation history using the database.
    """
    print(f"Received HTTP chat request for kb_id: {kb_id}")
    if customer_context:
        print(f"Customer context provided: {customer_context}")

    user_message = request.message
    handoff_marker = "(needs help)"

    # Define default error/handoff messages outside the try block
    generic_error_msg = "Sorry, I encountered an issue processing your request."
    iteration_limit_msg = f"Hmm, I seem to be having trouble finding that specific information right now. I'll ask a human colleague to take a look for you. {handoff_marker}"

    # Check cache first for faster response, but only for specific questions, not context-dependent words
    # Skip cache for short, context-dependent responses like "yes", "no", "ok", etc.
    should_use_cache = len(user_message.strip()) > 10 and not user_message.lower().strip() in ['yes', 'no', 'ok', 'sure', 'yeah', 'yep', 'nope', 'thanks', 'thank you']
    
    if should_use_cache:
        cached_response = get_cached_response(kb_id, user_message)
        if cached_response:
            logger.info(f"Using cached response for kb_id: {kb_id}")
            return ChatResponse(
                content=cached_response["response"],
                type="answer",
                kb_id=kb_id
            )

    try:
        # --- Memory Management (Load from DB) ---
        print(f"Loading conversation history for conversation_id: {request.conversation_id} from DB...")
        # Use conversation_id instead of kb_id to get conversation-specific history
        db_history = db_manager.get_conversation_history(request.conversation_id)
        print(f"DB history for conversation {request.conversation_id}: {db_history}")

        # Create a new memory instance for this request
        memory = ConversationBufferMemory(
            memory_key="chat_history", return_messages=True
        )

        # Populate memory from DB history
        for msg in db_history:
            if msg.get("message_type") == "human":
                memory.chat_memory.add_user_message(msg.get("content", ""))
            elif msg.get("message_type") == "ai":
                memory.chat_memory.add_ai_message(msg.get("content", ""))

        print(
            f"Populated memory for kb_id: {kb_id} with {len(db_history)} messages from DB."
        )
        # --- End Memory Management ---

        # Instantiate the agent executor for this KB, passing the populated memory
        print(f"Creating agent executor with memory for kb_id: {kb_id}")
        agent_executor = agent_manager.create_agent_executor(kb_id=kb_id, memory=memory, customer_context=customer_context)
        print(f"Agent executor created successfully for kb_id: {kb_id}")

        # --- Format History for Prompt ---
        memory_variables = memory.load_memory_variables({})
        history_string = memory_variables.get("chat_history", "")
        if not isinstance(history_string, str):
            formatted_history = []
            for msg in history_string:
                if isinstance(msg, HumanMessage):
                    formatted_history.append(f"Human: {msg.content}")
                elif isinstance(msg, AIMessage):
                    formatted_history.append(f"AI: {msg.content}")
            history_string = "\n".join(formatted_history)

        # --- Prepare Agent Input ---
        input_data = {"input": user_message, "chat_history": history_string}

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
                # Apply automatic handoff detection for insufficient answers
                cleaned_output = auto_add_handoff_if_needed(cleaned_output)
                
                final_content = cleaned_output  # Start with the agent's cleaned output
                response_type = "answer"

                print(f"cleaned output: {cleaned_output}")

                if handoff_marker in cleaned_output:
                    print(f"Handoff triggered by agent marker for {kb_id}.")
                    final_content = cleaned_output.replace(handoff_marker, "").strip()
                    response_type = "handoff"
            else:
                # Agent finished but output was invalid/empty
                print(
                    f"Agent output was invalid or empty for {kb_id}. Using generic error."
                )
                response_type = "error"
                final_content = generic_error_msg  # Use the generic error message
                # Setting cleaned_output to None ensures DB saving logic treats it as error
                cleaned_output = None

        # --- Handle Specific Agent Execution Errors ---
        except Exception as agent_exec_err:
            # Catch other potential errors during agent execution itself
            print(f"Error during agent execution for {kb_id}: {agent_exec_err}")
            import traceback

            traceback.print_exc()
            response_type = "error"  # Treat as general error
            final_content = generic_error_msg
            cleaned_output = None  # Ensure it's treated as error for DB saving

        # --- Save Interaction to DB ---
        print(f"DEBUG: Attempting to save interaction for conversation {request.conversation_id}...")
        # Always save user message
        if store_history:
            save_user_success = db_manager.add_conversation_message(
                request.conversation_id, "human", user_message
            )
            if not save_user_success:
                print(f"Warning: Failed to save user message to DB for conversation: {request.conversation_id}")

        # Save AI message based on response_type and content
        if store_history and response_type != "error":
            # Determine content to save: use cleaned_output if it exists (it will contain the marker on handoff)
            # Otherwise, use final_content (which might be the generic error if cleaning failed)
            content_to_save = (
                cleaned_output if cleaned_output is not None else final_content
            )
            print(
                f"DEBUG: Saving AI message. Type='{response_type}', Saved Content='{content_to_save}'"
            )
            save_ai_success = db_manager.add_conversation_message(
                request.conversation_id, "ai", content_to_save
            )
            if not save_ai_success:
                print(f"Warning: Failed to save AI message to DB for conversation: {request.conversation_id}")
        else:  # If response_type IS error
            print(
                f"DEBUG: Skipping save for AI message due to response_type='{response_type}'."
            )
            # Optionally save an error placeholder? For now, just skipping.

        # --- Cache successful responses ---
        # Only cache responses for specific questions, not context-dependent words
        if response_type == "answer" and final_content and "(needs help)" not in final_content and should_use_cache:
            set_cached_response(kb_id, user_message, final_content)
            
        # --- Return Response ---
        # Return the final_content (which has marker removed for handoffs)
        print(
            f"DEBUG: Returning ChatResponse. final_content='{final_content}', response_type='{response_type}'"
        )
        return ChatResponse(content=final_content, type=response_type)

    # --- Catch Errors Outside Agent Execution (e.g., memory loading, setup) ---
    except Exception as e:
        import traceback

        print(
            f"Critical error in HTTP chat endpoint setup/outside agent execution for {kb_id}: {e}\n{traceback.format_exc()}"
        )
        # Return a generic error via HTTPException, don't save anything
        raise HTTPException(
            status_code=500, detail=f"Error processing chat request: {str(e)}"
        )


@router.post("/conversations/human_response", response_model=StatusResponse)
async def human_response_endpoint(request: HumanResponseRequest):
    """
    Receives a human response after a handoff, adds it to the conversation history,
    and optionally updates the KB.
    """
    print(f"Received human response for conversation: {request.conversation_id}. Update KB: {request.update_kb}")

    # --- Add Human Agent response to conversation history FIRST ---
    # We do this regardless of whether KB is updated, to keep the chat flow intact.
    if request.human_response and request.human_response.strip():
        print(f"Adding human agent response to history for conversation {request.conversation_id}...")
        history_save_success = db_manager.add_conversation_message(
            conversation_id=request.conversation_id,
            message_type="human_agent",  # Differentiate from end-user ('human')
            content=request.human_response,
        )
        if not history_save_success:
            # Log a warning but don't necessarily fail the whole request
            print(
                f"Warning: Failed to save human agent response to conversation history for conversation {request.conversation_id}. Continuing..."
            )
    else:
        print(
            f"No human agent response content provided to add to history for conversation {request.conversation_id}."
        )
        # Decide if this should be an error or just proceed.
        # For now, proceed, but the frontend should ideally validate this.

    # --- Handle KB Update (Optional) ---
    kb_update_message = "Knowledge base not updated."
    if request.update_kb:
        # Get kb_id from the conversation
        conversation_response = (
            supabase.table("conversations")
            .select("bot_id")
            .eq("id", request.conversation_id)
            .execute()
        )
        if not conversation_response.data:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        bot_id = conversation_response.data[0]["bot_id"]
        bot_response = supabase.table("bots").select("kb_id").eq("id", bot_id).execute()
        if not bot_response.data:
            raise HTTPException(status_code=404, detail="Bot not found")
        
        kb_id = bot_response.data[0]["kb_id"]
        
        print(f"Attempting to update KB {kb_id} with human-provided text...")
        try:
            # Determine which text to use for KB update
            text_for_kb = (
                request.kb_update_text
                if request.kb_update_text
                else request.human_response
            )

            if not text_for_kb or not text_for_kb.strip():
                print(
                    f"No valid text provided for KB update. KB {kb_id} was not updated."
                )
                kb_update_message = (
                    "Knowledge base was not updated (no valid text provided)."
                )
                # Note: We still return success below because the response *was* received and added to history.
            else:
                # Use the existing KBManager function to add the response, passing metadata
                from datetime import datetime
                source_name = f"Human response - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                success = kb_manager.add_to_kb(
                    kb_id=kb_id,
                    text_to_add=text_for_kb,
                    metadata={"source": "human_verified"},
                    knowledge_source="human conversation",
                    source_name=source_name
                )
                if success:
                    print(f"Successfully updated KB {kb_id} with human response.")
                    kb_update_message = "Knowledge base updated."
                    # --- Log the update ---
                    log_success = db_manager.log_kb_update(kb_id, text_for_kb)
                    if not log_success:
                        print(
                            f"Warning: Failed to log KB update for {kb_id} after successful addition."
                        )
                    # --- End Log ---
                else:
                    # add_to_kb might return False if text is empty after stripping
                    print(
                        f"Failed to update KB {kb_id} (add_to_kb returned False). Response was not added."
                    )
                    kb_update_message = (
                        "Knowledge base was not updated (failed to add)."
                    )

        except Exception as e:
            print(f"Error updating KB {kb_id} with human response: {e}")
            # Log traceback
            import traceback

            traceback.print_exc()
            # We don't raise HTTPException here anymore, as the primary goal (receiving response)
            # might have succeeded. We'll return a success status but report the KB issue in the message.
            kb_update_message = (
                f"Failed to update knowledge base due to error: {str(e)}"
            )
    else:
        # If update_kb is false
        print(
            f"Human response received for conversation: {request.conversation_id}. KB not updated (update_kb={request.update_kb})."
        )
        # kb_update_message remains "Knowledge base not updated."

    # Return overall success status for receiving the response
    final_message = f"Human response received and added to history. {kb_update_message}"
    return StatusResponse(status="success", message=final_message)


@router.post("/conversations/human-chat", response_model=StatusResponse)
async def human_chat_endpoint(request: HumanChatRequest):
    """
    Endpoint for human agents to respond to conversations.
    This only adds the response to the chat history.
    """
    print(f"Received human chat response for conversation: {request.conversation_id}")

    if not request.message or not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    # Add message to conversation history
    history_save_success = db_manager.add_conversation_message(
        conversation_id=request.conversation_id, message_type="human_agent", content=request.message
    )

    if not history_save_success:
        raise HTTPException(
            status_code=500, detail="Failed to save message to conversation history"
        )

    return StatusResponse(
        status="success", message="Human agent response added to conversation history"
    )


@router.post("/agents/{kb_id}/human-knowledge", response_model=StatusResponse)
async def human_knowledge_endpoint(kb_id: str, request: HumanKnowledgeRequest):
    """
    Endpoint for human agents to add verified knowledge to the KB.
    This only updates the knowledge base, not the chat history.
    """
    print(f"Received human knowledge addition for kb_id: {kb_id}")

    if not request.knowledge_text or not request.knowledge_text.strip():
        raise HTTPException(status_code=400, detail="Knowledge text cannot be empty")

    try:
        # Prepare metadata, only including conversation_id if it's not None
        metadata_dict = {"source": "human_verified"}
        if request.source_conversation_id:
            metadata_dict["conversation_id"] = request.source_conversation_id

        # Add to knowledge base with potentially filtered metadata
        from datetime import datetime
        source_name = f"Chat verification - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        success = kb_manager.add_to_kb(
            kb_id=kb_id,
            text_to_add=request.knowledge_text,
            metadata=metadata_dict,  # Pass the constructed dictionary
            knowledge_source="human conversation",
            source_name=source_name
        )

        if not success:
            # Check kb_manager logs for specific reasons why add_to_kb might fail
            print(f"kb_manager.add_to_kb returned False for KB {kb_id}")
            raise HTTPException(
                status_code=500,
                detail="Failed to add knowledge to the knowledge base (internal KB error)",
            )

        # Log the KB update
        log_success = db_manager.log_kb_update(kb_id, request.knowledge_text)
        if not log_success:
            # Log warning but don't fail the request
            print(f"Warning: Failed to log KB update for {kb_id}")

        return StatusResponse(
            status="success",
            message="Knowledge successfully added to the knowledge base",
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
                detail=f"Failed to add knowledge to knowledge base: Metadata type error - {str(e)}",
            )
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to add knowledge to knowledge base: {str(e)}",
            )


@router.get("/conversations/{conversation_id}/history", response_model=ChatHistoryResponse)
async def get_chat_history_endpoint(conversation_id: str):
    """
    Retrieves the conversation history for a specific conversation.
    History is returned ordered by timestamp (oldest first).
    """
    print(f"Received request to get conversation history for conversation: {conversation_id}")
    try:
        # Retrieve history from the database manager
        db_history_raw = db_manager.get_conversation_history(conversation_id)

        # Convert raw DB results (list of dicts) into HistoryMessage objects
        history_messages = [
            HistoryMessage(
                type=msg.get("message_type", "unknown"),
                content=msg.get("content", ""),
                timestamp=msg.get("timestamp"),  # Pass timestamp along
            )
            for msg in db_history_raw
        ]

        print(f"Retrieved {len(history_messages)} messages for conversation {conversation_id} history.")

        return ChatHistoryResponse(conversation_id=conversation_id, history=history_messages)

    except Exception as e:
        print(f"Error retrieving conversation history for conversation {conversation_id}: {e}")
        import traceback

        traceback.print_exc()
        # Consider if a 404 is more appropriate if conversation_id potentially doesn't exist
        # For now, assuming any error is a 500
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve conversation history: {str(e)}"
        )


@router.delete(
    "/conversations/{conversation_id}/history",
    response_model=StatusResponse,
    status_code=status.HTTP_200_OK,
)
async def delete_chat_history_endpoint(conversation_id: str):
    """
    Deletes all stored conversation history for a specific conversation.
    """
    print(f"Received request to DELETE conversation history for conversation: {conversation_id}")
    try:
        # Call the database manager function to delete history
        success = db_manager.delete_conversation_history(conversation_id)

        if success:
            # Return a success status
            return StatusResponse(
                status="success",
                message=f"Conversation history for conversation {conversation_id} deleted successfully.",
            )
        else:
            # If the DB function returns False, it indicates an internal error
            raise HTTPException(
                status_code=500,
                detail=f"Failed to delete conversation history for conversation {conversation_id} due to an internal error.",
            )

    except Exception as e:
        # Catch any other unexpected errors
        print(f"Unexpected error during history deletion for conversation {conversation_id}: {e}")
        import traceback

        traceback.print_exc()
        raise HTTPException(
            status_code=500, detail=f"Failed to delete conversation history: {str(e)}"
        )


@router.get("/conversations", response_model=ListConversationsResponse)
async def list_conversations_endpoint():
    """
    Lists all conversations grouped by knowledge base,
    with preview information and handoff status.
    Used by the human desk interface to show conversations requiring attention.
    """
    print("Received request to list all conversations with handoff status")
    try:
        # Get all conversations from the database
        conversations_response = supabase.table("conversations").select("*, bots(kb_id, name)").execute()
        
        # Initialize response list
        conversations_list = []
        
        # Group conversations by kb_id
        kb_conversations = {}
        
        for conv in conversations_response.data:
            if not conv.get("bots") or not conv["bots"].get("kb_id"):
                continue
                
            kb_id = conv["bots"]["kb_id"]
            kb_name = conv["bots"].get("name", "Unknown KB")
            
            # Get conversation history for this specific conversation
            history = db_manager.get_conversation_history(conv["id"])
            
            # Skip if no history exists
            if not history or len(history) == 0:
                continue
            
            # Count total messages
            message_count = len(history)
            
            # Get the last message for preview
            last_message = history[-1]
            last_message_timestamp = last_message.get(
                "timestamp", datetime.datetime.now()
            )
            last_message_content = last_message.get("content", "")
            
            # Create a short preview (first 50 chars)
            preview = (
                last_message_content[:50] + "..."
                if len(last_message_content) > 50
                else last_message_content
            )
            
            # Determine if handoff is needed
            needs_attention = False
            if conv.get("status") == "human":
                needs_attention = True
            elif last_message.get("message_type") == "ai":
                content = last_message.get("content", "")
                if "(needs help)" in content:
                    needs_attention = True
            
            # Create conversation preview for this specific conversation
            conversation_preview = ConversationPreview(
                last_message_timestamp=last_message_timestamp,
                last_message_preview=preview,
                message_count=message_count,
                needs_human_attention=needs_attention,
            )
            
            # Group by kb_id for the response
            if kb_id not in kb_conversations:
                kb_conversations[kb_id] = {
                    "kb_id": kb_id,
                    "name": kb_name,
                    "conversations": []
                }
            
            kb_conversations[kb_id]["conversations"].append(conversation_preview)
        
        # Convert to response format (for now, just take the latest conversation per KB)
        for kb_data in kb_conversations.values():
            if kb_data["conversations"]:
                # Sort by timestamp and get the most recent
                latest_conv = max(kb_data["conversations"], key=lambda x: x.last_message_timestamp)
                conversations_list.append(
                    KBConversationGroup(
                        kb_id=kb_data["kb_id"],
                        name=kb_data["name"],
                        conversation=latest_conv
                    )
                )
        
        return ListConversationsResponse(conversations=conversations_list)
        
    except Exception as e:
        print(f"Error listing conversations: {e}")
        import traceback
        
        traceback.print_exc()
        raise HTTPException(
            status_code=500, detail=f"Failed to list conversations: {str(e)}"
        )


@router.post("/bots/{bot_id}/chat_human")
async def bot_chathuman_endpoint(request: ChatRequest, user=Depends(get_current_user)):
    if not user:
        return {"detail": "authentication error"}
    return post_message(request.conversation_id, request.message, "human")


@router.post("/bots/{bot_id}/chat", response_model=ChatResponse)
async def bot_chat_endpoint(bot_id: str, request: ChatRequest):
    """
    HTTP endpoint for stateful, non-streaming chat interactions with a bot,
    maintaining conversation history using the database.
    """
    print(f"Received HTTP chat request for bot_id: {bot_id}")

    add_user_message_response = (
        supabase.table("messages")
        .insert(
            {
                "conversation_id": request.conversation_id,
                "role": "user",
                "content": request.message,
                "reply_to_message_id": request.reply_to_message_id,
            }
        )
        .execute()
    )

    # Broadcast the user message to all connected clients
    if request.conversation_id in active_connections and add_user_message_response.data:
        user_message_id = add_user_message_response.data[0]["id"]
        for connection in active_connections[request.conversation_id]:
            try:
                await connection.send_json({
                    "type": "message",
                    "id": user_message_id,
                    "content": request.message,
                    "role": "user",
                    "reply_to_message_id": request.reply_to_message_id,
                    "timestamp": datetime.now().isoformat()
                })
            except Exception as e:
                print(f"Error sending user message to websocket: {e}")

    # Fetch bot and conversation data concurrently for better performance
    bot_task = supabase.table("bots").select("*").eq("id", bot_id).execute()
    conversation_task = supabase.table("conversations").select("*").eq("id", request.conversation_id).execute()
    
    # Process bot data
    response = bot_task
    bots_data = response.data[0]
    user_id = bots_data["user_id"]
    print(user_id, "user_id")
    kb_id = bots_data["kb_id"]

    # Get user data and conversation data
    userData = supabase.auth.admin.get_user_by_id(user_id)
    company_email = userData.user.email
    print(userData, "user_data")
    
    conversation_repsonse = conversation_task
    print(f"status is {conversation_repsonse.data}")
    if conversation_repsonse.data and len(conversation_repsonse.data) > 0:
        status = conversation_repsonse.data[0]["status"]
        # Extract customer context and bot info for the agent
        customer_context = {
            "customer_name": conversation_repsonse.data[0].get("customer_name"),
            "customer_email": conversation_repsonse.data[0].get("customer_email"),
            "customer_phone": conversation_repsonse.data[0].get("customer_phone"),
            "bot_name": bots_data.get("name", "Assistant"),  # Use bot's name
            "company_name": bots_data.get("company", "our company")  # Use bot's company
        }
        if status == "human":
            client = redisConnection.client
            if client:
                #check if the bot is online
                bot_online = client.get(f"bot:{bot_id}")
                print(bot_online, "bot_online----")
            if bot_online is None:
                notify_admin_on_user_message(
                    conversation_repsonse.data[0]["customer_name"],
                    conversation_repsonse.data[0]["customer_email"],
                    request.message,
                    request.conversation_id,
                    company_email,
                    bot_id  # Pass the bot_id parameter
                )
                return {
                "content": "Seems like no one is online to help you at the moment. But our team has been notified and will get back to you as soon as possible.",
                }
            else:
                return {
                "content": "",
                }
        # If conversation is closed, update it to "ai"
        if status == "closed":
            supabase.table("conversations").update({"status": "ai"}).eq(
                "id", request.conversation_id
            ).execute()
    # now use all logic from /agents/{kb_id}/chat endpoint
    response = await chat_endpoint(
        kb_id,
        request,
        store_history=False,  # Prevent duplicate DB insert – we already saved the user row above
        customer_context=customer_context if 'customer_context' in locals() else None,
    )

    # save user's message and bot's response to supabase
    bot_message_response = supabase.table("messages").insert(
        {
            "conversation_id": request.conversation_id,
            "role": "bot",
            "content": response.content,
        }
    ).execute()

    # Broadcast message to all connected clients
    if request.conversation_id in active_connections:
        print(f"Broadcasting to {len(active_connections[request.conversation_id])} connections for conversation_id {request.conversation_id}")
        content = response["content"] if isinstance(response, dict) else getattr(response, "content", "")
        message_id = bot_message_response.data[0]["id"] if bot_message_response.data else None
        for connection in active_connections[request.conversation_id]:
            try:
                await connection.send_json({
                    "type": "message",
                    "id": message_id,  # Add the DB id for dedupe
                    "content": content,
                    "role": "bot",
                    "timestamp": datetime.now().isoformat()
                })
            except Exception as e:
                print(f"Error sending message to websocket: {e}")

    # conversation_count = db_manager.get_conversation_count(user_id)
    # message_count = db_manager.get_message_count(user_id)
    # if conversation_count is not None and message_count is not None:
    #     if conversation_count >= 20 or message_count >= 100:
    #         print("The bad return")
    #         return {
    #             "content": "",
    #         }

    # if response.type == "handoff", update the user's message to status 'handoff'
    if response.type == "handoff":
        print("is a clean handoff------>", response)
        client = redisConnection.client
        if client:
            bot_online = client.get(f"bot:{bot_id}")
            print(bot_online, "bot_online")
            if bot_online is None:
                notify_admin_on_user_message(
                    conversation_repsonse.data[0]["customer_name"],
                    conversation_repsonse.data[0]["customer_email"],
                    request.message,
                    request.conversation_id,
                    company_email,
                    bot_id  # Pass the bot_id parameter
                )
        supabase.table("handover_requests").insert(
            {
                "conversation_id": request.conversation_id,
                "last_message_id": add_user_message_response.data[0]["id"],
            }
        ).execute()

        supabase.table("conversations").update({"status": "human"}).eq(
            "id", request.conversation_id
        ).execute()

        # Update the user's message to status 'handoff'
        supabase.table("messages").update({
            "status": "handoff"
        }).eq("id", add_user_message_response.data[0]["id"]).execute()

        

        # Broadcast message update to all clients so UI can update color immediately
        if request.conversation_id in active_connections:
            for connection in active_connections[request.conversation_id]:
                try:
                    await connection.send_json({
                        "type": "message_update",
                        "message_id": add_user_message_response.data[0]["id"],
                        "status": "handoff"
                    })
                except Exception as e:
                    print(f"Error sending message update to websocket: {e}")

        # sending a notification to the bot admin
        result = supabase.table("bots").select("*").eq("id", bot_id).single().execute()

        if result.data:  # ✅ Check if data exists
            user_id = result.data["user_id"]  # ✅ Access dict key
            print(user_id, "userid")
            result = (
                supabase.table("anon_push_subscriptions")
                .select("*")
                .eq("user_id", user_id)
                .execute()
            )
            print("result anon", result)
            if result.data and len(result.data) > 0:
                for data in result.data:
                    sub_obj = json.loads(data["subscription"])
                    send_push_notification(
                        sub_obj,
                        "Support Required",
                        "A new user has request for human support",
                    )
                    print(
                        f"msg: Result for {data['user_id']} is ready and push notification is been sent"
                    )
        else:
            print("Bot not found or query failed")
        # Fetch current value
        resp = supabase.table("conversations").select("handoff_requests").eq("id", request.conversation_id).single().execute()
        current = resp.data["handoff_requests"] if resp.data and "handoff_requests" in resp.data else 0

        # Increment (or decrement, clamp to >= 0)
        new_value = max(current + 1, 0)  # or max(current - 1, 0) for decrement

        # Update
        supabase.table("conversations").update({"handoff_requests": new_value}).eq("id", request.conversation_id).execute()
        return response


async def bot_chat_websocket_endpoint(bot_id: str, request: ChatRequest, websocket: WebSocket):
    """
    WebSocket-based bot chat endpoint for real-time response delivery.
    """
    logger.info(f"Starting WebSocket chat for bot_id: {bot_id}, conversation: {request.conversation_id}")
    
    try:
        # Save user message first
        add_user_message_response = (
            supabase.table("messages")
            .insert({
                "conversation_id": request.conversation_id,
                "role": "user",
                "content": request.message,
                "reply_to_message_id": request.reply_to_message_id,
            })
            .execute()
        )
        
        # Broadcast user message to all connections
        if add_user_message_response.data:
            user_message_id = add_user_message_response.data[0]["id"]
            await broadcast_to_all_connections(request.conversation_id, {
                "type": "message",
                "id": user_message_id,
                "content": request.message,
                "role": "user",
                "reply_to_message_id": request.reply_to_message_id,
                "timestamp": datetime.now().isoformat()
            })

        # ENFORCE SUBSCRIPTION LIMITS before AI responds (user message is always saved)
        await enforce_subscription_limits(bot_id, request.conversation_id)
        
        # Get bot and KB info
        bot_response = supabase.table("bots").select("*").eq("id", bot_id).execute()
        if not bot_response.data:
            await websocket.send_json({"type": "error", "content": "Bot not found"})
            return
            
        bot_data = bot_response.data[0]
        kb_id = bot_data["kb_id"]
        user_id = bot_data["user_id"]
        
        # Get conversation context
        conversation_response = (
            supabase.table("conversations")
            .select("*")
            .eq("id", request.conversation_id)
            .execute()
        )
        
        if not conversation_response.data:
            await websocket.send_json({"type": "error", "content": "Conversation not found"})
            return
            
        # Get chat response using the standard chat endpoint
        import time
        start_time = time.time()
        logger.info(f"Starting AI processing for message: '{request.message[:50]}...'")
        
        response = await chat_endpoint(
            kb_id,
            request,
            store_history=False,
            customer_context={
                "customer_name": conversation_response.data[0].get("customer_name"),
                "customer_email": conversation_response.data[0].get("customer_email"),
                "customer_phone": conversation_response.data[0].get("customer_phone"),
                "bot_name": bot_data.get("name", "Assistant"),
                "company_name": bot_data.get("company", "our company")
            }
        )
        
        processing_time = time.time() - start_time
        logger.info(f"AI processing completed in {processing_time:.2f} seconds")
        
        # Determine message status based on response type
        is_handoff = response.type == "handoff"
        logger.info(f"Bot response received: content='{response.content[:100]}...', type='{response.type}', handoff_triggered='{is_handoff}'")
        
        # Save the complete bot response to database (bot messages don't get handoff status)
        bot_message_response = supabase.table("messages").insert({
            "conversation_id": request.conversation_id,
            "role": "bot",
            "content": response.content,
            "status": None  # Bot messages don't get handoff status
        }).execute()
        logger.info(f"Bot message saved to database: {bot_message_response.data[0]['id'] if bot_message_response.data else 'FAILED'}")
        
        # Handle handoff workflow if triggered - update the USER message that caused the handoff
        if is_handoff:
            logger.info(f"Handoff triggered for conversation {request.conversation_id} - updating user message status")
            await handle_handoff_triggered(request.conversation_id)
            
            # Update the user message that triggered this handoff to have handoff status
            if add_user_message_response.data:
                user_message_id = add_user_message_response.data[0]["id"]
                logger.info(f"Updating user message {user_message_id} with handoff status")
                supabase.table("messages").update({
                    "status": "handoff"
                }).eq("id", user_message_id).execute()
                logger.info(f"User message {user_message_id} updated with handoff status")
                
                # Broadcast the user message status update to frontend
                await broadcast_to_all_connections(request.conversation_id, {
                    "type": "message_update",
                    "message_id": user_message_id,
                    "status": "handoff"
                })
        
        # Cache the response for future use
        set_cached_response(kb_id, request.message, response.content)
        
        # Broadcast message to all connections with correct event type
        if bot_message_response.data:
            message_data = {
                "type": "message",
                "id": bot_message_response.data[0]["id"],
                "content": response.content,
                "role": "bot",
                "status": None,  # Bot messages don't get handoff status
                "timestamp": datetime.now().isoformat()
            }
            logger.info(f"Broadcasting bot message to conversation {request.conversation_id}: {len(active_connections.get(request.conversation_id, []))} connections")
            await broadcast_to_all_connections(request.conversation_id, message_data)
        else:
            logger.error(f"Failed to save bot message to database for conversation {request.conversation_id}")
                
    except Exception as e:
        logger.error(f"Error in WebSocket chat: {e}")
        await broadcast_to_all_connections(request.conversation_id, {
            "type": "error",
            "content": "An error occurred while processing your request"
        })


@router.post(
    "/bots/{bot_id}/conversations", response_model=CreateBotConversationResponse
)
async def create_bot_conversation_endpoint(
    bot_id: str,
    customer_email: str = Query(None),
    customer_name: str = Query(None),
    request_body: dict = Body(None),
):
    """
    Creates a new conversation for a bot.
    Accepts customer_email and customer_name either as query parameters or in the request body.
    """
    print(f"Received request to create a new conversation for bot_id: {bot_id}")

    # Get values from either query params or request body
    if request_body:
        if not customer_email:
            customer_email = request_body.get("customer_email")

        if not customer_name:
            customer_name = request_body.get("customer_name")

    if not customer_email or not customer_name:
        raise HTTPException(
            status_code=400, detail="customer_email and customer_name are required"
        )

    try:
        from app.core.supabase_client import supabase

        # Convert datetime to ISO format string for JSON serialization
        current_time = datetime.now().isoformat()

        # Create the data payload
        data = {
            "bot_id": bot_id,
            "customer_email": customer_email,
            "customer_name": customer_name,
            "created_at": current_time,
        }

        # Make the Supabase API call
        response = supabase.table("conversations").insert(data).execute()

        # Check if we have data in the response
        if not response.data or len(response.data) == 0:
            raise HTTPException(
                status_code=500,
                detail="Failed to create conversation: No data returned from Supabase",
            )

        # Add to CRM if not present
        first_name, last_name = None, None
        if customer_name:
            parts = customer_name.split(" ", 1)
            first_name = parts[0]
            last_name = parts[1] if len(parts) > 1 else ""
        ensure_crm_entry(
            bot_id=bot_id,
            first_name=first_name,
            last_name=last_name,
            email=customer_email
        )

        return CreateBotConversationResponse(
            conversation_id=response.data[0]["id"],
            created_at=response.data[0]["created_at"],
            customer_email=response.data[0]["customer_email"],
            customer_name=response.data[0]["customer_name"],
        )
    except Exception as e:
        import traceback

        error_detail = str(e)
        error_traceback = traceback.format_exc()
        print(f"Error creating conversation: {error_detail}")
        print(f"Traceback: {error_traceback}")
        raise HTTPException(
            status_code=500, detail=f"Failed to create conversation: {error_detail}"
        )


@router.get(
    "/bots/{bot_id}/conversations", response_model=PaginatedListBotConversationsResponse
)
async def list_bot_conversations_endpoint(
    bot_id: str,
    filter: str = Query(
        None, description="Filter by status (open, my, unassigned, closed)"
    ),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(10, ge=1, le=100, description="Number of items per page"),
):
    """
    Lists all conversations for a specific bot with pagination.

    Parameters:
    - page: Page number (starts at 1)
    - page_size: Number of items per page (default 10, max 100)
    """
    print(
        f"Received request to list conversations for bot_id: {bot_id}, page: {page}, page_size: {page_size}"
    )

    try:
        from app.core.supabase_client import supabase

        # Calculate range for pagination
        start = (page - 1) * page_size
        end = start + page_size - 1

        # Get total count first
        count_response = (
            supabase.table("conversations")
            .select("id", count="exact")
            .eq("bot_id", bot_id)
            .execute()
        )
        total_count = count_response.count if hasattr(count_response, "count") else 0

        # Use the view that already contains the last message for every conversation
        query = supabase.table("conversations_last_message").select("*").eq("bot_id", bot_id)

        print("conversations------>", query)

        # Map filter values to status values
        filter_map = {
            "open": "*",
            "my": "human",
            "unassigned": "ai",
            "closed": "closed",
        }

        if filter and filter != "open":
            query = query.eq("status", filter_map[filter])
        if filter == "open":
            query = query.neq("status", "closed")

        # Get paginated data
        response = query.order("created_at", desc=True).execute()

        # Calculate total pages
        total_pages = math.ceil(total_count / page_size) if total_count > 0 else 1

        conversations = response.data  # Last message fields already included by the view

        return PaginatedListBotConversationsResponse(
            conversations=conversations,
            total_count=total_count,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    except Exception as e:
        print(f"Error listing conversations: {e}")
        import traceback

        traceback.print_exc()
        raise HTTPException(
            status_code=500, detail=f"Failed to list conversations: {str(e)}"
        )


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=PaginatedListMessagesResponse,
)
async def list_messages_endpoint(
    conversation_id: str,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(100, ge=1, le=100, description="Number of items per page"),
):
    """
    Lists all messages for a specific conversation with pagination.
    """
    print(
        f"Received request to list messages for conversation_id: {conversation_id}, page: {page}, page_size: {page_size}"
    )

    try:
        client = redisConnection.client
        if client:
            client.set(conversation_id, ONLINE, ex=EXPIRY_STATUS_TIME)

        # Calculate range for pagination
        start = (page - 1) * page_size
        end = start + page_size - 1

        # Get total count first
        count_response = (
            supabase.table("messages")
            .select("id", count="exact")
            .eq("conversation_id", conversation_id)
            .execute()
        )
        total_count = count_response.count if hasattr(count_response, "count") else 0

        # Get paginated data
        response = (
            supabase.table("messages")
            .select("*")
            .eq("conversation_id", conversation_id)
            .order("created_at", desc=True)
            .range(start, end)
            .execute()
        )

        # Calculate total page
        total_pages = math.ceil(total_count / page_size) if total_count > 0 else 1

        return PaginatedListMessagesResponse(
            messages=response.data,
            total_count=total_count,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    except Exception as e:
        print(f"Error listing messages: {e}")
        import traceback

        traceback.print_exc()
        raise HTTPException(
            status_code=500, detail=f"Failed to list messages: {str(e)}"
        )


@router.get("/bot_id/{conversation_id}")
def get_bot_id_from_conversation_id(conversation_id: str):
    try:
        conversation_response = (
            supabase.table("conversations")
            .select("*")
            .eq("id", conversation_id)
            .execute()
        )
        return conversation_response.data[0]["bot_id"]
    except Exception:
        return ""


@router.post("/send-msg-demobot", response_model=ChatResponse)
async def send_message_to_demo_bot(request: DemoChatRequest):
    """
    Endpoint for sending messages to a demo bot associated with a specific URL.
    The endpoint will:
    1. Find the demo bot's knowledge base using the URL
    2. Process the message using the AI
    3. Return the response
    """
    try:

        #get the domain from the url
        domain = str(request.url).replace("https://", "").replace("http://", "").replace("www.", "").replace("/", "")
        
        # 1. Get the demo bot's kb_id from the URL
        demo_bot_response = supabase.table("demo_bots").select("kb_id").eq("url", domain).execute()
        
        if not demo_bot_response.data or len(demo_bot_response.data) == 0:
            raise HTTPException(
                status_code=404,
                detail=f"No demo bot found for URL: {request.url}"
            )
        
        kb_id = demo_bot_response.data[0]["kb_id"]
        
        # 2. Create a ChatRequest for the existing chat endpoint
        chat_request = ChatRequest(
            message=request.message,
            conversation_id=f"demo_{kb_id}"  # Use a consistent conversation ID for demo bots
        )
        
        # 3. Use the existing chat endpoint logic
        response = await chat_endpoint(kb_id, chat_request)
        
        # 4. If the response is a handoff, add the additional message
        if response.type == "handoff":
            handoff_message = (
                "\n\nOur AI was not able to answer this and this is where a human hand off would be triggered - "
                "some one from your team can respond to the user and add this information to the knowledge base. "
                "Sign up for a free trail to fully experience the Magic of deskForce ✨😃"
            )
            response.content = response.content + handoff_message
        
        return response
        
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        print(f"Error processing demo bot message: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process message: {str(e)}"
        )

async def handle_user_chat(conversation_id: str, message: str, user_id: str = None, reply_to_message_id: str = None):
    """
    Handles a user (widget) message: inserts it into the messages table and updates the conversation.
    """
    from app.core.supabase_client import supabase

    insert_response = supabase.table("messages").insert({
        "conversation_id": conversation_id,
        "content": message,
        "role": "user",
        "read": True,
        "created_at": datetime.utcnow().isoformat(),
        "reply_to_message_id": reply_to_message_id
    }).execute()

    if not insert_response.data:
        raise HTTPException(status_code=500, detail="Failed to insert user message")

    supabase.table("conversations").update({
        "updated_at": datetime.utcnow().isoformat()
    }).eq("id", conversation_id).execute()

    return insert_response.data[0]

@router.websocket("/ws/{conversation_id}")
async def websocket_unified_endpoint(websocket: WebSocket, conversation_id: str):
    print(f"WebSocket connection attempt for conversation {conversation_id}")
    await websocket.accept()
    print(f"WebSocket connection accepted for conversation {conversation_id}")
    
    if conversation_id not in active_connections:
        active_connections[conversation_id] = set()
    active_connections[conversation_id].add(websocket)
    try:
        while True:
            try:
                data = await websocket.receive_json()
            except WebSocketDisconnect:
                print(f"WebSocket disconnected for conversation {conversation_id}")
                break
            except RuntimeError as e:
                if "WebSocket is not connected" in str(e):
                    print(f"WebSocket connection lost for conversation {conversation_id}")
                    break
                raise
            except Exception as e:
                print(f"Error receiving WebSocket data for conversation {conversation_id}: {e}")
                break
            
            # Handle ping/pong for keepalive
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
                continue
            
            # Handle status change request
            if data.get("type") == "change_status" and data.get("status"):
                new_status = data["status"]
                if new_status not in ["ai", "human", "closed"]:
                    await websocket.send_json({"error": "Invalid status"})
                    continue
                    
                # Update conversation status in database
                update_response = supabase.table("conversations").update({
                    "status": new_status
                }).eq("id", conversation_id).execute()
                
                if not update_response.data:
                    await websocket.send_json({"error": "Failed to update status"})
                    continue
                
                # Broadcast status change to all connected clients
                for ws in list(active_connections.get(conversation_id, [])):
                    try:
                        await ws.send_json({
                            "type": "conversation_status",
                            "status": new_status
                        })
                    except Exception as e:
                        print(f"Error sending status update to websocket: {e}")
                        active_connections[conversation_id].remove(ws)
                        if not active_connections[conversation_id]:
                            del active_connections[conversation_id]
                continue

            message = data.get("message")
            reply_to_message_id = data.get("reply_to_message_id")
            if not message:
                await websocket.send_json({"error": "Missing message"})
                continue

            # Get conversation status from DB
            conversation_response = (
                supabase.table("conversations")
                .select("status","bot_id")
                .eq("id", conversation_id)
                .execute()
            )
            status = conversation_response.data[0]["status"]
            bot_id = conversation_response.data[0]["bot_id"] if conversation_response.data else None

             
           

            print("status------>", status)
            print("bot_id------>", bot_id)


            role = data.get('role', 'user')  # Default to 'user' if not provided

            if status == "human":
                if role == "human":
                    # Message from agent - handle_human_chat will save to DB
                    result = await handle_human_chat(conversation_id, message, reply_to_message_id=reply_to_message_id)
                    
                    # Broadcast the human message using the broadcast function
                    message_id = result.get('id')
                    await broadcast_to_all_connections(conversation_id, {
                        "type": "message",
                        "id": message_id,
                        "content": message,
                        "role": "human",
                        "reply_to_message_id": reply_to_message_id,
                        "timestamp": datetime.utcnow().isoformat()
                    })

                    # --- NEW: Check if widget user is online, send email if not ---
                    # Fetch conversation details
                    conversation_details = (
                        supabase.table("conversations")
                        .select("customer_email, bot_id")
                        .eq("id", conversation_id)
                        .single()
                        .execute()
                    )
                    if conversation_details.data:
                        customer_email = conversation_details.data.get("customer_email")
                        bot_id = conversation_details.data.get("bot_id")
                        # Check user online status in Redis
                        client = redisConnection.client
                        user_online = None
                        if client and customer_email and bot_id:
                            user_online = client.get(f"user:{customer_email}:{bot_id}")
                        if not user_online:
                            # Fetch bot/company info
                            bot_data = supabase.table("bots").select("company,user_id").eq("id", bot_id).single().execute()
                            company_name = bot_data.data.get("company") if bot_data.data else ""
                            user_id = bot_data.data.get("user_id") if bot_data.data else None
                            company_email = None
                            if user_id:
                                user_data = supabase.auth.admin.get_user_by_id(user_id)
                                company_email = getattr(user_data.user, "email", None)
                            if company_name and company_email and customer_email:
                                from app.services.send_email import notify_client_message
                                notify_client_message(
                                    company_name,
                                    company_email,
                                    message,
                                    conversation_id,
                                    customer_email
                                )
                    # --- END NEW ---
                else:
                    # Message from user - handle_user_chat will save to DB
                    print("handling user chat------>", message)
                    result = await handle_user_chat(conversation_id, message, reply_to_message_id=reply_to_message_id)
                    
                    # Broadcast the user message using the broadcast function
                    message_id = result.get('id')
                    await broadcast_to_all_connections(conversation_id, {
                        "type": "message",
                        "id": message_id,
                        "content": message,
                        "role": "user",
                        "reply_to_message_id": reply_to_message_id,
                        "timestamp": datetime.utcnow().isoformat()
                    })

                    # Check if bot is online and send email notification if not
                    client = redisConnection.client
                    if client:
                        bot_online = client.get(f"bot:{bot_id}")
                        print(bot_online, "bot_online")
                        if bot_online is None:
                            # Get conversation details for email notification
                            conversation_response = supabase.table("conversations").select("*").eq("id", conversation_id).execute()
                            bot_data = supabase.table("bots").select("company,user_id").eq("id", bot_id).single().execute()
                            
                            company_name = bot_data.data.get("company") if bot_data.data else ""
                            user_id = bot_data.data.get("user_id") if bot_data.data else None
                            company_email = None
                            if user_id:
                                user_data = supabase.auth.admin.get_user_by_id(user_id)
                                company_email = getattr(user_data.user, "email", None)
                            if conversation_response.data:
                                notify_admin_on_user_message(
                                    conversation_response.data[0]["customer_name"],
                                    conversation_response.data[0]["customer_email"],
                                    message,
                                    conversation_id,  # This should be conversation_id, not bot_id
                                    company_email,
                                    bot_id  # Pass bot_id as the new parameter
                                )

                # Note: bot_chat_endpoint will handle broadcasting both user and bot messages with proper IDs
            else:
                # Handle as AI message with streaming support
                from app.models.chat import ChatRequest
                
                # First check cache for quick response, but only for specific questions, not context-dependent words
                if bot_id:
                    bot_data = supabase.table("bots").select("kb_id").eq("id", bot_id).single().execute()
                    kb_id = bot_data.data.get("kb_id") if bot_data.data else None
                    
                    # Skip cache for short, context-dependent responses
                    should_use_cache = len(message.strip()) > 10 and not message.lower().strip() in ['yes', 'no', 'ok', 'sure', 'yeah', 'yep', 'nope', 'thanks', 'thank you']
                    
                    if kb_id and should_use_cache:
                        cached_response = get_cached_response(kb_id, message)
                        if cached_response:
                            # Save cached response to database for consistency
                            logger.info("Using cached response for faster delivery")
                            cached_message_response = supabase.table("messages").insert({
                                "conversation_id": conversation_id,
                                "role": "bot",
                                "content": cached_response["response"],
                            }).execute()
                            
                            # Broadcast cached response to all connections
                            if cached_message_response.data:
                                await broadcast_to_all_connections(conversation_id, {
                                    "type": "message",
                                    "id": cached_message_response.data[0]["id"],
                                    "content": cached_response["response"],
                                    "role": "bot",
                                    "cached": True,
                                    "timestamp": datetime.utcnow().isoformat()
                                })
                            continue
                
                # If no cache, proceed with streaming response
                chat_request = ChatRequest(
                    conversation_id=conversation_id,
                    message=message,
                    reply_to_message_id=reply_to_message_id
                )
                print("chat_request------>, will use WebSocket", chat_request)
                
                # Call WebSocket version for real-time response
                await bot_chat_websocket_endpoint(bot_id, chat_request, websocket)
               
    except WebSocketDisconnect:
        print(f"WebSocket disconnected for conversation {conversation_id}")
    except Exception as e:
        print(f"WebSocket error for conversation {conversation_id}: {e}")
    finally:
        # Always clean up the connection
        if conversation_id in active_connections and websocket in active_connections[conversation_id]:
            active_connections[conversation_id].remove(websocket)
            if not active_connections[conversation_id]:
                del active_connections[conversation_id]

async def handle_human_chat(conversation_id: str, message: str, user_id: str = None, reply_to_message_id: str = None):
    """
    Handles a human agent message: inserts it into the messages table and updates the conversation.
    """
    from app.core.supabase_client import supabase

    # Insert the message
    insert_response = supabase.table("messages").insert({
        "conversation_id": conversation_id,
        "content": message,
        "role": "human",
        "read": True,
        "created_at": datetime.utcnow().isoformat(),
        "reply_to_message_id": reply_to_message_id
    }).execute()

    if not insert_response.data:
        raise HTTPException(status_code=500, detail="Failed to insert human message")

    # Update the conversation's last update time
    supabase.table("conversations").update({
        "updated_at": datetime.utcnow().isoformat()
    }).eq("id", conversation_id).execute()

    return insert_response.data[0]

@router.get("/bots/{bot_id}/conversations/by-email/{email}")
async def get_conversations_by_email(
    bot_id: str = Path(..., description="Bot ID"),
    email: str = Path(..., description="Customer email address")
):
    """
    Returns all conversations for a specific bot and customer email, including the last message for each conversation.
    """
    try:
        from app.core.supabase_client import supabase

        response = (
            supabase.table("conversations")
            .select("*")
            .eq("bot_id", bot_id)
            .eq("customer_email", email)
            .order("created_at", desc=True)
            .execute()
        )

        conversations = response.data if hasattr(response, "data") else []
        # For each conversation, fetch the last message
        for conv in conversations:
            last_msg_resp = (
                supabase.table("messages")
                .select("content,created_at")
                .eq("conversation_id", conv["id"])
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if last_msg_resp.data and len(last_msg_resp.data) > 0:
                conv["last_message"] = last_msg_resp.data[0]["content"]
                conv["last_message_time"] = last_msg_resp.data[0]["created_at"]
            else:
                conv["last_message"] = None
                conv["last_message_time"] = None
        return {"conversations": conversations}
    except Exception as e:
        import traceback
        print(f"Error fetching conversations by email: {e}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to fetch conversations by email")

# Add a new endpoint to resolve a handoff message
@router.post("/messages/{message_id}/resolve")
async def resolve_handoff_message(message_id: str):
    try:
        from app.core.supabase_client import supabase
        print(f"Attempting to resolve handoff message: {message_id}")
        
        # First, find the conversation_id for this message
        msg_resp = supabase.table("messages").select("conversation_id, status").eq("id", message_id).single().execute()
        if not msg_resp.data:
            print(f"Message not found: {message_id}")
            return {"success": False, "error": "Message not found"}
        
        conversation_id = msg_resp.data["conversation_id"]
        current_status = msg_resp.data.get("status")
        print(f"Found message in conversation {conversation_id} with status: {current_status}")
        
        # Update the message status in the DB
        update_resp = supabase.table("messages").update({"status": "handoff_resolved"}).eq("id", message_id).execute()
        if update_resp.data is None:
            print(f"Failed to update message status for {message_id}")
            return {"success": False, "error": "Failed to update message status"}
        
        print(f"Successfully updated message {message_id} to handoff_resolved")
        
        # Broadcast the update to all clients
        print(f"Broadcasting status update for message {message_id}")
        await broadcast_to_all_connections(conversation_id, {
            "type": "message_update",
            "message_id": message_id,
            "status": "handoff_resolved"
        })
        
        # Fetch current handoff_requests value and decrement
        resp = supabase.table("conversations").select("handoff_requests").eq("id", conversation_id).single().execute()
        current = resp.data.get("handoff_requests", 0) if resp.data else 0
        print(f"Current handoff_requests count: {current}")
        
        # Decrement handoff requests count (clamp to >= 0)
        new_value = max(current - 1, 0)
        print(f"Updating handoff_requests to: {new_value}")
        
        # Update the conversation
        supabase.table("conversations").update({"handoff_requests": new_value}).eq("id", conversation_id).execute()
        
        print(f"Successfully resolved handoff for message {message_id}")
        return {"success": True, "message": "Handoff resolved successfully"}
        
    except Exception as e:
        print(f"Error resolving handoff message {message_id}: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": f"Internal server error: {str(e)}"}

@router.get("/conversations/{conversation_id}")
async def get_conversation_status(conversation_id: str):
    """
    Get the status of a conversation by its ID.
    Returns the conversation status (ai, human, or closed).
    """
    try:
        response = (
            supabase.table("conversations")
            .select("status, customer_email")
            .eq("id", conversation_id)
            .execute()
        )
        
        # Check if any rows were returned
        if not response.data or len(response.data) == 0:
            raise HTTPException(
                status_code=404,
                detail=f"Conversation with ID {conversation_id} not found"
            )

        conversation_data = response.data[0]
        print("conversation_data------>", conversation_data)

        return {
            "status": conversation_data["status"],
            "customer_email": conversation_data["customer_email"]
        }

    except HTTPException:
        # Re-raise HTTP exceptions (like 404)
        raise
    except Exception as e:
        print(f"Error fetching conversation status: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch conversation status: {str(e)}"
        )
