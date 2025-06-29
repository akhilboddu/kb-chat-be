#!/usr/bin/env python3
"""
Test script to verify subscription implementation
"""
import asyncio
import logging
from app.services.subscription_service import SubscriptionService
from app.core.supabase_client import supabase

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_subscription_service():
    """Test the subscription service functionality"""
    service = SubscriptionService()
    
    # Test 1: Get a user with known subscription
    logger.info("Test 1: Fetching subscription with plan details...")
    try:
        # Get any user with active subscription
        users_with_subs = supabase.table("subscriptions").select("user_id").eq("status", "active").limit(1).execute()
        
        if users_with_subs.data:
            test_user_id = users_with_subs.data[0]["user_id"]
            logger.info(f"Testing with user_id: {test_user_id}")
            
            # Test get_subscription_with_plan
            subscription = await service.get_subscription_with_plan(test_user_id)
            if subscription:
                logger.info(f"✅ Got subscription: {subscription.plan_name}")
                if subscription.plan:
                    logger.info(f"✅ Plan details: {subscription.plan.key} - {subscription.plan.name}")
                    logger.info(f"✅ Plan limits: {subscription.plan.limits}")
                else:
                    logger.warning("⚠️  No plan details in subscription")
            else:
                logger.error("❌ No subscription found")
                
            # Test get_plan_limits
            limits = await service.get_plan_limits(test_user_id)
            logger.info(f"✅ Plan limits: {limits}")
            
            # Test check_quota
            is_within, limit = await service.check_quota(test_user_id, "messages", 10)
            logger.info(f"✅ Quota check (messages=10): within_limit={is_within}, limit={limit}")
            
        else:
            logger.warning("No users with active subscriptions found")
            
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
    
    # Test 2: Test with non-existent user (should get default limits)
    logger.info("\nTest 2: Testing with non-existent user...")
    try:
        fake_user_id = "00000000-0000-0000-0000-000000000000"
        
        subscription = await service.get_subscription_with_plan(fake_user_id)
        logger.info(f"Subscription for fake user: {subscription}")
        
        limits = await service.get_plan_limits(fake_user_id)
        logger.info(f"✅ Default limits returned: {limits}")
        
        # Should be trial limits
        assert limits.maxMessages == 50
        assert limits.maxConversations == 10
        logger.info("✅ Default limits match TRIAL plan")
        
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
    
    # Test 3: Verify plans table data
    logger.info("\nTest 3: Verifying plans table...")
    try:
        plans = supabase.table("plans").select("*").execute()
        logger.info(f"Found {len(plans.data)} plans:")
        for plan in plans.data:
            logger.info(f"  - {plan['key']}: {plan['name']} (limits: {plan.get('limits', 'No limits')})")
            
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")

if __name__ == "__main__":
    asyncio.run(test_subscription_service()) 