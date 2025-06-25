# agent_manager.py
import os
import re
from typing import List, Optional, Dict, Any, Union
from langchain.agents import AgentExecutor, create_react_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import AIMessage, HumanMessage
from langchain.memory import ConversationBufferMemory
from langchain_core.memory import BaseMemory
from langchain.callbacks.base import BaseCallbackHandler
import logging
from langchain.agents.output_parsers import ReActSingleInputOutputParser

from app.core.config import llm
from app.core.tools import (
    get_retriever_tool,
    # get_knowledge_update_tool, # This seems unused, can be removed if not needed
    # get_answering_tool, # This seems unused, can be removed if not needed
    get_web_search_tool,
    get_response_quality_checker_tool,
)
from app.core import supabase_metadata_manager as db_manager  # Import db_manager

logger = logging.getLogger(__name__)

# Define the core ReAct prompt template
# Updated for Persona, Tone, Proactivity, and Markdown
# REMOVED HARDCODED PROMPT - Now fetched from DB
# REACT_PROMPT_TEMPLATE = """..."""


# Custom output parser to handle formatting issues
class ForgivingReActOutputParser(ReActSingleInputOutputParser):
    """A more forgiving output parser for ReAct agents that fixes common formatting issues."""

    def parse(self, text: str) -> dict:
        """Parse the output text and fix formatting issues before standard parsing."""
        try:
            # First try standard parsing
            return super().parse(text)
        except Exception as original_error:
            # If it fails, try to fix the text before trying again
            try:
                fixed_text = self._fix_common_formatting(text)
                return super().parse(fixed_text)
            except Exception as err:
                # Special handling for "(needs help)" marker in the text
                if "(needs help)" in text:
                    # Create properly formatted Final Answer with the help marker
                    proper_format = self._format_help_needed_response(text)
                    try:
                        return super().parse(proper_format)
                    except:
                        # Last attempt emergency handling - explicitly create the return structure
                        # This is essentially what the parser would produce, but we construct it manually
                        return {"action": "Final Answer", "action_input": text.strip()}

                # If still fails, raise the original error
                raise original_error

    def _fix_common_formatting(self, text: str) -> str:
        """Fix common formatting issues in the LLM output."""
        # Special case: If this appears to be a direct answer with no format at all
        if not any(
            marker in text for marker in ["Thought:", "Action:", "Final Answer:"]
        ):
            # This is a completely unformatted response, format it as a Final Answer
            return f"Thought:\nI have the information to answer directly.\n\nFinal Answer:\n{text.strip()}"

        # Case 1: Missing newline after "Thought:"
        if "Thought:" in text and not re.search(r"Thought:\s*\n", text):
            text = re.sub(
                r"Thought:(.*?)(?=Action:|Final Answer:|$)",
                lambda m: f"Thought:\n{m.group(1).strip()}\n\n",
                text,
                flags=re.DOTALL,
            )

        # Case 2: Content immediately after "Thought:" without Action/Final Answer
        if "Thought:" in text and not any(
            marker in text for marker in ["Action:", "Final Answer:"]
        ):
            # Extract the content after Thought:
            match = re.search(r"Thought:(.*?)(?=\n\n|$)", text, re.DOTALL)
            if match:
                thought_content = match.group(1).strip()
                # If content looks like an answer, make it a Final Answer
                text = f"Thought:\nI have the information to answer directly.\n\nFinal Answer:\n{thought_content}"

        # Case 3: When LLM responds with direct answer format with uncertainty marker
        if "(needs help)" in text and "Final Answer:" not in text:
            text = self._format_help_needed_response(text)

        return text

    def _format_help_needed_response(self, text: str) -> str:
        """Format responses that contain the (needs help) marker into proper ReAct format."""
        # Extract just the content, without the formatting errors
        # If there's a "Thought:" but no proper format, extract content after it
        if "Thought:" in text:
            match = re.search(r"Thought:(.*?)(?=\n\n|$)", text, re.DOTALL)
            content = match.group(1).strip() if match else text.strip()
        else:
            content = text.strip()

        # Ensure (needs help) is at the end if it's not already
        if "(needs help)" not in content[-12:]:
            if "(needs help)" in content:
                # Remove it from wherever it is
                content = content.replace("(needs help)", "").strip()
                # Add it to the end
                content += " (needs help)"

        # Create a properly formatted response
        return f"""Thought:
I need to escalate this question as I don't have complete information.

Final Answer:
{content}"""


