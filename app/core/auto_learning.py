"""
Auto-Learning System for Knowledge Base Enhancement

This module analyzes conversation histories that had handoffs to identify
knowledge gaps and automatically generate chunks to be added to the KB.
Uses Gemini to analyze conversations and extract learnable insights.
"""

import json
import logging
from typing import Dict, List, Optional, Tuple, Any
import os

# Import existing functions we'll reuse
from app.core.supabase_metadata_manager import get_conversation_history, get_formatted_conversation_history_and_customer_details

# Gemini imports
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

logger = logging.getLogger(__name__)


class AutoLearningSystem:
    """
    Analyzes conversations with handoffs to generate knowledge base improvements.
    """
    
    def __init__(self, gemini_api_key: Optional[str] = None):
        """
        Initialize the auto-learning system.
        
        Args:
            gemini_api_key: Optional Gemini API key. If not provided, uses environment variable.
        """
        self.gemini_available = GEMINI_AVAILABLE
        
        if self.gemini_available:
            api_key = gemini_api_key or os.getenv("GOOGLE_API_KEY")
            if api_key:
                genai.configure(api_key=api_key)
                self.model = genai.GenerativeModel("gemini-1.5-flash")
                logger.info("✅ Auto-learning system initialized with Gemini")
            else:
                self.gemini_available = False
                logger.warning("❌ GOOGLE_API_KEY not found - Auto-learning system disabled")
        else:
            logger.warning("❌ Gemini not available - Auto-learning system disabled")
    
    async def analyze_handoff_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """
        Analyze a conversation that had a handoff to extract learnable insights.
        
        Args:
            conversation_id: The conversation ID to analyze
            
        Returns:
            Dictionary containing analysis results or None if analysis fails
        """
        if not self.gemini_available:
            logger.error("Cannot analyze conversation - Gemini not available")
            return None
        
        try:
            # Get conversation history using existing function
            conversation_data = await get_formatted_conversation_history_and_customer_details(conversation_id)
            
            if not conversation_data or not conversation_data.get('history'):
                logger.warning(f"No conversation history found for {conversation_id}")
                return None
            
            history = conversation_data['history']
            customer_email = conversation_data.get('customer_email')
            customer_phone = conversation_data.get('customer_phone_number')
            
            # Check if this conversation actually had a handoff
            if not self._conversation_had_handoff(history):
                logger.info(f"Conversation {conversation_id} did not have a handoff - skipping analysis")
                return None
            
            logger.info(f"Analyzing handoff conversation {conversation_id} for auto-learning")
            
            # Analyze with Gemini
            analysis = self._analyze_conversation_with_gemini(history, customer_email, customer_phone)
            
            if analysis:
                analysis['conversation_id'] = conversation_id
                analysis['customer_email'] = customer_email
                analysis['customer_phone'] = customer_phone
            
            return analysis
            
        except Exception as e:
            logger.error(f"Error analyzing conversation {conversation_id}: {e}")
            return None
    
    def _conversation_had_handoff(self, conversation_history: str) -> bool:
        """
        Check if a conversation actually had a handoff by looking for handoff indicators.
        
        Args:
            conversation_history: The formatted conversation history string
            
        Returns:
            True if handoff indicators are found
        """
        handoff_indicators = [
            "(needs help)",
            "human colleague",
            "Human Agent:",
            "Human Agent"
            "handoff",
            "need to check with",
            "let me get someone",
            "transfer you to"
        ]

        logger.info(f"Conversation history: {conversation_history}")
        
        history_lower = conversation_history.lower()
        return any(indicator.lower() in history_lower for indicator in handoff_indicators)
    
    def _analyze_conversation_with_gemini(self, conversation_history: str, customer_email: Optional[str] = None, customer_phone: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Use Gemini to analyze the conversation and extract learning opportunities.
        
        Args:
            conversation_history: The formatted conversation history
            customer_email: Customer email if available
            customer_phone: Customer phone if available
            
        Returns:
            Analysis results dictionary or None if analysis fails
        """
        prompt = f"""
You are an AI knowledge base analyst. Analyze this customer service conversation that resulted in a handoff to a human agent.

CONVERSATION HISTORY:
{conversation_history}

CUSTOMER INFO:
- Email: {customer_email} or 'Not provided'
- Phone: {customer_phone} or 'Not provided'

Your task is to identify what the AI assistant was unable to answer that caused the handoff, and generate a knowledge base chunk that would help prevent similar handoffs in the future.

Please provide your analysis in this exact JSON format:

{{
    "knowledge_gap_identified": true/false,
    "gap_summary": "Brief description of what the AI couldn't handle",
    "customer_question_theme": "The main topic/category of the customer's unanswered question",
    "recommended_kb_chunk": {{
        "title": "Clear title for the knowledge chunk",
        "content": "Comprehensive content that would help answer similar questions in the future. Include specific details, procedures, policies, or information that was missing."
    }},
    "confidence_score": 0.0-1.0,
}}

ANALYSIS GUIDELINES:
1. Only set knowledge_gap_identified to true if there's a clear, answerable question the AI failed to handle
2. The recommended_kb_chunk should be factual and helpful - don't make up information
3. Focus on procedural knowledge, policies, or commonly asked questions
4. If the handoff was due to a complex personal situation that requires human judgment, set knowledge_gap_identified to false
5. Confidence score should reflect how certain you are that this KB chunk would prevent similar handoffs

Be thorough and practical in your analysis.
"""

        try:
            response = self.model.generate_content(prompt)
            
            if not response or not response.text:
                logger.error("Empty response from Gemini")
                return None
            
            # Parse JSON response - handle markdown code blocks
            try:
                response_text = response.text.strip()
                
                # Remove markdown code blocks if present
                if response_text.startswith('```json'):
                    response_text = response_text[7:]  # Remove ```json
                elif response_text.startswith('```'):
                    response_text = response_text[3:]   # Remove ```
                
                if response_text.endswith('```'):
                    response_text = response_text[:-3]  # Remove trailing ```
                
                response_text = response_text.strip()
                
                analysis = json.loads(response_text)
                
                # Validate required fields
                required_fields = ['knowledge_gap_identified', 'gap_summary', 'confidence_score']
                if not all(field in analysis for field in required_fields):
                    logger.error(f"Missing required fields in Gemini analysis: {list(analysis.keys())}")
                    return None
                
                logger.info(f"Successfully analyzed conversation - Gap identified: {analysis.get('knowledge_gap_identified')}")
                return analysis
                
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse Gemini response as JSON: {e}")
                logger.error(f"Raw response: {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Error calling Gemini for conversation analysis: {e}")
            return None
    
    def generate_kb_chunk_from_analysis(self, analysis: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Extract a properly formatted KB chunk from the analysis results.
        
        Args:
            analysis: The analysis results from analyze_handoff_conversation
            
        Returns:
            Dictionary containing the formatted KB chunk ready for addition, or None
        """
        if not analysis or not analysis.get('knowledge_gap_identified'):
            logger.info("No knowledge gap identified or analysis unavailable")
            return None
        
        recommended_chunk = analysis.get('recommended_kb_chunk')
        if not recommended_chunk:
            logger.warning("Analysis didn't include recommended KB chunk")
            return None
        
        # Format the chunk for KB addition
        kb_chunk = {
            'title': recommended_chunk.get('title', 'Auto-learned Knowledge'),
            'content': recommended_chunk.get('content', ''),
            'source': 'auto-learning',
            'source_type': 'human_conversation',
            'confidence_score': analysis.get('confidence_score', 0.0),
            'gap_summary': analysis.get('gap_summary', ''),
            'customer_question_theme': analysis.get('customer_question_theme', ''),
            'conversation_id': analysis.get('conversation_id', ''),
            'metadata': {
                'customer_email': analysis.get('customer_email'),
                'customer_phone': analysis.get('customer_phone'),
                'analysis_method': 'gemini_auto_learning'
            }
        }
        
        # Validate the chunk has meaningful content
        if not kb_chunk['content'] or len(kb_chunk['content'].strip()) < 50:
            logger.warning("Generated KB chunk content is too short or empty")
            return None
        
        logger.info(f"Generated KB chunk: '{kb_chunk['title'][:50]}...' (confidence: {kb_chunk.get('confidence_score', 0.0)})")
        return kb_chunk
    
    async def process_handoff_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """
        Complete pipeline: analyze a handoff conversation and return a ready-to-use KB chunk.
        
        Args:
            conversation_id: The conversation ID to process
            
        Returns:
            Dictionary containing the KB chunk to be added, or None if no chunk should be created
        """
        logger.info(f"Processing handoff conversation {conversation_id} for auto-learning")
        
        # Step 1: Analyze the conversation
        analysis = await self.analyze_handoff_conversation(conversation_id)
        if not analysis:
            logger.info(f"No analysis results for conversation {conversation_id}")
            return None
        
        # Step 2: Generate KB chunk from analysis
        logger.info(f"Generating KB chunk from analysis for conversation {conversation_id}")
        kb_chunk = self.generate_kb_chunk_from_analysis(analysis)
        if not kb_chunk:
            logger.warning(f"No KB chunk generated for conversation {conversation_id}")
            return None
        
        # Step 3: Add timestamp
        import time
        if 'metadata' not in kb_chunk:
            kb_chunk['metadata'] = {}
        kb_chunk['metadata']['analysis_date'] = int(time.time())
        
        logger.info(f"Successfully processed conversation {conversation_id} - KB chunk ready for addition: {kb_chunk['title']}")
        return kb_chunk


# Convenience functions for easy usage
async def analyze_conversation_for_learning(conversation_id: str) -> Optional[Dict[str, Any]]:
    """
    Convenience function to analyze a single conversation.
    
    Args:
        conversation_id: The conversation ID to analyze
        
    Returns:
        Ready-to-use KB chunk dictionary or None
    """
    auto_learner = AutoLearningSystem()
    return await auto_learner.process_handoff_conversation(conversation_id)


async def batch_analyze_conversations(conversation_ids: List[str]) -> List[Dict[str, Any]]:
    """
    Analyze multiple conversations for learning opportunities.
    
    Args:
        conversation_ids: List of conversation IDs to analyze
        
    Returns:
        List of KB chunks ready for addition
    """
    auto_learner = AutoLearningSystem()
    kb_chunks = []
    
    for conversation_id in conversation_ids:
        try:
            chunk = await auto_learner.process_handoff_conversation(conversation_id)
            if chunk:
                kb_chunks.append(chunk)
        except Exception as e:
            logger.error(f"Error processing conversation {conversation_id}: {e}")
            continue
    
    logger.info(f"Batch analysis complete: {len(kb_chunks)} KB chunks generated from {len(conversation_ids)} conversations")
    return kb_chunks 