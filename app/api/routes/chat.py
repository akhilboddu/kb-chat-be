import asyncio
from fastapi import APIRouter, HTTPException, status
from langchain.memory import ConversationBufferMemory
from langchain_core.messages import HumanMessage, AIMessage

from app.models.chat import (
    ChatRequest, ChatResponse, HumanResponseRequest, 
    HumanChatRequest, HumanKnowledgeRequest, ChatHistoryResponse,
    HistoryMessage, ListConversationsResponse, KBConversationGroup, 
    ConversationPreview
)
from app.models.base import StatusResponse

from app.core import db_manager, kb_manager, agent_manager
from app.utils.text_processing import clean_agent_output

router = APIRouter(tags=["chat"])

@router.post("/agents/{kb_id}/chat", response_model=ChatResponse)
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
        agent_executor = agent_manager.create_agent_executor(kb_id=kb_id, memory=memory) 
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


@router.post("/agents/{kb_id}/human_response", response_model=StatusResponse)
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


@router.post("/agents/{kb_id}/human-chat", response_model=StatusResponse)
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


@router.post("/agents/{kb_id}/human-knowledge", response_model=StatusResponse)
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


@router.get("/agents/{kb_id}/history", response_model=ChatHistoryResponse)
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


@router.delete("/agents/{kb_id}/history", response_model=StatusResponse, status_code=status.HTTP_200_OK)
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


@router.get("/conversations", response_model=ListConversationsResponse)
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


@router.post("/bots/{bot_id}/chat", response_model=ChatResponse)
async def bot_chat_endpoint(bot_id: str, request: ChatRequest):
    """
    HTTP endpoint for stateful, non-streaming chat interactions with a bot,
    maintaining conversation history using the database.
    """
    print(f"Received HTTP chat request for bot_id: {bot_id}")

    from app.core.supabase_client import supabase
    response = supabase.table("bots").select("*").eq("id", bot_id).execute()
    kb_id = response.data[0]["kb_id"]

    # now use all logic from /agents/{kb_id}/chat endpoint
    return await chat_endpoint(kb_id, request)

import datetime  # For timestamp handling 