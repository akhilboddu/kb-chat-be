import os
from dotenv import load_dotenv
# from langchain_community.embeddings import HuggingFaceEmbeddings # Deprecated
from langchain_huggingface import HuggingFaceEmbeddings # New import path
from langchain_openai import ChatOpenAI # Using OpenAI wrapper for DeepSeek
import chromadb
from chromadb.api.types import EmbeddingFunction, Documents, Embeddings # ChromaDB types

load_dotenv()

# --- Environment Variables ---
CHROMADB_PATH = os.getenv("CHROMADB_PATH", "./chromadb_data")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_BASE = os.getenv("DEEPSEEK_API_BASE") # Should be set in .env, e.g., "https://api.deepseek.com/v1"
DEEPSEEK_MODEL_NAME = "deepseek-chat" # Hardcoded model name as requested

# --- SQLite Metadata DB --- 
# For local development, use a local path
# For Render deployment, we'd use /app/db via environment variable
SQLITE_DB_DIR = os.getenv("SQLITE_DB_DIR", "./db") # Default to local ./db directory
SQLITE_DB_PATH = os.path.join(SQLITE_DB_DIR, os.getenv("SQLITE_DB_FILENAME", "kb_metadata.sqlite"))

# --- ChromaDB ---
# Client is initialized in kb_manager.py

# --- Embeddings ---
# Initialize the original LangChain embedding function
lc_embedding_function = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")

# Define a wrapper for ChromaDB compatibility
class LangchainEmbeddingFunctionWrapper(EmbeddingFunction):
    def __init__(self, lc_embedding_function):
        self._lc_embedding_function = lc_embedding_function

    def __call__(self, input: Documents) -> Embeddings:
        # ChromaDB expects batch processing, LangChain embed_documents handles it
        return self._lc_embedding_function.embed_documents(input)

# Instantiate the wrapper
chroma_embedding_function = LangchainEmbeddingFunctionWrapper(lc_embedding_function)

# --- LLM Initialization ---
llm = None
if DEEPSEEK_API_KEY and DEEPSEEK_API_BASE:
    llm = ChatOpenAI(
        model=DEEPSEEK_MODEL_NAME,
        api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_API_BASE, # Point to DeepSeek endpoint
        # temperature=0.7 # Example: You can uncomment and set temperature if needed
    )
    print(f"LLM: Initialized {DEEPSEEK_MODEL_NAME} via OpenAI wrapper pointing to {DEEPSEEK_API_BASE}")
elif not DEEPSEEK_API_KEY:
    print("Warning: DEEPSEEK_API_KEY not found in .env. LLM not initialized.")
elif not DEEPSEEK_API_BASE:
     print("Warning: DEEPSEEK_API_BASE not found in .env. LLM not initialized.")


print("Configuration loaded.")
print(f"ChromaDB Path: {CHROMADB_PATH}")
print(f"SQLite DB Path: {SQLITE_DB_PATH}") # Add log for SQLite path

