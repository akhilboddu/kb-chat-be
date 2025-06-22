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
from datetime import datetime, timedelta
from typing import Optional

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