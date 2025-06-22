# kb-chat-be/app/core/follow_up_email_agent.py

import os
import json
from typing import Dict, Any, Optional
from datetime import datetime

from langchain.agents import AgentExecutor, create_react_agent
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from app.core.config import llm
from app.core import supabase_metadata_manager as db_manager
from app.core.tools import get_retriever_tool

# ReAct Agent Prompt Template for Follow-up Email Generation
REACT_FOLLOW_UP_EMAIL_PROMPT = """You are an expert email marketing assistant specialized in creating personalized follow-up emails using a ReAct (Reasoning and Acting) approach.

Your task is to:
1. First, analyze the conversation context and draft a follow-up email
2. Identify any missing information or areas that need enhancement
3. Use the knowledge base retriever tool to get relevant information about products, services, pricing, links, etc.
4. Refine the email with the retrieved information
5. Output the final email in the required JSON format

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

FOLLOW-UP INSTRUCTIONS:
{follow_up_instructions}

IMPORTANT CONSTRAINTS:
- You MUST NOT mention any CTAs if you do not have the links needed for the call-to-action
- Only include actionable items when you have specific links or resources from the knowledge base
- If you cannot find specific information, be honest about limitations
- Use the knowledge base to get accurate information about products, services, pricing, and contact details

You have access to the following tools: {tool_names}

{tools}

Use the following format:

Thought: I need to analyze the conversation and draft a follow-up email
Action: knowledge_base_retriever
Action Input: [search query for relevant information]
Observation: [result_of_action]
... (this Thought/Action/Action Input/Observation can repeat N times)
Thought: I now have enough information to create the final email
Final Answer: [JSON output with email content]

The Final Answer MUST be a JSON object with the following keys:
1. "subject": A compelling email subject line
2. "email_body": The complete email body in HTML format
3. "plain_text_body": The complete email body in plain text format
4. "key_points": An array of the main points addressed in the email
5. "call_to_action": The primary call-to-action from the email (null if no specific actionable links available)
6. "follow_up_reason": Brief explanation of why this follow-up is being sent
7. "urgency_level": "low", "medium", or "high" based on conversation context

Begin!

{agent_scratchpad}"""

async def generate_follow_up_email(
    bot_id: str, 
    conversation_id: str, 
    previous_email_context: Optional[str] = None,
    custom_instructions: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Generates a personalized follow-up email using ReAct Agent pattern.

    Args:
        bot_id: The ID of the bot to get configuration from.
        conversation_id: The ID of the conversation to analyze.
        previous_email_context: Optional context from previous emails in the thread.
        custom_instructions: Optional custom instructions for the follow-up email.

    Returns:
        A dictionary containing email content and metadata, or None if an error occurs.
    """
    print(f"Starting ReAct follow-up email generation for conversation {conversation_id} of bot {bot_id}")

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

    # 5. Set up follow-up instructions
    default_instructions = """
    Create a professional, helpful follow-up email that:
    - Shows genuine interest in the customer's needs
    - Provides additional value or information using the knowledge base
    - Maintains a warm but professional tone
    - Includes next steps or resources when available
    - Encourages continued engagement
    - Uses relevant product/service information to enhance the email
    """
    
    follow_up_instructions = custom_instructions or default_instructions

    # 6. Set up previous email context
    email_context = previous_email_context or "This is the first email in the conversation thread."

    # 7. Create tools for the ReAct agent (simplified to just KB retriever)
    tools = [
        get_retriever_tool(kb_id)
    ]

    # 8. Create the ReAct agent
    prompt = PromptTemplate.from_template(REACT_FOLLOW_UP_EMAIL_PROMPT)
    
    agent = create_react_agent(llm, tools, prompt)
    agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True, max_iterations=5)

    # 9. Invoke the ReAct agent
    try:
        print(f"Invoking ReAct agent for follow-up email generation on conversation {conversation_id}...")
        
        agent_input = {
            "chat_summary": history_data["history"],
            "customer_email": history_data.get("customer_email", ""),
            "customer_phone_number": history_data.get("customer_phone_number", ""),
            "customer_name": customer_name,
            "previous_email_context": email_context,
            "company_name": bot_info.get("company", "Our Company"),
            "bot_name": bot_info.get("name", "Assistant"),
            "follow_up_instructions": follow_up_instructions,
        }
        
        result = await agent_executor.ainvoke(agent_input)
        raw_output = result.get("output", "")
        
        print(f"Raw Agent Output: {raw_output}")

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
            json_output["generation_method"] = "react_agent"
            
            print(f"Successfully generated follow-up email for conversation {conversation_id}")
            return json_output
        else:
            missing_fields = [field for field in required_fields if field not in json_output]
            print(f"Error: Agent output for {conversation_id} was missing fields: {missing_fields}")
            return None

    except json.JSONDecodeError as e:
        print(f"Error: Failed to decode JSON from agent output for conversation {conversation_id}: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred during follow-up email generation for conversation {conversation_id}: {e}")
        return None


if __name__ == "__main__":
    import asyncio

    async def main_test():
        """A test function to run the ReAct follow-up email agent."""
        # Test with conversation ID
        test_bot_id = "18eb9b0c-d283-4781-a727-6140d940db42"
        test_conversation_id = "e2df092c-6726-4e14-aead-35d4f8e711ae"
        
        print(f"--- Testing ReAct Follow-Up Email Agent for Bot ID: {test_bot_id} ---")
        result = await generate_follow_up_email(
            bot_id=test_bot_id, 
            conversation_id=test_conversation_id,
            previous_email_context="This is the first email in the conversation thread.",
            custom_instructions="Use the ReAct approach to first draft an email, then use the knowledge base to enhance it with specific information about courses, pricing, and actionable next steps."
        )

        if result:
            print("\n--- ReAct Follow-Up Email Result ---")
            print(json.dumps(result, indent=2))
            print("----------------------------")
        else:
            print("\n--- ReAct Follow-Up Email Generation Failed ---")
            print("The agent did not return a valid email. Check the logs above for errors.")
            print("----------------------------------------")

    # Run the async test function
    asyncio.run(main_test()) 