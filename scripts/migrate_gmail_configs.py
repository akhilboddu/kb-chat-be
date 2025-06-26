#!/usr/bin/env python3
"""
Migration script to create the gmail_configs table for Gmail OAuth integration.
Run this script to set up the database table for storing Gmail configurations.
"""

import os
import sys
import psycopg2
from pathlib import Path

# Add the parent directory to the path so we can import from app
sys.path.append(str(Path(__file__).parent.parent))

from app.core.supabase_client import supabase

def run_migration():
    """Run the Gmail configs table migration"""
    
    # Read the SQL file
    sql_file_path = Path(__file__).parent / "create_gmail_configs_table.sql"
    
    if not sql_file_path.exists():
        print(f"❌ SQL file not found: {sql_file_path}")
        return False
    
    with open(sql_file_path, 'r') as file:
        sql_content = file.read()
    
    try:
        print("🔄 Running Gmail configs table migration...")
        
        # Execute the SQL using Supabase client
        result = supabase.rpc('exec_sql', {'sql': sql_content}).execute()
        
        print("✅ Successfully created gmail_configs table!")
        print("📋 Table structure:")
        print("   - id: UUID primary key")
        print("   - bot_id: UUID foreign key to bots table")
        print("   - is_enabled: Boolean (default: false)")
        print("   - email_address: VARCHAR(255)")
        print("   - refresh_token: TEXT")
        print("   - access_token: TEXT")
        print("   - token_expires_at: TIMESTAMP WITH TIME ZONE")
        print("   - scopes: TEXT")
        print("   - created_at: TIMESTAMP WITH TIME ZONE")
        print("   - updated_at: TIMESTAMP WITH TIME ZONE")
        print("")
        print("🔒 Constraints:")
        print("   - Foreign key to bots(id) with CASCADE delete")
        print("   - Unique constraint on bot_id (one config per bot)")
        print("")
        print("📊 Indexes:")
        print("   - idx_gmail_configs_bot_id")
        print("   - idx_gmail_configs_email")
        
        return True
        
    except Exception as e:
        print(f"❌ Migration failed: {str(e)}")
        print("\n🔧 Troubleshooting:")
        print("   1. Make sure your database connection is working")
        print("   2. Check if you have CREATE TABLE permissions")
        print("   3. Verify the bots table exists")
        return False

def check_table_exists():
    """Check if the gmail_configs table already exists"""
    try:
        result = supabase.table("gmail_configs").select("count", count="exact").limit(0).execute()
        return True
    except:
        return False

if __name__ == "__main__":
    print("📧 Gmail Configs Table Migration")
    print("=" * 40)
    
    # Check if table already exists
    if check_table_exists():
        print("ℹ️  gmail_configs table already exists!")
        
        response = input("Do you want to continue anyway? (y/N): ")
        if response.lower() != 'y':
            print("🚫 Migration cancelled.")
            sys.exit(0)
    
    # Run the migration
    success = run_migration()
    
    if success:
        print("\n🎉 Migration completed successfully!")
        print("You can now use Gmail OAuth integration with your bots.")
    else:
        print("\n💥 Migration failed!")
        sys.exit(1) 