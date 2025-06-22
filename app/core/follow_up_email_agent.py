# kb-chat-be/app/core/follow_up_email_agent.py

import os
import json
from typing import Dict, Any, Optional
from datetime import datetime

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from app.core.config import llm
from app.core import supabase_metadata_manager as db_manager
from app.core.supabase_kb_manager import kb_manager

FOLLOW_UP_EMAIL_PROMPT_TEMPLATE = """
You are an expert email marketing assistant specialized in creating personalized follow-up emails. Your task is to analyze a conversation history, customer details, and any previous email context to generate a compelling follow-up email.

CUSTOMER DETAILS:
- Email: {customer_email}
- Phone: {customer_phone_number}
- Name: {customer_name}

CHAT SUMMARY:
--- CONVERSATION START ---
{chat_summary}
--- CONVERSATION END ---

PREVIOUS EMAIL CONTEXT:
{previous_email_context}

COMPANY CONTEXT:
- Company Name: {company_name}
- Bot Name: {bot_name}

RELEVANT KNOWLEDGE BASE INFORMATION:
--- KNOWLEDGE BASE CONTEXT ---
{kb_context}
--- END KNOWLEDGE BASE CONTEXT ---

FOLLOW-UP INSTRUCTIONS:
{follow_up_instructions}

Based on the conversation history, customer context, and relevant knowledge base information, create a personalized follow-up email that:

1. References specific points from the conversation
2. Addresses any questions or concerns the customer had
3. Provides value or next steps using information from the knowledge base
4. Maintains the company's tone and brand voice
5. Includes a clear call-to-action and gets the links needed for the call-to-action from the knowledge base
6. Takes into account any previous email interactions
7. Utilizes relevant product/service information from the knowledge base to enhance the email content

The output MUST be a JSON object with the following keys:
1. "subject": A compelling email subject line
2. "email_body": The complete email body in HTML format
3. "plain_text_body": The complete email body in plain text format
4. "key_points": An array of the main points addressed in the email
5. "call_to_action": The primary call-to-action from the email
6. "follow_up_reason": Brief explanation of why this follow-up is being sent
7. "urgency_level": "low", "medium", or "high" based on conversation context

JSON Output:
"""

async def get_relevant_kb_context(kb_id: str, conversation_summary: str, customer_email: str = "", n_results: int = 5) -> str:
    """
    Retrieves relevant information from the knowledge base based on conversation context.
    
    Args:
        kb_id: The knowledge base ID to search
        conversation_summary: Summary of the conversation to use as search query
        customer_email: Customer email for additional context
        n_results: Number of results to retrieve from KB
        
    Returns:
        Formatted string with relevant KB information
    """
    try:
        # Create search queries based on conversation content
        search_queries = []
        
        # Main query from conversation summary
        if conversation_summary and conversation_summary.strip():
            search_queries.append(conversation_summary)
        
        # Extract key topics for additional searches
        conversation_lower = conversation_summary.lower() if conversation_summary else ""
        
        # Common business topics to search for
        business_keywords = [
            "pricing", "price", "cost", "plan", "subscription",
            "features", "benefits", "service", "product",
            "support", "help", "contact", "demo", "trial",
            "implementation", "setup", "onboarding", "training",
            "integration", "API", "documentation", "guide",
            "policy", "terms", "conditions", "refund", "guarantee"
        ]
        
        # Add specific searches for mentioned keywords
        for keyword in business_keywords:
            if keyword in conversation_lower:
                search_queries.append(keyword)
        
        # Collect all relevant documents
        all_docs = []
        
        for query in search_queries[:3]:  # Limit to top 3 queries to avoid too many API calls
            if query.strip():
                results = kb_manager.get_similar_docs(kb_id, query, n_results=n_results)
                
                if results:
                    for result in results:
                        # Avoid duplicates by checking if document content already exists
                        doc_content = result.get('document', '')
                        if doc_content and not any(doc_content in existing_doc for existing_doc in all_docs):
                            all_docs.append(doc_content)
        
        if not all_docs:
            return "No relevant information found in the knowledge base."
        
        # Format and limit the KB context to avoid token limits
        formatted_docs = []
        total_length = 0
        max_length = 3000  # Limit to prevent prompt from becoming too long
        
        for doc in all_docs[:10]:  # Limit to top 10 documents
            if total_length + len(doc) < max_length:
                formatted_docs.append(f"• {doc}")
                total_length += len(doc)
            else:
                break
        
        kb_context = "\n\n".join(formatted_docs)
        print(f"KB Context retrieved: {len(formatted_docs)} documents, {total_length} characters")
        
        return kb_context
        
    except Exception as e:
        print(f"Error retrieving KB context: {e}")
        return "Knowledge base information temporarily unavailable."

