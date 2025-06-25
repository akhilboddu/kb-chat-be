import os
import sys
from dotenv import load_dotenv
from supabase import create_client

# Load environment variables
load_dotenv(os.path.join(os.path.dirname(__file__), '../.env.local'))
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in environment.")
    sys.exit(1)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def list_kb_content(kb_id, limit=20, offset=0):
    query = (
        supabase.table('knowledge_base_documents')
        .select('id, document_id, content, created_at')
        .eq('kb_id', kb_id)
        .order('created_at')
        .range(offset, offset + limit - 1)
    )
    result = query.execute()
    docs = result.data or []
    print(f"\nKnowledge Base: {kb_id}")
    print(f"Total returned: {len(docs)} (showing up to {limit})\n")
    for i, doc in enumerate(docs, 1):
        print(f"[{i}] Document ID: {doc.get('document_id')} (created_at: {doc.get('created_at')})")
        content = doc.get('content', '')
        print(f"    Content: {content[:200]}{'...' if len(content) > 200 else ''}\n")
    if not docs:
        print("No documents found for this knowledge base.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python view_kb_content.py <kb_id> [limit] [offset]")
        sys.exit(1)
    kb_id = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    offset = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    list_kb_content(kb_id, limit, offset) 