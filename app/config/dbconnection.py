from psycopg2.pool import SimpleConnectionPool
import os
import logging
import psycopg2
from contextlib import contextmanager

logger = logging.getLogger(__name__)

POOL = None

# Supabase free tier has limited connections
# We need to be very conservative with connection usage
MAX_CONNECTIONS_PER_WORKER = 1


def get_db_pool():
    global POOL
    if POOL is None:
        # Determine max connections based on environment
        # For Celery workers, use minimal connections
        is_celery_worker = 'celery' in os.environ.get('ARGV', '').lower() or 'celery' in ' '.join(os.sys.argv).lower()
        
        if is_celery_worker:
            min_conn = 1
            max_conn = 1  # Minimal for workers
        else:
            # For API server, be extremely conservative
            min_conn = 1
            max_conn = 1  # Reduced from 2 to prevent exhaustion
            
        logger.info(f"Creating connection pool: min={min_conn}, max={max_conn}, is_celery={is_celery_worker}")
        
        try:
            POOL = SimpleConnectionPool(
                min_conn,
                max_conn,
                dsn="postgresql://postgres.qbhevelbszcvxkutfmlg:x8ODxTQ0LVDthVpV@aws-0-eu-west-2.pooler.supabase.com:5432/postgres",
                # Add connection settings to prevent hanging connections
                connect_timeout=10,
                keepalives_idle=600,
                keepalives_interval=30,
                keepalives_count=3,
            )
        except Exception as e:
            logger.error(f"Failed to create connection pool: {e}")
            raise
    return POOL


@contextmanager
def get_db_connection():
    """Context manager for database connections with automatic cleanup"""
    pool = get_db_pool()
    conn = None
    try:
        conn = pool.getconn()
        yield conn
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Database connection error: {e}")
        raise
    finally:
        if conn:
            try:
                pool.putconn(conn)
            except Exception as e:
                logger.error(f"Error returning connection to pool: {e}")


def get_conn():
    """Legacy function - use get_db_connection() context manager instead"""
    pool = get_db_pool()
    return pool.getconn()


def release_conn(conn):
    """Legacy function - use get_db_connection() context manager instead"""
    if conn:
        try:
            get_db_pool().putconn(conn)
        except Exception as e:
            logger.error(f"Error releasing connection: {e}")


def close_all_connections():
    """Close all connections in the pool"""
    global POOL
    if POOL:
        try:
            POOL.closeall()
            logger.info("All database connections closed")
        except Exception as e:
            logger.error(f"Error closing database connections: {e}")
        finally:
            POOL = None
