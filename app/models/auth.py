from pydantic import BaseModel, EmailStr, validator
from typing import Optional
from datetime import datetime


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str

    @validator('password')
    def password_min_length(cls, v):
        if len(v) < 6:
            raise ValueError('Password must be at least 6 characters long')
        return v


class UserRegisterRequest(BaseModel):
    email: EmailStr
    password: str

    @validator('password')
    def password_strength(cls, v):
        if len(v) < 6:
            raise ValueError('Password must be at least 6 characters long')
        return v


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    user_id: str
    email: str
    expires_in: int
    token_type: str = "Bearer"


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    new_password: str
    token: str  # Changed from access_token to token for clarity

    @validator('new_password')
    def password_min_length(cls, v):
        if len(v) < 6:
            raise ValueError('Password must be at least 6 characters long')
        return v


class GoogleAuthResponse(BaseModel):
    oauth_url: str


class EmailConfirmationRequest(BaseModel):
    access_token: str
    refresh_token: str
    type: Optional[str] = None


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class UserInfo(BaseModel):
    id: str
    email: str
    created_at: Optional[datetime] = None
    email_confirmed_at: Optional[datetime] = None