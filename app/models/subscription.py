from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class SubscriptionResponse(BaseModel):
    id: str
    user_id: str
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


class DashboardStatsResponse(BaseModel):
    total_messages: int
    total_conversations: int
    active_conversations: int
    team_member_count: int
    subscription: Optional[SubscriptionResponse] = None
    bots: list[BotResponse] = []