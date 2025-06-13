import os
import logging
import random
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
import requests
import secrets
from typing import Dict, Any, List
from datetime import datetime
from app.core import supabase_metadata_manager as db_manager, kb_manager, agent_manager
from app.models.chat import ChatRequest, ChatResponse
from app.utils.text_processing import clean_agent_output, auto_add_handoff_if_needed
from langchain.memory import ConversationBufferMemory
from langchain_core.messages import HumanMessage, AIMessage
import asyncio
import json

from app.models.whatsapp import (
    WhatsAppEmbeddedSignupRequest,
    WhatsAppSetupResponse,
    WhatsAppConfigResponse,
    WhatsAppTestMessageRequest
)
from app.core.supabase_client import supabase
from app.services.send_email import notify_admin_on_user_message, notify_client_message
from app.utils.crm_utils import ensure_crm_entry

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/whatsapp", tags=["WhatsApp"])

# Facebook/Meta API endpoints
GRAPH_API_URL = "https://graph.facebook.com/v18.0"

@router.post("/setup/{bot_id}", response_model=WhatsAppSetupResponse)
async def setup_whatsapp_integration(bot_id: str, request: WhatsAppEmbeddedSignupRequest):
    """
    Complete WhatsApp setup after embedded signup and link to knowledge base
    """
    # 🔍 Debug logging
    logger.info(f"🔍 Received WhatsApp setup request for KB: {bot_id}")
    logger.info(f"🔍 Request data: {request}")
    logger.info(f"🔍 Code: {request.code[:20]}...")  # Only log first 20 chars for security
    logger.info(f"🔍 App ID: {request.appid}")
    logger.info(f"🔍 redirect_uri: {request.redirect_uri}")
    #request.secret="00b8d2dec285e72f2e0389f123e59526"

    # Exchange authorization code for access token
    token_url = "https://graph.facebook.com/v18.0/oauth/access_token"

    payload = {
        "client_id": "1430403251470532",
        "client_secret": "00b8d2dec285e72f2e0389f123e59526", 
        "code": request.code,
        "waba_id": request.waba_id,
        "business_id": request.business_id,
        "phone_number_id": request.phone_number_id
    }

    print(payload)

    response = requests.post(token_url, data=payload)

    if response.status_code == 200:
        token_data = response.json()
        access_token = token_data.get('access_token')
        logger.info(f"🔍 Access token: {access_token}")
    else:
        error_text = response.text
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {error_text}")
    
    # Generate a secure webhook verify token
    webhook_verify_token = secrets.token_urlsafe(32)

    # Save the access token to the database
    supabase.table("whatsapp_configs").upsert({
        "bot_id": bot_id,
        "access_token": access_token,
        "phone_number_id": request.phone_number_id,
        "waba_id": request.waba_id,
        "business_id": request.business_id,
        "webhook_verify_token": webhook_verify_token
    }).execute()

    logger.info(f"WhatsApp integration successfully set up for bot: {bot_id}")

    return WhatsAppSetupResponse(
        bot_id=bot_id,
        code=request.code,
        redirect_uri=request.redirect_uri,
        appid=request.appid,
        status="success",
        message="WhatsApp integration configured successfully! Please configure the webhook URL in your Meta Developer Console."
    )

        
   
    #     # Generate a secure webhook verify token
    #     webhook_verify_token = secrets.token_urlsafe(32)
        
    #     # Prepare configuration data for Supabase
    #     config_data = {
    #         "kb_id": kb_id,
    #         "business_account_id": request.business_account_id,
    #         "access_token": request.access_token,  # Note: In production, encrypt this
    #         "phone_number_id": phone_number_id,
    #         "webhook_verify_token": webhook_verify_token,
    #         "is_active": True,
    #         "created_at": datetime.utcnow().isoformat(),
    #         "updated_at": datetime.utcnow().isoformat()
    #     }
        
    #     # Store configuration in Supabase (upsert to handle re-configuration)
    #     result = supabase.table("whatsapp_configs").upsert(config_data).execute()
        
    #     if not result.data:
    #         raise HTTPException(status_code=500, detail="Failed to save WhatsApp configuration")
        
    #     # Generate webhook URL for Meta Developer Console
    #     base_url = os.getenv('BASE_URL', 'https://9e9c-169-0-251-103.ngrok-free.app/')
    #     webhook_url = f"{base_url}/api/whatsapp/webhook/{kb_id}"
        
    #     logger.info(f"WhatsApp integration successfully set up for KB {kb_id}")
        
    #     return WhatsAppSetupResponse(
    #         kb_id=kb_id,
    #         business_account_id=request.business_account_id,
    #         phone_number_id=phone_number_id,
    #         webhook_url=webhook_url,
    #         message="WhatsApp integration configured successfully! Please configure the webhook URL in your Meta Developer Console."
    #     )
        
    # except HTTPException:
    #     raise
    # except Exception as e:
    #     logger.error(f"Error setting up WhatsApp for KB {kb_id}: {str(e)}")
    #     raise HTTPException(status_code=500, detail=f"Setup failed: {str(e)}")

