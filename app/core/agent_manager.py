# agent_manager.py

import os
import re
from typing import List, Optional
from langchain.agents import AgentExecutor, create_react_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import AIMessage, HumanMessage
from langchain.memory import ConversationBufferMemory
from langchain_core.memory import BaseMemory
import logging

from app.core.config import llm
from app.core.tools import get_retriever_tool, get_knowledge_update_tool, get_answering_tool
from app.core import db_manager # Import db_manager

logger = logging.getLogger(__name__)

# Define the core ReAct prompt template
# Updated for Persona, Tone, Proactivity, and Markdown
# REMOVED HARDCODED PROMPT - Now fetched from DB
# REACT_PROMPT_TEMPLATE = """..."""

def create_agent_executor(kb_id: str, memory: Optional[BaseMemory] = None) -> AgentExecutor:
    """
    Creates an AgentExecutor for a specific knowledge base, optionally with memory.

    Args:
        kb_id: The unique identifier for the knowledge base.
        memory: Optional LangChain memory object.

    Returns:
        An initialized AgentExecutor instance.
    """
    if not llm:
        raise ValueError("LLM not initialized. Check .env configuration.")

    # --- Fetch Agent Configuration --- 
    print(f"Fetching agent config for kb_id: {kb_id}")
    agent_config = db_manager.get_agent_config(kb_id)
    system_prompt_template = agent_config['system_prompt']
    max_iterations_config = agent_config['max_iterations']
    # Fetch other config values as needed
    # --- End Fetch --- 

    # 1. Get tools specific to this kb_id
    retriever_tool = get_retriever_tool(kb_id)
    # update_tool = get_knowledge_update_tool(kb_id) # We might not give the agent direct update ability initially
    # answering_tool = get_answering_tool(llm) # The ReAct agent directly uses the LLM for answering

    # Combine tools the agent can use
    # tools_list = [retriever_tool, update_tool, answering_tool]
    tools_list = [retriever_tool] # Start simple: only retrieval allowed

    # 2. Create the prompt using the fetched template
    # Ensure the prompt includes the memory placeholder
    prompt = ChatPromptTemplate.from_template(system_prompt_template) # Use fetched template

    # Ensure memory is initialized if not provided (remains necessary for prompt population)
    if memory is None:
        memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)

    # 3. Create the ReAct Agent
    agent = create_react_agent(
        llm=llm,
        tools=tools_list,
        prompt=prompt
    )

    # 4. Create the Agent Executor
    # Set handle_parsing_errors=True to make it more robust
    agent_executor = AgentExecutor(
        agent=agent,
        tools=tools_list,
        # memory=memory, # Still not directly used here with from_template
        verbose=True,  # Set to True for debugging agent steps
        handle_parsing_errors=True, # Helps with occasional LLM format mistakes
        max_iterations=max_iterations_config, # Use fetched config
        return_intermediate_steps=True # Keep this
    )

    print(f"Created AgentExecutor for kb_id: {kb_id} using dynamic config")
    return agent_executor

# Example Usage (Optional - for basic testing if needed)
if __name__ == '__main__':
    # This requires a KB to exist. Run the test_core_components.py first
    # or ensure a KB like 'test_kb_...' exists in your ./chromadb_data
    print("Attempting to create agent executor for a test KB ID...")
    # Find a recent test KB ID in the ChromaDB directory or use a known one
    try:
        # Simple way to find one - replace with a known good ID if needed
        db_path = os.path.join(".", "chromadb_data")
        potential_kbs = [d for d in os.listdir(db_path) if os.path.isdir(os.path.join(db_path, d)) and d.startswith("test_kb_")]
        if not potential_kbs:
            raise FileNotFoundError("No 'test_kb_*' directories found in ./chromadb_data. Run test script first.")
        
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