#!/usr/bin/env python3
"""
Migration script to create user_profiles table
Usage: python scripts/create_user_profiles_migration.py
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.supabase_client import supabase
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_user_profiles_table():
    """Create user_profiles table"""
    try:
        logger.info("Starting migration: Creating user_profiles table")
        
        # Check if table already exists
        logger.info("Checking if user_profiles table already exists...")
        try:
            # Try to select from the table - if it doesn't exist, this will fail
            result = supabase.table("user_profiles").select("id").limit(1).execute()
            logger.info("Table user_profiles already exists. Skipping migration.")
            return True
        except Exception as e:
            if "does not exist" in str(e) or "table" in str(e).lower():
                logger.info("Table doesn't exist. Proceeding with migration...")
            else:
                logger.error(f"Unexpected error checking table: {e}")
                return False
        
        # Provide SQL commands for manual execution
        logger.info("Creating user_profiles table...")
        
        sql_commands = [
            """
            CREATE TABLE IF NOT EXISTS user_profiles (
                id UUID PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                display_name TEXT,
                bio TEXT,
                avatar_url TEXT,
                payment_status TEXT DEFAULT 'TRIAL',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_user_profiles_email ON user_profiles(email);",
            "CREATE INDEX IF NOT EXISTS idx_user_profiles_payment_status ON user_profiles(payment_status);"
        ]
        
        logger.info("=" * 60)
        logger.info("MANUAL MIGRATION REQUIRED")
        logger.info("=" * 60)
        logger.info("Please execute the following SQL commands in your Supabase SQL Editor:")
        logger.info("")
        for i, cmd in enumerate(sql_commands, 1):
            logger.info(f"{i}. {cmd.strip()}")
            logger.info("")
        logger.info("After executing these commands, the migration will be complete.")
        logger.info("=" * 60)
        
        return True
        
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        return False

if __name__ == "__main__":
    success = create_user_profiles_table()
    if success:
        logger.info("Migration script completed successfully")
        sys.exit(0)
    else:
        logger.error("Migration script failed")
        sys.exit(1)