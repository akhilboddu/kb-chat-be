from typing import Dict, Any, List, Callable
from langchain.tools import Tool
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from app.core.kb_manager import kb_manager

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
        success = kb_manager.add_to_kb(kb_id, text_to_add)
        if success:
            return f"Successfully updated knowledge base {kb_id}."
        else:
            return "Failed to update knowledge base. Please ensure the text is not empty."
    
    return Tool(
        name="update_knowledge_base",
        description="Useful for adding new information to the knowledge base.",
        func=update_kb
    )