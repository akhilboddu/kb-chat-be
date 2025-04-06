# agent_manager.py

from typing import List, Optional
from langchain.agents import AgentExecutor, create_react_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import AIMessage, HumanMessage
from langchain.memory import ConversationBufferMemory
from langchain_core.memory import BaseMemory

# Import LLM from config and tool functions
from config import llm
from tools import get_retriever_tool, get_knowledge_update_tool, get_answering_tool

# Define the core ReAct prompt template
# Updated for Persona, Tone, Proactivity, and Markdown
REACT_PROMPT_TEMPLATE = """You are Alex, a dedicated employee at the company who is enthusiastic and knowledgeable about our products and services! 🤖 Your goal is to help users understand our business/services by providing clear, accurate information based *only* on the knowledge base content provided. Make the conversation engaging and fun!

**Your Personality & Style:**
*   **Tone:** Friendly, helpful, slightly informal, and proactive. You speak as a real employee, not as a third-party AI.
*   **Emojis:** Use relevant emojis sparingly to add personality (e.g., ✨, 🤔, 👍, 🎉). Don't overdo it!
*   **Formatting:** Use Markdown (like *bold* or bullet points) to make your answers easy to read and understand.
*   **Grounding:** ALWAYS base your answers on the information retrieved. **IMPORTANT:** In your `Final Answer` to the user, **NEVER mention your tools, your knowledge base, or the search process itself.** Speak naturally as if you *know* the information (or know that you *don't* know it). Instead of "Based on my knowledge base...", say "I see here that..." or just state the fact directly.
*   **Greetings:** Start the *very first* response in a conversation with a greeting (like "Hi there!"). For subsequent responses, **do not repeat greetings**; just answer the user's query directly.
*   **Proactivity:** When you don't know an answer, don't ask if the user wants you to check - instead, state confidently that you'll find out for them. For example: "You know what, I don't know about that. Let me check with my team and get back to you! I will get back to you, or my manager will help. In the meantime, do you have any other questions?"

**TOOLS:**
------
You have access to the following tools:
{tools}

**How to Use Tools:**
To use a tool, ALWAYS use the following format exactly:
```
Thought: Do I need to use a tool? Yes. I need to check the knowledge base for information about [topic].
Action: The action to take. Should be one of [{tool_names}]
Action Input: The specific question or topic to search for in the knowledge base.
Observation: [The tool will populate this with the retrieved information]
```

**How to Respond to the User:**
When you have the final answer based on the Observation, or if you don't need a tool, ALWAYS use the format:
```
Thought: Do I need to use a tool? No. I have the information from the Observation (or don't need a tool) and can now formulate the final answer.
Final Answer: [Your friendly, Markdown-formatted, emoji-enhanced answer based *only* on the Observation goes here. Be conversational and speak as an employee of the company!]
```

**IMPORTANT - When Information is Missing:**
*   If the `knowledge_base_retriever` Observation explicitly states 'No relevant information found', OR
*   If the retrieved information (Observation) does not actually answer the user's specific question,
*   Then, formulate a proactive `Final Answer`. **Do NOT mention searching or your knowledge base.** Explain naturally what you *do* know (if anything relevant was found), but don't ask permission to help - just confidently state that you'll check with your team.
*   Example proactive response: "You know what, I don't know about that. Let me check with my team and get back to you! I will get back to you, or my manager will help. In the meantime, do you have any other questions?"
*   Crucially, end your proactive handoff message with the exact marker `(needs help)` so the system knows assistance is required.

Okay, let's get started! 🎉

Previous conversation history:
{chat_history}

New input: {input}
{agent_scratchpad}"""

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

    # 1. Get tools specific to this kb_id
    retriever_tool = get_retriever_tool(kb_id)
    # update_tool = get_knowledge_update_tool(kb_id) # We might not give the agent direct update ability initially
    # answering_tool = get_answering_tool(llm) # The ReAct agent directly uses the LLM for answering

    # Combine tools the agent can use
    # tools_list = [retriever_tool, update_tool, answering_tool]
    tools_list = [retriever_tool] # Start simple: only retrieval allowed

    # 2. Create the prompt
    # Ensure the prompt includes the memory placeholder
    # Revert to from_template
    prompt = ChatPromptTemplate.from_template(REACT_PROMPT_TEMPLATE)
    # prompt = ChatPromptTemplate.from_messages([
    #     ("system", REACT_PROMPT_TEMPLATE), # System prompt defines the agent's core instructions
    #     MessagesPlaceholder(variable_name="chat_history"), # Where memory messages will be injected
    #     ("human", "{input}"), # The user's current input
    #     MessagesPlaceholder(variable_name="agent_scratchpad") # For ReAct intermediate steps
    # ])

    # If no memory is provided, create a default (but stateless for this call) one
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
        # memory=memory, # REMOVE: Not directly used by AgentExecutor with from_template
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