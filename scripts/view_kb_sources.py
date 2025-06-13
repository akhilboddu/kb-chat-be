#!/usr/bin/env python3
"""
Script to view knowledge base documents with their sources and content snippets.
Useful for debugging and verifying that content is being properly tagged with sources.
"""

import os
import sys
from dotenv import load_dotenv
from supabase import create_client, Client

# Load environment variables
load_dotenv()

# Get Supabase credentials
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env file")
    sys.exit(1)

# Create Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

def view_kb_documents(kb_id: str, limit: int = 10):
    """View documents in a knowledge base with their sources."""
    print(f"Viewing documents for KB: {kb_id}")
    print("-" * 80)
    
    try:
        # Get documents
        result = (supabase.table('knowledge_base_documents')
            .select('document_id, content, knowledge_source, created_at')
            .eq('kb_id', kb_id)
            .order('created_at', desc=True)
            .limit(limit)
            .execute())
        
        if not result.data:
            print(f"No documents found for KB: {kb_id}")
            return
            
        print(f"Found {len(result.data)} documents (showing up to {limit}):\n")
        
        for i, doc in enumerate(result.data, 1):
            print(f"Document {i}:")
            print(f"  ID: {doc['document_id']}")
            print(f"  Source: {doc.get('knowledge_source', 'unknown')}")
            print(f"  Created: {doc.get('created_at', 'unknown')}")
            
            # Show content preview (first 200 chars)
            content = doc.get('content', '')
            preview = content[:200] + "..." if len(content) > 200 else content
            print(f"  Content Preview: {preview}")
            print("-" * 60)
            
        # Show source summary for this KB
        print("\nSource Summary for this KB:")
        source_result = (supabase.table('knowledge_base_documents')
            .select('knowledge_source')
            .eq('kb_id', kb_id)
            .execute())
        
        source_counts = {}
        for doc in source_result.data:
            source = doc.get('knowledge_source', 'unknown')
            source_counts[source] = source_counts.get(source, 0) + 1
            
        for source, count in sorted(source_counts.items()):
            print(f"  {source}: {count} documents")
            
    except Exception as e:
        print(f"Error viewing KB documents: {str(e)}")

def list_knowledge_bases():
    """List all knowledge bases."""
    print("Available Knowledge Bases:")
    print("-" * 80)
    
    try:
        result = supabase.table('knowledge_bases').select('kb_id, name, created_at').execute()
        
        if not result.data:
            print("No knowledge bases found.")
            return
            
        for kb in sorted(result.data, key=lambda x: x.get('created_at', ''), reverse=True):
            print(f"  KB ID: {kb['kb_id']}")
            print(f"  Name: {kb.get('name', 'Unnamed')}")
            print(f"  Created: {kb.get('created_at', 'unknown')}")
            print("-" * 40)
            
    except Exception as e:
        print(f"Error listing knowledge bases: {str(e)}")

def main():
    """Main function."""
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python scripts/view_kb_sources.py list                    # List all KBs")
        print("  python scripts/view_kb_sources.py <kb_id> [limit]        # View KB documents")
        print("\nExample:")
        print("  python scripts/view_kb_sources.py kb_1234567890_abcd")
        print("  python scripts/view_kb_sources.py kb_1234567890_abcd 20")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "list":
        list_knowledge_bases()
    else:
        kb_id = command
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        view_kb_documents(kb_id, limit)

if __name__ == "__main__":
    main() 