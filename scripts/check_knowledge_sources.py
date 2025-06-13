#!/usr/bin/env python3
"""
Script to check knowledge sources in the knowledge_base_documents table.
This helps verify that knowledge source tracking is working properly.
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

def check_knowledge_sources(kb_id: str = None):
    """Check knowledge sources in the database."""
    print("Checking knowledge sources in knowledge_base_documents...")
    print("-" * 80)
    
    try:
        # Build query
        query = supabase.table('knowledge_base_documents').select('kb_id, knowledge_source, created_at')
        
        if kb_id:
            query = query.eq('kb_id', kb_id)
            
        # Get unique sources with counts
        result = query.execute()
        
        if not result.data:
            print("No documents found in knowledge_base_documents table.")
            return
            
        # Count sources by type
        source_counts = {}
        kb_sources = {}
        
        for doc in result.data:
            kb = doc['kb_id']
            source = doc.get('knowledge_source', 'unknown')
            
            # Overall counts
            source_counts[source] = source_counts.get(source, 0) + 1
            
            # Per-KB counts
            if kb not in kb_sources:
                kb_sources[kb] = {}
            kb_sources[kb][source] = kb_sources[kb].get(source, 0) + 1
        
        # Display overall summary
        print("Overall Knowledge Source Summary:")
        print("-" * 40)
        for source, count in sorted(source_counts.items()):
            print(f"  {source}: {count} documents")
        
        print(f"\nTotal documents: {len(result.data)}")
        
        # Display per-KB breakdown if not filtering by KB
        if not kb_id and len(kb_sources) > 1:
            print("\nPer-KB Breakdown:")
            print("-" * 40)
            for kb, sources in sorted(kb_sources.items()):
                print(f"\n{kb}:")
                for source, count in sorted(sources.items()):
                    print(f"  {source}: {count} documents")
        
        # Show sample of recent documents
        print("\nRecent documents (last 5):")
        print("-" * 40)
        recent_docs = sorted(result.data, key=lambda x: x.get('created_at', ''), reverse=True)[:5]
        for doc in recent_docs:
            print(f"  KB: {doc['kb_id']}")
            print(f"  Source: {doc.get('knowledge_source', 'unknown')}")
            print(f"  Created: {doc.get('created_at', 'unknown')}")
            print("  ---")
            
    except Exception as e:
        print(f"Error checking knowledge sources: {str(e)}")

def main():
    """Main function."""
    kb_id = None
    if len(sys.argv) > 1:
        kb_id = sys.argv[1]
        print(f"Filtering by KB ID: {kb_id}")
    
    check_knowledge_sources(kb_id)

if __name__ == "__main__":
    main() 