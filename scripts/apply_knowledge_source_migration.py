#!/usr/bin/env python3
"""
Script to apply the knowledge_source column migration to Supabase.
This adds the knowledge_source column to the knowledge_base_documents table.
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

def apply_migration():
    """Apply the knowledge_source column migration."""
    print("Applying knowledge_source column migration...")
    print("-" * 80)
    
    # Read the migration file
    migration_file = "supabase/migrations/002_add_knowledge_source_tracking.sql"
    
    if not os.path.exists(migration_file):
        print(f"Error: Migration file not found: {migration_file}")
        sys.exit(1)
    
    with open(migration_file, 'r') as f:
        migration_sql = f.read()
    
    print("Migration SQL:")
    print(migration_sql)
    print("-" * 80)
    
    try:
        # Note: Supabase Python client doesn't have a direct way to execute raw SQL
        # You'll need to run this migration through the Supabase dashboard or CLI
        print("\nIMPORTANT: The Supabase Python client doesn't support running raw SQL migrations.")
        print("\nTo apply this migration, you have two options:")
        print("\n1. Using Supabase Dashboard:")
        print("   - Go to your Supabase project dashboard")
        print("   - Navigate to the SQL Editor")
        print("   - Copy and paste the migration SQL above")
        print("   - Click 'Run' to execute")
        print("\n2. Using Supabase CLI:")
        print("   - Install Supabase CLI: npm install -g supabase")
        print("   - Link your project: supabase link --project-ref your-project-ref")
        print("   - Run: supabase db push")
        print("\nThe migration will:")
        print("  - Add a 'knowledge_source' column to knowledge_base_documents table")
        print("  - Create an index for efficient filtering by source")
        print("  - Set existing records to 'unknown' source")
        print("  - Add a descriptive comment to the column")
        
    except Exception as e:
        print(f"Error: {str(e)}")

def main():
    """Main function."""
    apply_migration()

if __name__ == "__main__":
    main() 