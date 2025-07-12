from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import RedirectResponse
from app.models.gmail import GmailConfigModel, GmailAuthRequest, GmailAuthResponse, GmailDisconnectRequest
from app.models.base import StatusResponse
from app.core.supabase_client import supabase
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
import os
import json
import base64
import email.mime.text
import email.mime.multipart
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from pydantic import BaseModel
import asyncio

router = APIRouter(prefix="/gmail", tags=["gmail"])

# Google OAuth2 Configuration
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

# Gmail OAuth client configuration
CLIENT_CONFIG = {
    "web": {
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": []
    }
}

# Pydantic models for email sending
class EmailRequest(BaseModel):
    to: str
    subject: str
    body_html: Optional[str] = None
    body_text: Optional[str] = None
    reply_to_message_id: Optional[str] = None  # For threading
    reply_to_thread_id: Optional[str] = None   # For threading

class EmailResponse(BaseModel):
    status: str
    message: str
    email_id: str
    thread_id: str
    email_details: Dict[str, Any]

class EmailReplyRequest(BaseModel):
    """Request body for replying to an email thread."""
    conversation_id: str
    to: str
    subject: Optional[str] = None
    body_html: Optional[str] = None
    body_text: Optional[str] = None
    # Gmail identifiers to maintain threading
    reply_to_message_id: Optional[str] = None  # Gmail Message-ID header of the email we are replying to
    reply_to_thread_id: Optional[str] = None   # Gmail threadId we are replying in
    # Link the reply to an existing chat message (optional)
    reply_to_chat_message_id: Optional[str] = None


@router.get("/{bot_id}/config", response_model=GmailConfigModel)
async def get_gmail_config(bot_id: str):
    """Get Gmail configuration for a bot"""
    try:
        # Check if bot exists
        bot_response = supabase.table("bots").select("id").eq("id", bot_id).execute()
        if not bot_response.data:
            raise HTTPException(status_code=404, detail="Bot not found")
        
        # Get Gmail configuration
        response = supabase.table("gmail_configs").select("*").eq("bot_id", bot_id).single().execute()
        
        if response.data:
            config = response.data
            return GmailConfigModel(
                bot_id=config["bot_id"],
                is_enabled=config["is_enabled"],
                email_address=config.get("email_address"),
                # Don't return sensitive tokens in API responses
                refresh_token=None,
                access_token=None,
                token_expires_at=config.get("token_expires_at"),
                scopes=config.get("scopes", "https://www.googleapis.com/auth/gmail.modify")
            )
        else:
            # Return default config if none exists
            return GmailConfigModel(
                bot_id=bot_id,
                is_enabled=False
            )
    
    except Exception as e:
        if "PGRST116" not in str(e):  # Not a "not found" error
            print(f"Error getting Gmail config for bot {bot_id}: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to get Gmail configuration")
        
        # Return default config if not found
        return GmailConfigModel(
            bot_id=bot_id,
            is_enabled=False
        )

