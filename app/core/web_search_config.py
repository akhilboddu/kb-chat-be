"""
Configuration and settings for web search tool.
"""

import os
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

@dataclass
class WebSearchConfig:
    """Configuration for web search tool."""
    
    # OpenAI API settings
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    model: str = "gpt-4.1"
    max_results: int = 3
    
    # Rate limiting
    max_searches_per_conversation: int = 5
    cooldown_seconds: int = 30
    
    # Content filtering
    allowed_domains: Optional[List[str]] = None
    blocked_domains: Optional[List[str]] = None

def get_default_web_search_config() -> WebSearchConfig:
    """Get default web search configuration."""
    return WebSearchConfig()

def validate_web_search_config(config: WebSearchConfig) -> bool:
    """Validate web search configuration."""
    if not config.openai_api_key:
        print("Warning: OpenAI API key not found in environment variables")
        return False
    
    return True

# Note: Business context functions have been removed as they are no longer needed
# for the simplified direct web search implementation.

def create_business_context_from_bot(bot_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create business context from bot data.
    
    Args:
        bot_data: Dictionary containing bot information
        
    Returns:
        Dictionary with business context
    """
    return {
        'company_name': bot_data.get('company', ''),
        'industry': bot_data.get('industry', ''),
        'products': bot_data.get('products', []),
        'services': bot_data.get('services', []),
        'bot_name': bot_data.get('name', 'Assistant'),
        'business_keywords': _extract_business_keywords(bot_data)
    }

def _extract_business_keywords(bot_data: Dict[str, Any]) -> List[str]:
    """Extract business keywords from bot data."""
    keywords = []
    
    # Add company name
    if bot_data.get('company'):
        keywords.append(bot_data['company'].lower())
    
    # Add industry
    if bot_data.get('industry'):
        keywords.append(bot_data['industry'].lower())
    
    # Add products and services
    products = bot_data.get('products', [])
    services = bot_data.get('services', [])
    
    for product in products:
        if isinstance(product, str):
            keywords.append(product.lower())
    
    for service in services:
        if isinstance(service, str):
            keywords.append(service.lower())
    
    return list(set(keywords))  # Remove duplicates

def is_business_relevant_query(query: str, business_context: Dict[str, Any], config: WebSearchConfig) -> Dict[str, Any]:
    """
    Determine if a query is business-relevant.
    
    Args:
        query: User query
        business_context: Business context dictionary
        config: Web search configuration
        
    Returns:
        Dictionary with relevance information
    """
    if not business_context:
        return {
            'is_business_relevant': False,
            'reason': 'No business context provided',
            'relevance_score': 0,
            'matched_categories': []
        }
    
    query_lower = query.lower()
    relevance_score = 0
    matched_categories = []
    
    # Check company name (highest weight)
    company_name = business_context.get('company_name', '').lower()
    if company_name and company_name in query_lower:
        relevance_score += 1
        matched_categories.append('company')
    
    # Check industry (high weight)
    industry = business_context.get('industry', '').lower()
    if industry and industry in query_lower:
        relevance_score += 2
        matched_categories.append('industry')
    
    # Check business keywords
    business_keywords = business_context.get('business_keywords', [])
    for keyword in business_keywords:
        if keyword in query_lower:
            relevance_score += 1
            if 'business_keyword' not in matched_categories:
                matched_categories.append('business_keyword')
    
    return {
        'is_business_relevant': relevance_score >= config.min_relevance_score,
        'relevance_score': relevance_score,
        'matched_categories': matched_categories,
        'should_search': relevance_score >= config.min_relevance_score
    }

def enhance_search_query(query: str, business_context: Dict[str, Any], config: WebSearchConfig) -> str:
    """
    Enhance search query with business context.
    
    Args:
        query: Original query
        business_context: Business context
        config: Web search configuration
        
    Returns:
        Enhanced query
    """
    if not config.enhance_query_with_context:
        return query
    
    enhanced_parts = [query]
    
    if config.include_company_name:
        company_name = business_context.get('company_name', '')
        if company_name:
            enhanced_parts.append(company_name)
    
    if config.include_industry:
        industry = business_context.get('industry', '')
        if industry:
            enhanced_parts.append(industry)
    
    print(f"Enhanced query: {enhanced_parts}")
    
    return ' '.join(enhanced_parts).strip() 