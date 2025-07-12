import logging
from typing import Optional, Dict, Any
from datetime import datetime
from app.core.supabase_client import supabase
from app.models.subscription import SubscriptionOut, Plan, PlanLimits, DashboardStatsResponse
from app.config.subscription_limits import get_plan_limits, SUBSCRIPTION_LIMITS

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
        plan_limits = get_plan_limits(plan_key)
        return plan_limits.get("maxKnowledgeSources", 2)

    def get_plan_limits(self, user_id: str) -> Optional[PlanLimits]:
        """Get plan limits for a user"""
        subscription = self.get_subscription_with_plan(user_id)
        if subscription and subscription.plan:
            return subscription.plan.limits
        
        # Fallback to TRIAL limits if no subscription
        trial_limits = get_plan_limits("TRIAL")
        return PlanLimits(
            maxMessages=trial_limits["maxMessages"],
            maxConversations=trial_limits["maxConversations"],
            maxBots=trial_limits["maxBots"],
            maxLiveBots=trial_limits["maxLiveBots"],
            maxKnowledgeSources=trial_limits["maxKnowledgeSources"],
            maxTeamMembers=trial_limits["maxTeamMembers"]
        )

    # ------------------------------------------------------------------
    # New helpers to fetch limits directly from a plan id (when we already
    # know the user's active plan, e.g. embedded in the JWT token).
    # ------------------------------------------------------------------

    def get_plan_limits_by_plan_id(self, plan_id: str | None) -> Optional[PlanLimits]:
        """Return PlanLimits for a specific plan id.

        Args:
            plan_id: UUID of the plan in the `plans` table.

        Returns:
            PlanLimits instance or ``None`` if not found / error.
        """
        if not plan_id:
            return None

        try:
            plan_resp = (
                self.supabase
                .table("plans")
                .select("key, limits, messages, conversations, live_bots, team_members")
                .eq("id", plan_id)
                .single()
                .execute()
            )

            if not plan_resp.data:
                return None

            plan = plan_resp.data

            # Ensure we always have a limits object
            limits_dict = plan.get("limits") or {
                "maxMessages": plan.get("messages", 50),
                "maxConversations": plan.get("conversations", 10),
                "maxBots": plan.get("live_bots", 1) * 3,
                "maxLiveBots": plan.get("live_bots", 1),
                "maxKnowledgeSources": self._get_knowledge_source_limit(plan.get("key", "TRIAL")),
                "maxTeamMembers": plan.get("team_members", 1),
            }

            return PlanLimits(**limits_dict)

        except Exception as e:
            logger.error(f"Error fetching plan limits for plan_id={plan_id}: {e}")
            return None

    # ------------------------------------------------------------------
    # Updated quota check that can work with either a user_id OR a known
    # plan_id that was embedded in the auth token (saves a DB round-trip
    # and avoids issues when user_id mappings differ).
    # ------------------------------------------------------------------

    def check_quota(
        self,
        user_id: str,
        resource: str,
        current_usage: int,
        *,
        plan_id: str | None = None,
    ) -> tuple[bool, Optional[int]]:
        """Check if usage is within limits.

        If *plan_id* is provided we fetch limits directly from that plan;
        otherwise we fall back to looking up the user's active subscription.
        """

        limits: Optional[PlanLimits]

        if plan_id:
            limits = self.get_plan_limits_by_plan_id(plan_id)
        else:
            limits = self.get_plan_limits(user_id)

        if not limits:
            return True, None

        limit_map = {
            "messages": limits.maxMessages,
            "conversations": limits.maxConversations,
            "bots": limits.maxBots,
            "live_bots": limits.maxLiveBots,
            "knowledge_sources": limits.maxKnowledgeSources,
            "team_members": limits.maxTeamMembers,
        }

        limit = limit_map.get(resource)
        if limit is None or limit == -1:
            return True, None

        return current_usage < limit, limit
