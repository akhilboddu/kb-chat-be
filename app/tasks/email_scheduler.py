#!/usr/bin/env python3

import os
import asyncio
import aiohttp
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
from app.worker.celery_app import celery_app, RetryableTask
from app.utils.logging import get_logger
from supabase import create_client, Client
from app.core.follow_up_email_agent import generate_follow_up_email

import builtins as _b

# --- Silence all existing prints/logger output ---
# We keep original print for selective use
_b.print_orig = _b.print

# Replace built-in print with a no-op to avoid noisy logs
def _quiet_print(*args, **kwargs):
    pass

_b.print = _quiet_print

# Keep logger enabled for error messages
logger = get_logger(__name__)
# logger.disabled = True

# Initialize Supabase client
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(supabase_url, supabase_key)

# 🔧 HELPER FUNCTION FOR EMAIL THREADING 🔧
def get_thread_info_for_queue(queue_id: str) -> Dict[str, Any]:
    """
    Get threading information for a specific follow-up queue.
    
    Args:
        queue_id: The follow-up queue ID
        
    Returns:
        Dict with thread_id, message_id, and additional threading info
    """
    try:
        print(f"🔍 Getting thread info for queue: {queue_id}")
        
        # Get all emails in this queue ordered by creation time
        response = supabase.table("follow_up_emails").select(
            "id, thread_id, email_provider_id, metadata, email_type, delivery_status, created_at, scheduled_for"
        ).eq("follow_up_queue_id", queue_id).order("created_at", desc=False).execute()
        
        if not response.data:
            print(f"📧 No emails found for queue {queue_id}")
            return {"thread_id": None, "message_id": None, "email_count": 0}
        
        emails = response.data
        print(f"📊 Found {len(emails)} total emails in queue {queue_id}")
        
        # Debug: Print all emails in queue
        for i, email in enumerate(emails):
            status_emoji = "✅" if email.get("delivery_status") == "sent" else "⏳" if email.get("delivery_status") == "pending" else "❌"
            thread_info = f"🧵{email.get('thread_id', 'None')}" if email.get('thread_id') else "🆕"
            print(f"  {i+1}. {status_emoji} {email.get('email_type', 'unknown')} | {thread_info} | {email.get('delivery_status', 'unknown')} | {email.get('created_at', 'unknown')}")
        
        # Find the first email with a thread_id (only among sent emails)
        thread_id = None
        message_id = None
        for email in emails:
            if email.get("delivery_status") == "sent" and email.get("thread_id"):
                thread_id = email["thread_id"]
                metadata = email.get("metadata", {})
                message_id = metadata.get("gmail_message_id_header")
                print(f"🔗 Found thread_id: {thread_id} from email {email.get('email_type', 'unknown')}")
                if message_id:
                    print(f"📨 Found Message-ID: {message_id}")
                break
        
        sent_count = len([e for e in emails if e.get("delivery_status") == "sent"])
        pending_count = len([e for e in emails if e.get("delivery_status") == "pending"])
        
        return {
            "thread_id": thread_id,
            "message_id": message_id,
            "email_count": len(emails),
            "sent_count": sent_count,
            "pending_count": pending_count,
            "emails": emails
        }
        
    except Exception as e:
        print(f"❌ Error getting thread info for queue {queue_id}: {str(e)}")
        return {"thread_id": None, "message_id": None, "email_count": 0, "error": str(e)}

# 🔧 HELPER FUNCTION TO GET PREVIOUS EMAIL SUBJECT 🔧
def get_previous_email_subject(queue_id: str) -> str:
    """
    Get the subject of the previous email in the queue to maintain consistency.
    
    Args:
        queue_id: The follow-up queue ID
        
    Returns:
        The subject of the previous email, or None if no previous email exists
    """
    try:
        # Get the most recent email (sent or pending) to get its subject
        response = supabase.table("follow_up_emails").select(
            "subject, email_type, delivery_status, created_at"
        ).eq("follow_up_queue_id", queue_id).order("created_at", desc=True).limit(1).execute()
        
        if response.data:
            previous_email = response.data[0]
            subject = previous_email.get("subject")
            print(f"📧 Found previous email subject: '{subject}' (type: {previous_email.get('email_type')}, status: {previous_email.get('delivery_status')})")
            return subject
        else:
            print(f"📧 No previous emails found for queue {queue_id}")
            return None
            
    except Exception as e:
        print(f"❌ Error getting previous email subject for queue {queue_id}: {str(e)}")
        return None

