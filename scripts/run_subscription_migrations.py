#!/usr/bin/env python3
"""
Script to run subscription migration SQL files in order
"""

import os
import sys
from pathlib import Path
from app.core.supabase_client import supabase
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def run_migration(sql_file_path: str, migration_name: str):
    """Run a single migration SQL file"""
    try:
        logger.info(f"Running migration: {migration_name}")
        
        with open(sql_file_path, 'r') as f:
            sql_content = f.read()
        
        # Run the SQL using supabase client
        result = supabase.rpc('exec_sql', {'sql': sql_content}).execute()
        
        if result.data:
            logger.info(f"✅ Migration {migration_name} completed successfully")
            return True
        else:
            logger.error(f"❌ Migration {migration_name} failed")
            return False
            
    except Exception as e:
        logger.error(f"❌ Error running migration {migration_name}: {str(e)}")
        return False

def main():
    """Run all subscription migrations in order"""
    migrations_dir = Path(__file__).parent.parent / "migrations"
    
    # List of migrations to run in order
    migrations = [
        "001_create_plans_table.sql",
        "002_add_plan_id_to_subscriptions.sql", 
        "003_backfill_plan_ids.sql"
    ]
    
    logger.info("Starting subscription migrations...")
    
    success_count = 0
    for migration in migrations:
        migration_path = migrations_dir / migration
        
        if not migration_path.exists():
            logger.warning(f"Migration file not found: {migration_path}")
            continue
            
        if run_migration(str(migration_path), migration):
            success_count += 1
        else:
            logger.error(f"Migration failed, stopping: {migration}")
            sys.exit(1)
    
    logger.info(f"\n✅ Successfully ran {success_count}/{len(migrations)} migrations")
    
    # Verify the migration results
    logger.info("\nVerifying migration results...")
    
    try:
        # Check plans table
        plans_result = supabase.table("plans").select("*").execute()
        logger.info(f"Plans table has {len(plans_result.data)} records")
        
        # Check subscriptions with plan_id
        subs_result = supabase.table("subscriptions").select("id").not_.is_("plan_id", "null").execute()
        logger.info(f"Subscriptions with plan_id: {len(subs_result.data)}")
        
        # Check subscriptions without plan_id
        null_subs_result = supabase.table("subscriptions").select("id").is_("plan_id", "null").execute()
        if null_subs_result.data:
            logger.warning(f"⚠️  Subscriptions without plan_id: {len(null_subs_result.data)}")
        else:
            logger.info("✅ All subscriptions have plan_id")
            
    except Exception as e:
        logger.error(f"Error verifying migrations: {str(e)}")

if __name__ == "__main__":
    main() 