@router.get("/{bot_id}/auth-url")
async def get_gmail_auth_url(bot_id: str, redirect_uri: str):
    """Generate Gmail OAuth authorization URL"""
    try:
        # Check if bot exists
        bot_response = supabase.table("bots").select("id").eq("id", bot_id).execute()
        if not bot_response.data:
            raise HTTPException(status_code=404, detail="Bot not found")
        
        if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
            raise HTTPException(status_code=500, detail="Google OAuth not configured")
        
        # Create OAuth2 flow
        flow = Flow.from_client_config(
            CLIENT_CONFIG,
            scopes=SCOPES
        )
        flow.redirect_uri = redirect_uri
        
        # Generate authorization URL
        auth_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent'  # Force consent to get refresh token
        )
        
        return {
            "auth_url": auth_url,
            "state": state
        }
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error generating Gmail auth URL for bot {bot_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to generate authorization URL")

@router.post("/{bot_id}/connect", response_model=GmailAuthResponse)
async def connect_gmail(bot_id: str, request: GmailAuthRequest):
    """Connect Gmail account using OAuth code"""
    try:
        # Check if bot exists
        bot_response = supabase.table("bots").select("id").eq("id", bot_id).execute()
        if not bot_response.data:
            raise HTTPException(status_code=404, detail="Bot not found")
        
        if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
            raise HTTPException(status_code=500, detail="Google OAuth not configured")
        
        # Create OAuth2 flow
        flow = Flow.from_client_config(
            CLIENT_CONFIG,
            scopes=SCOPES
        )
        flow.redirect_uri = request.redirect_uri
        
        # Exchange code for tokens
        flow.fetch_token(code=request.code)
        credentials = flow.credentials
        
        # Get user's email address
        gmail_service = build('gmail', 'v1', credentials=credentials)
        profile = gmail_service.users().getProfile(userId='me').execute()
        email_address = profile['emailAddress']
        
        # Calculate token expiry
        token_expires_at = None
        if credentials.expiry:
            token_expires_at = credentials.expiry.isoformat()
        
        # Save configuration to database
        config_data = {
            "bot_id": bot_id,
            "is_enabled": True,
            "email_address": email_address,
            "refresh_token": credentials.refresh_token,
            "access_token": credentials.token,
            "token_expires_at": token_expires_at,
            "scopes": " ".join(SCOPES),
            "updated_at": datetime.utcnow().isoformat()
        }
        
        # Upsert Gmail configuration
        supabase.table("gmail_configs").upsert(config_data).execute()
        
        # Call users.watch() once per connected account
        gmail_service = build("gmail", "v1", credentials=credentials)

        watch_resp = gmail_service.users().watch(
            userId="me",
            body={
                "topicName": "projects/ragtest-454923/topics/deskforce",
                # Optional: only fire on inbox label or sent label etc.
                "labelIds": ["INBOX"],
                "labelFilterAction": "include"
            }
        ).execute()

        # watch_resp returns {"historyId": "...", "expiration": 1723682219000}
        supabase.table("gmail_configs").update({
            "watch_history_id": watch_resp["historyId"],
            "watch_expires_at": datetime.utcfromtimestamp(
                int(watch_resp["expiration"]) / 1000
            ).isoformat(),
        }).eq("bot_id", bot_id).execute()
        
        return GmailAuthResponse(
            status="success",
            message="Gmail account connected successfully",
            email_address=email_address,
            is_connected=True
        )
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error connecting Gmail for bot {bot_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to connect Gmail account: {str(e)}")

@router.post("/{bot_id}/disconnect", response_model=StatusResponse)
async def disconnect_gmail(bot_id: str):
    """Disconnect Gmail account"""
    try:
        # Check if bot exists
        bot_response = supabase.table("bots").select("id").eq("id", bot_id).execute()
        if not bot_response.data:
            raise HTTPException(status_code=404, detail="Bot not found")
        
        # Get current Gmail configuration
        response = supabase.table("gmail_configs").select("*").eq("bot_id", bot_id).single().execute()
        
        if response.data:
            # Try to revoke the refresh token
            try:
                if response.data.get("refresh_token"):
                    credentials = Credentials(
                        token=response.data.get("access_token"),
                        refresh_token=response.data["refresh_token"],
                        token_uri=CLIENT_CONFIG["web"]["token_uri"],
                        client_id=GOOGLE_CLIENT_ID,
                        client_secret=GOOGLE_CLIENT_SECRET
                    )
                    credentials.revoke(Request())
            except Exception as revoke_error:
                print(f"Error revoking Gmail token: {revoke_error}")
                # Continue with disconnect even if revocation fails
            
            # Remove configuration from database
            supabase.table("gmail_configs").delete().eq("bot_id", bot_id).execute()
        
        return StatusResponse(
            status="success",
            message="Gmail account disconnected successfully"
        )
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error disconnecting Gmail for bot {bot_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to disconnect Gmail account")

@router.get("/{bot_id}/status")
async def get_gmail_status(bot_id: str):
    """Get Gmail connection status"""
    try:
        # Check if bot exists
        bot_response = supabase.table("bots").select("id").eq("id", bot_id).execute()
        if not bot_response.data:
            raise HTTPException(status_code=404, detail="Bot not found")
        
        # Get Gmail configuration
        response = supabase.table("gmail_configs").select("is_enabled, email_address, token_expires_at").eq("bot_id", bot_id).single().execute()
        
        if response.data and response.data["is_enabled"]:
            # Check if token is expired
            token_expired = False
            if response.data.get("token_expires_at"):
                try:
                    expiry = datetime.fromisoformat(response.data["token_expires_at"].replace('Z', '+00:00'))
                    token_expired = expiry <= datetime.now(expiry.tzinfo)
                except:
                    token_expired = True
            
            return {
                "is_connected": True,
                "email_address": response.data["email_address"],
                "token_expired": token_expired,
                "status": "expired" if token_expired else "active"
            }
        else:
            return {
                "is_connected": False,
                "email_address": None,
                "token_expired": False,
                "status": "disconnected"
            }
    
    except Exception as e:
        if "PGRST116" not in str(e):  # Not a "not found" error
            print(f"Error getting Gmail status for bot {bot_id}: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to get Gmail status")
        
        return {
            "is_connected": False,
            "email_address": None,
            "token_expired": False,
            "status": "disconnected"
        }

async def get_gmail_credentials(bot_id: str) -> Credentials:
    """Get valid Gmail credentials for a bot"""
    # Get Gmail configuration
    response = supabase.table("gmail_configs").select("*").eq("bot_id", bot_id).single().execute()
    
    if not response.data or not response.data["is_enabled"]:
        raise HTTPException(status_code=400, detail="Gmail not configured or disabled for this bot")
    
    config = response.data
    
    # Create credentials object
    credentials = Credentials(
        token=config.get("access_token"),
        refresh_token=config.get("refresh_token"),
        token_uri=CLIENT_CONFIG["web"]["token_uri"],
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET
    )
    
    # Check if token needs refresh
    if credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
            
            # Update tokens in database
            update_data = {
                "access_token": credentials.token,
                "token_expires_at": credentials.expiry.isoformat() if credentials.expiry else None,
                "updated_at": datetime.utcnow().isoformat()
            }
            supabase.table("gmail_configs").update(update_data).eq("bot_id", bot_id).execute()
            
        except Exception as e:
            raise HTTPException(status_code=401, detail=f"Failed to refresh Gmail token: {str(e)}")
    
    return credentials

def create_email_message(to: str, subject: str, body_html: str = None, body_text: str = None, 
                        reply_to_message_id: str = None, reply_to_thread_id: str = None) -> str:
    """Create email message in the format expected by Gmail API"""
    
    # Create message - use HTML if provided, otherwise text
    if body_html:
        message = email.mime.text.MIMEText(body_html, 'html')
    elif body_text:
        message = email.mime.text.MIMEText(body_text, 'plain')
    else:
        # Fallback to plain text
        message = email.mime.text.MIMEText(subject, 'plain')
    
    message['To'] = to
    message['Subject'] = subject
    # Note: From header will be set by Gmail automatically based on the authenticated account
    
    # ✅ Add threading headers
    if reply_to_message_id:
        message['In-Reply-To'] = reply_to_message_id
        message['References'] = reply_to_message_id
        print(f"🔗 Email threading: Added In-Reply-To and References headers with message_id: {reply_to_message_id}")


    print(f"message FINAL: {message}")
    
    # Convert to base64 encoded string
    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
    
    return raw_message

@router.post("/{bot_id}/send-email", response_model=EmailResponse)
async def send_email(bot_id: str, email_request: EmailRequest):
    """Send an email from the connected Gmail account"""
    try:
        # Check if bot exists
        bot_response = supabase.table("bots").select("id").eq("id", bot_id).execute()
        if not bot_response.data:
            raise HTTPException(status_code=404, detail="Bot not found")
        
        print(f"Email request --->: {email_request}")

        
        # Validate email content
        if not email_request.body_html and not email_request.body_text:
            raise HTTPException(status_code=400, detail="Either body_html or body_text must be provided")
        
        # Get Gmail credentials
        credentials = await get_gmail_credentials(bot_id)
        
        # Build Gmail service
        gmail_service = build('gmail', 'v1', credentials=credentials)

        print(f"Email request: {email_request}")
        
        # Create email message
        raw_message = create_email_message(
            to=email_request.to,
            subject=email_request.subject,
            body_html=email_request.body_html,
            #body_text=email_request.body_html,
            reply_to_message_id=email_request.reply_to_message_id,
            reply_to_thread_id=email_request.reply_to_thread_id
        )
        
        # Prepare message body for Gmail API
        message_body = {'raw': raw_message}
        
        # Add thread ID if replying
        if email_request.reply_to_thread_id:
            message_body['threadId'] = email_request.reply_to_thread_id
            print(f"🔗 Gmail API: Using threadId {email_request.reply_to_thread_id}")
        
        if email_request.reply_to_message_id:
            print(f"📧 Gmail API: Using message_id {email_request.reply_to_message_id} for In-Reply-To header")
        
        print(f"📤 Gmail API: Sending email with message_body: {message_body}")
        
        # Send the email
        sent_message = gmail_service.users().messages().send(
            userId='me', 
            body=message_body
        ).execute()
        
        print(f"📤 Gmail API: Sent message response: {sent_message}")
        print(f"📤 Gmail API: Message ID: {sent_message.get('id')}")
        print(f"📤 Gmail API: Thread ID: {sent_message.get('threadId')}")
        
        # Get the sent message details
        message_details = gmail_service.users().messages().get(
            userId='me', 
            id=sent_message['id'],
            format='full'
        ).execute()
        
        # Extract email details
        headers = {header['name']: header['value'] for header in message_details['payload']['headers']}

        # 🔧 FIX: Extract Message-ID header in a case-insensitive way
        message_id_header_value = ""
        for h_name, h_value in headers.items():
            if h_name.lower() == "message-id":
                message_id_header_value = h_value
                break
 
        email_details = {
            "message_id": sent_message['id'],
            "thread_id": sent_message['threadId'],
            "label_ids": message_details.get('labelIds', []),
            "snippet": message_details.get('snippet', ''),
            "headers": {
                "to": headers.get('To', ''),
                "subject": headers.get('Subject', ''),
                "date": headers.get('Date', ''),
                "message_id": message_id_header_value,
                "from": headers.get('From', ''),
                "in_reply_to": headers.get('In-Reply-To', ''),
                "references": headers.get('References', '')
            },
            "size_estimate": message_details.get('sizeEstimate', 0),
            "sent_at": datetime.utcnow().isoformat()
        }
        
        return EmailResponse(
            status="success",
            message="Email sent successfully",
            email_id=sent_message['id'],
            thread_id=sent_message['threadId'],
            email_details=email_details
        )
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error sending email for bot {bot_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to send email: {str(e)}")

@router.post("/{bot_id}/reply-email")
async def reply_to_email(bot_id: str, req: EmailReplyRequest):
    """Send a reply email via connected Gmail account and log it as a human message.

    After successfully sending, store the outgoing email in **messages** table with:
      • role = "human"
      • status = "email_sent"
      • reply_to_message_id = req.reply_to_chat_message_id (if provided)
    """
    try:
        # ---------------------------------------------
        # 1️⃣  Determine threading info if not provided
        # ---------------------------------------------
        thread_id = req.reply_to_thread_id
        reply_msg_id = req.reply_to_message_id
        subject = req.subject
        to_addr = req.to

        if not thread_id or not reply_msg_id or not subject or not to_addr:
            # Find follow_up_queue for this conversation & bot
            queue_resp = (
                supabase.table("follow_up_queue")
                .select("id")
                .eq("conversation_id", req.conversation_id)
                .eq("bot_id", bot_id)
                .order("created_at", desc=True)  # Get the most recent queue entry
                .limit(1)
                .execute()
            )

            if not queue_resp.data:
                raise HTTPException(status_code=404, detail="No follow-up queue for conversation")

            queue_id = queue_resp.data[0]["id"]

            email_resp = (
                supabase.table("follow_up_emails")
                .select("thread_id, metadata, subject, recipient_email")
                .eq("follow_up_queue_id", queue_id)
                .eq("email_type", "initial")
                .order("created_at", desc=False)
                .limit(1)
                .execute()
            )

            if not email_resp.data:
                raise HTTPException(status_code=404, detail="Initial follow-up email not found")

            init_email = email_resp.data[0]
            meta = init_email.get("metadata") or {}

            thread_id = thread_id or init_email.get("thread_id")
            reply_msg_id = reply_msg_id or meta.get("gmail_message_id_header")
            subject = init_email.get("subject")
            to_addr = to_addr or init_email.get("recipient_email")

        if not (thread_id and reply_msg_id and subject and to_addr):
            raise HTTPException(status_code=400, detail="Unable to resolve threading information for reply")

        # ---------------------------------------------
        # 2️⃣  Send the email using existing helper
        # ---------------------------------------------
        email_req = EmailRequest(
            to=to_addr,
            subject=subject,
            body_html=req.body_html,
            body_text=req.body_text,
            reply_to_message_id=reply_msg_id,
            reply_to_thread_id=thread_id,
        )

        send_resp: EmailResponse = await send_email(bot_id, email_req)  # type: ignore

        # ---------------------------------------------
        # 3️⃣  Persist chat message (dedupe check)
        # ---------------------------------------------
        msg_content = req.body_html or req.body_text or "(no content)"
        duplicate = (
            supabase.table("messages")
            .select("id")
            .eq("conversation_id", req.conversation_id)
            .eq("role", "human")
            .eq("status", "email_sent")
            .eq("content", msg_content)
            .limit(1)
            .execute()
        )

        if not duplicate.data:
            supabase.table("messages").insert({
                "conversation_id": req.conversation_id,
                "content": msg_content,
                "role": "human",
                "status": "email_sent",
                "reply_to_message_id": req.reply_to_chat_message_id,
                "created_at": datetime.utcnow().isoformat(),
            }).execute()

        return {
            "status": send_resp.status,
            "message": send_resp.message,
            "email_id": send_resp.email_id,
            "thread_id": send_resp.thread_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error replying to email for bot {bot_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to reply to email: {e}")

@router.get("/{bot_id}/email/{email_id}")
async def get_email_details(bot_id: str, email_id: str):
    """Get details of a specific email"""
    try:
        # Check if bot exists
        bot_response = supabase.table("bots").select("id").eq("id", bot_id).execute()
        if not bot_response.data:
            raise HTTPException(status_code=404, detail="Bot not found")
        
        # Get Gmail credentials
        credentials = await get_gmail_credentials(bot_id)
        
        # Build Gmail service
        gmail_service = build('gmail', 'v1', credentials=credentials)
        
        # Get email details
        message = gmail_service.users().messages().get(
            userId='me', 
            id=email_id,
            format='full'
        ).execute()
        
        # Extract headers
        headers = {header['name']: header['value'] for header in message['payload']['headers']}
        
        return {
            "email_id": email_id,
            "thread_id": message['threadId'],
            "label_ids": message.get('labelIds', []),
            "snippet": message.get('snippet', ''),
            "headers": headers,
            "size_estimate": message.get('sizeEstimate', 0),
            "internal_date": message.get('internalDate', '')
        }
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting email details for bot {bot_id}, email {email_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get email details: {str(e)}")

@router.get("/{bot_id}/thread/{thread_id}")
async def get_thread_details(bot_id: str, thread_id: str):
    """Get details of a specific email thread"""
    try:
        # Check if bot exists
        bot_response = supabase.table("bots").select("id").eq("id", bot_id).execute()
        if not bot_response.data:
            raise HTTPException(status_code=404, detail="Bot not found")
        
        # Get Gmail credentials
        credentials = await get_gmail_credentials(bot_id)
        
        # Build Gmail service
        gmail_service = build('gmail', 'v1', credentials=credentials)
        
        # Get thread details
        thread = gmail_service.users().threads().get(
            userId='me', 
            id=thread_id,
            format='metadata'
        ).execute()
        
        # Extract thread information
        messages = []
        for message in thread.get('messages', []):
            headers = {header['name']: header['value'] for header in message['payload']['headers']}
            messages.append({
                "id": message['id'],
                "snippet": message.get('snippet', ''),
                "headers": {
                    "from": headers.get('From', ''),
                    "to": headers.get('To', ''),
                    "subject": headers.get('Subject', ''),
                    "date": headers.get('Date', '')
                },
                "label_ids": message.get('labelIds', [])
            })
        
        return {
            "thread_id": thread_id,
            "history_id": thread.get('historyId', ''),
            "message_count": len(messages),
            "messages": messages
        }
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting thread details for bot {bot_id}, thread {thread_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get thread details: {str(e)}")

# Test function for send_email
async def test_send_email():
    """
    Test function for the send_email functionality.
    Fill in the details below and run this function to test email sending.
    """
    
    # TEST CONFIGURATION - FILL IN THESE DETAILS
    TEST_BOT_ID = "18eb9b0c-d283-4781-a727-6140d940db42"  # Replace with your actual bot ID
    TEST_RECIPIENT = "asifhassam14@gmail.com"  # Replace with test recipient email
    TEST_SUBJECT = "Test Email from Gmail API"
    TEST_BODY_HTML = """
    <html>
        <body>
            <h2>Test Email</h2>
            <p>This is a test email sent from the Gmail API integration.</p>
            <p>Features tested:</p>
            <ul>
                <li>HTML email formatting</li>
                <li>Gmail API integration</li>
                <li>Email and thread ID retrieval</li>
            </ul>
            <p>Best regards,<br>Your Bot</p>
        </body>
    </html>
    """
    TEST_BODY_TEXT = """
    Test Email
    
    This is a test email sent from the Gmail API integration.
    
    Features tested:
    - Plain text email formatting
    - Gmail API integration  
    - Email and thread ID retrieval
    
    Best regards,
    Your Bot
    """
    
    print("=" * 60)
    print("GMAIL SEND EMAIL TEST")
    print("=" * 60)
    
    try:
        # Create test email request
        test_email_request = EmailRequest(
            to=TEST_RECIPIENT,
            subject=TEST_SUBJECT,
            body_html=TEST_BODY_HTML,
            body_text=TEST_BODY_TEXT
        )
        
        print(f"📧 Testing email send to: {TEST_RECIPIENT}")
        print(f"📝 Subject: {TEST_SUBJECT}")
        print(f"🤖 Bot ID: {TEST_BOT_ID}")
        print("-" * 40)
        
        # Send the email
        result = await send_email(TEST_BOT_ID, test_email_request)
        
        print("✅ EMAIL SENT SUCCESSFULLY!")
        print("-" * 40)
        print(f"📧 Email ID: {result.email_id}")
        print(f"🧵 Thread ID: {result.thread_id}")
        print(f"📊 Status: {result.status}")
        print(f"💬 Message: {result.message}")
        
        print("\n📋 EMAIL DETAILS:")
        print("-" * 40)
        details = result.email_details
        print(f"To: {details['headers']['to']}")
        print(f"From: {details['headers']['from']}")
        print(f"Subject: {details['headers']['subject']}")
        print(f"Date: {details['headers']['date']}")
        print(f"Size: {details['size_estimate']} bytes")
        print(f"Snippet: {details['snippet'][:100]}...")
        
        # Test getting email details
        print("\n🔍 TESTING EMAIL DETAILS RETRIEVAL:")
        print("-" * 40)
        email_details = await get_email_details(TEST_BOT_ID, result.email_id)
        print(f"✅ Retrieved email details for: {email_details['email_id']}")
        
        # Test getting thread details
        print("\n🧵 TESTING THREAD DETAILS RETRIEVAL:")
        print("-" * 40)
        thread_details = await get_thread_details(TEST_BOT_ID, result.thread_id)
        print(f"✅ Retrieved thread with {thread_details['message_count']} message(s)")
        
        print("\n" + "=" * 60)
        print("🎉 ALL TESTS PASSED SUCCESSFULLY!")
        print("=" * 60)
        
        return result
        
    except HTTPException as he:
        print(f"❌ HTTP ERROR: {he.detail}")
        print(f"Status Code: {he.status_code}")
        return None
        
    except Exception as e:
        print(f"❌ UNEXPECTED ERROR: {str(e)}")
        return None

# Manual test runner - uncomment and run to test
if __name__ == "__main__":
    print("📧 Gmail Send Email Test Runner")
    print("⚠️  Make sure to fill in the test details in the test_send_email function first!")
    print("⚠️  Uncomment the line below to run the test:")
    print("# await test_send_email()")
    
    # Uncomment this line to run the test (after filling in details):
    asyncio.run(test_send_email()) 

# =========================================
# Helper: fetch new Gmail messages after a
#         Pub/Sub push notification
# =========================================

async def fetch_new_messages(email_address: str, notification_history_id: str) -> Dict[str, Any]:
    """Pull messages added between the previous stored history ID and *notification_history_id*."""

    # 1. Find bot + last stored history
    cfg_resp = (
        supabase.table("gmail_configs")
        .select("bot_id, watch_history_id")
        .eq("email_address", email_address)
        .single()
        .execute()
    )
    if not cfg_resp.data:
        raise HTTPException(status_code=404, detail=f"No bot linked to Gmail address {email_address}")

    bot_id = cfg_resp.data["bot_id"]
    prev_history_id = cfg_resp.data.get("watch_history_id")

    start_id = None
    if prev_history_id and str(prev_history_id).isdigit():
        start_id = str(prev_history_id)
    elif str(notification_history_id).isdigit():
        # first run – use notification_history_id - 1
        start_id = str(int(notification_history_id) - 1)
    else:
        start_id = str(notification_history_id)

    # 2. Get credentials
    credentials = await get_gmail_credentials(bot_id)
    gmail_service = build("gmail", "v1", credentials=credentials)

    # 3. Fetch history (paginate if nextPageToken present)
    message_ids: List[str] = []
    page_token = None
    while True:
        try:
            history_req = gmail_service.users().history().list(
                userId="me",
                startHistoryId=start_id,
                maxResults=100,
                pageToken=page_token,
            )
            history_resp = history_req.execute()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Gmail history fetch failed: {e}")

        for hist_item in history_resp.get("history", []):
            if "messagesAdded" in hist_item:
                for added in hist_item["messagesAdded"]:
                    message_ids.append(added["message"]["id"])
            if "messages" in hist_item:
                for m in hist_item["messages"]:
                    message_ids.append(m["id"])

        page_token = history_resp.get("nextPageToken")
        if not page_token:
            break

    message_ids = list(dict.fromkeys(message_ids))  # dedupe, preserve order
    print(f"🆕 message IDs found: {message_ids}")

    # 4. Pull full messages
    messages: List[Dict[str, Any]] = []
    for msg_id in message_ids:
        try:
            msg = gmail_service.users().messages().get(userId="me", id=msg_id, format="full").execute()
        except Exception as fetch_err:
            print(f"⚠️ Failed to fetch message {msg_id}: {fetch_err}")
            continue

        headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}

        # Helper to walk parts recursively
        def _extract_body(payload):
            if "parts" in payload:
                for p in payload["parts"]:
                    res = _extract_body(p)
                    if res:
                        return res
            mime_type = payload.get("mimeType", "")
            body_data = payload.get("body", {}).get("data")
            if not body_data:
                return None
            import base64, re, html
            try:
                decoded = base64.urlsafe_b64decode(body_data + "==").decode("utf-8", errors="ignore")
            except Exception:
                return None
            if mime_type == "text/plain":
                return decoded
            if mime_type == "text/html":
                # Strip HTML tags quickly
                text = re.sub(r"<[^>]+>", " ", decoded)
                text = html.unescape(text)
                return re.sub(r"\s+", " ", text).strip()
            return None

        raw_body = _extract_body(msg.get("payload", {})) or msg.get("snippet", "")

        def _clean_reply(text: str) -> str:
            import re
            # Strip everything after common reply separators
            patterns = [
                r"\nOn .*wrote:$",               # "On DATE, NAME wrote:"
                r"^>.*$",                        # quoted lines starting with >
                r"^From: .*",                   # From: header in body
            ]
            lines = text.splitlines()
            cleaned_lines = []
            for line in lines:
                # stop if matches first pattern
                if re.match(r"^On .* wrote:$", line):
                    break
                if line.startswith('>'):
                    continue
                cleaned_lines.append(line)
            cleaned = "\n".join(cleaned_lines).strip()
            # Collapse multiple blank lines
            cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
            return cleaned

        body_text = _clean_reply(raw_body)

        messages.append({
            "id": msg["id"],
            "thread_id": msg["threadId"],
            "body": body_text,
            "from": headers.get("from", ""),
            "to": headers.get("to", ""),
            "subject": headers.get("subject", ""),
            "date": headers.get("date", ""),
            "internal_date": msg.get("internalDate"),
            "label_ids": msg.get("labelIds", []),
        })

    # 5. Store new history ID for next invocation
    supabase.table("gmail_configs").update({"watch_history_id": str(notification_history_id)}).eq("bot_id", bot_id).execute()

    return {"bot_id": bot_id, "messages": messages}

# =========================================
# Helper: map Gmail thread_id -> conversation_id
# =========================================


async def map_thread_to_conversation(thread_id: str) -> Optional[str]:
    """Return conversation_id associated with a Gmail thread_id.

    Strategy: look up follow_up_emails.thread_id → get follow_up_queue_id → get conversation_id.
    Returns None if no mapping found.
    """

    # Find any email we previously sent that uses this thread
    email_resp = (
        supabase.table("follow_up_emails")
        .select("follow_up_queue_id")
        .eq("thread_id", thread_id)
        .limit(1)
        .execute()
    )

    if not email_resp.data:
        return None

    queue_id = email_resp.data[0]["follow_up_queue_id"]

    queue_resp = (
        supabase.table("follow_up_queue")
        .select("conversation_id")
        .eq("id", queue_id)
        .single()
        .execute()
    )

    if not queue_resp.data:
        return None

    return queue_resp.data["conversation_id"]

# =========================================
# Helper: insert reply into messages table and broadcast
# =========================================

async def insert_reply_as_chat_message(conversation_id: str, content: str, thread_id: str, gmail_message_id: str):
    """Insert an incoming email reply into messages table and broadcast via websocket."""

    from app.api.routes.chat import broadcast_to_all_connections  # local import to avoid circular

    # ----------------------------------------------------
    # Avoid storing duplicate "email_reply" messages
    # ----------------------------------------------------
    try:
        duplicate_check = (
            supabase.table("messages")
            .select("id")
            .eq("conversation_id", conversation_id)
            .eq("role", "user")
            .eq("status", "email_reply")
            .eq("content", content)
            .limit(1)
            .execute()
        )

        if duplicate_check.data:
            print(f"🔄 Duplicate email_reply already stored for conversation {conversation_id}, skipping.")
            return  # Skip broadcasting as it's already stored
        
        insert_resp = (
            supabase.table("messages").insert({
                "conversation_id": conversation_id,
                "content": content,
                "role": "user",
                "status": "email_reply",
                "read": True,
                "created_at": datetime.utcnow().isoformat(),
            }).execute()
        )

        if not insert_resp.data:
            print(f"❌ Failed to insert email reply into messages for conversation {conversation_id}")
            return

        message_id = insert_resp.data[0]["id"]
    except Exception as dup_err:
        print(f"⚠️ Error checking/inserting duplicate email_reply: {dup_err}")
        return
    # End duplicate handling and insertion

    # update conversation timestamp & status -> human (handoff)
    supabase.table("conversations").update({
        "updated_at": datetime.utcnow().isoformat(),
        "status": "human",
    }).eq("id", conversation_id).execute()

    # broadcast to websocket clients (if any)
    await broadcast_to_all_connections(conversation_id, {
        "type": "message",
        "id": message_id,
        "content": content,
        "role": "user",
        "status": "email_reply",
        "timestamp": datetime.utcnow().isoformat(),
    })

    print(f"✅ Stored and broadcasted email reply {gmail_message_id} in conversation {conversation_id}")

# =========================================
# Helper: cancel remaining follow-ups
# =========================================


def cancel_pending_followups(conversation_id: str):
    """Mark follow_up_queue items for this conversation as cancelled if not yet executed."""

    now_iso = datetime.utcnow().isoformat()

    try:

        follow_up_queue_response = (
            supabase.table("follow_up_queue")
            .select("id")
            .eq("conversation_id", conversation_id)
            .execute()
        )
        
        # cancel queue items with future due_date and not already cancelled/completed
        follow_up_queue_update_response = (
            supabase.table("follow_up_queue")
            .update({"status": "cancelled", "updated_at": now_iso})
            .eq("conversation_id", conversation_id)
            .gt("due_date", now_iso)
            .execute()
        )

        follow_up_emails_update_response = (
            supabase.table("follow_up_emails")
            .update({"delivery_status": "cancelled", "updated_at": now_iso})
            .eq("follow_up_queue_id", follow_up_queue_response.data[0]["id"]).eq("delivery_status", "pending")
            .execute()
        )
        if follow_up_queue_update_response.data:
            print(f"🛑 Cancelled {len(follow_up_queue_update_response.data)} follow-up queue item(s) for conversation {conversation_id}")
        if follow_up_emails_update_response.data:
            print(f"🛑 Cancelled {len(follow_up_emails_update_response.data)} follow-up emails for conversation {conversation_id}")
    except Exception as e:
        print(f"⚠️ Failed to cancel follow-ups for conversation {conversation_id}: {e}")

# -------------------------------------------------------------
# Gmail Pub/Sub push webhook – receives notifications when
# something in a watched mailbox changes (new email, label etc.)
# -------------------------------------------------------------

class PubSubPushBody(BaseModel):
    """Google Pub/Sub push message envelope"""

    message: Dict[str, Any]
    subscription: str


async def _process_pubsub_notification(email_address: str, history_id: str):
    """Background task: fetch new messages for the given history_id.
    For now this is a stub that simply logs; next tasks will
    implement full fetching/cancellation logic."""
    print(f"[GMAIL WEBHOOK] Received notification – emailAddress={email_address} historyId={history_id}")

    try:
        data = await fetch_new_messages(email_address, history_id)
    except HTTPException as he:
        print(f"❌ fetch_new_messages error: {he.detail}")
        return
    except Exception as err:
        print(f"❌ Unexpected error fetching messages: {err}")
        return

    for msg in data["messages"]:
        print(f"🔗 Processing Gmail msg {msg['id']} thread {msg['thread_id']}")
        # Ignore emails that originated from our own mailbox (label "SENT")
        if "SENT" in msg.get("label_ids", []):
            print(f"↩️ Skipping self-sent email {msg['id']} (label SENT)")
            continue

        conv_id = await map_thread_to_conversation(msg["thread_id"])
        if not conv_id:
            print(f"⚠️ No conversation mapping for thread {msg['thread_id']}, skipping.")
            continue

        # Try to get plaintext body; fallback to snippet
        content = msg.get("body", "(no content)")

        await insert_reply_as_chat_message(conv_id, content, msg["thread_id"], msg["id"])

        cancel_pending_followups(conv_id)


@router.post("/webhook")
async def gmail_webhook(body: PubSubPushBody):
    """Endpoint called by Google Pub/Sub (HTTP push) when Gmail mailbox changes.

    Google sends a JSON body of the form:
    {
      "message": {
        "data": "base64-encoded string",
        "messageId": "...",
        "publishTime": "..."
      },
      "subscription": "projects/…/subscriptions/…"
    }
    The data field decodes to: {"emailAddress": "...", "historyId": "..."}
    We parse it and trigger background processing.
    """
    try:
        envelope = body.message
        if "data" not in envelope:
            raise ValueError("Missing data field in Pub/Sub message")

        decoded_bytes = base64.b64decode(envelope["data"])
        decoded_str = decoded_bytes.decode()
        payload = json.loads(decoded_str)

        email_address = payload.get("emailAddress")
        history_id = payload.get("historyId")

        if not email_address or not history_id:
            raise ValueError("emailAddress or historyId missing in decoded payload")

        # Process asynchronously (don’t block Google’s retry logic)
        asyncio.create_task(_process_pubsub_notification(email_address, history_id))

        # Acknowledge immediately – Google treats 2xx as success
        return {"status": "accepted"}

    except Exception as e:
        # Log and let Google retry by returning 500
        print(f"Error handling Gmail webhook: {e}")
        raise HTTPException(status_code=500, detail="Failed to process notification") 