#!/usr/bin/env python3
"""
Example usage of the Lead Scorer Utility

This script demonstrates how to use the lead scorer utility to process conversations
and save lead scores to the bot_crms table.
"""

import asyncio
import sys
import os
import json

# Add the current directory to Python path to import app modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.utils.lead_scorer import (
    process_lead_scoring, 
    run_lead_scoring_batch, 
    run_single_lead_scoring
)

async def example_async_usage():
    """Example of using the async functions directly."""
    
    print("=== Async Lead Scorer Usage Example ===")
    
    # Example 1: Process multiple conversations asynchronously
    conversations_to_process = [
        {
            "conversation_id": "conv_12345",
            "bot_id": "bot_abc123"
        },
        {
            "conversation_id": "conv_67890", 
            "bot_id": "bot_def456"
        },
        {
            "conversation_id": "conv_11111",
            "bot_id": "bot_abc123"  # Same bot, different conversation
        }
    ]
    
    print(f"Processing {len(conversations_to_process)} conversations...")
    results = await process_lead_scoring(conversations_to_process)
    
    print("\n📊 Batch Processing Results:")
    print(f"   Total processed: {results['total_processed']}")
    print(f"   Successful: {results['successful']}")
    print(f"   Failed: {results['failed']}")
    
    if results['errors']:
        print(f"   Errors: {len(results['errors'])}")
        for error in results['errors'][:3]:  # Show first 3 errors
            print(f"     - {error}")
    
    if results['details']:
        print(f"   Details:")
        for detail in results['details'][:3]:  # Show first 3 details
            print(f"     - {detail}")

def example_sync_usage():
    """Example of using the synchronous wrapper functions."""
    
    print("\n=== Sync Lead Scorer Usage Example ===")
    
    # Example 2: Process a single conversation synchronously
    print("Processing single conversation...")
    single_result = run_single_lead_scoring(
        conversation_id="conv_single_test",
        bot_id="bot_single_test"
    )
    
    print(f"Single conversation result: {single_result}")
    
    # Example 3: Process multiple conversations synchronously
    print("\nProcessing batch synchronously...")
    batch_conversations = [
        {"conversation_id": "sync_conv_1", "bot_id": "sync_bot_1"},
        {"conversation_id": "sync_conv_2", "bot_id": "sync_bot_2"}
    ]
    
    batch_results = run_lead_scoring_batch(batch_conversations)
    print(f"Batch results: {json.dumps(batch_results, indent=2)}")

def example_integration_with_api():
    """Example of how this might be integrated with an API endpoint."""
    
    print("\n=== API Integration Example ===")
    
    # This is how you might use it in a FastAPI endpoint
    def api_endpoint_example():
        """
        Example API endpoint that processes conversations for lead scoring.
        
        This would be inside a FastAPI route like:
        
        @router.post("/process-leads")
        async def process_leads(request: LeadProcessingRequest):
            conversations = request.conversations
            results = await process_lead_scoring(conversations)
            return results
        """
        
        # Example request data that might come from the frontend
        request_data = {
            "conversations": [
                {"conversation_id": "api_conv_1", "bot_id": "api_bot_1"},
                {"conversation_id": "api_conv_2", "bot_id": "api_bot_1"}
            ]
        }
        
        # Process using the synchronous wrapper for this example
        results = run_lead_scoring_batch(request_data["conversations"])
        
        # Return results (in a real API, this would be JSON response)
        return {
            "status": "completed",
            "processed": results["total_processed"],
            "successful": results["successful"],
            "failed": results["failed"],
            "details": results["details"]
        }
    
    api_result = api_endpoint_example()
    print(f"API endpoint result: {json.dumps(api_result, indent=2)}")

async def main():
    """Main function to run all examples."""
    
    print("🚀 Lead Scorer Utility Usage Examples")
    print("=" * 50)
    
    # Run async example
    await example_async_usage()
    
    # Run sync examples
    example_sync_usage()
    
    # Show API integration example
    example_integration_with_api()
    
    print("\n" + "=" * 50)
    print("✅ All examples completed!")
    print("\nNote: These examples use test data and may not produce actual results")
    print("without real conversation data in your database.")

if __name__ == "__main__":
    asyncio.run(main()) 