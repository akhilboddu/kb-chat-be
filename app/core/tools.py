from typing import Dict, Any, List, Callable, Optional
from langchain.tools import Tool
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from app.core.supabase_kb_manager import kb_manager
from app.core.web_search_config import (
    WebSearchConfig, 
    get_default_web_search_config, 
    validate_web_search_config
)
import os
import json
import requests
from openai import OpenAI

def get_retriever_tool(kb_id: str) -> Tool:
    """
    Creates a tool for retrieving relevant information from the knowledge base.
    Returns only the formatted document text.
    
    Args:
        kb_id: ID of the knowledge base to retrieve from
        
    Returns:
        LangChain Tool for retrieval
    """
    def retrieve_from_kb(query: str) -> str:
        """Get relevant information from the knowledge base."""
        results = kb_manager.get_similar_docs(kb_id, query, n_results=10) # Get top 2 results
        
        if not results:
            return "No relevant information found in the knowledge base."
        
        # Format the results
        formatted_docs = "\n\n".join([f"DOCUMENT: {res['document']}" for res in results])
        
        return formatted_docs
    
    retriever_tool = Tool(
        name="knowledge_base_retriever",
        description="Use this tool to search the knowledge base. Format: Action: knowledge_base_retriever",
        func=retrieve_from_kb
    )
    return retriever_tool

def get_answering_tool(llm) -> Tool:
    """
    Creates a tool for generating answers based on context.
    
    Args:
        llm: LLM to use for answer generation
        
    Returns:
        LangChain Tool for answering
    """
    # Create a chain to format and answer questions
    answer_prompt = PromptTemplate.from_template(
        """You are a helpful AI sales agent.
        
        Use the following context to answer the user's question.
        If you don't know the answer based on the context, admit that you don't know.
        
        Context: {context}
        
        User Question: {question}
        
        Answer:"""
    )
    
    answer_chain = (
        {"context": RunnablePassthrough(), "question": RunnablePassthrough()}
        | answer_prompt
        | llm
        | StrOutputParser()
    )
    
    def generate_answer(context_and_question: Dict[str, str]) -> str:
        """Generate an answer based on context and question."""
        context = context_and_question.get("context", "")
        question = context_and_question.get("question", "")
        
        if not context or not question:
            return "Missing context or question. Please provide both."
        
        # Run the answering chain
        return answer_chain.invoke({"context": context, "question": question})
    
    return Tool(
        name="answer_generator",
        description="Useful for generating an answer based on retrieved context and a user question.",
        func=generate_answer
    )

def get_knowledge_update_tool(kb_id: str) -> Tool:
    """
    Creates a tool for updating the knowledge base.
    
    Args:
        kb_id: ID of the knowledge base to update
        
    Returns:
        LangChain Tool for updating the KB
    """
    def update_kb(text_to_add: str) -> str:
        """Update the knowledge base with new information."""
        success = kb_manager.add_to_kb(kb_id, text_to_add, knowledge_source="agent")
        if success:
            return f"Successfully updated knowledge base {kb_id}."
        else:
            return "Failed to update knowledge base. Please ensure the text is not empty."
    
    return Tool(
        name="update_knowledge_base",
        description="Useful for adding new information to the knowledge base.",
        func=update_kb
    )

def get_web_search_tool(config_data: Optional[Dict[str, Any]]) -> Optional[Tool]:
    """
    Creates a tool for searching the web using a dynamic, client-specific configuration.
    Returns None if the tool is not enabled in the configuration.
    
    Args:
        config_data: Dictionary with the client's saved web search settings.
        
    Returns:
        A LangChain Tool for web search, or None if disabled.
    """
    # If no config is provided or the tool is explicitly disabled, do not create the tool.
    if not config_data or not config_data.get('is_enabled'):
        return None

    # Create a dynamic WebSearchConfig object from the database data.
    dynamic_config = WebSearchConfig(
        max_results=3 # Hardcoded as per user request
    )
    
    def search_web(query: str) -> str:
        """Search the web for current information using OpenAI's web search API."""
        
        try:
            client = OpenAI(api_key=dynamic_config.openai_api_key)
            
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}"
            }
            
            data = {
                "model": "gpt-4.1",
                "tools": [{"type": "web_search_preview"}],
                "input": f"Search the web for: {query}\n\nPlease provide current, relevant information that would help answer this query. Focus on recent information and credible sources."
            }
            
            response = requests.post("https://api.openai.com/v1/responses", headers=headers, json=data)
            
            if response.status_code == 200:
                response_data = response.json()
                if 'output' in response_data:
                    for item in response_data['output']:
                        if item.get('type') == 'message' and 'content' in item:
                            content = item['content']
                            if isinstance(content, list):
                                text_parts = []
                                for part in content:
                                    if part.get('type') == 'output_text':
                                        text_parts.append(part.get('text', ''))
                                web_search_result = '\n'.join(text_parts)
                            else:
                                web_search_result = content
                            if web_search_result.strip():
                                return f"Current information for '{query}':\n\n{web_search_result}"
                return f"Unable to find current information for '{query}'. Let me try the knowledge base."
            else:
                print(f"Web search API error: {response.status_code} - {response.text}")
                return "Unable to search the web at this time. Let me try the knowledge base instead."
                
        except Exception as e:
            print(f"Web search error: {e}")
            return "Unable to search the web at this time. Let me try the knowledge base instead."

    # Dynamically create the tool description from the client's saved usage_guide
    usage_guide = config_data.get('usage_guide', '')
    

    # Append the required formatting instructions for the agent
    tool_description = f"""{usage_guide}

Format: Action: web_search
Action Input: [search query]"""
    
    web_search_tool = Tool(
        name="web_search",
        description=tool_description,
        func=search_web
    )
    
    return web_search_tool