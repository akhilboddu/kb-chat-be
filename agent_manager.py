# agent_manager.py

from typing import List
from langchain.agents import AgentExecutor, create_react_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import AIMessage, HumanMessage

# Import LLM from config and tool functions
from config import llm
from tools import get_retriever_tool, get_knowledge_update_tool, get_answering_tool

# Define the core ReAct prompt template
# Inspired by ReAct paper and LangChain examples
# Includes placeholder for chat history
REACT_PROMPT_TEMPLATE = """Assistant is a large language model trained by Google.

Assistant is designed to be able to assist with a wide range of tasks, from answering simple questions to providing in-depth explanations and discussions on a wide range of topics. As a language model, Assistant is able to communicate and generate human-like text in response to a wide range of prompts and questions.

TOOLS:
------
Assistant has access to the following tools:

{tools}

To use a tool, please use the following format:

```
Thought: Do I need to use a tool? Yes
Action: The action to take. Should be one of [{tool_names}]
Action Input: The input to the action
Observation: The result of the action
```

When you have a response to say to the Human, or if you do not need to use a tool, you MUST use the format:

```
Thought: Do I need to use a tool? No
Final Answer: [your response here]
```

If you retrieve information using the knowledge_base but determine it doesn't directly answer the user's question, or if the knowledge base returns 'No relevant information found', you MUST indicate that you need assistance by responding ONLY with the exact string "HANDOFF_REQUIRED" in the 'Final Answer' field. Do not add any other text or explanation when handing off.

Begin!

Previous conversation history:
{chat_history}

New input: {input}
{agent_scratchpad}"""

def create_agent_executor(kb_id: str) -> AgentExecutor:
    """
    Creates an AgentExecutor for a specific knowledge base.

    Args:
        kb_id: The unique identifier for the knowledge base.

    Returns:
        An initialized AgentExecutor instance.
    """
    if not llm:
        raise ValueError("LLM not initialized. Check .env configuration.")

    # 1. Get tools specific to this kb_id
    retriever_tool = get_retriever_tool(kb_id)
    # update_tool = get_knowledge_update_tool(kb_id) # We might not give the agent direct update ability initially
    # answering_tool = get_answering_tool(llm) # The ReAct agent directly uses the LLM for answering

    # Combine tools the agent can use
    # tools_list = [retriever_tool, update_tool, answering_tool]
    tools_list = [retriever_tool] # Start simple: only retrieval allowed

    # 2. Create the prompt
    prompt = ChatPromptTemplate.from_template(REACT_PROMPT_TEMPLATE)

    # Add memory/history placeholder
    # prompt = prompt.extend([MessagesPlaceholder(variable_name="chat_history")]) # Add this later if needed

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
        verbose=True,  # Set to True for debugging agent steps
        handle_parsing_errors=True, # Helps with occasional LLM format mistakes
        max_iterations=5, # Add a safety limit
        return_intermediate_steps=True # <<< Add this line
    )

    print(f"Created AgentExecutor for kb_id: {kb_id}")
    return agent_executor

# Example Usage (Optional - for basic testing if needed)
if __name__ == '__main__':
    # This requires a KB to exist. Run the test_core_components.py first
    # or ensure a KB like 'test_kb_...' exists in your ./chromadb_data
    print("Attempting to create agent executor for a test KB ID...")
    # Find a recent test KB ID in the ChromaDB directory or use a known one
    try:
        # Simple way to find one - replace with a known good ID if needed
        import os
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