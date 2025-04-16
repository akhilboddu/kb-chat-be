from typing import List, Dict, Any
from langchain.text_splitter import RecursiveCharacterTextSplitter
import json

def extract_text_from_json(data: Dict[str, Any]) -> str:
    """Recursively extracts all string values from a nested dictionary."""
    text_parts = []
    
    def recurse(item: Any):
        if isinstance(item, dict):
            for key, value in item.items():
                # Optionally include keys, or just values
                # text_parts.append(f"{key}: ") 
                recurse(value)
        elif isinstance(item, list):
            for element in item:
                recurse(element)
        elif isinstance(item, str):
            text_parts.append(item.strip()) 
        # Add handling for other types if necessary (e.g., numbers)
        # elif isinstance(item, (int, float)):
        #     text_parts.append(str(item))

    recurse(data)
    return " ".join(filter(None, text_parts)) # Join non-empty parts

def chunk_text(text: str, chunk_size: int = 1000, chunk_overlap: int = 150) -> List[str]:
    """Chunks text using RecursiveCharacterTextSplitter."""
    if not text:
        return []
        
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        is_separator_regex=False, # Use default separators
    )
    chunks = text_splitter.split_text(text)
    return chunks

# Example Usage (for testing)
if __name__ == '__main__':
    sample_json_string = '''
    {
        "company": "AI Solutions Inc.",
        "product": {
            "name": "CogniChat",
            "version": "2.1",
            "features": [
                "Natural Language Understanding",
                "Sentiment Analysis",
                {"integration": "Supports REST API and Webhooks"},
                "Multi-language support"
            ],
            "description": "An advanced AI chatbot for customer service automation."
        },
        "contact_email": "support@aisolutions.com",
        "pricing_tier": null,
        "active_users": 5000
    }
    '''
    
    try:
        sample_data = json.loads(sample_json_string)
        extracted = extract_text_from_json(sample_data)
        print("--- Extracted Text ---")
        print(extracted)
        print("\n--- Chunks ---")
        chunks = chunk_text(extracted)
        for i, chunk in enumerate(chunks):
            print(f"Chunk {i+1}:\n{chunk}\n")
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON: {e}")

