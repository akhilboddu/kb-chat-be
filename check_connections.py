#!/usr/bin/env python3
"""
Connection Health Check Script

This script checks the health of all external connections:
- Supabase PostgreSQL
- Redis
- Celery workers

Use this to diagnose connection issues before starting the main application.
"""

import os
import sys
import time
import redis
import psycopg2
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def check_redis():
    """Check Redis connection"""
    print("🔴 Checking Redis connection...")
    
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    try:
        client = redis.from_url(redis_url)
        response = client.ping()
        if response:
            print(f"✅ Redis connected successfully at {redis_url}")
            return True
    except Exception as e:
        print(f"❌ Redis connection failed: {e}")
        print(f"   URL: {redis_url}")
        return False

def check_postgres():
    """Check PostgreSQL connection"""
    print("\n🐘 Checking PostgreSQL connection...")
    
    # Use the same DSN as in dbconnection.py
    dsn = "postgresql://postgres.qbhevelbszcvxkutfmlg:x8ODxTQ0LVDthVpV@aws-0-eu-west-2.pooler.supabase.com:5432/postgres"
    
    try:
        conn = psycopg2.connect(
            dsn,
            connect_timeout=10,
            keepalives_idle=600,
            keepalives_interval=30,
            keepalives_count=3,
        )
        
        # Test with a simple query
        cursor = conn.cursor()
        cursor.execute("SELECT 1;")
        result = cursor.fetchone()
        
        if result and result[0] == 1:
            print("✅ PostgreSQL connected successfully")
            
            # Check connection limit
            cursor.execute("SELECT count(*) FROM pg_stat_activity WHERE state = 'active';")
            active_connections = cursor.fetchone()[0]
            
            cursor.execute("SHOW max_connections;")
            max_connections = cursor.fetchone()[0]
            
            print(f"   Active connections: {active_connections}/{max_connections}")
            
            if active_connections > int(max_connections) * 0.8:
                print("⚠️  Warning: High connection usage detected")
            
        cursor.close()
        conn.close()
        return True
        
    except psycopg2.OperationalError as e:
        if "Max client connections reached" in str(e):
            print("❌ PostgreSQL connection failed: Maximum connections reached")
            print("   This indicates the Supabase free tier connection limit has been exceeded")
            print("   Try stopping other applications or wait for connections to close")
        else:
            print(f"❌ PostgreSQL connection failed: {e}")
        return False
    except Exception as e:
        print(f"❌ PostgreSQL connection failed: {e}")
        return False

def check_celery():
    """Check if Celery workers are accessible"""
    print("\n🌿 Checking Celery worker connectivity...")
    
    try:
        from app.worker.celery_app import celery_app
        
        # Check if we can connect to broker
        broker_url = celery_app.conf.broker_url
        print(f"   Broker URL: {broker_url}")
        
        # Try to get active workers
        inspect = celery_app.control.inspect()
        active_workers = inspect.active()
        
        if active_workers:
            print(f"✅ Found {len(active_workers)} active Celery worker(s)")
            for worker_name, tasks in active_workers.items():
                print(f"   Worker: {worker_name} - {len(tasks)} active tasks")
        else:
            print("⚠️  No active Celery workers found")
            print("   This is normal if workers haven't been started yet")
        
        return True
        
    except Exception as e:
        print(f"❌ Celery check failed: {e}")
        return False

def main():
    """Run all connection checks"""
    print("🔍 Starting Connection Health Check\n")
    
    results = {}
    results['redis'] = check_redis()
    results['postgres'] = check_postgres()
    results['celery'] = check_celery()
    
    print("\n" + "="*50)
    print("📊 SUMMARY")
    print("="*50)
    
    for service, status in results.items():
        status_icon = "✅" if status else "❌"
        print(f"{status_icon} {service.title()}: {'OK' if status else 'FAILED'}")
    
    all_good = all(results.values())
    if all_good:
        print("\n🎉 All connections are healthy!")
        return 0
    else:
        print("\n⚠️  Some connections have issues. Check the details above.")
        print("\n💡 Troubleshooting tips:")
        if not results['redis']:
            print("   - Start Redis: brew services start redis (macOS) or systemctl start redis (Linux)")
        if not results['postgres']:
            print("   - Check if other applications are using too many connections")
            print("   - Wait a few minutes for connections to close automatically")
            print("   - Consider upgrading Supabase plan for more connections")
        return 1

if __name__ == "__main__":
    sys.exit(main()) 