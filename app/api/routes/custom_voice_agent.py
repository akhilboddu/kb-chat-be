from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse
import asyncio
import logging
import json
import time
from app.core import agent_manager
from app.utils.text_processing import clean_agent_output
from langchain.memory import ConversationBufferMemory
from langchain_core.messages import HumanMessage, AIMessage

logger = logging.getLogger(__name__)
router = APIRouter(tags=["custom-voice-agent"])

async def generate_streaming_response(content: str, stream: bool = True):
    """Generate OpenAI-compatible streaming response"""
    if not stream:
        # Non-streaming response
        yield json.dumps({
            "id": f"chatcmpl-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": "gpt-3.5-turbo",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content
                },
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0
            }
        })
    else:
        # Streaming response - send content in chunks
        chat_id = f"chatcmpl-{int(time.time())}"
        
        # Split content into words for streaming
        words = content.split()
        
        for i, word in enumerate(words):
            chunk = {
                "id": chat_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": "gpt-3.5-turbo",
                "choices": [{
                    "index": 0,
                    "delta": {
                        "content": word + (" " if i < len(words) - 1 else "")
                    },
                    "finish_reason": None
                }]
            }
            yield f"data: {json.dumps(chunk)}\n\n"
            await asyncio.sleep(0.01)  # Small delay between chunks
        
        # Send final chunk
        final_chunk = {
            "id": chat_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": "gpt-3.5-turbo",
            "choices": [{
                "index": 0,
                "delta": {},
                "finish_reason": "stop"
            }]
        }
        yield f"data: {json.dumps(final_chunk)}\n\n"
        yield "data: [DONE]\n\n"

@router.post("/rag-think")
async def custom_rag_think_provider(request: Request):
    """
    This endpoint acts as a custom 'think' provider for the Deepgram Voice Agent.
    It receives the conversation history, uses our RAG-enabled agent to generate
    a response, and returns it to Deepgram.
    """
    try:
        data = await request.json()
        logger.info(f"--- DEBUG: Received data from Deepgram: {data} ---")
        
        messages = data.get("messages", [])
        stream = data.get("stream", False)

        # 1) Preferred: header passed by Deepgram via endpoint configuration
        kb_id = request.headers.get("x-kb-id")
        user_data = {}

        # 2) Legacy fallback: user_data field (older implementation)
        if not kb_id:
            user_data = data.get("user_data", {})
            kb_id = user_data.get("kb_id")
        
        logger.info(f"--- DEBUG: Extracted kb_id: {kb_id} from user_data: {user_data} ---")

        if not kb_id:
            logger.error("kb_id not provided in request (header x-kb-id or user_data)")
            raise HTTPException(status_code=400, detail="kb_id is required (x-kb-id header or user_data)")

        if not messages:
            # This is the initial greeting from Deepgram, let it proceed
            content = "Hello! How can I help you today?"
            return StreamingResponse(
                generate_streaming_response(content, stream),
                media_type="text/event-stream" if stream else "application/json"
            )

        # --- Memory Management ---
        memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)
        user_message = ""

        for msg in messages:
            content = msg.get("content", "")
            if msg.get("role") == "user":
                memory.chat_memory.add_user_message(content)
                user_message = content
            elif msg.get("role") == "assistant":
                memory.chat_memory.add_ai_message(content)

        # --- Agent Execution ---
        agent_executor = agent_manager.create_agent_executor(kb_id=kb_id, memory=memory)

        memory_variables = memory.load_memory_variables({})
        history_string = memory_variables.get("chat_history", "")
        if not isinstance(history_string, str):
            formatted_history = [f"{'Human' if isinstance(m, HumanMessage) else 'AI'}: {m.content}" for m in history_string]
            history_string = "\n".join(formatted_history)

        input_data = {"input": user_message, "chat_history": history_string}

        response = await asyncio.to_thread(agent_executor.invoke, input_data)
        agent_output = response.get("output")

        if agent_output:
            cleaned_output = clean_agent_output(agent_output)
            # For voice, we don't want the handoff marker in the spoken response
            final_response = cleaned_output.replace("(needs help)", "").strip()
            logger.info(f"Generated response for kb_id {kb_id}: {final_response}")
            
            return StreamingResponse(
                generate_streaming_response(final_response, stream),
                media_type="text/event-stream" if stream else "application/json"
            )
        else:
            logger.warning(f"Agent for kb_id {kb_id} produced no output.")
            error_response = "I'm sorry, I'm having trouble understanding. Could you say that again?"
            return StreamingResponse(
                generate_streaming_response(error_response, stream),
                media_type="text/event-stream" if stream else "application/json"
            )

    except Exception as e:
        logger.error(f"Error in custom RAG think provider: {e}", exc_info=True)
        # Provide a safe, generic response for voice
        error_response = "I'm currently experiencing some technical difficulties. Please try again shortly."
        stream = data.get("stream", False) if 'data' in locals() else False
        return StreamingResponse(
            generate_streaming_response(error_response, stream),
            media_type="text/event-stream" if stream else "application/json"
        )