@router.get("/config/{bot_id}", response_model=WhatsAppConfigResponse)
async def get_whatsapp_config(bot_id: str):
    """
    Get WhatsApp configuration for a knowledge base
    """
    logger.info(f"Getting WhatsApp config for bot: {bot_id}")
    try:
        # Query WhatsApp configuration (excluding sensitive access_token)
        result = supabase.table("whatsapp_configs").select(
            "bot_id, phone_number_id,waba_id, business_id, is_active, created_at, updated_at"
        ).eq("bot_id", bot_id).execute()

        print(result.data)
        
        if not result.data:
            raise HTTPException(status_code=404, detail="WhatsApp integration not found for this knowledge base")
        
        config = result.data[0]
        
        # Generate webhook URL
        base_url = os.getenv('BASE_URL', 'https://yourdomain.com')
        webhook_url = f"{base_url}/api/whatsapp/webhook/{bot_id}"
        
        return WhatsAppConfigResponse(
            bot_id=config["bot_id"],
            business_account_id=config["business_id"],
            phone_number_id=config["phone_number_id"],
            waba_id=config["waba_id"],
            webhook_url=webhook_url,
            is_active=config["is_active"],
            created_at=config["created_at"],
            updated_at=config["updated_at"]
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting WhatsApp config for KB {kb_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get configuration")

@router.put("/config/{kb_id}/toggle")
async def toggle_whatsapp_integration(kb_id: str):
    """
    Toggle WhatsApp integration active/inactive status
    """
    try:
        # Get current status
        result = supabase.table("whatsapp_configs").select("is_active").eq("kb_id", kb_id).execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="WhatsApp integration not found")
        
        current_status = result.data[0]["is_active"]
        new_status = not current_status
        
        # Update status
        update_result = supabase.table("whatsapp_configs").update({
            "is_active": new_status,
            "updated_at": datetime.utcnow().isoformat()
        }).eq("kb_id", kb_id).execute()
        
        status_text = "activated" if new_status else "deactivated"
        
        return {
            "status": "success",
            "message": f"WhatsApp integration {status_text} for knowledge base {kb_id}",
            "is_active": new_status
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error toggling WhatsApp integration for KB {kb_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to toggle integration")

@router.delete("/config/{kb_id}")
async def remove_whatsapp_integration(kb_id: str):
    """
    Remove WhatsApp integration completely
    """
    try:
        # Check if integration exists
        result = supabase.table("whatsapp_configs").select("id").eq("kb_id", kb_id).execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="WhatsApp integration not found")
        
        # Delete the configuration
        delete_result = supabase.table("whatsapp_configs").delete().eq("kb_id", kb_id).execute()
        
        logger.info(f"WhatsApp integration removed for KB {kb_id}")
        
        return {
            "status": "success",
            "message": f"WhatsApp integration removed for knowledge base {kb_id}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error removing WhatsApp integration for KB {kb_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to remove integration")

@router.get("/configs")
async def list_whatsapp_integrations():
    """
    List all WhatsApp integrations (admin endpoint)
    """
    try:
        # Get all WhatsApp configurations
        result = supabase.table("whatsapp_configs").select(
            "kb_id, business_account_id, phone_number_id, is_active, created_at, updated_at"
        ).order("created_at", desc=True).execute()
        
        configs = []
        base_url = os.getenv('BASE_URL', 'https://yourdomain.com')
        
        for config in result.data:
            configs.append({
                "kb_id": config["kb_id"],
                "business_account_id": config["business_account_id"],
                "phone_number_id": config["phone_number_id"],
                "webhook_url": f"{base_url}/api/whatsapp/webhook/{config['kb_id']}",
                "is_active": config["is_active"],
                "created_at": config["created_at"],
                "updated_at": config["updated_at"]
            })
        
        return {
            "integrations": configs,
            "total_count": len(configs)
        }
        
    except Exception as e:
        logger.error(f"Error listing WhatsApp integrations: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to list integrations")

# Helper functions for Facebook Graph API calls
async def get_business_account_info(access_token: str, business_account_id: str) -> Dict[str, Any]:
    """
    Get business account information from Facebook Graph API
    """
    try:
        url = f"{GRAPH_API_URL}/{business_account_id}"
        headers = {"Authorization": f"Bearer {access_token}"}
        
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Facebook API error: {response.status_code} - {response.text}")
            raise HTTPException(
                status_code=400, 
                detail=f"Failed to get business account info: {response.json().get('error', {}).get('message', response.text)}"
            )
            
    except requests.RequestException as e:
        logger.error(f"Request error when calling Facebook API: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to connect to Facebook API")

async def get_business_phone_numbers(access_token: str, business_account_id: str) -> List[Dict[str, Any]]:
    """
    Get phone numbers associated with business account
    """
    try:
        url = f"{GRAPH_API_URL}/{business_account_id}/phone_numbers"
        headers = {"Authorization": f"Bearer {access_token}"}
        
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            return data.get("data", [])
        else:
            logger.error(f"Facebook API error getting phone numbers: {response.status_code} - {response.text}")
            raise HTTPException(
                status_code=400, 
                detail=f"Failed to get phone numbers: {response.json().get('error', {}).get('message', response.text)}"
            )
            
    except requests.RequestException as e:
        logger.error(f"Request error when getting phone numbers: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to connect to Facebook API")

@router.post("/test-message/{bot_id}")
async def send_test_message(bot_id: str, request: WhatsAppTestMessageRequest):
    """
    Send a test message to a WhatsApp number
    """
    try:
        # Get WhatsApp configuration
        result = supabase.table("whatsapp_configs").select(
            "phone_number_id, access_token"
        ).eq("bot_id", bot_id).execute()

        if not result.data:
            raise HTTPException(status_code=404, detail="WhatsApp configuration not found")

        config = result.data[0]
        phone_number_id = config["phone_number_id"]
        access_token = config["access_token"]

        # Prepare the message payload
        url = f"{GRAPH_API_URL}/{phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": request.phone_number,
            "type": "text",
            "text": {
                "body": request.message
            }
        }

        # Send the message
        response = requests.post(url, headers=headers, json=payload)

        if response.status_code != 200:
            error_data = response.json()
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Failed to send message: {error_data.get('error', {}).get('message', 'Unknown error')}"
            )

        return {
            "status": "success",
            "message": "Test message sent successfully",
            "details": response.json()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending test message: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to send test message: {str(e)}")
    
@router.get("/webhook")
async def verify_webhook(request: Request):
    """
    Verify webhook endpoint for WhatsApp
    """

    VERIFY_TOKEN = "itwaschatwise"
    params = dict(request.query_params)
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("✅ Webhook Verified!")
        return PlainTextResponse(content=challenge, status_code=200)
    else:
        print("❌ Webhook Verification Failed")
        return PlainTextResponse(content="Verification failed", status_code=403)


@router.post("/webhook")
async def whatsapp_webhook(request: Request):
    """
    Webhook endpoint to receive WhatsApp notifications
    """
    try:
        body = await request.json()  # Parse the JSON body
        logger.info(f"📦 Webhook data: {body}")

        # Extract message details if present
        if "entry" in body:
            for entry in body["entry"]:
                for change in entry.get("changes", []):
                    if change.get("value", {}).get("messages"):
                        for message in change["value"]["messages"]:
                            from_number = message.get('from')
                            message_content = message.get('text', {}).get('body')
                            message_id = message.get('id')
                            timestamp = message.get('timestamp')
                            
                            logger.info(f"💬 Message from: {from_number}")
                            logger.info(f"📝 Message content: {message_content}")
                            logger.info(f"🆔 Message ID: {message_id}")
                            logger.info(f"⏰ Timestamp: {timestamp}")

                            # Get the bot_id from the phone_number_id
                            phone_number_id = change["value"].get("metadata", {}).get("phone_number_id")
                            if not phone_number_id:
                                logger.error("No phone_number_id found in webhook data")
                                continue

                            # Get bot_id from phone_number_id
                            result = supabase.table("whatsapp_configs").select("bot_id").eq("phone_number_id", phone_number_id).execute()
                            if not result.data:
                                logger.error(f"No bot found for phone_number_id: {phone_number_id}")
                                continue

                            bot_id = result.data[0]["bot_id"]
                            
                            # Get kb_id from bot_id
                            bot_result = supabase.table("bots").select("kb_id").eq("id", bot_id).execute()
                            if not bot_result.data:
                                logger.error(f"No kb_id found for bot_id: {bot_id}")
                                continue

                            kb_id = bot_result.data[0]["kb_id"]

                            # Check if conversation exists for this phone number and bot
                            conversation_result = supabase.table("conversations").select("*").eq("bot_id", bot_id).eq("customer_phone", from_number).execute()
                            
                            conversation_id = None
                            if conversation_result.data:
                                # Update existing conversation
                                conversation_id = conversation_result.data[0]["id"]
                                supabase.table("conversations").update({
                                    "updated_at": datetime.utcnow().isoformat(),
                                    "status": "ai" if conversation_result.data[0]["status"] == "closed" else conversation_result.data[0]["status"]
                                }).eq("id", conversation_id).execute()
                            else:
                                # Create new conversation with 'awaiting_name' status
                                random_number = random.randint(1000, 9999)
                                new_conversation = supabase.table("conversations").insert({
                                    "bot_id": bot_id,
                                    "customer_phone": from_number,
                                    "customer_email": None,
                                    "customer_name": f"Whatsapp User {random_number}",  # Initial random name
                                    "channel": "whatsapp",
                                    "status": "awaiting_name",  # Special status for first-time users
                                    "read": False,
                                    "created_at": datetime.utcnow().isoformat(),
                                    "updated_at": datetime.utcnow().isoformat()
                                }).execute()
                                conversation_id = new_conversation.data[0]["id"]

                                # Send welcome message asking for name
                                welcome_message = "Hey! To get started, please tell me your name."
                                await send_whatsapp_message(
                                    phone_number_id=phone_number_id,
                                    to_number=from_number,
                                    message=welcome_message
                                )
                                # Store the welcome message
                                supabase.table("messages").insert({
                                    "conversation_id": conversation_id,
                                    "content": welcome_message,
                                    "role": "bot",
                                    "read": False,
                                    "created_at": datetime.utcnow().isoformat()
                                }).execute()
                                return {"status": "success", "message": "Welcome message sent"}

                            # Store the incoming message
                            supabase.table("messages").insert({
                                "conversation_id": conversation_id,
                                "content": message_content,
                                "role": "user",
                                "read": False,
                                "created_at": datetime.utcnow().isoformat()
                            }).execute()

                            # Handle name collection for first-time users
                            if conversation_result.data and conversation_result.data[0]["status"] == "awaiting_name":
                                # Update the conversation with the user's name
                                supabase.table("conversations").update({
                                    "customer_name": message_content,
                                    "status": "ai",
                                    "updated_at": datetime.utcnow().isoformat()
                                }).eq("id", conversation_id).execute()

                                # Update CRM with the new name
                                first_name, last_name = None, None
                                if message_content:
                                    parts = message_content.split(" ", 1)
                                    first_name = parts[0]
                                    last_name = parts[1] if len(parts) > 1 else ""

                                ensure_crm_entry(
                                    bot_id=bot_id,
                                    first_name=first_name,
                                    last_name=last_name,
                                    phone_number=from_number,
                                    email=None
                                )

                                # Send confirmation message
                                confirmation_message = f"Thank you {message_content}! How can I help you today?"
                                await send_whatsapp_message(
                                    phone_number_id=phone_number_id,
                                    to_number=from_number,
                                    message=confirmation_message
                                )
                                # Store the confirmation message
                                supabase.table("messages").insert({
                                    "conversation_id": conversation_id,
                                    "content": confirmation_message,
                                    "role": "bot",
                                    "read": False,
                                    "created_at": datetime.utcnow().isoformat()
                                }).execute()
                                return {"status": "success", "message": "Name collected"}

                            # Process the message using chat functionality
                            try:
                                # Create chat request
                                chat_request = ChatRequest(
                                    message=message_content,
                                    conversation_id=message_id
                                )

                                # Get conversation history
                                db_history = db_manager.get_conversation_history(kb_id)
                                
                                # Create memory instance
                                memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)
                                
                                # Populate memory from DB history
                                for msg in db_history:
                                    if msg.get('message_type') == 'human':
                                        memory.chat_memory.add_user_message(msg.get('content', ''))
                                    elif msg.get('message_type') == 'ai':
                                        memory.chat_memory.add_ai_message(msg.get('content', ''))

                                # Create agent executor
                                agent_executor = agent_manager.create_agent_executor(kb_id=kb_id, memory=memory)

                                # Format history for prompt
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

                                # Prepare agent input
                                input_data = {
                                    "input": message_content,
                                    "chat_history": history_string
                                }

                                # Invoke agent
                                response = await asyncio.to_thread(agent_executor.invoke, input_data)
                                
                                # Process response
                                agent_output = response.get("output")
                                if agent_output:
                                    cleaned_output = clean_agent_output(agent_output)
                                    # Apply automatic handoff detection for insufficient answers
                                    cleaned_output = auto_add_handoff_if_needed(cleaned_output)
                                    
                                    # Save messages to conversation history
                                    db_manager.add_conversation_message(kb_id, 'human', message_content)
                                    db_manager.add_conversation_message(kb_id, 'ai', cleaned_output)

                                    # Store the AI response message
                                    supabase.table("messages").insert({
                                        "conversation_id": conversation_id,
                                        "content": cleaned_output,
                                        "role": "bot",
                                        "read": False,
                                        "created_at": datetime.utcnow().isoformat()
                                    }).execute()

                                    # Send response back to WhatsApp
                                    message_sent = await send_whatsapp_message(
                                        phone_number_id=phone_number_id,
                                        to_number=from_number,
                                        message=cleaned_output
                                    )
                                    
                                    if not message_sent:
                                        # If message wasn't sent due to user not initiating conversation,
                                        # send a welcome message explaining how to start
                                        welcome_message = (
                                            "Welcome! To start chatting with our AI assistant, "
                                            "please send any message to this number. "
                                            "Once you do, I'll be able to respond to your questions."
                                        )
                                        await send_whatsapp_message(
                                            phone_number_id=phone_number_id,
                                            to_number=from_number,
                                            message=welcome_message
                                        )
                                        # Store the welcome message
                                        supabase.table("messages").insert({
                                            "conversation_id": conversation_id,
                                            "content": welcome_message,
                                            "role": "bot",
                                            "read": False,
                                            "created_at": datetime.utcnow().isoformat()
                                        }).execute()

                                    if cleaned_output and "(needs help)" in cleaned_output:
                                        # Remove the marker from the response
                                        cleaned_output = cleaned_output.replace("(needs help)", "").strip()
                                        
                                        # Update conversation status to human
                                        supabase.table("conversations").update({
                                            "status": "human"
                                        }).eq("id", conversation_id).execute()
                                        
                                        # Create handover request
                                        supabase.table("handover_requests").insert({
                                            "conversation_id": conversation_id,
                                            "last_message_id": message_id
                                        }).execute()

                                        #get user email from conversation_id in supabase
                                        user_data = supabase.table("users").select("*").eq("id", conversation_result.data[0]["user_id"]).execute()
                                        company_email = user_data.data[0]["email"]
                                        
                                        # Send notification to admin
                                        notify_admin_on_user_message(
                                            conversation_result.data[0]["customer_name"],
                                            conversation_result.data[0]["customer_email"],
                                            message_content,
                                            bot_id,
                                            company_email
                                        )
                                                
                                else:
                                    logger.error("No output from agent")
                                    error_message = "I apologize, but I'm having trouble processing your message right now."
                                    await send_whatsapp_message(
                                        phone_number_id=phone_number_id,
                                        to_number=from_number,
                                        message=error_message
                                    )
                                    # Store the error message
                                    supabase.table("messages").insert({
                                        "conversation_id": conversation_id,
                                        "content": error_message,
                                        "role": "ai",
                                        "read": False,
                                        "created_at": datetime.utcnow().isoformat()
                                    }).execute()

                            except Exception as e:
                                logger.error(f"Error processing message: {str(e)}")
                                await send_whatsapp_message(
                                    phone_number_id=phone_number_id,
                                    to_number=from_number,
                                    message="I apologize, but I encountered an error processing your message."
                                )

        return {"status": "success", "message": "Webhook received"}

    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        return {"status": "error", "message": str(e)}

