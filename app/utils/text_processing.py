import re


def clean_agent_output(text: str) -> str:
    """Removes surrounding markdown code blocks (```) and single backticks."""
    original_text = text
    cleaned_text = text.strip()
    # print(f"clean_agent_output: Original='{original_text}' Stripped='{cleaned_text}'") # Optional: less verbose logging

    # Remove leading/trailing code blocks (``` optional_lang newline ... newline ```)
    cleaned_text = re.sub(
        r"^```(?:[a-zA-Z0-9_]+)?\s*?\n(.*?)\n```$\s*",
        r"\1",
        cleaned_text,
        flags=re.DOTALL | re.MULTILINE,
    )
    # Remove leading/trailing code blocks (```...```) on a single line
    cleaned_text = re.sub(r"^```(.*?)```$\s*", r"\1", cleaned_text)
    # Remove leading/trailing single backticks
    cleaned_text = re.sub(r"^`(.*?)`$\s*", r"\1", cleaned_text)
    # Remove just trailing ``` that might be left over
    cleaned_text = re.sub(r"\n```$\s*", "", cleaned_text)
    cleaned_text = re.sub(r"```$\s*", "", cleaned_text)

    final_cleaned = cleaned_text.strip()
    if final_cleaned != original_text.strip():
        print(
            f"clean_agent_output: Cleaned from '{original_text.strip()}' to '{final_cleaned}'"
        )
    # else:
    # print("clean_agent_output: No changes made.") # Optional: less verbose logging
    return final_cleaned


def should_trigger_handoff(response_text: str) -> bool:
    """
    Detects if a response indicates insufficient information and should trigger a handoff.
    Returns True if handoff should be triggered.
    """
    if not response_text:
        return False
    
    # Normalize text for case-insensitive matching
    text_lower = response_text.lower()
    
    # Patterns that indicate insufficient information
    insufficient_info_patterns = [
        # Direct statements of lacking information
        r"i don'?t have.*information",
        r"i don'?t have.*details", 
        r"i don'?t know",
        r"i can'?t find.*information",
        r"i can'?t find.*details",
        r"i can'?t provide.*information",
        r"i don'?t have.*specific",
        r"i don'?t have.*complete",
        r"not.*enough.*information",
        r"insufficient.*information",
        r"limited.*information",
        
        # Uncertainty phrases
        r"i'?m not.*sure",
        r"i'?m uncertain",
        r"unable to.*find",
        r"unable to.*determine",
        r"can'?t.*definitively",
        r"cannot.*definitively",
        r"i cannot.*confirm",
        r"i can'?t.*confirm",
        
        # Vague or qualified responses
        r"however.*i.*don'?t",
        r"but.*i.*don'?t",
        r"unfortunately.*i.*don'?t",
        r"sorry.*i.*don'?t",
        
        # Hedging language that suggests uncertainty
        r"i.*believe.*but.*not.*sure",
        r"it.*seems.*but.*i.*can'?t",
        r"it.*appears.*but.*i.*don'?t",
    ]
    
    # Check if any pattern matches
    for pattern in insufficient_info_patterns:
        if re.search(pattern, text_lower):
            print(f"Handoff trigger detected: Pattern '{pattern}' matched in response")
            return True
    
    return False


def auto_add_handoff_if_needed(response_text: str) -> str:
    """
    Automatically adds handoff marker if the response indicates insufficient information.
    Returns the response with handoff marker added if needed.
    """
    if not response_text:
        return response_text
    
    # Check if handoff marker already exists
    if "(needs help)" in response_text:
        return response_text
    
    # Check if handoff should be triggered
    if should_trigger_handoff(response_text):
        # Add a transition phrase and handoff marker
        enhanced_response = response_text.rstrip()
        
        # Add appropriate transition based on response content
        if "however" in response_text.lower() or "but" in response_text.lower():
            enhanced_response += " Let me connect you with someone from our team who can provide more specific details. (needs help)"
        else:
            enhanced_response += " Let me check with my team and get back to you with more complete information. (needs help)"
        
        print(f"Auto-handoff triggered: Added handoff marker to response")
        return enhanced_response
    
    return response_text

