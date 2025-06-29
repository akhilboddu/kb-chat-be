from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from decimal import Decimal


class SubscriptionResponse(BaseModel):
    id: str
    user_id: str
    plan_id: str | None = None
    plan_name: str
    status: str
    price: float | None = None
    billing_cycle: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    auto_renew: bool | None = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    stripe_subscription_id: Optional[str] = None
    stripe_customer_id: Optional[str] = None


class BotResponse(BaseModel):
    id: str
    name: str
    company: str
    created_at: datetime
    bot_type: Optional[str] = None
    active_conversations: Optional[int] = 0
    is_live: Optional[bool] = False
    onboarding_status: Optional[str] = None


class PlanLimits(BaseModel):
    """Subscription plan limits"""
    maxMessages: int = Field(description="Maximum messages allowed")
    maxConversations: int = Field(description="Maximum conversations allowed")
    maxBots: int = Field(description="Maximum total bots allowed")
    maxLiveBots: int = Field(description="Maximum live bots allowed")
    maxKnowledgeSources: int = Field(description="Maximum knowledge sources per bot")
    maxTeamMembers: int = Field(description="Maximum team members allowed")


class Plan(BaseModel):
    """Subscription plan model"""
    id: str
    key: str = Field(description="Unique plan identifier (TRIAL, STARTER, PRO, ENTERPRISE)")
    name: str
    price_cents: Optional[int] = Field(None, description="Price in cents")
    currency: str = "usd"
    limits: PlanLimits = Field(description="Plan usage limits")
    features: Dict[str, Any] = Field(default_factory=dict, description="Additional features")
    is_active: bool = True
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }


class SubscriptionOut(BaseModel):
    id: str
    user_id: str
    plan_name: str
    plan_id: Optional[str] = None  # Keep for backward compatibility
    plan: Optional[Plan] = None     # New field with full plan details
    price: float
    billing_cycle: str
    status: str
    start_date: datetime
    end_date: Optional[datetime] = None
    auto_renew: bool = True
    payment_reference: Optional[str] = None
    created_at: Optional[datetime] = None


class DashboardStatsResponse(BaseModel):
    """Enhanced dashboard response with plan limits"""
    bots: List[Dict[str, Any]]
    total_messages: int
    total_conversations: int
    active_conversations: int
    team_member_count: int
    subscription: Optional[SubscriptionResponse] = None  # Use SubscriptionResponse for backward compatibility
    plan_limits: Optional[PlanLimits] = None  # New field for easy access to limits