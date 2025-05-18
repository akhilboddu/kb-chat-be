from fastapi import APIRouter, HTTPException, Body, Query
from .scrape import scrape_url_and_populate_kb
from app.models.scrape import ScrapeURLRequest

from app.models.base import StatusResponse
from app.models.bot import (
    AddKnowledgeRequest,
)
from app.models.scrape import ScrapeStatusResponse
from app.core import kb_manager, db_manager
from app.core.supabase_client import supabase
from fastapi import BackgroundTasks
import os
import httpx
from app.models.payment import CheckSubscriptionResponse
from datetime import datetime, timedelta
from typing import Optional

router = APIRouter(prefix="/payments", tags=["payments"])


async def update_user_subscription(user_id: str, payment_data: dict, plan_name: str):
    """Update user subscription details in Supabase"""
    try:
        # Update user metadata
        metadata_row = {
            "id": user_id,
            "payment_status": plan_name,
            "updated_at": datetime.utcnow().isoformat(),
        }

        print(metadata_row)

        supabase.table("users_metadata").upsert(metadata_row).execute()

        # Calculate subscription end date (1 month from now for monthly plans)
        end_date = datetime.utcnow() + timedelta(days=30)

        # Get the user's current subscription and mark it as inactive
        supabase.table("subscriptions").update({"status": "inactive"}).eq(
            "user_id", user_id
        ).execute()

        # Create new subscription record
        subscription_data = {
            "user_id": user_id,
            "plan_name": plan_name,
            "price": payment_data["amount"] / 100,  # Convert from kobo to NGN
            "billing_cycle": "monthly",
            "status": "active",
            "start_date": datetime.utcnow().isoformat(),
            "end_date": end_date.isoformat(),
            "payment_reference": payment_data["reference"],
        }

        supabase.table("subscriptions").insert(subscription_data).execute()

        return True
    except Exception as e:
        print(f"Error updating subscription: {str(e)}")
        return False


@router.get("/check-subscription", response_model=CheckSubscriptionResponse)
async def check_subscription(
    reference: str,
    user_id: str = Query(..., description="User ID to update subscription"),
):
    """
    Verify payment status using PayStack API and update user subscription
    """
    paystack_secret = os.getenv("PAYSTACK_SECRET_KEY")
    if not paystack_secret:
        raise HTTPException(status_code=500, detail="PayStack API key not configured")

    url = f"https://api.paystack.co/transaction/verify/{reference}"
    headers = {"Authorization": f"Bearer {paystack_secret}"}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            response_data = response.json()

            if response.status_code == 200 and response_data.get("status"):
                payment_data = response_data.get("data")

                if payment_data["status"] == "success":
                    # Determine subscription plan based on amount
                    plan_name = payment_data.get("plan_object", {}).get("name")

                    if not plan_name:
                        return {
                            "success": False,
                            "message": "Invalid payment amount. Does not match any subscription plan.",
                            "data": payment_data,
                        }

                    # Update user subscription and metadata
                    update_success = await update_user_subscription(
                        user_id, payment_data, plan_name
                    )

                    if not update_success:
                        return {
                            "success": False,
                            "message": "Payment verified but failed to update subscription. Please contact support.",
                            "data": payment_data,
                        }

                    return {
                        "success": True,
                        "message": f"Payment verified and {plan_name} subscription activated successfully",
                        "data": payment_data,
                    }
                else:
                    return {
                        "success": False,
                        "message": "Payment was not successful",
                        "data": payment_data,
                    }
            else:
                return {
                    "success": False,
                    "message": response_data.get(
                        "message", "Payment verification failed"
                    ),
                    "data": None,
                }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error verifying payment: {str(e)}",
            "data": None,
        }
