import logging
import os
import redis


class RedisConnection:
    def __init__(self):
        # Prefer REDIS_URL from environment; fallback to docker-compose default (service name)
        self.redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
        self.client = None

    def connect(self):
        print(self.redis_url, "-----------------------------k")
        if self.redis_url:
            print(self.redis_url)
            self.client = redis.Redis.from_url(self.redis_url)
            try:
                self.client.ping()
                logging.info("Redis Connected!!")
            except redis.ConnectionError:
                logging.error("Failed to connect to Redis")
                logging.error(self.redis_url)

    def disconnect(self):
        if self.client:
            self.client.close()
            logging.info("Redis Disconnected!!")


redisConnection = RedisConnection()


def getRedisKeyValue(key):
    if redisConnection.client:
        cached_data = redisConnection.client.get(key)
        if cached_data:
            logging.info(f"Cache hit for {key}")
            return cached_data  # pyright: ignore
    return None
