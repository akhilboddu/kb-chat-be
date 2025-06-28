from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime


class UserMetadata(BaseModel):
    """User metadata structure that matches Supabase Auth user_metadata"""
    display_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    payment_status: Optional[str] = "TRIAL"  # TRIAL, STARTER, PRO, ENTERPRISE


class UserProfileUpdate(BaseModel):
    """Model for updating user profile"""
    display_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None


class UserProfileResponse(BaseModel):
    """Response model for user profile"""
    id: str
    display_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    email: EmailStr
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    payment_status: str = "TRIAL"
    live_bot_count: int = 0


class ChangePasswordRequest(BaseModel):
    """Request model for password change"""
    new_password: str
    confirm_password: str