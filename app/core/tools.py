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
import re

# Import Gemini for the response quality checker
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

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
                "model": "gpt-4o-mini",
                "tools": [{"type": "web_search_preview","search_context_size": "low"}],
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

def get_response_quality_checker_tool() -> Optional[Tool]:
    """
    Creates a tool for checking if AI responses properly address user questions
    and match conversation flow using Gemini as the evaluator.
    
    Returns:
        LangChain Tool for response quality checking, or None if Gemini unavailable
    """
    if not GEMINI_AVAILABLE:
        print("Warning: Gemini not available for response quality checking")
        return None
    
    # Initialize Gemini
    api_key = os.getenv("GOOGLE_API_KEY")
    print(f"API Key: {api_key}")
    if not api_key:
        print("Warning: GOOGLE_API_KEY not set - response quality checker disabled")
        return None
    
    genai.configure(api_key=api_key)
    # Use the same model variant as the main LLM to avoid per-model quota splits
    model = genai.GenerativeModel("gemini-2.0-flash")
    
    def check_response_quality(evaluation_data: str) -> str:
        """
        Evaluate if an AI response properly addresses the user's question.
        
        Expected input format (JSON string):
        {
            "user_question": "What is your pricing?",
            "ai_response": "Our weather is nice today...",
            "chat_history": "chat history"
        }
        """
        try:
            # Remove Markdown code block fences if present
            cleaned_input = evaluation_data.strip()
            if cleaned_input.startswith("```"):
                # Strip the opening ``` or ```json and the closing ```
                cleaned_input = re.sub(r"^```[a-zA-Z]*\n", "", cleaned_input)
                cleaned_input = re.sub(r"\n```$", "", cleaned_input)

            # Parse the input data
            data = json.loads(cleaned_input)
            user_question = data.get("user_question", "")
            ai_response = data.get("ai_response", "")
            chat_history = data.get("chat_history", "")
            
            if not user_question or not ai_response:
                return json.dumps({
                    "quality_score": 0,
                    "issues": ["Missing user question or AI response"],
                    "recommendation": "Please provide both user question and AI response"
                })
            
            # Create evaluation prompt
            evaluation_prompt = f"""
You are a quality assurance expert evaluating AI chatbot responses. 

CONVERSATION CONTEXT (if any):
{chat_history}

USER'S QUESTION:
{user_question}

AI'S RESPONSE:
{ai_response}

Please evaluate the AI response on these criteria:

1. RELEVANCE: Does the response directly address the user's question?
2. CONVERSATION FLOW: Does it fit naturally with the conversation context?
3. COMPLETENESS: Does it provide a helpful and complete answer?
4. APPROPRIATENESS: Is the tone and content suitable for the question?
5. TONE & STYLE: Does the reply sound like a friendly, helpful human sales representative (not a robotic FAQ bot)? Look for conversational language, warmth, personality, and natural sales flow. AVOID robotic phrases like "I see...", "I am looking into...", "Let me check our knowledge base", or "I'm searching for information". A real sales employee would speak naturally and directly address the customer's needs while maintaining professionalism.
6. CORRECTNESS: Check if any links are provided and if they are correct by using the web_search tool.
7. GUAGE SENTIMENT: If the response is not positive, make sure to include a (needs help) in the response.

If the answer has a (needs help) - this means that we need to tigger a handoff, make sure you keep it in the answer.

Provide your evaluation as a JSON object with these fields:
- quality_score: Integer from 0-10 (10 = perfect response)
- relevance_score: Integer from 0-10 
- flow_score: Integer from 0-10
- completeness_score: Integer from 0-10
- issues: Array of specific problems identified
- positive_aspects: Array of what the response did well
- recommendation: String with improvement suggestions if needed if scores are below 8
- is_off_topic: Boolean indicating if response is completely off-topic

Be thorough but concise in your analysis.
"""

            # Get evaluation from Gemini
            try:
                response = model.generate_content(
                    evaluation_prompt,
                    generation_config={
                        "max_output_tokens": 500,
                        "temperature": 0.1,  # Low temperature for consistent evaluation
                        "top_p": 0.8,
                        "top_k": 40,
                    },
                )
            except Exception as gemini_err:
                # Quota exhausted or transient error – return stub result so agent still satisfies prompt
                return json.dumps({
                    "quality_score": 0,
                    "issues": [f"Checker error: {str(gemini_err)}"],
                    "recommendation": "Quality checker fallback – review manually",
                })
            
            if response and response.text:
                # Try to extract JSON from response
                response_text = response.text.strip()
                
                # Remove markdown formatting if present
                if response_text.startswith("```json"):
                    response_text = response_text.replace("```json", "").replace("```", "").strip()
                elif response_text.startswith("```"):
                    response_text = response_text.replace("```", "").strip()
                
                # Validate it's proper JSON
                try:
                    evaluation_result = json.loads(response_text)
                    return json.dumps(evaluation_result, indent=2)
                except json.JSONDecodeError:
                    # If JSON parsing fails, return a structured response
                    return json.dumps({
                        "quality_score": 5,
                        "issues": ["Could not parse Gemini evaluation as JSON"],
                        "recommendation": "Manual review required",
                        "raw_evaluation": response_text
                    })
            else:
                return json.dumps({
                    "quality_score": 0,
                    "issues": ["Gemini evaluation failed - no response"],
                    "recommendation": "Retry evaluation or use manual review"
                })
                
        except json.JSONDecodeError as e:
            return json.dumps({
                "quality_score": 0,
                "issues": [f"Invalid input JSON format: {str(e)}"],
                "recommendation": "Please provide valid JSON input with user_question and ai_response fields"
            })
        except Exception as e:
            return json.dumps({
                "quality_score": 0,
                "issues": [f"Evaluation error: {str(e)}"],
                "recommendation": "Please check input format and try again"
            })
    
    quality_checker_tool = Tool(
        name="response_quality_checker",
        description="""Use this tool to evaluate if AI responses properly address user questions and match conversation flow.

Input should be a JSON string with:
- user_question: The user's original question
- ai_response: The AI's response to evaluate  
- conversation_context: chat history


Returns a detailed quality assessment with scores and recommendations.""",
        func=check_response_quality
    )
    
    return quality_checker_tool