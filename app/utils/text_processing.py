import re

def clean_agent_output(text: str) -> str:
    """Removes surrounding markdown code blocks (```) and single backticks."""
    original_text = text
    cleaned_text = text.strip()
    # print(f"clean_agent_output: Original='{original_text}' Stripped='{cleaned_text}'") # Optional: less verbose logging

    # Remove leading/trailing code blocks (``` optional_lang newline ... newline ```)
    cleaned_text = re.sub(r'^```(?:[a-zA-Z0-9_]+)?\s*?\n(.*?)\n```$\s*', r'\1', cleaned_text, flags=re.DOTALL | re.MULTILINE)
    # Remove leading/trailing code blocks (```...```) on a single line
    cleaned_text = re.sub(r'^```(.*?)```$\s*', r'\1', cleaned_text)
    # Remove leading/trailing single backticks
    cleaned_text = re.sub(r'^`(.*?)`$\s*', r'\1', cleaned_text)
    # Remove just trailing ``` that might be left over
    cleaned_text = re.sub(r'\n```$\s*', '', cleaned_text) 
    cleaned_text = re.sub(r'```$\s*', '', cleaned_text) 

    final_cleaned = cleaned_text.strip()
    if final_cleaned != original_text.strip():
        print(f"clean_agent_output: Cleaned from '{original_text.strip()}' to '{final_cleaned}'")
    # else:
        # print("clean_agent_output: No changes made.") # Optional: less verbose logging
    return final_cleaned 