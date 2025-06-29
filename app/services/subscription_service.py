import logging
from typing import Optional, Dict, Any
from datetime import datetime
from app.core.supabase_client import supabase
from app.models.subscription import SubscriptionOut, Plan, PlanLimits, DashboardStatsResponse

logger = logging.getLogger(__name__)


class SubscriptionService:
    def __init__(self):
        self.supabase = supabase
    
    def get_subscription_with_plan(self, user_id: str) -> Optional[SubscriptionOut]:
        """Get user subscription with full plan details"""
        try:
            # Query subscription with joined plan data
            subscription_data = self.supabase.table("subscriptions").select(
                "*, plan:plan_id(id, key, name, price_cents, currency, limits, features, is_active, messages, conversations, live_bots, team_members)"
            ).eq("user_id", user_id).eq("status", "active").single().execute()
            
            if subscription_data.data:
                sub_dict = subscription_data.data
                
                # Transform plan data if exists
                if sub_dict.get('plan'):
                    plan_data = sub_dict['plan']
                    
                    # Convert individual limit columns to limits object if not present
                    if 'limits' not in plan_data or not plan_data['limits']:
                        plan_data['limits'] = {
                            'maxMessages': plan_data.get('messages', 50),
                            'maxConversations': plan_data.get('conversations', 10),
                            'maxBots': plan_data.get('live_bots', 1) * 3,
                            'maxLiveBots': plan_data.get('live_bots', 1),
                            'maxKnowledgeSources': self._get_knowledge_source_limit(plan_data.get('key', 'TRIAL')),
                            'maxTeamMembers': plan_data.get('team_members', 1)
                        }
                    
                    # Create Plan object
                    sub_dict['plan'] = Plan(
                        id=plan_data['id'],
                        key=plan_data.get('key', 'TRIAL'),
                        name=plan_data.get('name', 'Trial'),
                        price_cents=plan_data.get('price_cents', 0),
                        currency=plan_data.get('currency', 'usd'),
                        limits=PlanLimits(**plan_data['limits']),
                        features=plan_data.get('features', {}),
                        is_active=plan_data.get('is_active', True)
                    )
                
                return SubscriptionOut(**sub_dict)
                
        except Exception as e:
            logger.error(f"Error getting subscription with plan: {str(e)}")
            
        return None

    def _get_knowledge_source_limit(self, plan_key: str) -> int:
        """Helper to get knowledge source limits by plan key"""
        limits_map = {
            'TRIAL': 2,
            'STARTER': 10,
            'PRO': 50,
            'ENTERPRISE': -1  # Unlimited
        }
        return limits_map.get(plan_key.upper(), 10)

    def get_plan_limits(self, user_id: str) -> Optional[PlanLimits]:
        """Get plan limits for a user"""
        subscription = self.get_subscription_with_plan(user_id)
        if subscription and subscription.plan:
            return subscription.plan.limits
        
        # Fallback to TRIAL limits if no subscription
        return PlanLimits(
            maxMessages=50,
            maxConversations=10,
            maxBots=1,
            maxLiveBots=1,
            maxKnowledgeSources=2,
            maxTeamMembers=1
        )
    
    def check_quota(self, user_id: str, resource: str, current_usage: int) -> tuple[bool, Optional[int]]:
        """
        Check if user has exceeded quota for a resource
        Returns: (is_within_limit, limit_value)
        """
        limits = self.get_plan_limits(user_id)
        if not limits:
            return True, None  # No limits found, allow by default
        
        limit_map = {
            'messages': limits.maxMessages,
            'conversations': limits.maxConversations,
            'bots': limits.maxBots,
            'live_bots': limits.maxLiveBots,
            'knowledge_sources': limits.maxKnowledgeSources,
            'team_members': limits.maxTeamMembers
        }
        
        limit = limit_map.get(resource)
        if limit is None or limit == -1:  # -1 means unlimited
            return True, None
            
        return current_usage < limit, limit