# Create a callback handler to intercept agent timeouts
class TimeoutCallbackHandler(BaseCallbackHandler):
    """Custom callback handler to intercept agent timeouts and provide better responses."""

    def __init__(self):
        self.agent_observation = None
        self.user_query = None

    def on_tool_end(self, output: str, **kwargs: Any) -> None:
        """Save the most recent observation from a tool call."""
        self.agent_observation = output

    def on_chain_start(
        self, serialized: Dict[str, Any], inputs: Dict[str, Any], **kwargs: Any
    ) -> None:
        """Capture the user's original query."""
        if "input" in inputs:
            self.user_query = inputs.get("input")

    def on_agent_action(self, action, **kwargs: Any) -> Any:
        """Capture any agent action for later use."""
        # We could save more state here if needed
        pass

    def on_agent_finish(self, finish, **kwargs: Any) -> None:
        """Capture the agent's final output."""
        # We could handle specific finish conditions here
        pass

    def get_help_response(self) -> str:
        """Generate a proper help response when the agent times out."""
        # If we have observation data but the agent timed out, try to use
        # the observation to generate a response
        if self.agent_observation:
            # Check if the observation contains a CTO reference or other relevant info
            if (
                "CTO" in self.agent_observation
                or "Asif Hassam" in self.agent_observation
            ):
                return "I can confirm that Asif Hassam is the CTO of Zaio. However, I don't have complete information about your specific question. Let me check with the team and get back to you. (needs help)"

            # General uncertainty response
            return f"I'm sorry, but I couldn't find specific information to answer your question accurately. Let me check with our team and get back to you with more details. (needs help)"

        # Fallback when we have no observation
        return "I'm sorry, but I had difficulty processing your request. Let me get someone from our team to assist you. (needs help)"


# Create a wrapper class for the AgentExecutor to handle timeouts
class EnhancedAgentExecutor:
    """Wrapper around AgentExecutor to handle timeouts and parsing errors."""

    def __init__(self, agent_executor, timeout_handler):
        self.agent_executor = agent_executor
        self.timeout_handler = timeout_handler

    def invoke(self, inputs):
        """Wrapper around invoke that handles timeouts and formatting errors."""
        try:
            result = self.agent_executor.invoke(inputs)

            # Check if we got a timeout or iteration limit error
            if "Agent stopped due to iteration limit or time limit" in str(
                result.get("output", "")
            ):
                # Replace with a more helpful response using our timeout handler
                help_response = self.timeout_handler.get_help_response()
                result["output"] = help_response

            return result
        except Exception as e:
            # Handle unexpected errors
            logger.error(f"Agent execution error: {e}")
            return {
                "output": "I encountered an unexpected issue. Let me connect you with our support team. (needs help)"
            }

    def __getattr__(self, name):
        """Delegate all other attribute access to the wrapped agent_executor."""
        return getattr(self.agent_executor, name)


def get_bot_business_context(kb_id: str) -> Dict[str, Any]:
    """
    Retrieve business context for a bot from the database.
    
    Args:
        kb_id: Knowledge base ID
        
    Returns:
        Dictionary containing business context
    """
    # Hardcoded Zaio business context since Supabase doesn't contain this data
    zaio_business_context = {
        'company_name': 'Zaio',
        'industry': 'Edtech',
        'products': ['Full Stack Bootcamp', 'Data Science Bootcamp', 'Cyber Security Bootcamp'],
        'services': ['Full Stack Development Training', 'Data Science Training', 'Cyber Security Training'],
        'bot_name': 'Zaio Assistant',
        'business_keywords': [
            'zaio', 'edtech', 'full stack', 'data science', 'cyber security', 'bootcamp', 'training', 
            'coding', 'programming', 'education', 'tech education', 'developer', 'programmer', 
            'salary', 'earnings', 'income', 'pay', 'compensation', 'job market', 'career', 'employment'
        ]
    }
    
    return zaio_business_context

