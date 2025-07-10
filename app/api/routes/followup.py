from fastapi import APIRouter, HTTPException, Depends, Request, Body
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta, timezone
import os
import asyncio
from supabase import create_client, Client
from app.utils.cookie_auth import require_cookie_auth
from app.core.follow_up_email_agent import generate_follow_up_email

router = APIRouter(prefix="/followup", tags=["followup"])

# Initialize Supabase client
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(supabase_url, supabase_key)

class FollowUpQueueItem(BaseModel):
    conversation_id: str
    customer_name: str
    customer_email: str
    customer_phone: Optional[str] = None
    subject: str | None = None
    message: str | None = None
    priority: str = "medium"  # low, medium, high
    due_date: Optional[datetime] = None
    max_follow_ups: int = 3
    lead_score: Optional[int] = None
    tags: Optional[List[str]] = None

class FollowUpEmailResponse(BaseModel):
    id: str
    follow_up_queue_id: str
    email_type: str
    subject: str
    message: str
    recipient_email: str
    recipient_name: str
    scheduled_for: datetime
    delivery_status: str
    opened_at: Optional[datetime]
    clicked_at: Optional[datetime]
    bounce_reason: Optional[str]
    email_provider: Optional[str]
    email_provider_id: Optional[str]
    thread_id: Optional[str]
    metadata: Optional[dict]
    created_at: datetime

class FollowUpQueueResponse(BaseModel):
    id: str
    bot_id: str
    conversation_id: str
    customer_name: str
    customer_email: str
    customer_phone: Optional[str]
    subject: Optional[str]
    message: Optional[str]
    status: str
    priority: str
    due_date: Optional[datetime]
    created_at: datetime
    follow_up_count: int
    max_follow_ups: int
    lead_score: Optional[int]
    tags: Optional[List[str]]
    emails: Optional[List[FollowUpEmailResponse]] = []

