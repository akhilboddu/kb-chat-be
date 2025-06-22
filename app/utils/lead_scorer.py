"""
Lead Scorer Utility

This module provides functions to process conversations through the lead scoring agent
and save the results to the bot_crms table.
"""

import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime

from app.core.lead_scoring_agent import score_lead_from_conversation
from app.core.supabase_client import supabase
from app.core.supabase_metadata_manager import get_formatted_conversation_history_and_customer_details


async def process_lead_scoring(conversations: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Process an array of conversations through the lead scoring agent and save results to bot_crms table.
    
    Args:
        conversations: List of dictionaries with 'conversation_id' and 'bot_id' keys
        
    Returns:
        Dictionary with processing results including success count, errors, and details
    """
    results = {
        "total_processed": 0,
        "successful": 0,
        "failed": 0,
        "errors": [],
        "details": []
    }
    
    if not conversations:
        results["errors"].append("No conversations provided")
        return results
    
    print(f"Starting lead scoring for {len(conversations)} conversations...")
    
    for i, conversation in enumerate(conversations):
        conversation_id = conversation.get('conversation_id')
        bot_id = conversation.get('bot_id')
        
        if not conversation_id or not bot_id:
            error_msg = f"Missing conversation_id or bot_id in conversation {i}: {conversation}"
            results["errors"].append(error_msg)
            results["failed"] += 1
            results["total_processed"] += 1
            continue
        
        try:
            # Process the conversation through the lead scoring agent
            lead_score_result = await score_lead_from_conversation(bot_id, conversation_id)
            
            if lead_score_result:
                # Extract the lead scoring data
                score = lead_score_result.get('score', 0)
                reason = lead_score_result.get('reason', '')
                contact_info = lead_score_result.get('email or phone number')
                
                # Validate contact_info
                if not contact_info or contact_info.strip() == "":
                    print(f"⚠️  No contact info found for conversation {conversation_id}, skipping CRM update")
                    results["details"].append({
                        "conversation_id": conversation_id,
                        "bot_id": bot_id,
                        "score": score,
                        "status": "skipped - no contact info"
                    })
                    results["successful"] += 1
                    results["total_processed"] += 1
                    continue
                
                # Get the conversation history for chat summary
                chat_summary = await get_formatted_conversation_history_and_customer_details(conversation_id)
                if not chat_summary:
                    chat_summary = "No conversation history available"
                
                # Update the bot_crms table with lead score and chat summary
                crm_data = {
                    "bot_id": bot_id,
                    "email": contact_info,
                    "lead_score": score,
                    "chat_summary": reason,
                    "updated_at": datetime.utcnow().isoformat()
                }

                print(f"CRM data: {crm_data}")
                
                # First try to find existing record, then update or insert
                try:
                    # Check if record exists
                    if chat_summary.get("customer_email"):
                        
                        existing_record = supabase.table('bot_crms').select('id').eq('bot_id', bot_id).eq('email', contact_info).execute()
                    else:
                        existing_record = supabase.table('bot_crms').select('id').eq('bot_id', bot_id).eq('phone_number', contact_info).execute()

                    
                    if existing_record.data and len(existing_record.data) > 0:
                        # Update existing record
                        record_id = existing_record.data[0]['id']
                        response = supabase.table('bot_crms').update(crm_data).eq('id', record_id).execute()
                    else:
                        # Insert new record
                        crm_data['created_at'] = datetime.utcnow().isoformat()
                        response = supabase.table('bot_crms').insert(crm_data).execute()
                    
                    if response.data:
                        results["successful"] += 1
                        results["details"].append({
                            "conversation_id": conversation_id,
                            "bot_id": bot_id,
                            "score": score,
                            "status": "success"
                        })
                        print(f"✅ Successfully processed conversation {conversation_id} with score {score}")
                    else:
                        error_msg = f"Failed to save to database for conversation {conversation_id}"
                        results["errors"].append(error_msg)
                        results["failed"] += 1
                        
                except Exception as db_error:
                    error_msg = f"Database error for conversation {conversation_id}: {str(db_error)}"
                    results["errors"].append(error_msg)
                    results["failed"] += 1
                    print(f"❌ Database error: {error_msg}")
                    print(f"   CRM data that failed: {crm_data}")
                    print(f"   Contact info: {contact_info}")
                    import traceback
                    traceback.print_exc()
                    
            else:
                # Lead scoring returned None (likely disabled or no config)
                results["details"].append({
                    "conversation_id": conversation_id,
                    "bot_id": bot_id,
                    "score": None,
                    "status": "skipped - lead scoring disabled or no config"
                })
                results["successful"] += 1  # Count as successful since it's expected behavior
                print(f"⏭️  Skipped conversation {conversation_id} - lead scoring disabled or no config")
                
        except Exception as e:
            error_msg = f"Error processing conversation {conversation_id}: {str(e)}"
            results["errors"].append(error_msg)
            results["failed"] += 1
            print(f"❌ Error: {error_msg}")
            
        results["total_processed"] += 1
    
    print(f"\n📊 Lead scoring complete:")
    print(f"   Total processed: {results['total_processed']}")
    print(f"   Successful: {results['successful']}")
    print(f"   Failed: {results['failed']}")
    
    return results


async def score_single_conversation(conversation_id: str, bot_id: str) -> Optional[Dict[str, Any]]:
    """
    Score a single conversation and save to bot_crms table.
    
    Args:
        conversation_id: The conversation ID to process
        bot_id: The bot ID associated with the conversation
        
    Returns:
        Dictionary with the result or None if failed
    """
    conversations = [{"conversation_id": conversation_id, "bot_id": bot_id}]
    results = await process_lead_scoring(conversations)
    
    if results["successful"] > 0:
        return results["details"][0] if results["details"] else None
    else:
        return None


def run_lead_scoring_batch(conversations: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Synchronous wrapper for batch lead scoring processing.
    
    Args:
        conversations: List of dictionaries with 'conversation_id' and 'bot_id' keys
        
    Returns:
        Dictionary with processing results
    """
    return asyncio.run(process_lead_scoring(conversations))


def run_single_lead_scoring(conversation_id: str, bot_id: str) -> Optional[Dict[str, Any]]:
    """
    Synchronous wrapper for single conversation lead scoring.
    
    Args:
        conversation_id: The conversation ID to process
        bot_id: The bot ID associated with the conversation
        
    Returns:
        Dictionary with the result or None if failed
    """
    return asyncio.run(score_single_conversation(conversation_id, bot_id))


if __name__ == "__main__":
    # Example usage for testing
    import json
    
    async def test_lead_scorer():
        """Test function to demonstrate usage"""
        
        # Example conversations to process
        test_conversations = [
            {
                "conversation_id": "5f397169-f05f-4903-9ef9-656b7c02ed97",
                "bot_id": "18eb9b0c-d283-4781-a727-6140d940db42"
            }
        ]
        
        print("🧪 Testing lead scorer utility...")
        results = await process_lead_scoring(test_conversations)
        
        print("\n📋 Results:")
        print(json.dumps(results, indent=2))
        
        # Test single conversation scoring
        print("\n🧪 Testing single conversation scoring...")
        single_result = await score_single_conversation("test-conversation-3", "test-bot-3")
        print(f"Single result: {single_result}")
    
    # Run the test
    asyncio.run(test_lead_scorer()) 