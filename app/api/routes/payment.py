from fastapi import APIRouter, HTTPException, Body, Query, Request
from .scrape import scrape_url_and_populate_kb
from app.models.scrape import ScrapeURLRequest

from app.models.base import StatusResponse
from app.models.bot import (
    AddKnowledgeRequest,
)
from app.models.scrape import ScrapeStatusResponse
from app.core import kb_manager, supabase_metadata_manager as db_manager
from app.core.supabase_client import supabase
from fastapi import BackgroundTasks
import os
import httpx
from app.models.payment import CheckSubscriptionResponse
from datetime import datetime, timedelta
from typing import Optional
import uuid
from app.services.auth_service import get_user_from_token
from app.models.payment import PaymentMethodResponse, PaymentMethodCreate, InvoiceResponse

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

# ---------------------------------------------
# Utility
# ---------------------------------------------

def convert_user_id_to_uuid(user_id: str) -> str:
    """Convert Google OAuth numeric ID to deterministic UUID so it matches DB."""
    if str(user_id).isdigit():
        namespace = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
        return str(uuid.uuid5(namespace, f"google_user_{user_id}"))
    return user_id

# ---------------------------------------------
# Payment-methods endpoints
# ---------------------------------------------

@router.get("/methods", response_model=list[PaymentMethodResponse])
async def list_payment_methods(request: Request):
    """Return all payment methods for the current user (default first)."""
    # Authenticate via secure session cookie
    auth_token = request.cookies.get("auth_token")
    if not auth_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        user = get_user_from_token(auth_token)
    except Exception as ex:
        raise HTTPException(status_code=401, detail="Invalid token") from ex

    user_uuid = convert_user_id_to_uuid(user["id"])

    try:
        result = (
            supabase.table("payment_methods")
            .select("*")
            .eq("user_id", user_uuid)
            .order("is_default", desc=True)
            .execute()
        )
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"Database error: {ex}") from ex

    return result.data or []

@router.post("/methods", response_model=PaymentMethodResponse)
async def create_payment_method(payload: PaymentMethodCreate, request: Request):
    """Insert a new payment method for the user."""
    auth_token = request.cookies.get("auth_token")
    if not auth_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        user = get_user_from_token(auth_token)
    except Exception as ex:
        raise HTTPException(status_code=401, detail="Invalid token") from ex

    user_uuid = convert_user_id_to_uuid(user["id"])

    insert_data = {
        "user_id": user_uuid,
        "provider": "demo",  # Replace with real provider identifier in production
        "last_four": payload.last_four,
        "card_type": payload.card_type,
        "exp_month": payload.exp_month,
        "exp_year": payload.exp_year,
        "is_default": payload.is_default,
    }

    try:
        result = (
            supabase.table("payment_methods")
            .insert(insert_data)
            .select("*")
            .single()
            .execute()
        )
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"Database error: {ex}") from ex

    # Optionally update users_metadata payment_status
    try:
        supabase.table("users_metadata").update({"payment_status": "ACTIVE"}).eq("id", user_uuid).execute()
    except Exception:
        pass

    return result.data

# ---------------------------------------------
# Invoices endpoint
# ---------------------------------------------

@router.get("/invoices", response_model=list[InvoiceResponse])
async def list_invoices(request: Request):
    """Return all invoices for the current user."""
    auth_token = request.cookies.get("auth_token")
    if not auth_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        user = get_user_from_token(auth_token)
    except Exception as ex:
        raise HTTPException(status_code=401, detail="Invalid token") from ex

    user_uuid = convert_user_id_to_uuid(user["id"])

    try:
        result = (
            supabase.table("invoices")
            .select("*")
            .eq("user_id", user_uuid)
            .order("invoice_date", desc=True)
            .execute()
        )
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"Database error: {ex}") from ex

    return result.data or []