async def generate_follow_up_email(
    bot_id: str, 
    conversation_id: str, 
    previous_email_context: Optional[str] = None,
    custom_instructions: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Generates a personalized follow-up email based on conversation history and customer details.

    Args:
        bot_id: The ID of the bot to get configuration from.
        conversation_id: The ID of the conversation to analyze.
        previous_email_context: Optional context from previous emails in the thread.
        custom_instructions: Optional custom instructions for the follow-up email.

    Returns:
        A dictionary containing email content and metadata, or None if an error occurs.
    """
    print(f"Starting follow-up email generation for conversation {conversation_id} of bot {bot_id}")

    # 1. Get follow-up configuration from database
    config = db_manager.get_follow_up_config(bot_id) if hasattr(db_manager, 'get_follow_up_config') else None
    
    # Use default configuration if none exists
    if not config:
        print(f"No follow-up configuration found for bot {bot_id}. Using defaults.")
        config = {
            "is_enabled": True,
            "follow_up_method": "gmail",
            "max_follow_ups": 3,
            "stop_on_reply": True
        }

    if not config.get("is_enabled"):
        print(f"Follow-up email tool is not enabled for bot {bot_id}. Skipping.")
        return None

    # 2. Get bot information for company context and KB ID
    bot_info = db_manager.get_bot_by_bot_id(bot_id)
    if not bot_info:
        print(f"Bot information not found for bot_id: {bot_id}")
        return None

    # Get the knowledge base ID (assuming it's stored in bot_info or using bot_id as kb_id)
    kb_id = bot_info.get('kb_id') or bot_id

    # 3. Fetch the conversation history and customer details
    history_data = await db_manager.get_formatted_conversation_history_and_customer_details(conversation_id)
    if not history_data:
        print(f"No conversation history found for {conversation_id}. Skipping.")
        return None

    # 4. Get conversation details for customer name
    try:
        conversation_details = db_manager.supabase.table("conversations").select("*").eq("id", conversation_id).execute()
        customer_name = "Valued Customer"  # Default
        if conversation_details.data and len(conversation_details.data) > 0:
            # Try to extract name from conversation or use email prefix
            customer_email = history_data.get("customer_email", "")
            if customer_email:
                customer_name = customer_email.split("@")[0].title()
    except Exception as e:
        print(f"Error getting conversation details: {e}")
        customer_name = "Valued Customer"

    # 5. Retrieve relevant knowledge base context
    print(f"Retrieving knowledge base context for KB: {kb_id}")
    kb_context = await get_relevant_kb_context(
        kb_id=kb_id, 
        conversation_summary=history_data["history"],
        customer_email=history_data.get("customer_email", "")
    )

    # 6. Set up follow-up instructions
    default_instructions = """
    Create a professional, helpful follow-up email that:
    - Shows genuine interest in the customer's needs
    - Provides additional value or information from the knowledge base
    - Maintains a warm but professional tone
    - Includes next steps or resources
    - Encourages continued engagement
    - Uses relevant product/service information to enhance the email
    """
    
    follow_up_instructions = custom_instructions or default_instructions

    # 7. Set up previous email context
    email_context = previous_email_context or "This is the first email in the conversation thread."

    # 8. Create the prompt and chain
    prompt = ChatPromptTemplate.from_template(FOLLOW_UP_EMAIL_PROMPT_TEMPLATE)
    chain = prompt | llm | StrOutputParser()

    # 9. Invoke the chain with all the context
    try:
        print(f"Invoking LLM for follow-up email generation on conversation {conversation_id}...")
        raw_output = await chain.ainvoke({
            "chat_summary": history_data["history"],
            "customer_email": history_data.get("customer_email", ""),
            "customer_phone_number": history_data.get("customer_phone_number", ""),
            "customer_name": customer_name,
            "previous_email_context": email_context,
            "company_name": bot_info.get("company", "Our Company"),
            "bot_name": bot_info.get("name", "Assistant"),
            "kb_context": kb_context,
            "follow_up_instructions": follow_up_instructions,
        })
        
        print(f"Raw LLM Output: {raw_output}")

        # 10. Clean and parse the JSON output
        cleaned_output = raw_output.strip()
        if cleaned_output.startswith("```json"):
            cleaned_output = cleaned_output[7:]
        if cleaned_output.endswith("```"):
            cleaned_output = cleaned_output[:-3]
        cleaned_output = cleaned_output.strip()

        # Remove trailing commas from the JSON object before parsing
        cleaned_output = cleaned_output.rstrip("}").rstrip().rstrip(",") + "}"

        json_output = json.loads(cleaned_output)
        
        # 11. Validate required fields
        required_fields = ["subject", "email_body", "plain_text_body", "key_points", "call_to_action", "follow_up_reason", "urgency_level"]
        if all(field in json_output for field in required_fields):
            # Add metadata
            json_output["generated_at"] = datetime.utcnow().isoformat()
            json_output["conversation_id"] = conversation_id
            json_output["bot_id"] = bot_id
            json_output["kb_id"] = kb_id
            json_output["customer_email"] = history_data.get("customer_email", "")
            json_output["kb_context_used"] = len(kb_context) > 50  # Indicates if KB context was meaningful
            
            print(f"Successfully generated follow-up email for conversation {conversation_id}")
            return json_output
        else:
            missing_fields = [field for field in required_fields if field not in json_output]
            print(f"Error: LLM output for {conversation_id} was missing fields: {missing_fields}")
            return None

    except json.JSONDecodeError as e:
        print(f"Error: Failed to decode JSON from LLM output for conversation {conversation_id}: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred during follow-up email generation for conversation {conversation_id}: {e}")
        return None


async def generate_follow_up_email_from_summary(
    customer_email: str,
    customer_name: str,
    chat_summary: str,
    company_name: str,
    bot_name: str,
    kb_id: Optional[str] = None,
    previous_email_context: Optional[str] = None,
    custom_instructions: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Generates a follow-up email from provided summary data (without needing conversation ID).
    
    Args:
        customer_email: Customer's email address
        customer_name: Customer's name
        chat_summary: Summary of the conversation
        company_name: Name of the company
        bot_name: Name of the bot/assistant
        kb_id: Optional knowledge base ID for context retrieval
        previous_email_context: Optional context from previous emails
        custom_instructions: Optional custom instructions for the email
        
    Returns:
        A dictionary containing email content and metadata, or None if an error occurs.
    """
    print(f"Generating follow-up email from summary for customer: {customer_email}")
    
    # Retrieve knowledge base context if KB ID is provided
    kb_context = "No additional knowledge base information available."
    if kb_id:
        print(f"Retrieving knowledge base context for KB: {kb_id}")
        kb_context = await get_relevant_kb_context(
            kb_id=kb_id, 
            conversation_summary=chat_summary,
            customer_email=customer_email
        )
    
    # Set up default instructions
    default_instructions = """
    Create a professional, helpful follow-up email that:
    - Shows genuine interest in the customer's needs
    - Provides additional value or information from the knowledge base
    - Maintains a warm but professional tone
    - Includes next steps or resources
    - Encourages continued engagement
    - Uses relevant product/service information to enhance the email
    """
    
    follow_up_instructions = custom_instructions or default_instructions
    email_context = previous_email_context or "This is the first email in the conversation thread."
    
    # Create the prompt and chain
    prompt = ChatPromptTemplate.from_template(FOLLOW_UP_EMAIL_PROMPT_TEMPLATE)
    chain = prompt | llm | StrOutputParser()
    
    try:
        print(f"Invoking LLM for follow-up email generation from summary...")
        raw_output = await chain.ainvoke({
            "chat_summary": chat_summary,
            "customer_email": customer_email,
            "customer_phone_number": "",  # Not available in summary mode
            "customer_name": customer_name,
            "previous_email_context": email_context,
            "company_name": company_name,
            "bot_name": bot_name,
            "kb_context": kb_context,
            "follow_up_instructions": follow_up_instructions,
        })
        
        print(f"Raw LLM Output: {raw_output}")

        # Clean and parse the JSON output
        cleaned_output = raw_output.strip()
        if cleaned_output.startswith("```json"):
            cleaned_output = cleaned_output[7:]
        if cleaned_output.endswith("```"):
            cleaned_output = cleaned_output[:-3]
        cleaned_output = cleaned_output.strip()

        # Remove trailing commas from the JSON object before parsing
        cleaned_output = cleaned_output.rstrip("}").rstrip().rstrip(",") + "}"

        json_output = json.loads(cleaned_output)
        
        # Validate required fields
        required_fields = ["subject", "email_body", "plain_text_body", "key_points", "call_to_action", "follow_up_reason", "urgency_level"]
        if all(field in json_output for field in required_fields):
            # Add metadata
            json_output["generated_at"] = datetime.utcnow().isoformat()
            json_output["customer_email"] = customer_email
            json_output["generation_method"] = "summary"
            json_output["kb_id"] = kb_id
            json_output["kb_context_used"] = len(kb_context) > 50 if kb_id else False
            
            print(f"Successfully generated follow-up email from summary for customer: {customer_email}")
            return json_output
        else:
            missing_fields = [field for field in required_fields if field not in json_output]
            print(f"Error: LLM output was missing fields: {missing_fields}")
            return None

    except json.JSONDecodeError as e:
        print(f"Error: Failed to decode JSON from LLM output: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred during follow-up email generation: {e}")
        return None


if __name__ == "__main__":
    import asyncio

    async def main_test():
        """A test function to run the follow-up email agent."""
        # Test with conversation ID
        test_bot_id = "18eb9b0c-d283-4781-a727-6140d940db42"
        test_conversation_id = "e2df092c-6726-4e14-aead-35d4f8e711ae"
        
        print(f"--- Testing Follow-Up Email Agent with KB Integration for Bot ID: {test_bot_id} ---")
        result = await generate_follow_up_email(
            bot_id=test_bot_id, 
            conversation_id=test_conversation_id,
            previous_email_context="This is the first email in the conversation thread.",
            custom_instructions="Focus on using relevant information from the knowledge base to provide helpful resources and next steps."
        )

        if result:
            print("\n--- Follow-Up Email Result ---")
            print(json.dumps(result, indent=2))
            print("----------------------------")
        else:
            print("\n--- Follow-Up Email Generation Failed ---")
            print("The agent did not return a valid email. Check the logs above for errors.")
            print("----------------------------------------")
            
        # Test with summary data including KB integration
        print("\n--- Testing Follow-Up Email Agent with Summary Data and KB Integration ---")
        summary_result = await generate_follow_up_email_from_summary(
            customer_email="test@example.com",
            customer_name="John Smith",
            chat_summary="The user showed high interest by asking about courses and wanting to apply for a specific bootcamp. They also expressed a clear need by indicating their desire to enroll. The user provided an email address.",
            company_name="Zaio",
            bot_name="Abi",
            kb_id=test_bot_id,  # Use bot_id as kb_id for testing
            previous_email_context="This is the first email in the conversation thread",
            custom_instructions="Use knowledge base information to provide specific details about courses, pricing, and enrollment process."
        )
        
        if summary_result:
            print("\n--- Summary-Based Follow-Up Email Result ---")
            print(json.dumps(summary_result, indent=2))
            print("------------------------------------------")
        else:
            print("\n--- Summary-Based Follow-Up Email Generation Failed ---")

    # Run the async test function
    asyncio.run(main_test()) 