# kb-chat-be/app/core/follow_up_email_agent.py

import os
import json
import json5
import re
from typing import Dict, Any, Optional
from datetime import datetime

from langchain.agents import AgentExecutor, create_react_agent
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI
from app.core.config import llm
from app.core import supabase_metadata_manager as db_manager
from app.core.tools import get_retriever_tool

# 🔧 DEDICATED OPENAI LLM FOR FOLLOW-UP EMAIL GENERATION 🔧
def get_openai_llm_for_followup():
    """
    Get a dedicated OpenAI LLM instance specifically for follow-up email generation.
    This ensures we use OpenAI even if the default LLM is configured to use other providers.
    """
    openai_api_key = os.getenv("OPENAI_API_KEY")
    openai_model = os.getenv("OPENAI_MODEL", "gpt-4")
    
    if not openai_api_key:
        print("⚠️  Warning: OPENAI_API_KEY not found. Falling back to default LLM.")
        return llm
    
    try:
        openai_llm = ChatOpenAI(
            model=openai_model,
            api_key=openai_api_key,
            temperature=0.3,  # Slightly higher temperature for more creative emails
            max_tokens=2000,  # Ensure enough tokens for email generation
            request_timeout=60  # Longer timeout for email generation
        )
        print(f"✅ Using OpenAI {openai_model} for follow-up email generation")
        return openai_llm
    except Exception as e:
        print(f"❌ Failed to initialize OpenAI LLM for follow-up emails: {e}")
        print("⚠️  Falling back to default LLM configuration")
        return llm

# ReAct Agent Prompt Template for Follow-up Email Generation
REACT_FOLLOW_UP_EMAIL_PROMPT = """You are an expert email marketing assistant specialized in creating personalized follow-up emails using a ReAct (Reasoning and Acting) approach.

Your task is to:
1. First, analyze the conversation context and draft a follow-up email using the previous email context as a reference
2. The new email should not sound like a copy of the previous email
3. Identify any missing information or areas that need enhancement
4. Use the knowledge base retriever tool to get relevant information about products, services, pricing, links, etc.
5. Refine the email with the retrieved information - keep email short - medium length is best.
6. Output the final email in the required JSON format
7. The email should be in HTML format with proper structure using <br> tags for line breaks - No images in the emails.

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

CRITICAL FORMAT RULES - YOU MUST FOLLOW THESE EXACTLY:

1. ALWAYS start with a "Thought:" followed by your reasoning
2. ALWAYS follow "Thought:" with either "Action:" or "Final Answer:" on the next line
3. NEVER leave a "Thought:" without an immediate "Action:" or "Final Answer:"
4. Use this exact format:

Thought: [Your reasoning here]
Action: knowledge_base_retriever
Action Input: [search query]

OR

Thought: [Your reasoning here]
Final Answer: [JSON output]

5. The "Final Answer:" must contain ONLY the JSON object, no additional text or markdown formatting.

The Final Answer MUST be a JSON object with the following keys:
1. "subject": A compelling email subject line
2. "email_body": The complete email body in HTML format
3. "plain_text_body": The complete email body in plain text format
4. "key_points": An array of the main points addressed in the email
5. "call_to_action": The primary call-to-action from the email (null if no specific actionable links available)
6. "follow_up_reason": Brief explanation of why this follow-up is being sent
7. "urgency_level": "low", "medium", or "high" based on conversation context

Example Final Answer format:
{{
    "subject": "Follow-up on our conversation",
    "email_body": "The complete email body in HTML format",
    "plain_text_body": "The complete email body in plain text format",
    "key_points": ["Point 1", "Point 2", "Point 3"],
    "call_to_action": "Primary call-to-action or null",
    "follow_up_reason": "Brief explanation of why this follow-up is being sent",
    "urgency_level": "low|medium|high"
}}

Begin!

{agent_scratchpad}"""

