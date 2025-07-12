"""
Centralized subscription limits configuration.
This is the single source of truth for all subscription limits across the application.
"""

from typing import Dict, Any

# Subscription tier definitions
SUBSCRIPTION_TIERS = ["TRIAL", "STARTER", "PRO", "ENTERPRISE"]

# Centralized subscription limits configuration
SUBSCRIPTION_LIMITS: Dict[str, Dict[str, Any]] = {
    "TRIAL": {
        "maxMessages": 100,
        "maxConversations": 20,
        "maxTeamMembers": 1,
        "maxLiveBots": 1,
        "maxBots": 1,
        "maxKnowledgeSources": 2,
        "advancedAnalytics": False,
        "customBranding": False,
        "showPoweredBy": True,
        "name": "Trial Plan",
        "key": "TRIAL"
    },
    "STARTER": {
        "maxMessages": 1000,
        "maxConversations": 100,
        "maxTeamMembers": 1,
        "maxLiveBots": 1,
        "maxBots": 1,
        "maxKnowledgeSources": 10,
        "advancedAnalytics": False,
        "customBranding": False,
        "showPoweredBy": True,
        "name": "deskForce Starter Plan",
        "key": "STARTER"
    },
    "PRO": {
        "maxMessages": 5000,
        "maxConversations": 500,
        "maxTeamMembers": 4,
        "maxLiveBots": 4,
        "maxBots": 12,
        "maxKnowledgeSources": 50,
        "advancedAnalytics": True,
        "customBranding": True,
        "showPoweredBy": False,
        "name": "deskForce Pro Plan",
        "key": "PRO"
    },
    "ENTERPRISE": {
        "maxMessages": 10000,
        "maxConversations": 999,
        "maxTeamMembers": 50,
        "maxLiveBots": 100,
        "maxBots": 300,
        "maxKnowledgeSources": -1,  # Unlimited
        "advancedAnalytics": True,
        "customBranding": True,
        "showPoweredBy": False,
        "price_cents": 0,  # Custom pricing
        "currency": "usd",
        "name": "Enterprise Plan",
        "key": "ENTERPRISE"
    }
}

def get_plan_limits(plan_key: str) -> Dict[str, Any]:
    """Get limits for a specific plan key."""
    return SUBSCRIPTION_LIMITS.get(plan_key.upper(), SUBSCRIPTION_LIMITS["TRIAL"])

def get_all_plans() -> Dict[str, Dict[str, Any]]:
    """Get all plan configurations."""
    return SUBSCRIPTION_LIMITS

def get_plan_names() -> Dict[str, str]:
    """Get plan names mapping."""
    return {key: plan["name"] for key, plan in SUBSCRIPTION_LIMITS.items()}

def get_plan_keys() -> list:
    """Get all plan keys."""
    return list(SUBSCRIPTION_LIMITS.keys())

# Export for easy access
__all__ = [
    "SUBSCRIPTION_LIMITS",
    "SUBSCRIPTION_TIERS", 
    "get_plan_limits",
    "get_all_plans",
    "get_plan_names",
    "get_plan_keys"
] 