def create_agent_executor(
    kb_id: str, memory: Optional[BaseMemory] = None, bot_id: str = None, customer_context: Optional[Dict[str, Any]] = None
) -> Union[AgentExecutor, EnhancedAgentExecutor]:
    """
    Creates an AgentExecutor for a specific knowledge base, optionally with memory.

    Args:
        kb_id: The unique identifier for the knowledge base.
        bot_id: The unique identifier for the bot.
        memory: Optional LangChain memory object.
        customer_context: Optional dictionary containing customer information (name, email, phone)

    Returns:
        An initialized AgentExecutor or EnhancedAgentExecutor instance.
    """
    if not llm:
        raise ValueError("LLM not initialized. Check .env configuration.")

    # --- Fetch Agent Configuration from DB ---
    print(f"Fetching agent config for kb_id: {kb_id}")
    
    # First, try to get custom prompt from bots table if bot_id is provided
    custom_prompt_from_bot = None
    if bot_id:
        bot_info = db_manager.get_bot_by_bot_id(bot_id)
        if bot_info:
            custom_prompt_from_bot = bot_info.get("custom_prompt")
            if custom_prompt_from_bot and custom_prompt_from_bot.strip():
                print(f"Found custom prompt for bot {bot_id}")
            else:
                print(f"No custom prompt found for bot {bot_id}, using agent config")
    
    # Get the agent config (for max_iterations and fallback prompt)
    agent_config = db_manager.get_agent_config(kb_id)
    
    # Use custom prompt from bot if available, otherwise use agent config prompt
    if custom_prompt_from_bot and custom_prompt_from_bot.strip():
        # For custom prompts, append the tools and ReAct formatting from the default prompt
        from app.core.prompts import DEFAULT_SYSTEM_PROMPT
        
        # Extract the tools and ReAct formatting section from the default prompt
        default_prompt = DEFAULT_SYSTEM_PROMPT
        tools_section_start = default_prompt.find("## 🛠 TOOLS:")
        
        if tools_section_start != -1:
            tools_and_react_section = default_prompt[tools_section_start:]
            # Combine custom prompt with tools/ReAct formatting
            system_prompt_template = f"{custom_prompt_from_bot.strip()}\n\n---\n\n{tools_and_react_section}"
            print(f"Using custom prompt from bot table with appended tools/ReAct formatting for bot_id: {bot_id}")
        else:
            # Fallback if tools section not found
            system_prompt_template = custom_prompt_from_bot
            print(f"Warning: Could not find tools section in default prompt, using custom prompt as-is for bot_id: {bot_id}")
    else:
        system_prompt_template = agent_config["system_prompt"]
        print(f"Using default prompt from agent config for kb_id: {kb_id}")
    
    max_iterations_config = agent_config["max_iterations"]
    
    # --- Format customer context into the prompt ---
    if customer_context:
        customer_name = customer_context.get("customer_name") or "None"
        customer_email = customer_context.get("customer_email") or "None"
        customer_phone = customer_context.get("customer_phone") or "None"
        bot_name = customer_context.get("bot_name") or "Assistant"
        company_name = customer_context.get("company_name") or "our company"
        
        # Ensure all values are strings to avoid TypeError in replace()
        customer_name = str(customer_name) if customer_name is not None else "None"
        customer_email = str(customer_email) if customer_email is not None else "None"
        customer_phone = str(customer_phone) if customer_phone is not None else "None"
        bot_name = str(bot_name) if bot_name is not None else "Assistant"
        company_name = str(company_name) if company_name is not None else "our company"
        
        # Replace only the customer context placeholders, keep ReAct template placeholders intact
        system_prompt_template = system_prompt_template.replace("{customer_name}", customer_name)
        system_prompt_template = system_prompt_template.replace("{customer_email}", customer_email)
        system_prompt_template = system_prompt_template.replace("{customer_phone}", customer_phone)
        system_prompt_template = system_prompt_template.replace("{bot_name}", bot_name)
        system_prompt_template = system_prompt_template.replace("{company_name}", company_name)
        
        print(f"Customer context provided - Name: {customer_name}, Email: {customer_email}, Bot: {bot_name}, Company: {company_name}")
    else:
        # If no customer context, replace with default values
        system_prompt_template = system_prompt_template.replace("{customer_name}", "None")
        system_prompt_template = system_prompt_template.replace("{customer_email}", "None")
        system_prompt_template = system_prompt_template.replace("{customer_phone}", "None")
        system_prompt_template = system_prompt_template.replace("{bot_name}", "Assistant")
        system_prompt_template = system_prompt_template.replace("{company_name}", "our company")
    # --- End Format ---

    # --- Get Tools ---
    
    # 1. Get the retriever tool (always included)
    retriever_tool = get_retriever_tool(kb_id)
    tools_list = [retriever_tool]
    
    # 2. Get Bot Info and dynamically build Web Search Tool
    bot_info = db_manager.get_bot_by_bot_id(bot_id)
    
    if bot_info:
        # Fetch the client's saved web search configuration from the database
        web_search_config_data = db_manager.get_web_search_config(bot_info['id'])

        # 3. Dynamically create and add the web search tool if it's enabled
        web_search_tool = get_web_search_tool(config_data=web_search_config_data)
        
        if web_search_tool:
            tools_list.append(web_search_tool)
            print(f"Web search tool enabled and added for bot_id: {bot_info['id']}")
        else:
            print(f"Web search tool is disabled for bot_id: {bot_info['id']}")
    else:
        print(f"Warning: Could not find bot info for kb_id: {kb_id}. Web search tool will be disabled.")
    
    # 4. Add the response quality checker tool (always included)
    quality_checker_tool = get_response_quality_checker_tool()
    if quality_checker_tool:
        tools_list.append(quality_checker_tool)
        print(f"Response quality checker tool enabled and added for kb_id: {kb_id}")
    else:
        print(f"Warning: Response quality checker tool could not be created - Gemini may not be available")

    # Get tool names
    tool_names = [tool.name for tool in tools_list]

    print(f"Tool names: {tool_names}")

    # 2. Create the ReAct-compatible prompt template
    # Ensure the prompt includes all required ReAct variables
    react_template = f"""{system_prompt_template}

Here is the conversation so far (you have already said these messages, so DO NOT repeat yourself):
{{chat_history}}

You have access to the following tools:

{{tools}}

Use the following format:

Question: the input question you must answer
Thought: you should always think about what to do
Action: the action to take, should be one of [{{tool_names}}]
Action Input: the input to the action
Observation: the result of the action
... (this Thought/Action/Action Input/Observation can repeat N times)
Thought: I now know the final answer
Final Answer: the final answer to the original input question

Begin!

Question: {{input}}
Thought:{{agent_scratchpad}}"""

    prompt = ChatPromptTemplate.from_template(react_template)

    # Ensure memory is initialized if not provided (remains necessary for prompt population)
    if memory is None:
        memory = ConversationBufferMemory(
            memory_key="chat_history", return_messages=True
        )

    # Use the more forgiving output parser
    custom_parser = ForgivingReActOutputParser()

    # Create our timeout handler
    timeout_handler = TimeoutCallbackHandler()

    # 3. Create the ReAct Agent
    agent = create_react_agent(
        llm=llm,
        tools=tools_list,
        prompt=prompt,
        output_parser=custom_parser,  # Use our custom parser
    )

    # 4. Create the Agent Executor
    # Set handle_parsing_errors=True to make it more robust
    agent_executor = AgentExecutor(
        agent=agent,
        tools=tools_list,
        # memory=memory, # Still not directly used here with from_template
        verbose=True,  # Set to True for debugging agent steps
        handle_parsing_errors=True,  # Helps with occasional LLM format mistakes
        max_iterations=max_iterations_config,  # Use fetched config
        return_intermediate_steps=True,  # Keep this
        max_parsing_retries=1,  # Only retry parsing once before using our custom parser
        callbacks=[timeout_handler],  # Add our custom timeout handler
    )

    # Instead of modifying the AgentExecutor directly, wrap it in our enhanced executor
    enhanced_executor = EnhancedAgentExecutor(agent_executor, timeout_handler)

    print(f"Created EnhancedAgentExecutor for kb_id: {kb_id} using dynamic config")
    return enhanced_executor


# Example Usage (Optional - for basic testing if needed)
if __name__ == "__main__":
    # This requires a KB to exist in Supabase
    print("Attempting to create agent executor for a test KB ID...")
    try:
        # Use a specific KB ID for testing (replace with actual KB ID)
        test_kb_id = "test_kb_example"
        print(f"Using test KB ID: {test_kb_id}")

        executor = create_agent_executor(test_kb_id)
        print(f"Agent Executor created: {executor}")

        # Example invocation (requires user input)
        # response = executor.invoke({"input": "What is blue?", "chat_history": []}) # Add chat_history
        # print("\n--- Agent Response ---")
        # print(response)

    except Exception as e:
        print(f"Error during example usage: {e}")

