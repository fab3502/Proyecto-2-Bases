# config.py
import os

SECRET_KEY = os.getenv("SECRET_KEY", "dev")

MONGO_URI  = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
MONGO_DB   = os.getenv("MONGO_DB", "Proyecto2")

REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB   = int(os.getenv("REDIS_DB", "0"))