# 🔧 EMAIL THREADING VERIFICATION FUNCTION 🔧
def verify_email_threading(queue_id: str) -> Dict[str, Any]:
    """
    Verify that email threading is working correctly for a queue.
    
    Args:
        queue_id: The follow-up queue ID to verify
        
    Returns:
        Dict with verification results and recommendations
    """
    try:
        print(f"🔍 VERIFYING EMAIL THREADING for queue: {queue_id}")
        print("=" * 60)
        
        thread_info = get_thread_info_for_queue(queue_id)
        
        issues = []
        recommendations = []
        
        # Check if we have emails
        if thread_info["email_count"] == 0:
            issues.append("No emails found in queue")
            return {"status": "no_emails", "issues": issues}
        
        # Check if sent emails have thread_id
        if thread_info["sent_count"] > 0:
            if not thread_info["thread_id"]:
                issues.append("Sent emails don't have thread_id - threading is broken")
                recommendations.append("Check Gmail API response and database storage")
            else:
                print(f"✅ Thread ID found: {thread_info['thread_id']}")
                
                # Check if all sent emails have the same thread_id
                emails = thread_info["emails"]
                sent_emails = [e for e in emails if e.get("delivery_status") == "sent"]
                
                thread_ids = set()
                for email in sent_emails:
                    if email.get("thread_id"):
                        thread_ids.add(email["thread_id"])
                
                if len(thread_ids) > 1:
                    issues.append(f"Multiple thread IDs found: {thread_ids} - emails are not properly threaded")
                    recommendations.append("All emails in a queue should have the same thread_id")
                elif len(thread_ids) == 1:
                    print(f"✅ All sent emails use the same thread_id: {list(thread_ids)[0]}")
                
        # Check Message-ID storage
        if thread_info["message_id"]:
            print(f"✅ Message-ID found for threading: {thread_info['message_id']}")
        else:
            if thread_info["sent_count"] > 0:
                issues.append("No Message-ID found in metadata - In-Reply-To headers may be missing")
                recommendations.append("Check Gmail API response parsing and metadata storage")
        
        # Overall status
        if not issues:
            status = "healthy"
            print(f"🎉 EMAIL THREADING IS WORKING CORRECTLY!")
        else:
            status = "issues_found"
            print(f"⚠️ THREADING ISSUES DETECTED:")
            for i, issue in enumerate(issues, 1):
                print(f"  {i}. {issue}")
            
            if recommendations:
                print(f"💡 RECOMMENDATIONS:")
                for i, rec in enumerate(recommendations, 1):
                    print(f"  {i}. {rec}")
        
        print("=" * 60)
        
        return {
            "status": status,
            "queue_id": queue_id,
            "thread_id": thread_info["thread_id"],
            "message_id": thread_info["message_id"],
            "email_count": thread_info["email_count"],
            "sent_count": thread_info["sent_count"],
            "pending_count": thread_info["pending_count"],
            "issues": issues,
            "recommendations": recommendations,
            "emails": thread_info["emails"]
        }
        
    except Exception as e:
        print(f"❌ Error verifying threading for queue {queue_id}: {str(e)}")
        return {"status": "error", "error": str(e)}

@celery_app.task(bind=True, base=RetryableTask, queue="email", soft_time_limit=300, time_limit=600)
def send_scheduled_followup_emails(self):
    """
    Celery task to send scheduled follow-up emails using the existing Gmail API.
    This task should be run every 5-10 minutes to check for emails that need to be sent.
    """
    # CRON JOB EXECUTION LOG - This will be printed every time the cron job runs
    print("=" * 80)
    print(f"📧 EMAIL CRON JOB EXECUTED at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🕐 Task ID: {self.request.id}")
    print("=" * 80)
    
    logger.info(f"Starting scheduled email check at {datetime.now()}")
    print(f"📧 Email scheduler cron job started at {datetime.now()}")
    print(f"________________________________________YOLO - FUNCTION STARTED")
    
    try:
        # Get all pending emails that are due to be sent
        current_time = datetime.now(timezone.utc).isoformat()
        print(f"Current time: {current_time}")
        
        # Query for emails that are due to be sent
        print(f"________________________________________YOLO - About to query database")
        # Look for pending emails that are ready to be sent
        response = supabase.table("follow_up_emails").select(
            "*, follow_up_queue!inner(*)"
        ).eq("delivery_status", "pending").lte("scheduled_for", current_time).execute()

        print(f"________________________________________YOLO - Query completed")
        print(f"Response: {response}")
        print(f"________________________________________YOLO - Response data length: {len(response.data) if response.data else 0}")
        
        if not response.data:
            logger.info(f"No emails due for sending at {current_time}")
            print(f"📧 No emails due for sending at {current_time}")
            return {"sent": 0, "errors": 0}
        
        logger.info(f"Found {len(response.data)} emails due for sending")
        print(f"📧 Found {len(response.data)} emails due for sending")
        
        sent_count = 0
        error_count = 0
        
        for email_record in response.data:
            print(f"EMAIL RECORD: {email_record}")
            try:
                result = send_single_followup_email(email_record)
                print(f"RESULT: {result}")
                if result["success"]:
                    sent_count += 1
                    logger.info(f"Successfully sent email {email_record['id']} to {email_record['recipient_email']}")
                    print(f"✅ Successfully sent email {email_record['id']} to {email_record['recipient_email']}")
                else:
                    error_count += 1
                    logger.error(f"Failed to send email {email_record['id']}: {result['error']}")
                    print(f"❌ Failed to send email {email_record['id']}: {result['error']}")
                    
            except Exception as e:
                error_count += 1
                logger.error(f"Error processing email {email_record['id']}: {str(e)}")
                print(f"💥 Error processing email {email_record['id']}: {str(e)}")
                
                #Mark as failed
                supabase.table("follow_up_emails").update({
                    "delivery_status": "failed",
                    "bounce_reason": f"Scheduler error: {str(e)}",
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }).eq("id", email_record["id"]).execute()
        
        logger.info(f"Email scheduler completed: {sent_count} sent, {error_count} errors")
        print(f"📧 Email scheduler completed: {sent_count} sent, {error_count} errors")
        print("=" * 80)
        return {"sent": sent_count, "errors": error_count}
        
    except Exception as e:
        logger.error(f"Critical error in email scheduler: {str(e)}")
        print(f"❌ CRITICAL ERROR in email scheduler: {str(e)}")
        print("=" * 80)
        return {"sent": 0, "errors": 1, "critical_error": str(e)}