def extract_json_from_markdown(text: str) -> Optional[str]:
    """
    Extract JSON content from markdown code blocks.
    Handles various markdown formats including 3 and 4 backticks.
    """
    if not text:
        return None
    
    # Patterns for different markdown code block formats
    patterns = [
        # 4 backticks with language specification
        r'````json\s*\n(.*?)\n````',
        # 4 backticks without language
        r'````\s*\n(.*?)\n````',
        # 3 backticks with language specification
        r'```json\s*\n(.*?)\n```',
        # 3 backticks without language
        r'```\s*\n(.*?)\n```',
        # Inline code blocks
        r'`(.*?)`',
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, text, re.DOTALL)
        if matches:
            # Use the longest match (most likely to be complete JSON)
            longest_match = max(matches, key=len)
            cleaned = longest_match.strip()
            
            # Basic validation - should start with { and end with }
            if cleaned.startswith('{') and cleaned.endswith('}'):
                return cleaned
    
    # If no markdown blocks found, try to extract JSON directly
    # Look for JSON object boundaries
    start = text.find('{')
    end = text.rfind('}')
    
    if start != -1 and end != -1 and end > start:
        potential_json = text[start:end + 1]
        # Basic validation
        if potential_json.count('{') == potential_json.count('}'):
            return potential_json
    
    return None

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

    # 0. Check OpenAI configuration for follow-up emails
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        print("⚠️  Warning: OPENAI_API_KEY not found. Follow-up emails will use default LLM configuration.")
    else:
        print(f"✅ OpenAI API key found. Will use OpenAI for follow-up email generation.")

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

    # 8. Create the ReAct agent with dedicated OpenAI LLM
    prompt = PromptTemplate.from_template(REACT_FOLLOW_UP_EMAIL_PROMPT)
    
    # Use dedicated OpenAI LLM for follow-up email generation
    followup_llm = get_openai_llm_for_followup()
    
    agent = create_react_agent(followup_llm, tools, prompt)
    agent_executor = AgentExecutor(
        agent=agent, 
        tools=tools, 
        verbose=True, 
        max_iterations=10,  # Reduced to prevent loops and format errors
        handle_parsing_errors=True,
        return_intermediate_steps=True  # This helps with debugging
    )

    # 9. Invoke the ReAct agent
    try:
        print(f"Invoking ReAct agent for follow-up email generation on conversation {conversation_id}...")
        print(f"🤖 Using LLM: {followup_llm.__class__.__name__} for follow-up email generation")
        
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
        
        print(f"Agent input prepared with customer: {customer_name}, email: {history_data.get('customer_email', '')}")
        
        result = await agent_executor.ainvoke(agent_input)
        raw_output = result.get("output", "")
        
        print(f"Agent execution completed. Output length: {len(raw_output)}")
        if len(raw_output) > 500:
            print(f"First 500 chars: {raw_output[:500]}")
            print(f"Last 500 chars: {raw_output[-500:]}")
        else:
            print(f"Full output: {raw_output}")
        
        print(f"Raw Agent Output: {raw_output}")
        print(f"Raw output length: {len(raw_output)}")
        print(f"Raw output starts with: {raw_output[:50]}")
        print(f"Raw output ends with: {raw_output[-50:]}")

        # 10. Extract and parse JSON using robust libraries
        json_content = extract_json_from_markdown(raw_output)
        
        if json_content:
            print(f"Extracted JSON content: {json_content[:200]}...")
            
            # Try parsing with json5 first (more lenient)
            try:
                json_output = json5.loads(json_content)
                print("Successfully parsed JSON with json5")
            except Exception as e:
                print(f"json5 parsing failed: {e}")
                
                # Fallback to standard json with some cleanup
                try:
                    # Basic cleanup for standard json
                    cleaned_json = json_content.strip()
                    # Remove trailing commas
                    cleaned_json = re.sub(r',(\s*[}\]])', r'\1', cleaned_json)
                    # Fix common JSON issues
                    cleaned_json = re.sub(r'\\"', '"', cleaned_json)  # Fix escaped quotes
                    cleaned_json = re.sub(r'\\\\', '\\', cleaned_json)  # Fix double escapes
                    json_output = json.loads(cleaned_json)
                    print("Successfully parsed JSON with standard json after cleanup")
                except Exception as e2:
                    print(f"Standard json parsing also failed: {e2}")
                    
                    # Last resort: try to extract just the essential fields
                    try:
                        print("Attempting to extract essential fields manually...")
                        subject_match = re.search(r'"subject":\s*"([^"]+)"', json_content)
                        urgency_match = re.search(r'"urgency_level":\s*"([^"]+)"', json_content)
                        reason_match = re.search(r'"follow_up_reason":\s*"([^"]+)"', json_content)
                        
                        if subject_match:
                            json_output = {
                                "subject": subject_match.group(1),
                                "email_body": f"<p>Hi {customer_name},</p><p>I wanted to follow up on our conversation and see if you have any questions or need additional information.</p><p>Best regards,<br>{bot_info.get('name', 'Assistant')}</p>",
                                "plain_text_body": f"Hi {customer_name},\n\nI wanted to follow up on our conversation and see if you have any questions or need additional information.\n\nBest regards,\n{bot_info.get('name', 'Assistant')}",
                                "key_points": ["Follow-up on conversation", "Offer additional support"],
                                "call_to_action": None,
                                "follow_up_reason": reason_match.group(1) if reason_match else "Standard follow-up after conversation",
                                "urgency_level": urgency_match.group(1) if urgency_match else "medium"
                            }
                            print("Successfully extracted essential fields manually")
                        else:
                            json_output = None
                    except Exception as e3:
                        print(f"Manual extraction also failed: {e3}")
                        json_output = None
        else:
            print("No JSON content found in markdown")
            json_output = None
        
        # If all parsing failed, create fallback
        if not json_output:
            print("Creating fallback email structure...")
            json_output = {
                "subject": f"Follow-up: {customer_name}",
                "email_body": f"<p>Hi {customer_name},</p><p>I wanted to follow up on our conversation and see if you have any questions or need additional information.</p><p>Best regards,<br>{bot_info.get('name', 'Assistant')}</p>",
                "plain_text_body": f"Hi {customer_name},\n\nI wanted to follow up on our conversation and see if you have any questions or need additional information.\n\nBest regards,\n{bot_info.get('name', 'Assistant')}",
                "key_points": ["Follow-up on conversation", "Offer additional support"],
                "call_to_action": None,
                "follow_up_reason": "Standard follow-up after conversation",
                "urgency_level": "medium"
            }
        
        # 11. Validate required fields
        required_fields = ["subject", "email_body", "plain_text_body", "key_points", "call_to_action", "follow_up_reason", "urgency_level"]
        if all(field in json_output for field in required_fields):
            # Add metadata
            json_output["generated_at"] = datetime.utcnow().isoformat()
            json_output["conversation_id"] = conversation_id
            json_output["bot_id"] = bot_id
            json_output["kb_id"] = kb_id
            json_output["customer_email"] = history_data.get("customer_email", "")
            json_output["generation_method"] = "react_agent_openai"  # Indicate OpenAI was used
            
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