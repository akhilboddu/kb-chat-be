import os
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()  # loads from .env file

SUPABASE_URL = os.getenv("SUPABASE_URL")
# Allow both SUPABASE_SERVICE_ROLE_KEY (preferred) and legacy SUPABASE_SERVICE_KEY
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise Exception("Missing Supabase configuration in .env")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)