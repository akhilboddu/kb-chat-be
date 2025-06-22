# kb-chat-be/app/core/lead_scoring_agent.py

import os
import json
from typing import Dict, Any, Optional

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from app.core.config import llm
from app.core import supabase_metadata_manager as db_manager

# This is a placeholder for the actual Supabase table name we will create later
LEAD_SCORER_CONFIG_TABLE = "lead_scorer_configs"

LEAD_SCORER_PROMPT_TEMPLATE = """
You are an expert lead scoring assistant. Your task is to analyze a conversation and score the user's potential as a lead based on a set of provided criteria.

Here is the customer email:
{customer_email}

Here is the customer phone number:
{customer_phone_number}

Here is the full conversation history:
--- CONVERSATION START ---
{conversation_history}
--- CONVERSATION END ---

Here are the rules and criteria for scoring the lead. You MUST follow these instructions:
--- SCORING GUIDE ---
{scoring_guide}
--- SCORING GUIDE END ---

Based on the conversation and the scoring guide, provide your analysis. The output MUST be a JSON object with three keys:
1. "email or phone number": The email address or phone number of the user. If not found, the value should be null.
2. "score": An integer representing the total calculated score.
3. "reason": A brief, one or two-sentence summary explaining why you assigned that score, citing specific parts of the conversation.

JSON Output:
"""

async def score_lead_from_conversation(bot_id: str, conversation_id: str) -> Optional[Dict[str, Any]]:
    """
    Analyzes a conversation history to score a lead based on dynamic, user-defined criteria.

    Args:
        bot_id: The ID of the bot to get the lead scoring configuration from.
        conversation_id: The ID of the conversation to analyze.

    Returns:
        A dictionary containing the 'score' and 'reason', or None if an error occurs.
    """
    print(f"Starting lead scoring for conversation {conversation_id} of bot {bot_id}")

    # 1. Get lead scoring configuration from database
    config = db_manager.get_lead_scorer_config(bot_id)
    
    # If no config exists, use default disabled state
    if not config:
        print(f"No lead scorer configuration found for bot {bot_id}. Tool is disabled.")
        return None

    if not config.get("is_enabled"):
        print(f"Lead scorer tool is not enabled for bot {bot_id}. Skipping.")
        return None

    scoring_guide = config.get("scoring_guide")
    if not scoring_guide:
        print(f"No scoring guide found for bot {bot_id}. Skipping.")
        return None

    # 2. Fetch the conversation history
    # Note: We assume a function get_formatted_conversation_history exists
    history = await db_manager.get_formatted_conversation_history_and_customer_details(conversation_id)
    if not history:
        print(f"No conversation history found for {conversation_id}. Skipping.")
        return None

    # 3. Create the prompt and chain
    prompt = ChatPromptTemplate.from_template(LEAD_SCORER_PROMPT_TEMPLATE)
    
    chain = prompt | llm | StrOutputParser()

    # 4. Invoke the chain with the conversation details
    try:
        print(f"Invoking LLM for lead scoring on conversation {conversation_id}...")
        raw_output = await chain.ainvoke({
            "conversation_history": history["history"],
            "customer_email": history["customer_email"],
            "customer_phone_number": history["customer_phone_number"],
            "scoring_guide": scoring_guide,
        })
        
        print(f"Raw LLM Output: {raw_output}")

        # 5. Clean and parse the JSON output
        # The LLM often wraps the JSON in a markdown block, so we need to remove it.
        cleaned_output = raw_output.strip()
        if cleaned_output.startswith("```json"):
            cleaned_output = cleaned_output[7:]
        if cleaned_output.endswith("```"):
            cleaned_output = cleaned_output[:-3]
        cleaned_output = cleaned_output.strip()

        # Remove trailing commas from the JSON object before parsing
        cleaned_output = cleaned_output.rstrip("}").rstrip().rstrip(",") + "}"

        json_output = json.loads(cleaned_output)
        
        # Basic validation
        if "score" in json_output and "reason" in json_output and "email or phone number" in json_output:
            print(f"Successfully scored lead for conversation {conversation_id}. Score: {json_output['score']}")
            return json_output
        else:
            print(f"Error: LLM output for {conversation_id} was missing one of 'email or phone number', 'score', or 'reason'.")
            return None

    except json.JSONDecodeError:
        print(f"Error: Failed to decode JSON from LLM output for conversation {conversation_id}.")
        return None
    except Exception as e:
        print(f"An unexpected error occurred during lead scoring for conversation {conversation_id}: {e}")
        return None

if __name__ == "__main__":
    import asyncio

    async def main_test():
        """A test function to run the lead scoring agent."""
        # --- IMPORTANT ---
        # Replace these with a real bot_id and conversation_id from your database for testing.
        test_bot_id = "18eb9b0c-d283-4781-a727-6140d940db42"
        test_conversation_id = "a0197cfc-4766-4b39-8e19-ebb00ced86e4"
        # --- /IMPORTANT ---

        if "your_test_" in test_bot_id or "your_test_" in test_conversation_id:
            print("="*80)
            print("WARNING: Please replace the placeholder test_bot_id and test_conversation_id")
            print("         in the main_test() function of lead_scoring_agent.py before running.")
            print("="*80)
            return

        print(f"--- Testing Lead Scoring Agent for Bot ID: {test_bot_id} ---")
        result = await score_lead_from_conversation(
            bot_id=test_bot_id, conversation_id=test_conversation_id
        )

        if result:
            print("\\n--- Lead Scoring Result ---")
            print(json.dumps(result, indent=2))
            print("---------------------------")
        else:
            print("\\n--- Lead Scoring Failed ---")
            print("The agent did not return a valid score. Check the logs above for errors.")
            print("---------------------------")

    # Run the async test function
    asyncio.run(main_test())