import os
from dotenv import load_dotenv

# from langchain_community.embeddings import HuggingFaceEmbeddings # Deprecated
from langchain_huggingface import HuggingFaceEmbeddings  # New import path
from langchain_openai import ChatOpenAI  # Using OpenAI wrapper for DeepSeek
from langchain_google_genai import ChatGoogleGenerativeAI  # Add Gemini import

load_dotenv()

# --- Environment Variables ---
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_BASE = os.getenv(
    "DEEPSEEK_API_BASE"
)  # Should be set in .env, e.g., "https://api.deepseek.com/v1"
# DEEPSEEK_MODEL_NAME = "deepseek-chat" # Hardcoded model name as requested - Moved to LLM init block
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")  # Read Google API Key
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL")

# --- SQLite Metadata DB ---
# [REMOVED: SQLite configuration - now using Supabase for all metadata storage]

# --- Embeddings ---
# Initialize the original LangChain embedding function
lc_embedding_function = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)

# --- LLM Initialization ---
llm = None
# Prioritize Google Gemini if API key is available
if GOOGLE_API_KEY:
    try:
        # Explicitly pass the key, though it often reads from env var too
        llm = ChatGoogleGenerativeAI(
            model="gemini-2.0-flash", 
            google_api_key=GOOGLE_API_KEY,
            temperature=0.1,  # Lower temperature for more consistent behavior
            top_p=0.8,
            top_k=40
        )
        print(f"LLM: Initialized Google Gemini Pro (gemini-2.0-flash) with temperature=0.1")
    except Exception as e:
        print(
            f"Warning: Failed to initialize Google Gemini even though key was found: {e}"
        )
        llm = None  # Ensure llm is None if initialization fails

# Fallback to OPENAI if Gemini is not initialized and OPENAI_API_KEY and OPENAI_MODEL are available
if llm is None and OPENAI_API_KEY and OPENAI_MODEL:
    try:
        OPENAI_MODEL = "gpt-4"  # Define model name here
        llm = ChatOpenAI(
            model=OPENAI_MODEL,
            api_key=OPENAI_API_KEY,
            # temperature=0.7 # Example: You can uncomment and set temperature if needed
        )
        print(f"LLM: Initialized {OPENAI_MODEL} via OpenAI wrapper pointing to")
    except Exception as e:
        print(f"Warning: Failed to initialize OpenAI: {e}")
        llm = None  # Ensure llm is None if initialization fails

# Fallback to DeepSeek if Gemini is not initialized and DeepSeek keys are available
if llm is None and DEEPSEEK_API_KEY and DEEPSEEK_API_BASE:
    try:
        DEEPSEEK_MODEL_NAME = "deepseek-chat"  # Define model name here
        llm = ChatOpenAI(
            model=DEEPSEEK_MODEL_NAME,
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_API_BASE,  # Point to DeepSeek endpoint
            # temperature=0.7 # Example: You can uncomment and set temperature if needed
        )
        print(
            f"LLM: Initialized {DEEPSEEK_MODEL_NAME} via OpenAI wrapper pointing to {DEEPSEEK_API_BASE}"
        )
    except Exception as e:
        print(f"Warning: Failed to initialize DeepSeek: {e}")
        llm = None  # Ensure llm is None if initialization fails

# Final check if any LLM was initialized
if llm is None:
    print("Warning: No LLM could be initialized. Check API keys and base URLs in .env.")


print("Configuration loaded.")
