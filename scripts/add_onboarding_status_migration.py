#!/usr/bin/env python3
"""
Migration script to add onboarding_status column to bots table
Usage: python scripts/add_onboarding_status_migration.py
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.supabase_client import supabase
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def add_onboarding_status_column():
    """Add onboarding_status column to bots table"""
    try:
        logger.info("Starting migration: Adding onboarding_status column to bots table")
        
        # Check if column already exists
        logger.info("Checking if onboarding_status column already exists...")
        try:
            # Try to select the column - if it doesn't exist, this will fail
            result = supabase.table("bots").select("onboarding_status").limit(1).execute()
            logger.info("Column onboarding_status already exists. Skipping migration.")
            return True
        except Exception as e:
            if "does not exist" in str(e) or "column" in str(e).lower():
                logger.info("Column doesn't exist. Proceeding with migration...")
            else:
                logger.error(f"Unexpected error checking column: {e}")
                return False
        
        # Add the column using SQL RPC (if your Supabase instance supports it)
        # Note: This requires the SQL to be executed directly in Supabase
        logger.info("Adding onboarding_status column...")
        
        # For now, we'll provide instructions for manual execution
        sql_commands = [
            "ALTER TABLE bots ADD COLUMN onboarding_status TEXT DEFAULT 'pending';",
            "UPDATE bots SET onboarding_status = 'completed' WHERE is_live = true;",
            "COMMENT ON COLUMN bots.onboarding_status IS 'Tracks bot onboarding completion status: pending, completed';"
        ]
        
        logger.info("=" * 60)
        logger.info("MANUAL MIGRATION REQUIRED")
        logger.info("=" * 60)
        logger.info("Please execute the following SQL commands in your Supabase SQL Editor:")
        logger.info("")
        for i, cmd in enumerate(sql_commands, 1):
            logger.info(f"{i}. {cmd}")
        logger.info("")
        logger.info("After executing these commands, the migration will be complete.")
        logger.info("=" * 60)
        
        return True
        
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        return False

if __name__ == "__main__":
    success = add_onboarding_status_column()
    if success:
        logger.info("Migration script completed successfully")
        sys.exit(0)
    else:
        logger.error("Migration script failed")
        sys.exit(1)