async def send_whatsapp_message(phone_number_id: str, to_number: str, message: str):
    """
    Send a message back to WhatsApp
    """
    try:
        # Get access token
        result = supabase.table("whatsapp_configs").select("access_token").eq("phone_number_id", phone_number_id).execute()
        if not result.data:
            raise Exception("No access token found for phone_number_id")

        access_token = result.data[0]["access_token"]

        # Prepare the message payload
        url = f"{GRAPH_API_URL}/{phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": to_number,
            "type": "text",
            "text": {
                "body": message
            }
        }

        # Send the message
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code != 200:
            error_data = response.json()
            logger.error(f"📤 WhatsApp API Error Response: {json.dumps(error_data, indent=2)}")
            error_message = error_data.get('error', {}).get('message', 'Unknown error')
            error_code = error_data.get('error', {}).get('code')
            
            # Handle specific WhatsApp API errors
            if error_code == 131037:
                logger.warning(f"User {to_number} needs to initiate conversation first")
                return False
            else:
                raise Exception(f"Failed to send message: {error_message}")

        return True

    except Exception as e:
        logger.error(f"Error sending WhatsApp message: {str(e)}")
        raise

@router.post("/whatsapp-from-agent")
async def send_whatsapp_from_agent(request: Request):
    """
    Endpoint for sending WhatsApp messages from human agents.
    Receives conversation_id and message, then sends to the appropriate WhatsApp number.
    """
    try:
        # Parse request body
        body = await request.json()
        conversation_id = body.get("conversation_id")
        message = body.get("message")

        if not conversation_id or not message:
            raise HTTPException(
                status_code=400,
                detail="conversation_id and message are required"
            )

        # Get conversation details from Supabase
        conversation_result = supabase.table("conversations").select(
            "bot_id, customer_phone"
        ).eq("id", conversation_id).execute()

        if not conversation_result.data:
            raise HTTPException(
                status_code=404,
                detail="Conversation not found"
            )

        conversation = conversation_result.data[0]
        bot_id = conversation["bot_id"]
        to_number = conversation["customer_phone"]

        # Get WhatsApp configuration for the bot
        whatsapp_config = supabase.table("whatsapp_configs").select(
            "phone_number_id"
        ).eq("bot_id", bot_id).execute()

        if not whatsapp_config.data:
            raise HTTPException(
                status_code=404,
                detail="WhatsApp configuration not found for this bot"
            )

        phone_number_id = whatsapp_config.data[0]["phone_number_id"]

        # Send the WhatsApp message
        message_sent = await send_whatsapp_message(
            phone_number_id=phone_number_id,
            to_number=to_number,
            message=message
        )

        if not message_sent:
            raise HTTPException(
                status_code=500,
                detail="Failed to send WhatsApp message"
            )

        return {
            "status": "success",
            "message": "WhatsApp message sent successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending WhatsApp message from agent: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to send WhatsApp message: {str(e)}"
        )