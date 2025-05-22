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
    get_knowledge_update_tool,
    get_answering_tool,
)
from app.core import db_manager  # Import db_manager

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


def create_agent_executor(
    kb_id: str, memory: Optional[BaseMemory] = None
) -> Union[AgentExecutor, EnhancedAgentExecutor]:
    """
    Creates an AgentExecutor for a specific knowledge base, optionally with memory.

    Args:
        kb_id: The unique identifier for the knowledge base.
        memory: Optional LangChain memory object.

    Returns:
        An initialized AgentExecutor or EnhancedAgentExecutor instance.
    """
    if not llm:
        raise ValueError("LLM not initialized. Check .env configuration.")

    # --- Fetch Agent Configuration ---
    print(f"Fetching agent config for kb_id: {kb_id}")
    agent_config = db_manager.get_agent_config(kb_id)
    system_prompt_template = agent_config["system_prompt"]
    max_iterations_config = agent_config["max_iterations"]
    # Fetch other config values as needed
    # --- End Fetch ---

    # 1. Get tools specific to this kb_id
    retriever_tool = get_retriever_tool(kb_id)
    # update_tool = get_knowledge_update_tool(kb_id) # We might not give the agent direct update ability initially
    # answering_tool = get_answering_tool(llm) # The ReAct agent directly uses the LLM for answering

    # Combine tools the agent can use
    # tools_list = [retriever_tool, update_tool, answering_tool]
    tools_list = [retriever_tool]  # Start simple: only retrieval allowed

    # Get tool names
    tool_names = [tool.name for tool in tools_list]

    # 2. Create the prompt using the fetched template
    # Ensure the prompt includes the memory placeholder
    prompt = ChatPromptTemplate.from_template(
        system_prompt_template
    )  # Use fetched template

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
    # This requires a KB to exist. Run the test_core_components.py first
    # or ensure a KB like 'test_kb_...' exists in your ./chromadb_data
    print("Attempting to create agent executor for a test KB ID...")
    # Find a recent test KB ID in the ChromaDB directory or use a known one
    try:
        # Simple way to find one - replace with a known good ID if needed
        db_path = os.path.join(".", "chromadb_data")
        potential_kbs = [
            d
            for d in os.listdir(db_path)
            if os.path.isdir(os.path.join(db_path, d)) and d.startswith("test_kb_")
        ]
        if not potential_kbs:
            raise FileNotFoundError(
                "No 'test_kb_*' directories found in ./chromadb_data. Run test script first."
            )

        # Use the most recent one based on timestamp in the name
        test_kb_id = sorted(potential_kbs, reverse=True)[0]
        print(f"Using existing test KB ID: {test_kb_id}")

        executor = create_agent_executor(test_kb_id)
        print(f"Agent Executor created: {executor}")

        # Example invocation (requires user input)
        # response = executor.invoke({"input": "What is blue?", "chat_history": []}) # Add chat_history
        # print("\n--- Agent Response ---")
        # print(response)

    except Exception as e:
        print(f"Error during example usage: {e}")

