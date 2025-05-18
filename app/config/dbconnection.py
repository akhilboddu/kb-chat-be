from psycopg2.pool import SimpleConnectionPool

POOL = None


def get_db_pool():
    global POOL
    if POOL is None:
        POOL = SimpleConnectionPool(
            1,
            10,  # min/max connections
            dsn="postgresql://postgres.qbhevelbszcvxkutfmlg:x8ODxTQ0LVDthVpV@aws-0-eu-west-2.pooler.supabase.com:5432/postgres",
        )
    return POOL


def get_conn():
    pool = get_db_pool()
    return pool.getconn()


def release_conn(conn):
    get_db_pool().putconn(conn)
