from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from uuid import UUID
import secrets

class WhatsAppEmbeddedSignupRequest(BaseModel):
    """Request from WhatsApp Embedded Signup callback"""
    code: str
    redirect_uri: str
    appid: Optional[str] = None
    phone_number_id: Optional[str] = None
    waba_id: Optional[str] = None
    business_id: Optional[str] = None
    status: str = "success"
    message: Optional[str] = None

class WhatsAppSetupResponse(BaseModel):
    """Response after successful WhatsApp setup"""
    bot_id: UUID
    access_token: Optional[str] = None
    phone_number_id: Optional[str] = None
    waba_id: Optional[str] = None
    business_id: Optional[str] = None
    status: str = "success"
    message: str

class WhatsAppConfig(BaseModel):
    """WhatsApp configuration model"""
    id: Optional[UUID] = None
    bot_id: UUID
    business_account_id: str
    phone_number_id: Optional[str] = None
    webhook_verify_token: str
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class WhatsAppConfigResponse(BaseModel):
    """WhatsApp configuration response (without sensitive data)"""
    bot_id: UUID
    business_account_id: str
    phone_number_id: Optional[str] = None
    webhook_url: str
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class WhatsAppTestMessageRequest(BaseModel):
    """Request model for sending a test WhatsApp message"""
    phone_number: str = Field(..., description="The recipient's phone number with country code (e.g., +1234567890)")
    message: str = Field(..., description="The message text to send") 