async def call_generate_next_email_api(queue_id: str, api_base_url: str) -> Dict[str, Any]:
    """
    Call the new API endpoint to generate the next follow-up email.
    
    Args:
        queue_id: The follow-up queue ID
        api_base_url: The base URL for the API
        
    Returns:
        Dict with success status and response data
    """
    try:
        logger.info(f"Calling generate next email API for queue {queue_id}")
        
        # Make the API call to generate the next email using the internal endpoint
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{api_base_url}/api/followup/internal/queue/{queue_id}/generate-next-email",
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=60)  # Longer timeout for email generation
            ) as response:
                
                if response.status == 200:
                    result = await response.json()
                    logger.info(f"Generate next email API success: {result}")
                    return {"success": True, "data": result}
                else:
                    error_text = await response.text()
                    logger.error(f"Generate next email API error - Status: {response.status}, Response: {error_text}")
                    return {"success": False, "error": f"HTTP {response.status}: {error_text}"}
                    
    except asyncio.TimeoutError:
        logger.error("Generate next email API timeout")
        return {"success": False, "error": "Request timeout"}
    except Exception as e:
        logger.error(f"Generate next email API exception: {str(e)}")
        return {"success": False, "error": str(e)}

async def send_email_via_gmail_api(bot_id: str, to_email: str, subject: str, html_content: str, thread_id: str = None, message_id: str = None) -> Dict[str, Any]:

    
    """
    Send email using the existing Gmail API endpoint.
    
    Args:
        bot_id: The bot ID for the API call
        to_email: Recipient email address
        subject: Email subject
        html_content: Email HTML content
        
    Returns:
        Dict with success status and response data
    """
    try:
        # Get the API base URL from environment
        api_base_url = os.getenv("API_BASE_URL", "http://localhost:8000")
        
        # Prepare the email request payload
        # Only payload details will be printed (see below). No other logs.
        email_payload = {
            "to": to_email,
            "subject": subject,
            "body_html": html_content,
            "body_text": html_content  # Fallback text content
        }

        # ------------  SINGLE DEBUG OUTPUT  -------------
        # Show exactly what we send to Gmail API (threadId + headers)
        
        # -------------------------------------------------

       
        
        # Add thread_id and message_id if provided for email threading
        if thread_id:
            email_payload["reply_to_thread_id"] = thread_id
            print(f"🔗 Using thread_id {thread_id} for email threading")
            
            # Add message_id for proper threading headers (this is the key for In-Reply-To)
            if message_id:
                email_payload["reply_to_message_id"] = message_id
                print(f"📧 Using message_id {message_id} for In-Reply-To header")
            else:
                print(f"⚠️  WARNING: No message_id available for In-Reply-To header")
        else:
            print(f"📧 No thread_id provided, starting new email thread")
       
    
        logger.info(f"Sending email via Gmail API - Bot: {bot_id}, To: {to_email}, Subject: {subject}, HTML CONTENT: {html_content}")

        _b.print_orig("GMAIL API PAYLOAD:", email_payload)
        
        # Make the API call
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{api_base_url}/api/gmail/{bot_id}/send-email",
                json=email_payload,
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                
                if response.status == 200:
                    result = await response.json()
                    logger.info(f"Gmail API success: {result}")
                    return {"success": True, "data": result}
                else:
                    error_text = await response.text()
                    logger.error(f"Gmail API error - Status: {response.status}, Response: {error_text}")
                    return {"success": False, "error": f"HTTP {response.status}: {error_text}"}
                    
    except asyncio.TimeoutError:
        logger.error("Gmail API timeout")
        return {"success": False, "error": "Request timeout"}
    except Exception as e:
        logger.error(f"Gmail API exception: {str(e)}")
        return {"success": False, "error": str(e)}

