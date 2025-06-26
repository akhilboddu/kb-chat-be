from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class GmailConfigModel(BaseModel):
    """Model for Gmail configuration"""
    bot_id: str
    is_enabled: bool = False
    email_address: Optional[str] = None
    refresh_token: Optional[str] = None
    access_token: Optional[str] = None
    token_expires_at: Optional[datetime] = None
    scopes: Optional[str] = "https://www.googleapis.com/auth/gmail.modify"

class GmailAuthRequest(BaseModel):
    """Model for Gmail OAuth request"""
    bot_id: str
    code: str
    redirect_uri: str

class GmailAuthResponse(BaseModel):
    """Model for Gmail OAuth response"""
    status: str
    message: str
    email_address: Optional[str] = None
    is_connected: bool = False

class GmailDisconnectRequest(BaseModel):
    """Model for Gmail disconnect request"""
    bot_id: str 