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
from typing import Optional, Dict, Any
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
    
    # Create message
    if body_html and body_text:
        # Multipart message with both HTML and text
        message = email.mime.multipart.MIMEMultipart('alternative')
        text_part = email.mime.text.MIMEText(body_text, 'plain')
        html_part = email.mime.text.MIMEText(body_html, 'html')
        message.attach(text_part)
        message.attach(html_part)
    elif body_html:
        # HTML only
        message = email.mime.text.MIMEText(body_html, 'html')
    else:
        # Text only (fallback)
        message = email.mime.text.MIMEText(body_text or subject, 'plain')
    
    message['To'] = to
    message['Subject'] = subject
    
    # Add threading headers if replying
    if reply_to_message_id:
        message['In-Reply-To'] = reply_to_message_id
        message['References'] = reply_to_message_id
    
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
        
        # Validate email content
        if not email_request.body_html and not email_request.body_text:
            raise HTTPException(status_code=400, detail="Either body_html or body_text must be provided")
        
        # Get Gmail credentials
        credentials = await get_gmail_credentials(bot_id)
        
        # Build Gmail service
        gmail_service = build('gmail', 'v1', credentials=credentials)
        
        # Create email message
        raw_message = create_email_message(
            to=email_request.to,
            subject=email_request.subject,
            body_html=email_request.body_html,
            body_text=email_request.body_text,
            reply_to_message_id=email_request.reply_to_message_id,
            reply_to_thread_id=email_request.reply_to_thread_id
        )
        
        # Prepare message body for Gmail API
        message_body = {'raw': raw_message}
        
        # Add thread ID if replying
        if email_request.reply_to_thread_id:
            message_body['threadId'] = email_request.reply_to_thread_id
        
        # Send the email
        sent_message = gmail_service.users().messages().send(
            userId='me', 
            body=message_body
        ).execute()
        
        # Get the sent message details
        message_details = gmail_service.users().messages().get(
            userId='me', 
            id=sent_message['id'],
            format='full'
        ).execute()
        
        # Extract email details
        headers = {header['name']: header['value'] for header in message_details['payload']['headers']}
        
        email_details = {
            "message_id": sent_message['id'],
            "thread_id": sent_message['threadId'],
            "label_ids": message_details.get('labelIds', []),
            "snippet": message_details.get('snippet', ''),
            "headers": {
                "to": headers.get('To', ''),
                "subject": headers.get('Subject', ''),
                "date": headers.get('Date', ''),
                "message_id": headers.get('Message-ID', ''),
                "from": headers.get('From', '')
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