def send_single_followup_email(email_record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send a single follow-up email using the Gmail API.
    
    Args:
        email_record: The email record from the database
        
    Returns:
        Dict with success status and any error message
    """
    print(f"🚀 FUNCTION CALLED: send_single_followup_email")
    try:
        # Extract email data
        recipient_email = email_record["recipient_email"]
        recipient_name = email_record["recipient_name"]
        subject = email_record["subject"]
        html_content = email_record["message"]
        email_id = email_record["id"]
        bot_id = email_record["follow_up_queue"]["bot_id"]
        
        logger.info(f"Sending email {email_id} to {recipient_email} via bot {bot_id}")
        
        
        # 🔧 IMPROVED THREADING LOGIC 🔧
        # Get thread_id and message_id using the helper function
        thread_info = get_thread_info_for_queue(email_record["follow_up_queue_id"])
        thread_id = thread_info.get("thread_id")
        _b.print_orig(f"🧵 THREAD ID: {thread_id}")
        message_id = thread_info.get("message_id")
        _b.print_orig(f"📧 MESSAGE ID: {message_id}")
        
        # If we have threading info, we'll use it; otherwise start a new thread
        # We keep verbose logging minimal – only important conditions
        if not thread_id and thread_info.get("sent_count", 0) > 0:
            # Previous emails exist but no thread id captured – could indicate an earlier failure
            pass
        
        # Send email using the Gmail API
        # Note: We need to run this in an async context
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                send_email_via_gmail_api(bot_id, recipient_email, subject, html_content, thread_id, message_id)
            )
        finally:
            loop.close()
        
        if result["success"]:
            # Extract thread_id and email_id from the response
            response_data = result.get("data", {})
            new_thread_id = response_data.get("thread_id")
            email_id_gmail = response_data.get("email_id")  # This is the Gmail message ID
            _b.print_orig(f"📤 Email sent successfully!")
            _b.print_orig(f"🧵 THREAD ID: {new_thread_id}")
            _b.print_orig(f"📧 GMAIL EMAIL ID: {email_id_gmail}")
            
            # Update email status to sent and store thread_id and email_provider_id
            update_data = {
                "delivery_status": "sent",
                "updated_at": datetime.now(timezone.utc).isoformat()
            }

            _b.print_orig(f"📝 UPDATE DATA: {update_data}")
            
            if new_thread_id:
                update_data["thread_id"] = new_thread_id
                _b.print_orig(f"✅ Storing thread_id {new_thread_id} for email {email_id}")
                
                if email_id_gmail:
                    update_data["email_provider_id"] = email_id_gmail
                    _b.print_orig(f"✅ Storing email_provider_id {email_id_gmail} for email {email_id}")
                    
                    # Store the Message-ID header in metadata for future threading
                    email_details = response_data.get("email_details", {})
                    headers = email_details.get("headers", {})
                    message_id_header = headers.get("message_id")  # This is the Message-ID header (Message-Id)
                    if message_id_header:
                        # Update metadata to include the Message-ID header
                        current_metadata = email_record.get("metadata", {})
                        current_metadata["gmail_message_id_header"] = message_id_header
                        update_data["metadata"] = current_metadata
                        _b.print_orig(f"✅ Storing Message-ID header in metadata: {message_id_header}")
                    else:
                        _b.print_orig("⚠️ No Message-ID header found in email response")
                else:
                    _b.print_orig("⚠️ No email_id_gmail found in response data")
            else:
                _b.print_orig("⚠️ No new_thread_id found in response data")
        
        # Debug: Check threading information
        if new_thread_id and email_id_gmail:
            if new_thread_id == email_id_gmail:
                _b.print_orig(f"⚠️ WARNING: thread_id and email_id_gmail are the same: {new_thread_id}")
            else:
                _b.print_orig(f"✅ thread_id ({new_thread_id}) and email_id_gmail ({email_id_gmail}) are different - this is correct")
        
        # 🔧 IMPROVED DATABASE UPDATE 🔧
        # Update the database and ensure the transaction is committed before proceeding
        try:
            update_response = supabase.table("follow_up_emails").update(update_data).eq("id", email_id).execute()
            _b.print_orig(f"✅ Database updated successfully for email {email_id}")
            
            # Verify the update was successful
            if not update_response.data:
                _b.print_orig(f"⚠️ Warning: Database update returned no data for email {email_id}")
            else:
                _b.print_orig(f"📊 Updated email record: {update_response.data[0].get('thread_id', 'No thread_id')}")
                
        except Exception as db_error:
            _b.print_orig(f"❌ Error updating database for email {email_id}: {db_error}")
            # Continue anyway - the email was sent successfully

            # Update queue item status to in_progress (don't increment count yet)
            queue_id = email_record["follow_up_queue_id"]
        try:
            queue_update_response = supabase.table("follow_up_queue").update({
                "status": "in_progress",
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).eq("id", queue_id).execute()
            _b.print_orig(f"✅ Queue status updated to in_progress for queue {queue_id}")
        except Exception as queue_error:
            _b.print_orig(f"⚠️ Error updating queue status: {queue_error}")
        
        # 🔧 VERIFY EMAIL THREADING 🔧
        # Verify that threading is working correctly for this queue
        _b.print_orig(f"🔍 Verifying email threading after sending...")
        verification_result = verify_email_threading(queue_id)
        if verification_result["status"] == "healthy":
            _b.print_orig(f"✅ Email threading verification passed!")
        elif verification_result["status"] == "issues_found":
            _b.print_orig(f"⚠️ Email threading issues detected - see verification output above")
        
        # 🔧 IMPROVED NEXT EMAIL GENERATION 🔧
        # Add a small delay to ensure database consistency before generating next email
        _b.print_orig("⏳ Waiting for database consistency before generating next email…")
        import time
        time.sleep(2)  # Ensure DB consistency
        # NOTE: generation of the next email is handled by a separate Celery task
        return {"success": True}
            
    except Exception as e:
        logger.error(f"Error sending email {email_record.get('id', 'unknown')}: {str(e)}")
        return {"success": False, "error": str(e)}

def generate_new_followup_email(email_record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate a new follow-up email using the follow-up email agent and save it to the database.
    
    Args:
        email_record: The current email record that was just sent
        
    Returns:
        Dict with success status and any error message
    """
    try:
        print(f"🔄 Generating new follow-up email for queue item: {email_record['follow_up_queue_id']}")
        
        # Extract data from the email record
        queue_id = email_record["follow_up_queue_id"]
        print(f"QUEUE ID: {queue_id}")
        conversation_id = email_record["follow_up_queue"]["conversation_id"]
        print(f"CONVERSATION ID: {conversation_id}")
        bot_id = email_record["follow_up_queue"]["bot_id"]
        print(f"BOT ID: {bot_id}")
        # Get the current email content as previous context
        previous_email_context = email_record["message"]
        print(f"PREVIOUS EMAIL CONTEXT: {previous_email_context}")
        
        # Generate the new email using the follow-up email agent
        try:
            # Use nest_asyncio to handle nested event loops in Celery
            import nest_asyncio
            nest_asyncio.apply()
            
            # Force a clean event loop state
            # Note: asyncio is already imported at the top of the file
            import sys
            
            # Check if we're in a thread with an existing event loop
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    print("Event loop is closed, creating new one")
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                elif loop.is_running():
                    print("Event loop is running, using nest_asyncio")
                    # nest_asyncio should handle this
                else:
                    print("Using existing event loop")
            except RuntimeError:
                print("No event loop exists, creating new one")
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            # Run the email generation
            new_email_data = loop.run_until_complete(generate_follow_up_email(
                bot_id=bot_id,
                conversation_id=conversation_id,
                previous_email_context=previous_email_context
            ))
            
        except Exception as e:
            error_msg = f"Error running generate_follow_up_email: {str(e)}"
            logger.error(error_msg)
            print(f"💥 {error_msg}")
            return {"success": False, "error": error_msg}
        
        if not new_email_data:
            error_msg = f"Failed to generate new follow-up email for conversation {conversation_id}"
            logger.error(error_msg)
            print(f"❌ {error_msg}")
            return {"success": False, "error": error_msg}
        
        # Determine the correct email type based on current follow-up count
        current_follow_up_count = email_record["follow_up_queue"]["follow_up_count"]
        email_type_map = {
            0: "initial",
            1: "follow_up_1", 
            2: "follow_up_2",
            3: "follow_up_3"
        }
        email_type = email_type_map.get(current_follow_up_count + 1, "custom")
        
        # 🔧 MAINTAIN SAME SUBJECT AS PREVIOUS EMAIL 🔧
        # Get the previous email's subject to maintain consistency
        previous_subject = get_previous_email_subject(queue_id)
        subject_to_use = previous_subject if previous_subject else new_email_data["subject"]
        
        if previous_subject:
            print(f"📧 Using previous email subject: '{previous_subject}' (AI generated: '{new_email_data['subject']}')")
        else:
            print(f"📧 No previous email found, using AI generated subject: '{new_email_data['subject']}'")
        
        # Create the new email record in the database
        new_email_record = {
            "follow_up_queue_id": queue_id,
            "email_type": email_type,  # Use the determined email type
            "recipient_email": email_record["recipient_email"],
            "recipient_name": email_record["recipient_name"],
            "subject": subject_to_use,  # Use previous subject for consistency
            "message": new_email_data["email_body"],  # Use HTML body
            "delivery_status": "pending",
            "scheduled_for": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(),  # Schedule for 1 minute from now
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Insert the new email record
        insert_response = supabase.table("follow_up_emails").insert(new_email_record).execute()
        
        if not insert_response.data:
            error_msg = f"Failed to save new follow-up email to database"
            logger.error(error_msg)
            print(f"❌ {error_msg}")
            return {"success": False, "error": error_msg}
        
        new_email_id = insert_response.data[0]["id"]
        logger.info(f"Successfully generated and saved new follow-up email {new_email_id} for conversation {conversation_id}")
        print(f"✅ Generated new follow-up email {new_email_id} for conversation {conversation_id}")
        
        return {"success": True, "email_id": new_email_id}
        
    except Exception as e:
        error_msg = f"Error generating new follow-up email: {str(e)}"
        logger.error(error_msg)
        print(f"💥 {error_msg}")
        return {"success": False, "error": error_msg}

@celery_app.task(bind=True, base=RetryableTask, queue="email", soft_time_limit=300, time_limit=600)
def generate_new_followup_email_task(self, email_record: Dict[str, Any]):
    """
    Separate Celery task to generate new follow-up emails.
    This avoids event loop conflicts by running in isolation.
    """
    print(f"🔄 TASK EXECUTED: generate_new_followup_email_task for queue: {email_record['follow_up_queue_id']}")
    print(f"🔄 Task ID: {self.request.id}")
    print(f"🔄 Email record keys: {list(email_record.keys())}")
    
    try:
        print(f"🔄 Starting separate task to generate new follow-up email for queue: {email_record['follow_up_queue_id']}")
        
        # Use nest_asyncio to handle nested event loops in Celery
        import nest_asyncio
        nest_asyncio.apply()
        
        # Extract data from the email record
        queue_id = email_record["follow_up_queue_id"]
        conversation_id = email_record["follow_up_queue"]["conversation_id"]
        bot_id = email_record["follow_up_queue"]["bot_id"]
        previous_email_context = email_record["message"]
        
        print(f"Generating new email - Queue: {queue_id}, Conversation: {conversation_id}, Bot: {bot_id}")
        
        # Generate the new email using asyncio.run() which handles event loops properly
        new_email_data = asyncio.run(generate_follow_up_email(
            bot_id=bot_id,
            conversation_id=conversation_id,
            previous_email_context=previous_email_context
        ))
        
        if not new_email_data:
            print(f"❌ Failed to generate new follow-up email for conversation {conversation_id}")
            return {"success": False, "error": "Failed to generate email"}
        
        # Determine the correct email type based on current follow-up count
        current_follow_up_count = email_record["follow_up_queue"]["follow_up_count"]
        email_type_map = {
            0: "initial",
            1: "follow_up_1", 
            2: "follow_up_2",
            3: "follow_up_3"
        }
        email_type = email_type_map.get(current_follow_up_count + 1, "custom")
        
        # 🔧 MAINTAIN SAME SUBJECT AS PREVIOUS EMAIL 🔧
        # Get the previous email's subject to maintain consistency
        previous_subject = get_previous_email_subject(queue_id)
        subject_to_use = previous_subject if previous_subject else new_email_data["subject"]
        
        if previous_subject:
            print(f"📧 Using previous email subject: '{previous_subject}' (AI generated: '{new_email_data['subject']}')")
        else:
            print(f"📧 No previous email found, using AI generated subject: '{new_email_data['subject']}'")
        
        # Create the new email record in the database
        new_email_record = {
            "follow_up_queue_id": queue_id,
            "email_type": email_type,
            "recipient_email": email_record["recipient_email"],
            "recipient_name": email_record["recipient_name"],
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
            print(f"❌ Failed to save new follow-up email to database")
            return {"success": False, "error": "Failed to save to database"}
        
        new_email_id = insert_response.data[0]["id"]
        print(f"✅ Successfully generated and saved new follow-up email {new_email_id} for conversation {conversation_id}")
        
        return {"success": True, "email_id": new_email_id}
            
    except Exception as e:
        error_msg = f"Error in generate_new_followup_email_task: {str(e)}"
        logger.error(error_msg)
        print(f"💥 {error_msg}")
        return {"success": False, "error": error_msg}

@celery_app.task(bind=True, base=RetryableTask, queue="email", soft_time_limit=300, time_limit=600)
def cleanup_failed_emails(self):
    """
    Clean up failed emails and retry logic.
    This task can be run daily to handle failed emails.
    """
    # CLEANUP CRON JOB EXECUTION LOG
    print("=" * 80)
    print(f"🧹 EMAIL CLEANUP CRON JOB EXECUTED at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🕐 Task ID: {self.request.id}")
    print("=" * 80)
    
    logger.info(f"Starting email cleanup at {datetime.now()}")
    print(f"🧹 Email cleanup cron job started at {datetime.now()}")
    
    try:
        # Get failed emails from the last 24 hours
        yesterday = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        
        response = supabase.table("follow_up_emails").select("*").eq("delivery_status", "failed").gte("created_at", yesterday.isoformat()).execute()
        
        if not response.data:
            logger.info("No failed emails to process")
            return {"processed": 0}
        
        logger.info(f"Found {len(response.data)} failed emails")
        
        for email_record in response.data:
            # You can implement retry logic here
            # For now, just log them
            logger.info(f"Failed email: {email_record['id']} to {email_record['recipient_email']}")
        
        return {"processed": len(response.data)}
        
    except Exception as e:
        logger.error(f"Email cleanup error: {str(e)}")
        return {"processed": 0, "error": str(e)}

# Test function to manually trigger email sending
def test_email_scheduler():
    """
    Test function to manually trigger the email scheduler.
    Useful for testing and debugging.
    """
    logger.info("Testing email scheduler...")
    result = send_scheduled_followup_emails.delay()
    logger.info(f"Task ID: {result.id}")
    return result

def create_test_email():
    """
    Create a test email in the database to trigger the email scheduler.
    This is useful for testing the email generation flow.
    """
    try:
        # Create a test email record
        test_email = {
            "follow_up_queue_id": "test-queue-id",  # You'll need a real queue ID
            "email_type": "initial",
            "subject": "Test Follow-up Email",
            "message": "This is a test email to trigger the scheduler.",
            "recipient_email": "test@example.com",
            "recipient_name": "Test User",
            "delivery_status": "pending",
            "scheduled_for": datetime.now(timezone.utc).isoformat(),  # Schedule for now
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Insert the test email
        response = supabase.table("follow_up_emails").insert(test_email).execute()
        
        if response.data:
            print(f"✅ Created test email with ID: {response.data[0]['id']}")
            return response.data[0]['id']
        else:
            print("❌ Failed to create test email")
            return None
            
    except Exception as e:
        print(f"💥 Error creating test email: {str(e)}")
        return None

# Schedule configuration moved to celery_app.py for better integration

# 🔧 TESTING AND DEBUGGING UTILITIES 🔧

def test_email_threading(queue_id: str):
    """
    Test email threading for a specific queue.
    Use this function to debug threading issues.
    
    Example usage:
    python -c "from app.tasks.email_scheduler import test_email_threading; test_email_threading('your-queue-id')"
    """
    print(f"🧪 TESTING EMAIL THREADING for queue: {queue_id}")
    print("=" * 80)
    
    # Get and display thread info
    thread_info = get_thread_info_for_queue(queue_id)
    print(f"📊 Thread Info:")
    print(f"  - Thread ID: {thread_info.get('thread_id', 'None')}")
    print(f"  - Message ID: {thread_info.get('message_id', 'None')}")
    print(f"  - Total Emails: {thread_info.get('email_count', 0)}")
    print(f"  - Sent Emails: {thread_info.get('sent_count', 0)}")
    print(f"  - Pending Emails: {thread_info.get('pending_count', 0)}")
    
    # Run verification
    verification = verify_email_threading(queue_id)
    
    # Summary
    print(f"\n📋 SUMMARY:")
    print(f"  - Status: {verification.get('status', 'unknown')}")
    if verification.get('issues'):
        print(f"  - Issues: {len(verification['issues'])}")
    if verification.get('recommendations'):
        print(f"  - Recommendations: {len(verification['recommendations'])}")
    
    print("=" * 80)
    return verification

def list_all_threading_issues():
    """
    Find all follow-up queues with potential threading issues.
    """
    print(f"🔍 SCANNING ALL QUEUES FOR THREADING ISSUES...")
    print("=" * 80)
    
    try:
        # Get all active follow-up queues
        queues_response = supabase.table("follow_up_queue").select("id, customer_name, customer_email, follow_up_count").execute()
        
        if not queues_response.data:
            print("📭 No follow-up queues found.")
            return
        
        print(f"📊 Found {len(queues_response.data)} follow-up queues to check...")
        
        issues_found = []
        healthy_queues = []
        
        for queue in queues_response.data:
            queue_id = queue["id"]
            try:
                verification = verify_email_threading(queue_id)
                
                if verification["status"] == "issues_found":
                    issues_found.append({
                        "queue_id": queue_id,
                        "customer": queue.get("customer_name", "Unknown"),
                        "email": queue.get("customer_email", "Unknown"),
                        "issues": verification.get("issues", []),
                        "email_count": verification.get("email_count", 0)
                    })
                elif verification["status"] == "healthy":
                    healthy_queues.append(queue_id)
                    
            except Exception as e:
                print(f"❌ Error checking queue {queue_id}: {str(e)}")
        
        print(f"\n📊 RESULTS SUMMARY:")
        print(f"  - Healthy Queues: {len(healthy_queues)}")
        print(f"  - Queues with Issues: {len(issues_found)}")
        
        if issues_found:
            print(f"\n⚠️ QUEUES WITH THREADING ISSUES:")
            for issue_queue in issues_found:
                print(f"  📧 {issue_queue['customer']} ({issue_queue['email']})")
                print(f"     Queue ID: {issue_queue['queue_id']}")
                print(f"     Email Count: {issue_queue['email_count']}")
                print(f"     Issues: {', '.join(issue_queue['issues'])}")
                print()
        
        print("=" * 80)
        return {"healthy": len(healthy_queues), "issues": len(issues_found), "details": issues_found}
        
    except Exception as e:
        print(f"❌ Error scanning queues: {str(e)}")
        return None

def manual_fix_queue_threading(queue_id: str, force_thread_id: str = None):
    """
    Manually fix threading for a queue by setting all emails to use the same thread_id.
    
    Args:
        queue_id: The queue to fix
        force_thread_id: Optional thread_id to use. If not provided, uses the first found thread_id.
    """
    print(f"🔧 MANUALLY FIXING THREADING for queue: {queue_id}")
    print("=" * 60)
    
    try:
        # Get all emails in the queue
        emails_response = supabase.table("follow_up_emails").select("*").eq("follow_up_queue_id", queue_id).order("created_at", desc=False).execute()
        
        if not emails_response.data:
            print("❌ No emails found in queue")
            return False
        
        emails = emails_response.data
        print(f"📧 Found {len(emails)} emails in queue")
        
        # Find or set the thread_id to use
        target_thread_id = force_thread_id
        if not target_thread_id:
            # Look for the first email with a thread_id
            for email in emails:
                if email.get("thread_id"):
                    target_thread_id = email["thread_id"]
                    print(f"🔗 Using existing thread_id: {target_thread_id}")
                    break
        
        if not target_thread_id:
            print("❌ No thread_id found and none provided. Cannot fix threading.")
            return False
        
        # Update all emails to use the same thread_id
        updated_count = 0
        for email in emails:
            if email.get("thread_id") != target_thread_id:
                try:
                    supabase.table("follow_up_emails").update({
                        "thread_id": target_thread_id,
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    }).eq("id", email["id"]).execute()
                    
                    print(f"✅ Updated email {email['email_type']} to use thread_id: {target_thread_id}")
                    updated_count += 1
                except Exception as e:
                    print(f"❌ Error updating email {email['id']}: {str(e)}")
        
        print(f"🎉 Fixed {updated_count} emails. Verifying...")
        
        # Verify the fix
        verification = verify_email_threading(queue_id)
        if verification["status"] == "healthy":
            print(f"✅ Threading fix successful!")
            return True
        else:
            print(f"⚠️ Threading fix may not have worked completely")
            return False
        
    except Exception as e:
        print(f"❌ Error fixing threading: {str(e)}")
        return False

if __name__ == "__main__":
    print("🔧 EMAIL SCHEDULER TESTING & DEBUGGING UTILITIES")
    print("=" * 60)
    print("Available functions:")
    print("1. test_email_threading(queue_id) - Test threading for a specific queue")
    print("2. list_all_threading_issues() - Find all queues with threading issues")
    print("3. manual_fix_queue_threading(queue_id) - Manually fix threading for a queue")
    print("4. verify_email_threading(queue_id) - Verify threading for a queue")
    print("5. get_thread_info_for_queue(queue_id) - Get detailed thread info")
    print()
    print("Example usage:")
    print("python -c \"from app.tasks.email_scheduler import test_email_threading; test_email_threading('your-queue-id')\"")
    print("python -c \"from app.tasks.email_scheduler import list_all_threading_issues; list_all_threading_issues()\"")
    print("=" * 60)
    
    # Uncomment these lines to run tests:
    # test_email_scheduler()
    # list_all_threading_issues()