@router.post("/queue/{bot_id}", response_model=FollowUpQueueResponse)
async def add_to_followup_queue(
    bot_id: str,
    item: FollowUpQueueItem,
    current_user: dict = Depends(require_cookie_auth)
):
    """
    Add a conversation to the follow-up queue for automated follow-ups.
    
    This endpoint allows adding conversations that need follow-up attention
    to a queue that can be processed by automated follow-up systems.
    """
    try:
        print(f"Adding to follow-up queue - bot_id: {bot_id}, user_id: {current_user.get('id')}")
        print(f"Request item: {item}")
        
        # Validate that the bot belongs to the current user
        bot_response = supabase.table("bots").select("id").eq("id", bot_id).eq("user_id", current_user["id"]).execute()
        
        print(f"Bot response: {bot_response.data}")
        
        if not bot_response.data:
            print(f"Bot not found - bot_id: {bot_id}, user_id: {current_user.get('id')}")
            raise HTTPException(status_code=404, detail="Bot not found or access denied")
        
        # Set default due date if not provided (12 hours from now)
        if not item.due_date:
            #item.due_date = datetime.utcnow() + timedelta(hours=12)
            item.due_date = datetime.now(timezone.utc) + timedelta(minutes=1)
        
        # Generate follow-up email using the AI agent
        print(f"Generating follow-up email for conversation {item.conversation_id}")
        generated_email = None
        try:
            generated_email = await generate_follow_up_email(
                bot_id=bot_id,
                conversation_id=item.conversation_id,
                previous_email_context="Th is is the first follow-up email in the conversation thread.",
                custom_instructions="Create a personalized follow-up email that shows genuine interest in the customer's needs and provides additional value."
            )
            print(f"Email generation result: {generated_email is not None}")
        except Exception as e:
            print(f"Error generating follow-up email: {e}")
            # Continue without generated email if there's an error
        
        # Use generated email content if available, otherwise use provided/default values
        email_subject = item.subject
        email_message = item.message
        
        if generated_email:
            email_subject = generated_email.get("subject", item.subject or "Follow-up from our conversation")
            email_message = generated_email.get("plain_text_body", item.message or "Thank you for your interest. I wanted to follow up on our conversation.")
            print(f"Using generated email - Subject: {email_subject[:50]}...")
        else:
            print("Using default email content")
            if not email_subject:
                email_subject = f"Follow-up: {item.customer_name}"
            if not email_message:
                email_message = f"Hi {item.customer_name}, I wanted to follow up on our conversation and see if you have any questions or need additional information."
        
        # Prepare the data for insertion
        queue_data = {
            "bot_id": bot_id,
            "conversation_id": item.conversation_id,
            "customer_name": item.customer_name,
            "customer_email": item.customer_email,
            "customer_phone": item.customer_phone,
            "subject": email_subject,
            "message": email_message,
            "status": "pending",
            "priority": item.priority,
            "due_date": item.due_date.isoformat() if item.due_date else None,
            "follow_up_count": 0,
            "max_follow_ups": item.max_follow_ups,
            "lead_score": item.lead_score,
            "tags": item.tags or [],
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }
        
        # Insert into follow_up_queue table
        response = supabase.table("follow_up_queue").insert(queue_data).execute()
        
        if not response.data:
            raise HTTPException(status_code=500, detail="Failed to add to follow-up queue")
        
        # Return the created item
        created_item = response.data[0]
        
        # Always add an email record to the follow_up_emails table
        try:
            email_record = {
                "follow_up_queue_id": created_item["id"],
                "email_type": "initial",
                "subject": email_subject or "Follow-up Email",
                "message": email_message or "Follow-up message",
                "recipient_email": item.customer_email,
                "recipient_name": item.customer_name,
                "scheduled_for": item.due_date.isoformat(),  # Schedule for the due date
                "delivery_status": "pending",  # Mark as pending until actually sent
                "email_provider": "gmail",
                "email_provider_id": None,
                "opened_at": None,
                "clicked_at": None,
                "bounce_reason": None,
                "metadata": {
                    "generated_by": "ai_agent" if generated_email else "fallback",
                    "generation_data": generated_email if generated_email else None,
                    "key_points": generated_email.get("key_points", []) if generated_email else ["Follow-up on conversation", "Offer additional support"],
                    "urgency_level": generated_email.get("urgency_level", "medium") if generated_email else "medium",
                    "follow_up_reason": generated_email.get("follow_up_reason", "") if generated_email else "Standard follow-up after conversation",
                    "call_to_action": generated_email.get("call_to_action") if generated_email else None,
                    "scheduled_send_time": item.due_date.isoformat(),
                    "scheduled_delay_hours": 12 if not item.due_date else None
                },
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat()
            }
            
            print(f"Adding email record to follow_up_emails table: {email_record['subject']}")
            email_response = supabase.table("follow_up_emails").insert(email_record).execute()
            
            if email_response.data:
                print(f"Successfully added email to database with ID: {email_response.data[0]['id']}")
            else:
                print("Failed to add email to database - no data returned")
                print(f"Email response: {email_response}")
                
        except Exception as e:
            print(f"Error adding email to database: {e}")
            print(f"Email record that failed: {email_record}")
            # Don't fail the entire operation if email recording fails
        
        # Get the email record that was created
        emails = []
        try:
            # Fetch the email we just created
            print(f"Fetching email for response: {created_item['id']}")
            email_response = supabase.table("follow_up_emails").select("*").eq("follow_up_queue_id", created_item["id"]).execute()
            print(f"Email response: {email_response.data}")
            if email_response.data:
                for email in email_response.data:
                    emails.append(FollowUpEmailResponse(
                        id=email["id"],
                        follow_up_queue_id=email["follow_up_queue_id"],
                        email_type=email["email_type"],
                        subject=email["subject"],
                        message=email["message"],
                        recipient_email=email["recipient_email"],
                        recipient_name=email["recipient_name"],
                        scheduled_for=datetime.fromisoformat(email["scheduled_for"]),
                        delivery_status=email["delivery_status"],
                        opened_at=datetime.fromisoformat(email["opened_at"]) if email["opened_at"] else None,
                        clicked_at=datetime.fromisoformat(email["clicked_at"]) if email["clicked_at"] else None,
                        bounce_reason=email["bounce_reason"],
                        email_provider=email["email_provider"],
                        email_provider_id=email["email_provider_id"],
                        metadata=email["metadata"],
                        created_at=datetime.fromisoformat(email["created_at"])
                    ))
                print(f"Successfully fetched {len(emails)} email records for response")
            else:
                print("No email records found for the queue item")
        except Exception as e:
            print(f"Error fetching email for response: {e}")
        
        return FollowUpQueueResponse(
            id=created_item["id"],
            bot_id=created_item["bot_id"],
            conversation_id=created_item["conversation_id"],
            customer_name=created_item["customer_name"],
            customer_email=created_item["customer_email"],
            customer_phone=created_item["customer_phone"],
            subject=created_item["subject"],
            message=created_item["message"],
            status=created_item["status"],
            priority=created_item["priority"],
            due_date=datetime.fromisoformat(created_item["due_date"]) if created_item["due_date"] else None,
            created_at=datetime.fromisoformat(created_item["created_at"]),
            follow_up_count=created_item["follow_up_count"],
            max_follow_ups=created_item["max_follow_ups"],
            lead_score=created_item["lead_score"],
            tags=created_item["tags"],
            emails=emails
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error adding to follow-up queue: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/queue/{bot_id}", response_model=List[FollowUpQueueResponse])
async def get_followup_queue(
    bot_id: str,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    current_user: dict = Depends(require_cookie_auth)
):
    """
    Get the follow-up queue for a specific bot with optional filtering.
    """
    try:
        # Validate that the bot belongs to the current user
        bot_response = supabase.table("bots").select("id").eq("id", bot_id).eq("user_id", current_user["id"]).execute()
        
        if not bot_response.data:
            raise HTTPException(status_code=404, detail="Bot not found or access denied")
        
        # Build the query
        query = supabase.table("follow_up_queue").select("*").eq("bot_id", bot_id)
        
        # Add filters if provided
        if status:
            query = query.eq("status", status)
        if priority:
            query = query.eq("priority", priority)
        
        # Order by due date (earliest first) and priority
        query = query.order("due_date", desc=False).order("priority", desc=True)
        
        response = query.execute()
        
        # Transform the response
        queue_items = []
        for item in response.data:
            # Get emails for this queue item
            emails_response = supabase.table("follow_up_emails").select("*").eq("follow_up_queue_id", item["id"]).order("scheduled_for", desc=False).execute()
            
            emails = []
            for email in emails_response.data:
                emails.append(FollowUpEmailResponse(
                    id=email["id"],
                    follow_up_queue_id=email["follow_up_queue_id"],
                    email_type=email["email_type"],
                    subject=email["subject"],
                    message=email["message"],
                    recipient_email=email["recipient_email"],
                    recipient_name=email["recipient_name"],
                    scheduled_for=datetime.fromisoformat(email["scheduled_for"]),
                    delivery_status=email["delivery_status"],
                    opened_at=datetime.fromisoformat(email["opened_at"]) if email["opened_at"] else None,
                    clicked_at=datetime.fromisoformat(email["clicked_at"]) if email["clicked_at"] else None,
                    bounce_reason=email["bounce_reason"],
                    email_provider=email["email_provider"],
                    email_provider_id=email["email_provider_id"],
                    thread_id=email.get("thread_id"),
                    metadata=email["metadata"],
                    created_at=datetime.fromisoformat(email["created_at"])
                ))
            
            queue_items.append(FollowUpQueueResponse(
                id=item["id"],
                bot_id=item["bot_id"],
                conversation_id=item["conversation_id"],
                customer_name=item["customer_name"],
                customer_email=item["customer_email"],
                customer_phone=item["customer_phone"],
                subject=item["subject"],
                message=item["message"],
                status=item["status"],
                priority=item["priority"],
                due_date=datetime.fromisoformat(item["due_date"]) if item["due_date"] else None,
                created_at=datetime.fromisoformat(item["created_at"]),
                follow_up_count=item["follow_up_count"],
                max_follow_ups=item["max_follow_ups"],
                lead_score=item["lead_score"],
                tags=item["tags"],
                emails=emails
            ))
        
        return queue_items
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting follow-up queue: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/queue-by-conversation", response_model=List[FollowUpQueueResponse])
async def search_followup_queue(
    conversation_id: Optional[str] = None,
    current_user: dict = Depends(require_cookie_auth)
):
    """
    Search for follow-up queue items by conversation_id.
    """
    try:
        # Build the query
        query = supabase.table("follow_up_queue").select("*, bots!inner(*)")
        
        # Add conversation_id filter if provided
        if conversation_id:
            query = query.eq("conversation_id", conversation_id)
        
        # Filter by user's bots
        query = query.eq("bots.user_id", current_user["id"])
        
        # Order by created_at (newest first)
        query = query.order("created_at", desc=True)
        
        response = query.execute()
        
        # Transform the response
        queue_items = []
        for item in response.data:
            # Get emails for this queue item
            emails_response = supabase.table("follow_up_emails").select("*").eq("follow_up_queue_id", item["id"]).order("scheduled_for", desc=False).execute()
            
            emails = []
            for email in emails_response.data:
                emails.append(FollowUpEmailResponse(
                    id=email["id"],
                    follow_up_queue_id=email["follow_up_queue_id"],
                    email_type=email["email_type"],
                    subject=email["subject"],
                    message=email["message"],
                    recipient_email=email["recipient_email"],
                    recipient_name=email["recipient_name"],
                    scheduled_for=datetime.fromisoformat(email["scheduled_for"]),
                    delivery_status=email["delivery_status"],
                    opened_at=datetime.fromisoformat(email["opened_at"]) if email["opened_at"] else None,
                    clicked_at=datetime.fromisoformat(email["clicked_at"]) if email["clicked_at"] else None,
                    bounce_reason=email["bounce_reason"],
                    email_provider=email["email_provider"],
                    email_provider_id=email["email_provider_id"],
                    thread_id=email.get("thread_id"),
                    metadata=email["metadata"],
                    created_at=datetime.fromisoformat(email["created_at"])
                ))
            
            queue_items.append(FollowUpQueueResponse(
                id=item["id"],
                bot_id=item["bot_id"],
                conversation_id=item["conversation_id"],
                customer_name=item["customer_name"],
                customer_email=item["customer_email"],
                customer_phone=item["customer_phone"],
                subject=item["subject"],
                message=item["message"],
                status=item["status"],
                priority=item["priority"],
                due_date=datetime.fromisoformat(item["due_date"]) if item["due_date"] else None,
                created_at=datetime.fromisoformat(item["created_at"]),
                follow_up_count=item["follow_up_count"],
                max_follow_ups=item["max_follow_ups"],
                lead_score=item["lead_score"],
                tags=item["tags"],
                emails=emails
            ))
        
        return queue_items
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error searching follow-up queue: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/queue-item/{queue_id}", response_model=FollowUpQueueResponse)
async def get_followup_queue_item(
    queue_id: str,
    current_user: dict = Depends(require_cookie_auth)
):
    """
    Get a specific follow-up queue item by ID.
    """
    try:
        # Get the queue item
        queue_response = supabase.table("follow_up_queue").select("*, bots!inner(*)").eq("id", queue_id).execute()
        
        if not queue_response.data:
            raise HTTPException(status_code=404, detail="Follow-up queue item not found")
        
        queue_item = queue_response.data[0]
        
        # Verify bot ownership
        if queue_item["bots"]["user_id"] != current_user["id"]:
            raise HTTPException(status_code=404, detail="Follow-up queue item not found or access denied")
        
        # Get emails for this queue item
        emails_response = supabase.table("follow_up_emails").select("*").eq("follow_up_queue_id", queue_id).order("scheduled_for", desc=False).execute()
        
        emails = []
        for email in emails_response.data:
            emails.append(FollowUpEmailResponse(
                id=email["id"],
                follow_up_queue_id=email["follow_up_queue_id"],
                email_type=email["email_type"],
                subject=email["subject"],
                message=email["message"],
                recipient_email=email["recipient_email"],
                recipient_name=email["recipient_name"],
                scheduled_for=datetime.fromisoformat(email["scheduled_for"]),
                delivery_status=email["delivery_status"],
                opened_at=datetime.fromisoformat(email["opened_at"]) if email["opened_at"] else None,
                clicked_at=datetime.fromisoformat(email["clicked_at"]) if email["clicked_at"] else None,
                bounce_reason=email["bounce_reason"],
                email_provider=email["email_provider"],
                email_provider_id=email["email_provider_id"],
                thread_id=email.get("thread_id"),
                metadata=email["metadata"],
                created_at=datetime.fromisoformat(email["created_at"])
            ))
        
        return FollowUpQueueResponse(
            id=queue_item["id"],
            bot_id=queue_item["bot_id"],
            conversation_id=queue_item["conversation_id"],
            customer_name=queue_item["customer_name"],
            customer_email=queue_item["customer_email"],
            customer_phone=queue_item["customer_phone"],
            subject=queue_item["subject"],
            message=queue_item["message"],
            status=queue_item["status"],
            priority=queue_item["priority"],
            due_date=datetime.fromisoformat(queue_item["due_date"]) if queue_item["due_date"] else None,
            created_at=datetime.fromisoformat(queue_item["created_at"]),
            follow_up_count=queue_item["follow_up_count"],
            max_follow_ups=queue_item["max_follow_ups"],
            lead_score=queue_item["lead_score"],
            tags=queue_item["tags"],
            emails=emails
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting follow-up queue item: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.put("/queue/{queue_id}/status")
async def update_followup_status(
    queue_id: str,
    status: str,
    current_user: dict = Depends(require_cookie_auth)
):
    """
    Update the status of a follow-up queue item.
    """
    try:
        # Validate status
        valid_statuses = ["pending", "in_progress", "completed", "overdue", "cancelled"]
        if status not in valid_statuses:
            raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}")
        
        # Get the queue item to verify ownership
        queue_response = supabase.table("follow_up_queue").select("bot_id").eq("id", queue_id).execute()
        
        if not queue_response.data:
            raise HTTPException(status_code=404, detail="Follow-up queue item not found")
        
        bot_id = queue_response.data[0]["bot_id"]
        
        # Verify bot ownership
        bot_response = supabase.table("bots").select("id").eq("id", bot_id).eq("user_id", current_user["id"]).execute()
        
        if not bot_response.data:
            raise HTTPException(status_code=404, detail="Bot not found or access denied")
        
        # Update the status
        update_data = {
            "status": status,
            "updated_at": datetime.utcnow().isoformat()
        }
        
        # If marking as completed, increment follow_up_count
        if status == "completed":
            current_item = supabase.table("follow_up_queue").select("follow_up_count").eq("id", queue_id).execute()
            if current_item.data:
                update_data["follow_up_count"] = current_item.data[0]["follow_up_count"] + 1
        
        response = supabase.table("follow_up_queue").update(update_data).eq("id", queue_id).execute()
        
        if not response.data:
            raise HTTPException(status_code=500, detail="Failed to update follow-up status")
        
        return {"message": "Follow-up status updated successfully", "status": status}
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error updating follow-up status: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.delete("/queue/{queue_id}")
async def remove_from_followup_queue(
    queue_id: str,
    current_user: dict = Depends(require_cookie_auth)
):
    """
    Remove an item from the follow-up queue.
    """
    try:
        # Get the queue item to verify ownership
        queue_response = supabase.table("follow_up_queue").select("bot_id").eq("id", queue_id).execute()
        
        if not queue_response.data:
            raise HTTPException(status_code=404, detail="Follow-up queue item not found")
        
        bot_id = queue_response.data[0]["bot_id"]
        
        # Verify bot ownership
        bot_response = supabase.table("bots").select("id").eq("id", bot_id).eq("user_id", current_user["id"]).execute()
        
        if not bot_response.data:
            raise HTTPException(status_code=404, detail="Bot not found or access denied")
        
        # Delete the queue item
        response = supabase.table("follow_up_queue").delete().eq("id", queue_id).execute()
        
        return {"message": "Follow-up queue item removed successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error removing from follow-up queue: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

class SendFollowUpEmailRequest(BaseModel):
    email_type: str = "follow_up_1"  # initial, follow_up_1, follow_up_2, follow_up_3, custom
    subject: str
    message: str
    email_provider: str = "gmail"  # gmail, deskforce, etc.
    email_provider_id: Optional[str] = None
    metadata: Optional[dict] = None

@router.post("/queue/{queue_id}/send-email", response_model=FollowUpEmailResponse)
async def send_followup_email(
    queue_id: str,
    email_data: SendFollowUpEmailRequest,
    current_user: dict = Depends(require_cookie_auth)
):
    """
    Send a follow-up email and record it in the follow_up_emails table.
    """
    try:
        # Get the queue item to verify ownership
        queue_response = supabase.table("follow_up_queue").select("*, bots!inner(*)").eq("id", queue_id).execute()
        
        if not queue_response.data:
            raise HTTPException(status_code=404, detail="Follow-up queue item not found")
        
        queue_item = queue_response.data[0]
        bot_id = queue_item["bot_id"]
        
        # Verify bot ownership
        if queue_item["bots"]["user_id"] != current_user["id"]:
            raise HTTPException(status_code=404, detail="Bot not found or access denied")
        
        # Check if we haven't exceeded max_follow_ups
        if queue_item["follow_up_count"] >= queue_item["max_follow_ups"]:
            raise HTTPException(status_code=400, detail="Maximum follow-up count reached")
        
        # Prepare email data for insertion
        email_record = {
            "follow_up_queue_id": queue_id,
            "email_type": email_data.email_type,
            "subject": email_data.subject,
            "message": email_data.message,
            "recipient_email": queue_item["customer_email"],
            "recipient_name": queue_item["customer_name"],
            "scheduled_for": datetime.utcnow().isoformat(),
            "delivery_status": "sent",
            "email_provider": email_data.email_provider,
            "email_provider_id": email_data.email_provider_id,
            "metadata": email_data.metadata or {},
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }
        
        # Insert email record
        email_response = supabase.table("follow_up_emails").insert(email_record).execute()
        
        if not email_response.data:
            raise HTTPException(status_code=500, detail="Failed to record email")
        
        created_email = email_response.data[0]
        
        # Update queue item status to in_progress if it was pending
        if queue_item["status"] == "pending":
            supabase.table("follow_up_queue").update({
                "status": "in_progress",
                "updated_at": datetime.utcnow().isoformat()
            }).eq("id", queue_id).execute()
        
        return FollowUpEmailResponse(
            id=created_email["id"],
            follow_up_queue_id=created_email["follow_up_queue_id"],
            email_type=created_email["email_type"],
            subject=created_email["subject"],
            message=created_email["message"],
            recipient_email=created_email["recipient_email"],
            recipient_name=created_email["recipient_name"],
            scheduled_for=datetime.fromisoformat(created_email["scheduled_for"]),
            delivery_status=created_email["delivery_status"],
            opened_at=datetime.fromisoformat(created_email["opened_at"]) if created_email["opened_at"] else None,
            clicked_at=datetime.fromisoformat(created_email["clicked_at"]) if created_email["clicked_at"] else None,
            bounce_reason=created_email["bounce_reason"],
            email_provider=created_email["email_provider"],
            email_provider_id=created_email["email_provider_id"],
            thread_id=created_email.get("thread_id"),
            metadata=created_email["metadata"],
            created_at=datetime.fromisoformat(created_email["created_at"])
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error sending follow-up email: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/queue/{queue_id}/generate-next-email", response_model=FollowUpEmailResponse)
async def generate_next_followup_email(
    queue_id: str,
    current_user: dict = Depends(require_cookie_auth)
):
    """
    Generate the next follow-up email for a given queue item using the AI agent.
    """
    try:
        # Get the queue item and verify ownership
        queue_response = supabase.table("follow_up_queue").select("*, bots!inner(*)").eq("id", queue_id).execute()
        if not queue_response.data:
            raise HTTPException(status_code=404, detail="Follow-up queue item not found")
        queue_item = queue_response.data[0]
        bot_id = queue_item["bot_id"]
        # Verify bot ownership
        if queue_item["bots"]["user_id"] != current_user["id"]:
            raise HTTPException(status_code=404, detail="Bot not found or access denied")
        # Get the latest email for this queue item (by scheduled_for desc)
        emails_response = supabase.table("follow_up_emails").select("*").eq("follow_up_queue_id", queue_id).order("scheduled_for", desc=True).limit(1).execute()
        previous_email = emails_response.data[0] if emails_response.data else None
        previous_email_context = previous_email["message"] if previous_email else "This is the first follow-up email in the conversation thread."
        # Generate the new follow-up email using the AI agent
        generated_email = await generate_follow_up_email(
            bot_id=bot_id,
            conversation_id=queue_item["conversation_id"],
            previous_email_context=previous_email_context
        )
        if not generated_email:
            raise HTTPException(status_code=500, detail="Failed to generate follow-up email")
        # Determine the next email_type
        follow_up_count = queue_item.get("follow_up_count", 0)
        email_type_map = {
            0: "initial",
            1: "follow_up_1",
            2: "follow_up_2",
            3: "follow_up_3"
        }
        next_email_type = email_type_map.get(follow_up_count + 1, "custom")
        # 🔧 MAINTAIN SAME SUBJECT AS PREVIOUS EMAIL 🔧
        # Get the previous email's subject to maintain consistency
        from app.tasks.email_scheduler import get_previous_email_subject
        previous_subject = get_previous_email_subject(queue_id)
        subject_to_use = previous_subject if previous_subject else generated_email["subject"]
        
        if previous_subject:
            print(f"📧 Using previous email subject: '{previous_subject}' (AI generated: '{generated_email['subject']}')")
        else:
            print(f"📧 No previous email found, using AI generated subject: '{generated_email['subject']}'")
        
        # Insert the new email record
        new_email_record = {
            "follow_up_queue_id": queue_id,
            "email_type": next_email_type,
            "subject": subject_to_use,  # Use previous subject for consistency
            "message": generated_email["email_body"],
            "recipient_email": queue_item["customer_email"],
            "recipient_name": queue_item["customer_name"],
            "scheduled_for": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(),
            "delivery_status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        insert_response = supabase.table("follow_up_emails").insert(new_email_record).execute()
        if not insert_response.data:
            raise HTTPException(status_code=500, detail="Failed to save new follow-up email to database")
        email = insert_response.data[0]
        return FollowUpEmailResponse(
            id=email["id"],
            follow_up_queue_id=email["follow_up_queue_id"],
            email_type=email["email_type"],
            subject=email["subject"],
            message=email["message"],
            recipient_email=email["recipient_email"],
            recipient_name=email["recipient_name"],
            scheduled_for=datetime.fromisoformat(email["scheduled_for"]),
            delivery_status=email["delivery_status"],
            opened_at=datetime.fromisoformat(email["opened_at"]) if email["opened_at"] else None,
            clicked_at=datetime.fromisoformat(email["clicked_at"]) if email["clicked_at"] else None,
            bounce_reason=email["bounce_reason"],
            email_provider=email.get("email_provider"),
            email_provider_id=email.get("email_provider_id"),
            thread_id=email.get("thread_id"),
            metadata=email.get("metadata"),
            created_at=datetime.fromisoformat(email["created_at"])
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error generating next follow-up email: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/internal/queue/{queue_id}/generate-next-email", response_model=FollowUpEmailResponse)
async def generate_next_followup_email_internal(queue_id: str):
    """
    Internal endpoint to generate the next follow-up email.
    This endpoint is for internal service calls and doesn't require authentication.
    """
    try:
        print(f"Internal generate next email called for queue: {queue_id}")
        
        # Get the follow-up queue item
        queue_response = supabase.table("follow_up_queue").select("*").eq("id", queue_id).execute()
        
        if not queue_response.data:
            raise HTTPException(status_code=404, detail="Follow-up queue item not found")
        
        queue_item = queue_response.data[0]
        
        # Get the latest email for context
        emails_response = supabase.table("follow_up_emails").select("*").eq("follow_up_queue_id", queue_id).order("created_at", desc=True).limit(1).execute()
        
        if not emails_response.data:
            raise HTTPException(status_code=404, detail="No previous emails found for context")
        
        latest_email = emails_response.data[0]
        previous_email_context = latest_email["message"]
        
        # Generate the new email using the follow-up email agent
        new_email_data = await generate_follow_up_email(
            bot_id=queue_item["bot_id"],
            conversation_id=queue_item["conversation_id"],
            previous_email_context=previous_email_context
        )
        
        if not new_email_data:
            raise HTTPException(status_code=500, detail="Failed to generate new follow-up email")
        
        # Determine the correct email type based on current follow-up count
        current_follow_up_count = queue_item["follow_up_count"]
        email_type_map = {
            0: "initial",
            1: "follow_up_1", 
            2: "follow_up_2",
            3: "follow_up_3"
        }
        email_type = email_type_map.get(current_follow_up_count + 1, "custom")
        
        # 🔧 MAINTAIN SAME SUBJECT AS PREVIOUS EMAIL 🔧
        # Get the previous email's subject to maintain consistency
        from app.tasks.email_scheduler import get_previous_email_subject
        previous_subject = get_previous_email_subject(queue_id)
        subject_to_use = previous_subject if previous_subject else new_email_data["subject"]
        
        if previous_subject:
            print(f"📧 Using previous email subject: '{previous_subject}' (AI generated: '{new_email_data['subject']}')")
        else:
            print(f"📧 No previous email found, using AI generated subject: '{new_email_data['subject']}'")
        
        # Create the new email record
        new_email_record = {
            "follow_up_queue_id": queue_id,
            "email_type": email_type,
            "recipient_email": queue_item["customer_email"],
            "recipient_name": queue_item["customer_name"],
            "subject": subject_to_use,  # Use previous subject for consistency
            "message": new_email_data["email_body"],
            "delivery_status": "pending",
            "scheduled_for": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Insert the new email record
        insert_response = supabase.table("follow_up_emails").insert(new_email_record).execute()
        
        if not insert_response.data:
            raise HTTPException(status_code=500, detail="Failed to save new follow-up email to database")
        
        # Increment the follow-up count after successfully generating the new email
        new_follow_up_count = current_follow_up_count + 1
        supabase.table("follow_up_queue").update({
            "follow_up_count": new_follow_up_count,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", queue_id).execute()
        
        email = insert_response.data[0]
        
        return FollowUpEmailResponse(
            id=email["id"],
            follow_up_queue_id=email["follow_up_queue_id"],
            email_type=email["email_type"],
            subject=email["subject"],
            message=email["message"],
            recipient_email=email["recipient_email"],
            recipient_name=email["recipient_name"],
            scheduled_for=datetime.fromisoformat(email["scheduled_for"]),
            delivery_status=email["delivery_status"],
            opened_at=datetime.fromisoformat(email["opened_at"]) if email["opened_at"] else None,
            clicked_at=datetime.fromisoformat(email["clicked_at"]) if email["clicked_at"] else None,
            bounce_reason=email["bounce_reason"],
            email_provider=email.get("email_provider"),
            email_provider_id=email.get("email_provider_id"),
            thread_id=email.get("thread_id"),
            metadata=email.get("metadata"),
            created_at=datetime.fromisoformat(email["created_at"])
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in internal generate next follow-up email: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

# 🔧 EMAIL THREADING DEBUGGING ENDPOINTS 🔧

class EmailThreadingStatus(BaseModel):
    queue_id: str
    status: str  # "healthy", "issues_found", "no_emails", "error"
    thread_id: Optional[str]
    message_id: Optional[str]
    email_count: int
    sent_count: int
    pending_count: int
    issues: List[str] = []
    recommendations: List[str] = []

@router.get("/queue/{queue_id}/threading-status", response_model=EmailThreadingStatus)
async def get_email_threading_status(
    queue_id: str,
    current_user: dict = Depends(require_cookie_auth)
):
    """
    Get email threading status for a specific follow-up queue.
    This endpoint helps debug threading issues.
    """
    try:
        # Verify queue item ownership
        queue_response = supabase.table("follow_up_queue").select("bot_id, bots!inner(user_id)").eq("id", queue_id).execute()
        
        if not queue_response.data:
            raise HTTPException(status_code=404, detail="Follow-up queue item not found")
        
        queue_item = queue_response.data[0]
        
        # Verify ownership
        if queue_item["bots"]["user_id"] != current_user["id"]:
            raise HTTPException(status_code=404, detail="Follow-up queue item not found or access denied")
        
        # Import the verification function from the email scheduler
        from app.tasks.email_scheduler import verify_email_threading
        
        # Get threading status
        verification_result = verify_email_threading(queue_id)
        
        return EmailThreadingStatus(
            queue_id=queue_id,
            status=verification_result.get("status", "error"),
            thread_id=verification_result.get("thread_id"),
            message_id=verification_result.get("message_id"),
            email_count=verification_result.get("email_count", 0),
            sent_count=verification_result.get("sent_count", 0),
            pending_count=verification_result.get("pending_count", 0),
            issues=verification_result.get("issues", []),
            recommendations=verification_result.get("recommendations", [])
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting threading status: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

class FixThreadingRequest(BaseModel):
    force_thread_id: Optional[str] = None

class FixThreadingResponse(BaseModel):
    success: bool
    message: str
    updated_emails: int = 0
    final_status: Optional[EmailThreadingStatus] = None

@router.post("/queue/{queue_id}/fix-threading", response_model=FixThreadingResponse)
async def fix_email_threading(
    queue_id: str,
    request: FixThreadingRequest,
    current_user: dict = Depends(require_cookie_auth)
):
    """
    Manually fix email threading for a specific follow-up queue.
    This endpoint helps repair broken threading.
    """
    try:
        # Verify queue item ownership
        queue_response = supabase.table("follow_up_queue").select("bot_id, bots!inner(user_id)").eq("id", queue_id).execute()
        
        if not queue_response.data:
            raise HTTPException(status_code=404, detail="Follow-up queue item not found")
        
        queue_item = queue_response.data[0]
        
        # Verify ownership
        if queue_item["bots"]["user_id"] != current_user["id"]:
            raise HTTPException(status_code=404, detail="Follow-up queue item not found or access denied")
        
        # Import the fix function from the email scheduler
        from app.tasks.email_scheduler import manual_fix_queue_threading, verify_email_threading
        
        # Attempt to fix threading
        success = manual_fix_queue_threading(queue_id, request.force_thread_id)
        
        # Get final status
        final_verification = verify_email_threading(queue_id)
        final_status = EmailThreadingStatus(
            queue_id=queue_id,
            status=final_verification.get("status", "error"),
            thread_id=final_verification.get("thread_id"),
            message_id=final_verification.get("message_id"),
            email_count=final_verification.get("email_count", 0),
            sent_count=final_verification.get("sent_count", 0),
            pending_count=final_verification.get("pending_count", 0),
            issues=final_verification.get("issues", []),
            recommendations=final_verification.get("recommendations", [])
        )
        
        if success:
            return FixThreadingResponse(
                success=True,
                message="Email threading fixed successfully",
                updated_emails=final_status.email_count,
                final_status=final_status
            )
        else:
            return FixThreadingResponse(
                success=False,
                message="Failed to fix email threading",
                final_status=final_status
            )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fixing threading: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/debug/threading-overview")
async def get_threading_overview(current_user: dict = Depends(require_cookie_auth)):
    """
    Get an overview of email threading status across all user's bots.
    """
    try:
        # Get all bots for the current user
        bots_response = supabase.table("bots").select("id, name").eq("user_id", current_user["id"]).execute()
        
        if not bots_response.data:
            return {"message": "No bots found", "bots": []}
        
        # Get all follow-up queues for these bots
        bot_ids = [bot["id"] for bot in bots_response.data]
        
        overview = {
            "total_bots": len(bot_ids),
            "total_queues": 0,
            "healthy_queues": 0,
            "problematic_queues": 0,
            "bot_details": []
        }
        
        for bot in bots_response.data:
            bot_id = bot["id"]
            bot_name = bot["name"]
            
            # Get queues for this bot
            queues_response = supabase.table("follow_up_queue").select("id, customer_name, customer_email").eq("bot_id", bot_id).execute()
            
            if not queues_response.data:
                overview["bot_details"].append({
                    "bot_id": bot_id,
                    "bot_name": bot_name,
                    "queue_count": 0,
                    "healthy_count": 0,
                    "problem_count": 0,
                    "queues": []
                })
                continue
            
            bot_healthy = 0
            bot_problems = 0
            queue_details = []
            
            # Import verification function
            from app.tasks.email_scheduler import verify_email_threading
            
            for queue in queues_response.data:
                queue_id = queue["id"]
                try:
                    verification = verify_email_threading(queue_id)
                    status = verification.get("status", "error")
                    
                    queue_details.append({
                        "queue_id": queue_id,
                        "customer_name": queue["customer_name"],
                        "customer_email": queue["customer_email"],
                        "status": status,
                        "email_count": verification.get("email_count", 0),
                        "issues": verification.get("issues", [])
                    })
                    
                    if status == "healthy":
                        bot_healthy += 1
                    else:
                        bot_problems += 1
                        
                except Exception as e:
                    queue_details.append({
                        "queue_id": queue_id,
                        "customer_name": queue["customer_name"],
                        "customer_email": queue["customer_email"],
                        "status": "error",
                        "email_count": 0,
                        "issues": [f"Error checking: {str(e)}"]
                    })
                    bot_problems += 1
            
            overview["bot_details"].append({
                "bot_id": bot_id,
                "bot_name": bot_name,
                "queue_count": len(queues_response.data),
                "healthy_count": bot_healthy,
                "problem_count": bot_problems,
                "queues": queue_details
            })
            
            overview["total_queues"] += len(queues_response.data)
            overview["healthy_queues"] += bot_healthy
            overview["problematic_queues"] += bot_problems
        
        return overview
        
    except Exception as e:
        print(f"Error getting threading overview: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.put("/emails/{email_id}/status")
async def update_email_status(
    email_id: str,
    delivery_status: str,
    opened_at: Optional[datetime] = None,
    clicked_at: Optional[datetime] = None,
    bounce_reason: Optional[str] = None,
    current_user: dict = Depends(require_cookie_auth)
):
    """
    Update the delivery status of a follow-up email (e.g., opened, clicked, bounced).
    """
    try:
        # Validate delivery status
        valid_statuses = ["pending", "sent", "delivered", "bounced", "failed", "opened", "clicked"]
        if delivery_status not in valid_statuses:
            raise HTTPException(status_code=400, detail=f"Invalid delivery status. Must be one of: {valid_statuses}")
        
        # Get the email to verify ownership
        email_response = supabase.table("follow_up_emails").select("follow_up_queue_id, follow_up_queue!inner(bot_id, bots!inner(user_id))").eq("id", email_id).execute()
        
        if not email_response.data:
            raise HTTPException(status_code=404, detail="Email not found")
        
        email_item = email_response.data[0]
        
        # Verify ownership
        if email_item["follow_up_queue"]["bots"]["user_id"] != current_user["id"]:
            raise HTTPException(status_code=404, detail="Email not found or access denied")
        
        # Prepare update data
        update_data = {
            "delivery_status": delivery_status,
            "updated_at": datetime.utcnow().isoformat()
        }
        
        if opened_at:
            update_data["opened_at"] = opened_at.isoformat()
        if clicked_at:
            update_data["clicked_at"] = clicked_at.isoformat()
        if bounce_reason:
            update_data["bounce_reason"] = bounce_reason
        
        # Update the email
        response = supabase.table("follow_up_emails").update(update_data).eq("id", email_id).execute()
        
        if not response.data:
            raise HTTPException(status_code=500, detail="Failed to update email status")
        
        return {"message": "Email status updated successfully", "delivery_status": delivery_status}
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error updating email status: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.put("/emails/{email_id}", response_model=FollowUpEmailResponse)
async def update_followup_email(
    email_id: str,
    data: dict = Body(...),
    current_user: dict = Depends(require_cookie_auth)
):
    """
    Update the subject and message of a follow-up email if it is still pending (scheduled_for in the future).
    """
    try:
        print(f"🔧 Updating email {email_id} with data: {data}")
        
        # Get the email with a simple query
        email_response = supabase.table("follow_up_emails").select("*").eq("id", email_id).execute()
        print(f"🔍 Email response: {email_response}")
        
        if not email_response.data:
            print(f"❌ Email {email_id} not found")
            raise HTTPException(status_code=404, detail="Email not found")
        
        email = email_response.data[0]
        print(f"📧 Found email: {email.get('id')}, queue: {email.get('follow_up_queue_id')}")
        
        # Only allow edit if scheduled_for is in the future
        from datetime import datetime, timezone
        scheduled_for = email.get("scheduled_for")
        
        if scheduled_for:
            try:
                scheduled_dt = datetime.fromisoformat(scheduled_for.replace('Z', '+00:00'))
                current_dt = datetime.now(timezone.utc)
                print(f"📅 Scheduled: {scheduled_dt}, Current: {current_dt}")
                
                if scheduled_dt <= current_dt:
                    print(f"❌ Email is in the past or already sent")
                    raise HTTPException(status_code=400, detail="Cannot edit an email that has already been sent or is in the past")
            except Exception as date_error:
                print(f"❌ Error parsing date: {date_error}")
                raise HTTPException(status_code=400, detail="Invalid scheduled date format")
        
        # Only allow editing subject and message
        update_data = {}
        if "subject" in data:
            update_data["subject"] = data["subject"]
        if "message" in data:
            update_data["message"] = data["message"]
        print(f"🔧 Update data------>: {update_data}")
        
        if not update_data:
            print(f"❌ No valid fields to update")
            raise HTTPException(status_code=400, detail="No valid fields to update")
        
        update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
        print(f"📝 Update data: {update_data}")
        
        # Update the email
        updated = supabase.table("follow_up_emails").update(update_data).eq("id", email_id).execute()
        
        print("Supabase update response:", updated)
        if hasattr(updated, 'error') and updated.error:
            print("Supabase update error:", updated.error)
            raise HTTPException(status_code=500, detail=f"Supabase update error: {updated.error}")
        if not updated.data:
            print("Supabase update returned no data")
            raise HTTPException(status_code=500, detail="Supabase update returned no data")
        
        updated_email = updated.data[0]
        print(f"✅ Email updated successfully")
        
        # Return the updated email
        return FollowUpEmailResponse(
            id=updated_email["id"],
            follow_up_queue_id=updated_email["follow_up_queue_id"],
            email_type=updated_email["email_type"],
            subject=updated_email["subject"],
            message=updated_email["message"],
            recipient_email=updated_email["recipient_email"],
            recipient_name=updated_email["recipient_name"],
            scheduled_for=datetime.fromisoformat(updated_email["scheduled_for"]),
            delivery_status=updated_email["delivery_status"],
            opened_at=datetime.fromisoformat(updated_email["opened_at"]) if updated_email.get("opened_at") else None,
            clicked_at=datetime.fromisoformat(updated_email["clicked_at"]) if updated_email.get("clicked_at") else None,
            bounce_reason=updated_email.get("bounce_reason"),
            email_provider=updated_email.get("email_provider"),
            email_provider_id=updated_email.get("email_provider_id"),
            thread_id=updated_email.get("thread_id"),
            metadata=updated_email.get("metadata"),
            created_at=datetime.fromisoformat(updated_email["created_at"])
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error updating follow-up email: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.get("/emails/{queue_id}", response_model=List[FollowUpEmailResponse])
async def get_followup_emails(
    queue_id: str,
    current_user: dict = Depends(require_cookie_auth)
):
    """
    Get all emails for a specific follow-up queue item.
    """
    try:
        # Verify queue item ownership
        queue_response = supabase.table("follow_up_queue").select("bot_id, bots!inner(user_id)").eq("id", queue_id).execute()
        
        if not queue_response.data:
            raise HTTPException(status_code=404, detail="Follow-up queue item not found")
        
        queue_item = queue_response.data[0]
        
        # Verify ownership
        if queue_item["bots"]["user_id"] != current_user["id"]:
            raise HTTPException(status_code=404, detail="Follow-up queue item not found or access denied")
        
        # Get emails for this queue item
        emails_response = supabase.table("follow_up_emails").select("*").eq("follow_up_queue_id", queue_id).order("scheduled_for", desc=False).execute()
        
        print(f"🔍 Fetching emails for queue {queue_id}")
        print(f"📊 Raw emails response: {emails_response.data}")
        print(f"📧 Number of emails found: {len(emails_response.data) if emails_response.data else 0}")
        
        emails = []
        for email in emails_response.data:
            try:
                emails.append(FollowUpEmailResponse(
                    id=email["id"],
                    follow_up_queue_id=email["follow_up_queue_id"],
                    email_type=email["email_type"],
                    subject=email["subject"],
                    message=email["message"],
                    recipient_email=email["recipient_email"],
                    recipient_name=email["recipient_name"],
                    scheduled_for=datetime.fromisoformat(email["scheduled_for"]),
                    delivery_status=email["delivery_status"],
                    opened_at=datetime.fromisoformat(email["opened_at"]) if email["opened_at"] else None,
                    clicked_at=datetime.fromisoformat(email["clicked_at"]) if email["clicked_at"] else None,
                    bounce_reason=email["bounce_reason"],
                    email_provider=email["email_provider"],
                    email_provider_id=email["email_provider_id"],
                    thread_id=email.get("thread_id"),  # Add missing thread_id field
                    metadata=email["metadata"],
                    created_at=datetime.fromisoformat(email["created_at"])
                ))
            except Exception as e:
                print(f"Error processing email {email.get('id', 'unknown')}: {str(e)}")
                print(f"Email data: {email}")
                # Skip this email and continue with others
                continue
        
        return emails
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting follow-up emails: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/test-db")
async def test_database_connection():
    """
    Test endpoint to verify database connection and table existence.
    """
    try:
        # Test basic connection
        print("Testing database connection...")
        
        # Test bots table
        bots_response = supabase.table("bots").select("count").execute()
        print(f"Bots table accessible: {bots_response.data}")
        
        # Test follow_up_queue table
        try:
            queue_response = supabase.table("follow_up_queue").select("count").execute()
            print(f"Follow-up queue table accessible: {queue_response.data}")
        except Exception as e:
            print(f"Follow-up queue table error: {e}")
            return {"error": f"Follow-up queue table not accessible: {str(e)}"}
        
        return {"status": "Database connection successful", "bots_count": bots_response.data}
        
    except Exception as e:
        print(f"Database test error: {e}")
        return {"error": f"Database connection failed: {str(e)}"}

@router.get("/stats/{bot_id}")
async def get_followup_stats(
    bot_id: str,
    current_user: dict = Depends(require_cookie_auth)
):
    """
    Get follow-up statistics for a specific bot.
    """
    try:
        # Validate that the bot belongs to the current user
        bot_response = supabase.table("bots").select("id").eq("id", bot_id).eq("user_id", current_user["id"]).execute()
        
        if not bot_response.data:
            raise HTTPException(status_code=404, detail="Bot not found or access denied")
        
        # Get queue statistics
        queue_stats_response = supabase.table("follow_up_stats").select("*").eq("bot_id", bot_id).execute()
        queue_stats = queue_stats_response.data[0] if queue_stats_response.data else {}
        
        # Get email statistics
        email_stats_response = supabase.table("follow_up_email_stats").select("*").eq("bot_id", bot_id).execute()
        email_stats = email_stats_response.data[0] if email_stats_response.data else {}
        
        return {
            "queue_stats": queue_stats,
            "email_stats": email_stats
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting follow-up stats: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error") 